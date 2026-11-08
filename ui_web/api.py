import os
import subprocess
import base64
import tempfile
from pathlib import Path
from typing import List, Optional, Dict, Any
import webview

from core import ConverterManager, PDFToolkit, BackgroundRemover


class DesktopAPI:
    """
    Bridge API exposed to the JavaScript frontend via PyWebView.
    All methods here can be called directly from JavaScript with:
    await window.pywebview.api.method_name(...)
    """

    def __init__(self):
        self.manager = ConverterManager()
        self._window: Optional[webview.Window] = None

    def set_window(self, window: webview.Window):
        self._window = window

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"

    def _file_info(self, file_path: Path) -> Dict[str, Any]:
        targets = self.manager.get_supported_target_formats(file_path)
        ext = file_path.suffix.lower()
        is_image = ext in BackgroundRemover.SUPPORTED_INPUTS
        is_excel = ext in {".xlsx", ".xls"}
        is_presentation = ext in {".pptx", ".ppt"}
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
        }

    # ================= Carga y Drag & Drop =================

    def load_file_from_path(self, path_str: str) -> Optional[Dict[str, Any]]:
        """Carga los metadatos de un archivo soltado con ruta local."""
        p = Path(path_str)
        if p.exists() and p.is_file():
            return self._file_info(p)
        return None

    def load_dropped_base64(self, filename: str, data_url: str) -> Optional[Dict[str, Any]]:
        """Carga un archivo soltado cuando el navegador envía los bytes en Base64."""
        try:
            if "," in data_url:
                _, encoded = data_url.split(",", 1)
            else:
                encoded = data_url
            file_bytes = base64.b64decode(encoded)

            temp_dir = Path(tempfile.gettempdir()) / "ArchiveConverter"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_file = temp_dir / filename
            temp_file.write_bytes(file_bytes)

            return self._file_info(temp_file)
        except Exception as e:
            print(f"[ERROR] Error al procesar archivo arrastrado: {e}")
            return None

    # ================= Dialogs =================

    def select_file(self) -> Optional[Dict[str, Any]]:
        """Abre el diálogo nativo de Windows para seleccionar un archivo."""
        if not self._window:
            return None
        result = self._window.create_file_dialog(
            dialog_type=webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("Archivos soportados (*.pdf;*.docx;*.xlsx;*.xls;*.pptx;*.ppt;*.png;*.jpg;*.jpeg;*.webp;*.ico)", "Todos los archivos (*.*)")
        )
        if result and len(result) > 0:
            p = Path(result[0])
            if p.exists():
                return self._file_info(p)
        return None

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

        return {
            "success": result.success,
            "output_path": str(result.output_path) if result.output_path else None,
            "filename": result.output_path.name if result.output_path else None,
            "elapsed_seconds": result.elapsed_seconds,
            "error_message": result.error_message
        }

    # ================= Removedor de Fondos (IA) =================

    def remove_image_bg(self, file_path: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """Elimina el fondo de una imagen usando IA en local."""
        try:
            in_p = Path(file_path)
            out_target = None
            if output_dir:
                out_target = Path(output_dir) / f"{in_p.stem}_sin_fondo.png"

            res = BackgroundRemover.remove_background(in_p, out_target)
            return {
                "success": True,
                "output_path": str(res),
                "filename": res.name
            }
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    # ================= Caja de Herramientas PDF =================

    def pdf_merge(self, file_paths: List[str], output_dir: Optional[str] = None) -> Dict[str, Any]:
        try:
            paths = [Path(p) for p in file_paths]
            dest_dir = Path(output_dir) if output_dir else paths[0].parent
            dest_file = dest_dir / "documentos_unidos.pdf"
            
            counter = 1
            while dest_file.exists():
                dest_file = dest_dir / f"documentos_unidos_{counter}.pdf"
                counter += 1

            res = PDFToolkit.merge(paths, dest_file)
            return {"success": True, "output_path": str(res), "filename": res.name}
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    def pdf_split(self, file_path: str, mode: str, page_range: str = "") -> Dict[str, Any]:
        try:
            in_p = Path(file_path)
            if mode == "range":
                parts = page_range.split("-")
                fp, tp = int(parts[0]), int(parts[1])
                res = PDFToolkit.split_range(in_p, fp, tp)
                return {"success": True, "output_path": str(res), "filename": res.name}
            else:
                files = PDFToolkit.split_all_pages(in_p)
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
            return {"success": True, "output_path": str(res), "filename": res.name}
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    def pdf_protect(self, file_path: str, password: str) -> Dict[str, Any]:
        try:
            res = PDFToolkit.protect(Path(file_path), user_password=password)
            return {"success": True, "output_path": str(res), "filename": res.name}
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    def pdf_unlock(self, file_path: str, password: str) -> Dict[str, Any]:
        try:
            res = PDFToolkit.unlock(Path(file_path), password=password)
            return {"success": True, "output_path": str(res), "filename": res.name}
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    def pdf_watermark(self, file_path: str, text: str) -> Dict[str, Any]:
        """Añade marca de agua diagonal con opacidad suave a un PDF."""
        try:
            res = PDFToolkit.add_watermark(Path(file_path), watermark_text=text)
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
            return {"success": True, "output_path": str(res), "filename": res.name}
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    # ================= Sistema Operativo =================

    def open_file(self, file_path: str):
        p = Path(file_path)
        if p.exists():
            os.startfile(str(p))

    def open_folder(self, file_path: str):
        p = Path(file_path)
        if p.exists():
            if p.is_dir():
                os.startfile(str(p))
            else:
                subprocess.Popen(f'explorer /select,"{str(p)}"')
