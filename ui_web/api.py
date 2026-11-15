import os
import subprocess
import base64
import tempfile
import atexit
import shutil
import datetime
import threading
import concurrent.futures
import json
import io
import uuid
import time
from pathlib import Path
from typing import List, Optional, Dict, Any, Set
try:
    import webview
except ImportError:
    webview = None

from core import (
    ConverterManager,
    PDFToolkit,
    BackgroundRemover,
    ImageConverter,
    APP_VERSION,
    check_for_updates as _core_check_for_updates,
    download_update as _core_download_update,
    apply_update_and_restart as _core_apply_update,
)

TEMP_FOLDER = Path(tempfile.gettempdir()) / "ArchiveConverter"
HEAVY_AI_FORMATS = {"remove_bg", "sin_fondo", "no_bg", "bg_remove"}
_AI_EXECUTION_LOCK = threading.Lock()

# Nombres de dispositivo reservados en Windows que provocan fallos fatales de E/S
_WINDOWS_RESERVED_NAMES = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def sanitize_filename(filename: str, fallback: str = "archivo.bin") -> str:
    """
    Sanitiza nombres de archivo contra Path Traversal, caracteres ilegales en Windows
    y nombres de dispositivo reservados (CON, PRN, AUX, NUL, COM1-COM9, LPT1-LPT9).
    """
    raw_name = Path(str(filename or "")).name
    clean_chars = "".join(c for c in raw_name if c not in '<>:"/\\|?*' and ord(c) >= 32)
    # En Windows, los espacios o puntos al final del nombre son inválidos
    safe_name = clean_chars.strip(" .")
    if not safe_name:
        return fallback

    p = Path(safe_name)
    stem_upper = p.stem.upper()
    if stem_upper in _WINDOWS_RESERVED_NAMES or safe_name.upper() in _WINDOWS_RESERVED_NAMES:
        safe_name = f"safe_{safe_name}"

    return safe_name


def cleanup_temp_files():
    """Limpia los archivos temporales generados por la aplicación."""
    try:
        if TEMP_FOLDER.exists():
            for item in TEMP_FOLDER.iterdir():
                try:
                    if item.is_file():
                        item.unlink(missing_ok=True)
                    elif item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                except Exception:
                    pass
    except Exception:
        pass


# Limpiar residuos al salir y al iniciar
atexit.register(cleanup_temp_files)
cleanup_temp_files()


class DesktopAPI:
    """
    Bridge API exposed to the JavaScript frontend via PyWebView.
    All methods here can be called directly from JavaScript with:
    await window.pywebview.api.method_name(...)
    """

    def __init__(self, initial_file: Optional[str] = None):
        self.manager = ConverterManager()
        self._window: Optional[webview.Window] = None
        self.initial_file = initial_file
        self.history: List[Dict[str, Any]] = []

    def get_initial_file(self) -> Optional[Dict[str, Any]]:
        """Devuelve los datos del archivo inicial si la app se abrió con uno (ej: menú contextual)."""
        if self.initial_file:
            p = Path(self.initial_file)
            if p.exists() and p.is_file():
                return self._file_info(p)
        return None

    def set_window(self, window: webview.Window):
        self._window = window

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"

    def _generate_thumbnail(self, file_path: Path) -> Optional[str]:
        """Genera una miniatura ligera en Base64 para imágenes y documentos PDF."""
        ext = file_path.suffix.lower()
        try:
            if ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".ico"}:
                from PIL import Image
                with Image.open(file_path) as img:
                    img_copy = img.copy()
                    img_copy.thumbnail((160, 160))
                    buf = io.BytesIO()
                    if img_copy.mode in ("RGBA", "LA") or (img_copy.mode == "P" and "transparency" in img_copy.info):
                        img_copy.save(buf, format="PNG")
                        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                        return f"data:image/png;base64,{b64}"
                    else:
                        if img_copy.mode != "RGB":
                            img_copy = img_copy.convert("RGB")
                        img_copy.save(buf, format="JPEG", quality=80)
                        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                        return f"data:image/jpeg;base64,{b64}"
            elif ext == ".pdf":
                try:
                    import pymupdf
                    with pymupdf.open(str(file_path)) as doc:
                        if not doc.is_encrypted and len(doc) > 0:
                            page = doc[0]
                            pix = page.get_pixmap(dpi=60)
                            b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
                            return f"data:image/png;base64,{b64}"
                except Exception:
                    pass
        except Exception:
            pass
        return None

    def _file_info(self, file_path: Path) -> Dict[str, Any]:
        targets = self.manager.get_supported_target_formats(file_path)
        ext = file_path.suffix.lower()
        is_image = ext in BackgroundRemover.SUPPORTED_INPUTS
        is_excel = ext in {".xlsx", ".xls"}
        is_presentation = ext in {".pptx", ".ppt"}

        page_count = None
        if ext == ".pdf":
            try:
                import pymupdf
                with pymupdf.open(str(file_path)) as doc:
                    page_count = len(doc)
            except Exception:
                pass

        return {
            "name": file_path.name,
            "path": str(file_path.resolve()),
            "size": self._format_size(file_path.stat().st_size),
            "size_bytes": file_path.stat().st_size,
            "extension": ext.lstrip("."),
            "supported_targets": targets,
            "is_image": is_image,
            "is_excel": is_excel,
            "is_presentation": is_presentation,
            "page_count": page_count,
            "thumbnail": self._generate_thumbnail(file_path)
        }

    # ================= Historial de Sesión =================

    def _add_history(self, name: str, output_path: str, op_type: str, elapsed: float = 0.0):
        try:
            self.history.insert(0, {
                "name": name,
                "path": str(output_path),
                "type": op_type,
                "time": datetime.datetime.now().strftime("%H:%M:%S"),
                "elapsed": round(elapsed, 2)
            })
            if len(self.history) > 40:
                self.history.pop()
        except Exception:
            pass

    def get_history(self) -> List[Dict[str, Any]]:
        """Devuelve el historial de tareas y conversiones realizadas en la sesión."""
        return self.history

    def clear_history(self) -> bool:
        """Limpia el registro de conversiones de la sesión."""
        self.history.clear()
        return True

    # ================= Carga y Drag & Drop =================

    def load_file_from_path(self, path_str: str) -> Optional[Dict[str, Any]]:
        """Carga los metadatos de un archivo soltado con ruta local."""
        p = Path(path_str)
        if p.exists() and p.is_file():
            return self._file_info(p)
        return None

    def load_files_from_paths(self, path_list: List[str]) -> List[Dict[str, Any]]:
        """Carga metadatos de múltiples archivos para conversión por lotes."""
        results = []
        for p_str in path_list:
            p = Path(p_str)
            if p.exists() and p.is_file():
                results.append(self._file_info(p))
        return results

    def get_files_details(self, path_list: List[str]) -> List[Dict[str, Any]]:
        """Devuelve información detallada de una lista de archivos para vistas interactivas (ej: Merge)."""
        return self.load_files_from_paths(path_list)

    def get_common_target_formats(self, path_list: List[str]) -> List[str]:
        """Calcula qué formatos de destino son compatibles con todos los archivos seleccionados."""
        if not path_list:
            return []
        common: Optional[Set[str]] = None
        for p_str in path_list:
            targets = set(self.manager.get_supported_target_formats(Path(p_str)))
            if common is None:
                common = targets
            else:
                common = common.intersection(targets)
        return sorted(list(common)) if common else []

    def load_dropped_base64(self, filename: str, data_url: str) -> Optional[Dict[str, Any]]:
        """Carga un archivo soltado cuando el navegador envía los bytes en Base64."""
        try:
            if "," in data_url:
                _, encoded = data_url.split(",", 1)
            else:
                encoded = data_url
            file_bytes = base64.b64decode(encoded)

            temp_dir = (Path(tempfile.gettempdir()) / "ArchiveConverter").resolve()
            temp_dir.mkdir(parents=True, exist_ok=True)

            # Sanitización contra Path Traversal, caracteres peligrosos y nombres reservados de Windows
            safe_name = sanitize_filename(filename, fallback="archivo_arrastrado.bin")

            # Aislamiento por subcarpeta única con UUID para evitar colisiones concurrentes
            uid = uuid.uuid4().hex[:8]
            drop_subfolder = temp_dir / f"drop_{uid}"
            drop_subfolder.mkdir(parents=True, exist_ok=True)

            temp_file = (drop_subfolder / safe_name).resolve()
            if not temp_file.is_relative_to(temp_dir):
                raise ValueError("Ruta de archivo no autorizada.")

            temp_file.write_bytes(file_bytes)
            return self._file_info(temp_file)
        except Exception as e:
            print(f"[ERROR] Error al procesar archivo arrastrado: {e}")
            return None

    @staticmethod
    def create_temp_path(filename: str, prefix: str = "temp") -> Path:
        """Crea una ruta de archivo temporal aislada con UUID corto para operaciones concurrentes."""
        temp_dir = TEMP_FOLDER.resolve()
        temp_dir.mkdir(parents=True, exist_ok=True)
        safe_name = sanitize_filename(filename, fallback="temp.bin")
        uid = uuid.uuid4().hex[:8]
        sub = temp_dir / f"{prefix}_{uid}"
        sub.mkdir(parents=True, exist_ok=True)
        return (sub / safe_name).resolve()

    def _safe_evaluate_js(self, script: str) -> None:
        """Ejecuta JS en la ventana PyWebView de forma segura si está disponible y abierta."""
        if self._window:
            try:
                self._window.evaluate_js(script)
            except Exception:
                pass

    # ================= Dialogs =================

    def select_file(self) -> Optional[Dict[str, Any]]:
        """Abre el diálogo nativo de Windows para seleccionar un archivo."""
        if not self._window:
            return None
        result = self._window.create_file_dialog(
            dialog_type=webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("Archivos soportados (*.pdf;*.docx;*.xlsx;*.xls;*.pptx;*.ppt;*.png;*.jpg;*.jpeg;*.webp;*.ico;*.heic;*.heif)", "Todos los archivos (*.*)")
        )
        if result and len(result) > 0:
            p = Path(result[0])
            if p.exists():
                return self._file_info(p)
        return None

    def select_batch_files(self) -> List[Dict[str, Any]]:
        """Abre el diálogo para seleccionar múltiples archivos a convertir a la vez."""
        if not self._window:
            return []
        result = self._window.create_file_dialog(
            dialog_type=webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=("Archivos soportados (*.pdf;*.docx;*.xlsx;*.xls;*.pptx;*.ppt;*.png;*.jpg;*.jpeg;*.webp;*.ico;*.heic;*.heif)", "Todos los archivos (*.*)")
        )
        files = []
        if result:
            for item in result:
                p = Path(item)
                if p.exists() and p.is_file():
                    files.append(self._file_info(p))
        return files

    def select_image_file(self) -> Optional[Dict[str, Any]]:
        """Abre el diálogo para seleccionar específicamente una imagen o firma."""
        if not self._window:
            return None
        result = self._window.create_file_dialog(
            dialog_type=webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("Imágenes (*.png;*.jpg;*.jpeg;*.webp)", "Todos los archivos (*.*)")
        )
        if result and len(result) > 0:
            p = Path(result[0])
            if p.exists():
                return self._file_info(p)
        return None

    def select_multiple_files(self) -> List[Dict[str, Any]]:
        """Abre el diálogo para seleccionar múltiples archivos."""
        if not self._window:
            return []
        result = self._window.create_file_dialog(
            dialog_type=webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=("Archivos PDF (*.pdf)", "Todos los archivos (*.*)")
        )
        files = []
        if result:
            for item in result:
                p = Path(item)
                if p.exists():
                    files.append(self._file_info(p))
        return files

    def select_folder(self) -> Optional[str]:
        """Abre el diálogo para seleccionar carpeta de destino."""
        if not self._window:
            return None
        result = self._window.create_file_dialog(dialog_type=webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            return str(Path(result[0]).resolve())
        return None

    # ================= Conversión Universal =================

    def convert_file(
        self,
        input_path: str,
        target_format: str,
        output_dir: Optional[str] = None,
        auto_fit: bool = True,
        orientation: str = "auto"
    ) -> Dict[str, Any]:
        """Ejecuta la conversión de archivo a través del motor core."""
        in_p = Path(input_path)
        out_target = None
        if output_dir:
            out_d = Path(output_dir)
            target_ext = f".{target_format.lower()}"
            out_target = out_d / f"{in_p.stem}{target_ext}"
            if out_target == in_p:
                out_target = out_d / f"{in_p.stem}_convertido{target_ext}"

        result = self.manager.convert_file(
            input_path=in_p,
            target_format=target_format,
            output_path=out_target,
            auto_fit=auto_fit,
            orientation=orientation
        )

        if result.success and result.output_path:
            self._add_history(
                result.output_path.name,
                str(result.output_path),
                f"Conversión ({target_format.upper()})",
                result.elapsed_seconds
            )

        return {
            "success": result.success,
            "output_path": str(result.output_path) if result.output_path else None,
            "filename": result.output_path.name if result.output_path else None,
            "elapsed_seconds": result.elapsed_seconds,
            "error_message": result.error_message
        }

    def convert_batch(
        self,
        file_paths: List[str],
        target_format: str,
        output_dir: Optional[str] = None,
        auto_fit: bool = True,
        orientation: str = "auto"
    ) -> Dict[str, Any]:
        """
        Ejecuta la conversión por lotes (batch) con ThreadPoolExecutor:
        - Conversiones ligeras de documentos/imágenes: hasta 4 hilos paralelos.
        - Tareas pesadas de IA (remove_bg): estrictamente secuencial (max_workers=1)
          para evitar agotar la memoria RAM del sistema.
        Garantiza inicialización/desinicialización de COM por cada hilo de trabajo
        y aislamiento de nombres de archivos con UUID para evitar colisiones.
        """
        if not file_paths:
            return {
                "total": 0,
                "success_count": 0,
                "failed_count": 0,
                "output_dir": str(output_dir or ""),
                "success_list": [],
                "failed_list": [],
            }

        is_heavy_ai = target_format.lower().strip(".") in HEAVY_AI_FORMATS
        success_list = []
        failed_list = []
        out_d = Path(output_dir) if output_dir else Path(file_paths[0]).parent
        out_d.mkdir(parents=True, exist_ok=True)
        total = len(file_paths)
        completed_lock = threading.Lock()
        allocated_names_lock = threading.Lock()
        allocated_names: Set[str] = set()
        completed_count = 0

        def get_unique_output_path(in_p: Path) -> Path:
            if is_heavy_ai:
                target_ext = ".png"
                base_name = f"{in_p.stem}_sin_fondo{target_ext}"
            else:
                target_ext = f".{target_format.lower().lstrip('.')}"
                base_name = f"{in_p.stem}{target_ext}"
                if base_name == in_p.name:
                    base_name = f"{in_p.stem}_convertido{target_ext}"

            with allocated_names_lock:
                cand = out_d / base_name
                if base_name in allocated_names or cand.exists():
                    uid = uuid.uuid4().hex[:8]
                    stem_part = f"{in_p.stem}_sin_fondo" if is_heavy_ai else in_p.stem
                    base_name = f"{stem_part}_{uid}{target_ext}"
                    cand = out_d / base_name
                allocated_names.add(base_name)
                return cand

        def process_single(p_str: str):
            nonlocal completed_count
            in_p = Path(p_str)
            out_target = get_unique_output_path(in_p)

            if is_heavy_ai:
                t0 = time.perf_counter()
                try:
                    with _AI_EXECUTION_LOCK:
                        out_res = BackgroundRemover.remove_background(in_p, out_target)
                    elapsed = round(time.perf_counter() - t0, 3)
                    ok, detail, out_path_str = True, out_res.name, str(out_res)
                except Exception as err:
                    elapsed = round(time.perf_counter() - t0, 3)
                    ok, detail, out_path_str = False, str(err), None
            else:
                com_initialized = False
                try:
                    import pythoncom
                    pythoncom.CoInitialize()
                    com_initialized = True
                except Exception:
                    pass

                try:
                    res = self.manager.convert_file(
                        input_path=in_p,
                        target_format=target_format,
                        output_path=out_target,
                        auto_fit=auto_fit,
                        orientation=orientation
                    )
                finally:
                    if com_initialized:
                        try:
                            import pythoncom
                            import gc
                            gc.collect()
                            pythoncom.CoUninitialize()
                        except Exception:
                            pass

                elapsed = res.elapsed_seconds
                if res.success:
                    ok, detail, out_path_str = True, res.output_path.name, str(res.output_path)
                else:
                    ok, detail, out_path_str = False, res.error_message, None

            with completed_lock:
                completed_count += 1
                curr_done = completed_count

            safe_name = json.dumps(in_p.name)
            self._safe_evaluate_js(
                f"if (window.onBatchProgressUpdate) window.onBatchProgressUpdate({curr_done}, {total}, {safe_name});"
            )

            return ok, in_p.name, detail, elapsed, out_path_str

        # Restringir tareas pesadas de IA a ejecución estrictamente secuencial (1 a la vez)
        max_workers = 1 if is_heavy_ai else min(4, max(1, os.cpu_count() or 2))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(process_single, file_paths))

        for ok, name, detail, elapsed, out_p in results:
            if ok:
                success_list.append({"name": name, "output_name": detail, "elapsed": elapsed})
                if out_p:
                    self._add_history(detail, out_p, f"Lote ({target_format.upper()})", elapsed)
            else:
                failed_list.append({"name": name, "error": detail})

        return {
            "total": total,
            "success_count": len(success_list),
            "failed_count": len(failed_list),
            "output_dir": str(out_d),
            "success_list": success_list,
            "failed_list": failed_list,
        }

    # ================= Compresión de Imágenes =================

    def compress_image(
        self,
        file_path: str,
        max_size_kb: Optional[int] = None,
        quality: int = 80,
        output_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """Comprime una imagen reduciendo su tamaño en KB de forma inteligente."""
        try:
            in_p = Path(file_path)
            out_target = None
            if output_dir:
                ext = in_p.suffix.lower()
                if ext in {".heic", ".heif", ".bmp", ".tiff"}:
                    ext = ".jpg"
                out_target = Path(output_dir) / f"{in_p.stem}_comprimido{ext}"

            res_p, old_sz, new_sz = ImageConverter.compress_image(
                input_path=in_p,
                output_path=out_target,
                max_size_kb=max_size_kb,
                target_quality=quality
            )
            reduction = (1 - (new_sz / old_sz)) * 100 if old_sz > 0 else 0

            self._add_history(res_p.name, str(res_p), "Compresión Imagen")

            return {
                "success": True,
                "output_path": str(res_p),
                "filename": res_p.name,
                "old_size": self._format_size(old_sz),
                "new_size": self._format_size(new_sz),
                "reduction_percent": round(reduction, 1)
            }
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    # ================= Removedor de Fondos (IA) =================

    def check_ai_model_status(self) -> Dict[str, Any]:
        """Comprueba si el modelo local de IA (u2net.onnx) está disponible."""
        return BackgroundRemover.check_model_availability()

    def remove_image_bg(self, file_path: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """Elimina el fondo de una imagen usando IA en local de forma aislada y secuencial."""
        try:
            in_p = Path(file_path)
            with _AI_EXECUTION_LOCK:
                res = BackgroundRemover.remove_background_structured(
                    input_path=in_p,
                    output_dir=output_dir,
                )

            out_path = Path(res["output_path"])
            self._add_history(out_path.name, str(out_path), "Quitar Fondo IA")
            return {
                "ok": True,
                "success": True,
                "output_path": str(out_path),
                "filename": out_path.name,
                "width": res.get("width"),
                "height": res.get("height"),
                "original_width": res.get("original_width"),
                "original_height": res.get("original_height"),
                "downscaled": bool(res.get("downscaled", False)),
                "error_code": None,
                "message": None,
                "error_message": None,
            }
        except Exception as e:
            err_code = getattr(e, "error_code", "PROCESSING_ERROR")
            msg = str(e)
            return {
                "ok": False,
                "success": False,
                "output_path": None,
                "filename": None,
                "width": None,
                "height": None,
                "original_width": None,
                "original_height": None,
                "downscaled": False,
                "error_code": err_code,
                "message": msg,
                "error_message": msg,
            }

    def remove_batch_bg(self, file_paths: List[str], output_dir: Optional[str] = None) -> Dict[str, Any]:
        """Elimina el fondo de múltiples imágenes de forma estrictamente secuencial para proteger la RAM."""
        return self.convert_batch(file_paths=file_paths, target_format="remove_bg", output_dir=output_dir)

    # ================= Caja de Herramientas PDF =================

    def pdf_merge(self, file_paths: List[str], output_dir: Optional[str] = None) -> Dict[str, Any]:
        try:
            paths = [Path(p) for p in file_paths]
            dest_dir = Path(output_dir) if output_dir else paths[0].parent
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_file = dest_dir / "documentos_unidos.pdf"
            
            if dest_file.exists():
                uid = uuid.uuid4().hex[:8]
                dest_file = dest_dir / f"documentos_unidos_{uid}.pdf"

            res = PDFToolkit.merge(paths, dest_file)
            self._add_history(res.name, str(res), "Unir PDFs")
            return {"success": True, "output_path": str(res), "filename": res.name}
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    def pdf_split(self, file_path: str, mode: str, page_range: str = "") -> Dict[str, Any]:
        try:
            in_p = Path(file_path)
            if mode == "range":
                parts = [p.strip() for p in page_range.split("-")]
                if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                    return {
                        "success": False,
                        "error_message": "Formato de rango no válido. Introduce 'desde-hasta' con números positivos (ej: 1-3)."
                    }
                fp, tp = int(parts[0]), int(parts[1])
                res = PDFToolkit.split_range(in_p, fp, tp)
                self._add_history(res.name, str(res), f"Dividir PDF ({fp}-{tp})")
                return {"success": True, "output_path": str(res), "filename": res.name}
            else:
                files = PDFToolkit.split_all_pages(in_p)
                self._add_history(f"{len(files)} páginas", str(files[0].parent), "Dividir PDF")
                return {
                    "success": True,
                    "output_path": str(files[0].parent),
                    "filename": f"{len(files)} páginas separadas",
                    "is_folder": True
                }
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    def pdf_compress(self, file_path: str) -> Dict[str, Any]:
        try:
            in_p = Path(file_path)
            old_size = in_p.stat().st_size
            res = PDFToolkit.compress(in_p)
            new_size = res.stat().st_size
            reduction = (1 - (new_size / old_size)) * 100 if old_size > 0 else 0
            self._add_history(res.name, str(res), "Comprimir PDF")
            return {
                "success": True,
                "output_path": str(res),
                "filename": res.name,
                "old_size": self._format_size(old_size),
                "new_size": self._format_size(new_size),
                "reduction_percent": round(reduction, 1)
            }
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    def pdf_extract_images(self, file_path: str) -> Dict[str, Any]:
        try:
            in_p = Path(file_path)
            imgs = PDFToolkit.extract_images(in_p)
            if not imgs:
                return {"success": False, "error_message": "No se encontraron imágenes en este PDF."}
            self._add_history(f"{len(imgs)} imágenes", str(imgs[0].parent), "Extraer Imágenes PDF")
            return {
                "success": True,
                "output_path": str(imgs[0].parent),
                "count": len(imgs),
                "is_folder": True
            }
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    def pdf_rotate(self, file_path: str, degrees: int = 90) -> Dict[str, Any]:
        try:
            res = PDFToolkit.rotate_pages(Path(file_path), degrees=degrees)
            self._add_history(res.name, str(res), f"Rotar PDF ({degrees}°)")
            return {"success": True, "output_path": str(res), "filename": res.name}
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    def pdf_protect(self, file_path: str, password: str) -> Dict[str, Any]:
        try:
            res = PDFToolkit.protect(Path(file_path), user_password=password)
            self._add_history(res.name, str(res), "Proteger PDF")
            return {"success": True, "output_path": str(res), "filename": res.name}
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    def pdf_unlock(self, file_path: str, password: str) -> Dict[str, Any]:
        try:
            res = PDFToolkit.unlock(Path(file_path), password=password)
            self._add_history(res.name, str(res), "Desbloquear PDF")
            return {"success": True, "output_path": str(res), "filename": res.name}
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    def pdf_watermark(self, file_path: str, text: str) -> Dict[str, Any]:
        """Añade marca de agua diagonal con opacidad suave a un PDF."""
        try:
            res = PDFToolkit.add_watermark(Path(file_path), watermark_text=text)
            self._add_history(res.name, str(res), "Marca de Agua PDF")
            return {"success": True, "output_path": str(res), "filename": res.name}
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    def pdf_sign(
        self,
        file_path: str,
        signature_path: str,
        position: str = "bottom-right",
        page_num: int = -1
    ) -> Dict[str, Any]:
        """Estampa imagen de firma o sello sobre un PDF."""
        try:
            res = PDFToolkit.add_signature(
                input_path=Path(file_path),
                signature_path=Path(signature_path),
                position=position,
                page_num=page_num
            )
            self._add_history(res.name, str(res), "Firmar PDF")
            return {"success": True, "output_path": str(res), "filename": res.name}
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    # ================= Sistema Operativo =================

    def open_file(self, file_path: str):
        p = Path(file_path)
        if p.exists():
            os.startfile(str(p))

    def open_folder(self, file_path: str):
        p = Path(file_path).resolve()
        if p.exists():
            if p.is_dir():
                os.startfile(str(p))
            else:
                subprocess.Popen(["explorer", f"/select,{str(p)}"])

    # ================= Auto-Actualización (GitHub Releases) =================

    def check_for_updates(self) -> Dict[str, Any]:
        """
        Consulta de forma segura y silenciosa si existe una versión superior en GitHub Releases.
        Si no hay conexión a internet, devuelve update_available=False sin interrumpir la app.
        """
        info = _core_check_for_updates(current_version=APP_VERSION)
        if info:
            return info
        return {
            "update_available": False,
            "current_version": APP_VERSION,
        }

    def download_and_install_update(self, download_url: str, filename: Optional[str] = None) -> Dict[str, Any]:
        """
        Descarga el paquete de actualización en TEMP_FOLDER reportando progreso a la UI,
        genera `update.bat`, lo lanza en segundo plano y cierra la app para reemplazar el binario.
        """
        last_emit = [0.0]
        last_pct = [-1.0]

        def on_progress(downloaded: int, total: int, percent: float):
            now = time.monotonic()
            is_done = (total > 0 and downloaded >= total) or percent >= 100.0
            if not is_done and (now - last_emit[0]) < 0.15 and abs(percent - last_pct[0]) < 1.0:
                return
            last_emit[0] = now
            last_pct[0] = percent
            self._safe_evaluate_js(
                f"if (window.onUpdateDownloadProgress) window.onUpdateDownloadProgress({int(downloaded)}, {int(total)}, {float(percent):.2f});"
            )

        downloaded_path = _core_download_update(
            download_url=download_url,
            filename=filename,
            temp_dir=TEMP_FOLDER / "updates",
            progress_callback=on_progress,
        )
        if not downloaded_path:
            return {
                "success": False,
                "error_message": "No se pudo descargar la actualización. Verifica tu conexión a internet."
            }

        try:
            _core_apply_update(downloaded_file=downloaded_path, exit_app=True)
            return {"success": True}
        except SystemExit:
            raise
        except Exception as e:
            return {"success": False, "error_message": f"Error al preparar el instalador de actualización: {e}"}
