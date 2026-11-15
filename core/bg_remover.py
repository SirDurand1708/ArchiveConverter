import atexit
import ctypes
import hashlib
import multiprocessing
import os
import queue
import socket
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
from PIL import Image, ImageOps


class BackgroundRemovalError(RuntimeError):
    """Error tipado para el pipeline de eliminación de fondos con IA local."""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class BackgroundRemovalValueError(BackgroundRemovalError, ValueError):
    """Error de validación de entrada/formato compatible con ValueError y BackgroundRemovalError."""


def _win32_create_kill_on_close_job() -> Optional[int]:
    """Crea un Windows Job Object con JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE."""
    if sys.platform != "win32":
        return None
    try:
        kernel32 = ctypes.windll.kernel32

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            job,
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            kernel32.CloseHandle(job)
            return None
        return int(job)
    except Exception:
        return None


def _win32_assign_pid_to_job(job_handle: Optional[int], pid: Optional[int]) -> None:
    """Asocia un proceso hijo al Job Object para evitar procesos huérfanos en Windows."""
    if sys.platform != "win32" or not job_handle or not pid:
        return
    try:
        kernel32 = ctypes.windll.kernel32
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001
        proc_handle = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, int(pid))
        if proc_handle:
            try:
                kernel32.AssignProcessToJobObject(ctypes.c_void_p(job_handle), proc_handle)
            finally:
                kernel32.CloseHandle(proc_handle)
    except Exception:
        pass


def _normalize_image_array_to_uint8(arr: np.ndarray, mode: str) -> np.ndarray:
    """Normaliza arreglos de alta profundidad (I;16, I, F) a uint8 [0, 255]."""
    if mode.startswith("I;16"):
        return np.clip(arr.astype(np.int32) >> 8, 0, 255).astype(np.uint8)
    if mode == "I":
        max_val = int(np.max(arr)) if arr.size else 0
        if max_val > 255:
            scale = 255.0 / float(max_val)
            return np.clip(arr.astype(np.float32) * scale, 0, 255).astype(np.uint8)
        return np.clip(arr, 0, 255).astype(np.uint8)
    if mode == "F":
        clean = np.nan_to_num(arr.astype(np.float32), nan=0.0, posinf=255.0, neginf=0.0)
        max_val = float(np.max(clean)) if clean.size else 0.0
        min_val = float(np.min(clean)) if clean.size else 0.0
        if 0.0 <= min_val and max_val <= 1.0:
            clean = clean * 255.0
        return np.clip(clean, 0.0, 255.0).astype(np.uint8)
    return np.clip(arr, 0, 255).astype(np.uint8)


def sanitize_and_load_image(
    input_path: Path,
    max_dim: int = 2048,
    max_pixels: int = 40_000_000,
    meta_out: Optional[Dict[str, Any]] = None,
) -> Tuple[Image.Image, Optional[Image.Image]]:
    """
    Pipeline seguro de lectura, validación de cabecera, corrección EXIF,
    downscaling preventivo y normalización de modos de color.
    Devuelve (rgb_para_modelo, alfa_previo_opcional).
    """
    prev_max_pixels = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(input_path) as img:
            n_frames = getattr(img, "n_frames", 1)
            if n_frames and n_frames > 1:
                raise BackgroundRemovalValueError(
                    "ANIMATED_UNSUPPORTED",
                    f"Las imágenes animadas o multipágina no están soportadas ({n_frames} frames).",
                )

            if (img.format or "").upper() == "JPEG" and max(img.size) > max_dim:
                try:
                    img.draft("RGB", (max_dim, max_dim))
                except Exception:
                    pass

            img = ImageOps.exif_transpose(img)
            orig_w, orig_h = img.size

            if max(img.size) > max_dim:
                img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

            if meta_out is not None:
                meta_out["original_width"] = int(orig_w)
                meta_out["original_height"] = int(orig_h)
                meta_out["downscaled"] = (img.width < orig_w) or (img.height < orig_h)

            mode = img.mode
            if mode.startswith("I;16") or mode in ("I", "F"):
                arr = np.asarray(img)
                u8 = _normalize_image_array_to_uint8(arr, mode)
                rgba = Image.fromarray(u8, mode="L").convert("RGBA")
            elif mode == "P":
                rgba = img.convert("RGBA")
            elif mode in ("RGBA", "LA"):
                rgba = img.convert("RGBA")
            else:
                rgba = img.convert("RGBA")

            prior_alpha: Optional[Image.Image] = None
            if mode in ("RGBA", "LA") or (mode == "P" and "transparency" in img.info):
                alpha_ch = rgba.getchannel("A")
                extrema = alpha_ch.getextrema()
                if extrema and extrema[0] < 255:
                    prior_alpha = alpha_ch
                    bg = Image.new("RGBA", rgba.size, (128, 128, 128, 255))
                    rgb_for_model = Image.alpha_composite(bg, rgba).convert("RGB")
                    return rgb_for_model, prior_alpha

            return rgba.convert("RGB"), None

    except BackgroundRemovalError:
        raise
    except Image.DecompressionBombError as err:
        raise BackgroundRemovalValueError(
            "IMAGE_TOO_LARGE",
            f"La imagen supera el límite seguro de píxeles ({max_pixels}): {err}",
        ) from err
    except MemoryError as err:
        raise BackgroundRemovalError(
            "PROCESSING_ERROR",
            f"Memoria insuficiente al decodificar la imagen '{input_path.name}': {err}",
        ) from err
    except Exception as err:
        raise BackgroundRemovalValueError(
            "UNSUPPORTED_FORMAT",
            f"No se pudo abrir o decodificar la imagen '{input_path.name}': {err}",
        ) from err
    finally:
        Image.MAX_IMAGE_PIXELS = prev_max_pixels


def _preprocess_for_u2net(rgb_img: Image.Image, input_size: Tuple[int, int] = (320, 320)) -> np.ndarray:
    """Convierte RGB PIL a tensor NCHW float32 normalizado para U2-Net."""
    resized = rgb_img.resize(input_size, Image.Resampling.BILINEAR)
    arr = np.asarray(resized, dtype=np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    norm = (arr - mean) / std
    chw = np.transpose(norm, (2, 0, 1))
    return np.expand_dims(chw, axis=0).astype(np.float32)


def _postprocess_u2net_mask(pred: np.ndarray, target_size: Tuple[int, int]) -> Image.Image:
    """Normaliza la salida de U2-Net a máscara L [0, 255] del tamaño procesado."""
    mask = np.squeeze(pred).astype(np.float32)
    if mask.ndim > 2:
        mask = mask[0]
    ma = float(np.max(mask))
    mi = float(np.min(mask))
    if ma > mi:
        mask = (mask - mi) / (ma - mi)
    else:
        mask = np.zeros_like(mask, dtype=np.float32)
    mask_u8 = np.clip(mask * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(mask_u8, mode="L").resize(target_size, Image.Resampling.LANCZOS)


def create_onnx_session(model_path: Path):
    """Crea una sesión de onnxruntime strictly-CPU con hilos acotados."""
    try:
        import onnxruntime as ort
    except ImportError as err:
        raise BackgroundRemovalError(
            "PROCESSING_ERROR",
            f"El módulo 'onnxruntime' no está instalado: {err}",
        ) from err

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = min(4, os.cpu_count() or 2)
    opts.inter_op_num_threads = 1
    try:
        return ort.InferenceSession(
            str(model_path),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
    except Exception as err:
        raise BackgroundRemovalError(
            "MODEL_CORRUPT",
            f"Error al inicializar onnxruntime con '{model_path.name}': {err}",
        ) from err


def _atomic_save_png_exclusive(
    rgba_img: Image.Image,
    out_dir: Path,
    base_stem: str,
    explicit_output: Optional[Path] = None,
) -> Path:
    """
    Escribe el PNG en un archivo temporal en out_dir (flush + fsync) y reserva
    exclusivamente el nombre destino sin sobrescribir archivos existentes.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=str(out_dir),
            prefix=".tmp_nobg_",
            suffix=".png",
            delete=False,
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            rgba_img.save(tmp_file, format="PNG")
            tmp_file.flush()
            os.fsync(tmp_file.fileno())

        candidates = []
        if explicit_output is not None:
            exp_stem = explicit_output.stem
            candidates.append(out_dir / f"{exp_stem}.png")
            for _ in range(8):
                candidates.append(out_dir / f"{exp_stem}_{uuid.uuid4().hex[:8]}.png")
        else:
            candidates.append(out_dir / f"{base_stem}_nobg.png")
            for _ in range(8):
                candidates.append(out_dir / f"{base_stem}_nobg_{uuid.uuid4().hex[:8]}.png")

        for candidate in candidates:
            for attempt in range(3):
                try:
                    os.link(str(tmp_path), str(candidate))
                    return candidate
                except FileExistsError:
                    break
                except PermissionError:
                    if attempt < 2:
                        time.sleep(0.05 * (attempt + 1))
                        continue
                    raise
                except OSError:
                    # Fallback en sistemas de archivos donde os.link no esté soportado
                    try:
                        fd = os.open(str(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
                        try:
                            with open(tmp_path, "rb") as src_f:
                                while True:
                                    chunk = src_f.read(1024 * 1024)
                                    if not chunk:
                                        break
                                    os.write(fd, chunk)
                                os.fsync(fd)
                        finally:
                            os.close(fd)
                        return candidate
                    except FileExistsError:
                        break

        raise BackgroundRemovalError(
            "PERMISSION_DENIED",
            f"No se pudo reservar un nombre de salida único en '{out_dir}'.",
        )
    except PermissionError as err:
        raise BackgroundRemovalError(
            "PERMISSION_DENIED",
            f"Sin permisos de escritura en '{out_dir}': {err}",
        ) from err
    finally:
        if tmp_path is not None and tmp_path.exists():
            for attempt in range(3):
                try:
                    tmp_path.unlink()
                    break
                except PermissionError:
                    if attempt < 2:
                        time.sleep(0.05 * (attempt + 1))
                except OSError:
                    break


def run_inference_in_process(
    input_path: Path,
    out_dir: Path,
    model_path: Path,
    session: Any = None,
    explicit_output: Optional[Path] = None,
    max_dim: int = 2048,
    max_pixels: int = 40_000_000,
) -> Dict[str, Any]:
    """Ejecuta el pipeline completo (Pillow + onnxruntime + guardado atómico)."""
    meta: Dict[str, Any] = {}
    rgb_img, prior_alpha = sanitize_and_load_image(
        input_path,
        max_dim=max_dim,
        max_pixels=max_pixels,
        meta_out=meta,
    )
    if session is None:
        session = create_onnx_session(model_path)

    tensor = _preprocess_for_u2net(rgb_img)
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: tensor})
    mask = _postprocess_u2net_mask(outputs[0], rgb_img.size)

    if prior_alpha is not None:
        mask_arr = np.minimum(np.asarray(mask, dtype=np.uint8), np.asarray(prior_alpha, dtype=np.uint8))
        mask = Image.fromarray(mask_arr, mode="L")

    rgba_out = rgb_img.convert("RGBA")
    rgba_out.putalpha(mask)

    out_path = _atomic_save_png_exclusive(
        rgba_out,
        out_dir=out_dir,
        base_stem=input_path.stem,
        explicit_output=explicit_output,
    )
    return {
        "ok": True,
        "output_path": str(out_path),
        "width": rgba_out.width,
        "height": rgba_out.height,
        "original_width": meta.get("original_width", rgba_out.width),
        "original_height": meta.get("original_height", rgba_out.height),
        "downscaled": bool(meta.get("downscaled", False)),
        "error_code": None,
        "message": None,
    }


def _worker_loop(req_queue: Any, res_queue: Any, model_path_str: str) -> None:
    """Bucle del proceso worker aislado para inferencia ONNX."""
    session = None
    model_path = Path(model_path_str)
    while True:
        task = req_queue.get()
        if task is None:
            break
        in_str, out_dir_str, explicit_out_str = task
        try:
            if session is None:
                session = create_onnx_session(model_path)
            explicit_out = Path(explicit_out_str) if explicit_out_str else None
            result = run_inference_in_process(
                input_path=Path(in_str),
                out_dir=Path(out_dir_str),
                model_path=model_path,
                session=session,
                explicit_output=explicit_out,
            )
            res_queue.put(result)
        except BackgroundRemovalError as err:
            res_queue.put({
                "ok": False,
                "output_path": None,
                "width": None,
                "height": None,
                "error_code": err.error_code,
                "message": err.message,
            })
        except MemoryError as err:
            res_queue.put({
                "ok": False,
                "output_path": None,
                "width": None,
                "height": None,
                "error_code": "PROCESSING_ERROR",
                "message": f"Memoria insuficiente durante inferencia ONNX: {err}",
            })
        except Exception as err:
            res_queue.put({
                "ok": False,
                "output_path": None,
                "width": None,
                "height": None,
                "error_code": "PROCESSING_ERROR",
                "message": f"Error inesperado en worker IA: {err}",
            })


class BackgroundRemover:
    """
    Eliminación de fondo de imágenes por IA en local usando onnxruntime directo (u2net.onnx)
    aislado en un subproceso spawn con Windows Job Object, semáforo estricto y TTL de inactividad.
    """

    SUPPORTED_INPUTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
    DEFAULT_MODEL = "u2net"
    U2NET_EXPECTED_SHA256 = "8d10d2f3bb75ae3b6d527c77944fc5e7dcd94b29809d47a739a7a728a912b491"
    MAX_DIMENSION = 2048
    MAX_IMAGE_PIXELS = 40_000_000
    WORKER_TIMEOUT_SECONDS = 120.0
    WORKER_IDLE_TTL_SECONDS = 60.0

    _state_lock = threading.Lock()
    _infer_semaphore = threading.Semaphore(1)
    _model_hash_cache: Dict[Tuple[str, int, int], str] = {}
    _job_handle: Optional[int] = None
    _worker_proc: Any = None
    _req_queue: Any = None
    _res_queue: Any = None
    _worker_model_path: Optional[str] = None
    _ttl_timer: Optional[threading.Timer] = None
    _in_flight: bool = False
    _shutdown_registered: bool = False

    @classmethod
    def _candidate_model_dirs(cls) -> list[Path]:
        """Devuelve los directorios candidatos donde puede residir el modelo ONNX."""
        dirs: list[Path] = []
        u2net_home = os.environ.get("U2NET_HOME")
        if u2net_home:
            dirs.append(Path(u2net_home))

        if getattr(sys, "frozen", False):
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                dirs.append(Path(meipass) / "models")
                dirs.append(Path(meipass) / ".u2net")
            exe_dir = Path(sys.executable).parent
            dirs.append(exe_dir / "models")
            dirs.append(exe_dir / ".u2net")
        else:
            repo_root = Path(__file__).resolve().parent.parent
            dirs.append(repo_root / "models")
            dirs.append(repo_root / "assets" / "models")

        dirs.append(Path.home() / ".u2net")
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            dirs.append(Path(local_appdata) / "ArchiveConverter" / "models")
        return dirs

    @classmethod
    def find_local_model(cls, model_name: str = DEFAULT_MODEL) -> Optional[Path]:
        """Busca el modelo ONNX localmente en rutas empaquetadas, dev o de usuario."""
        filename = f"{model_name}.onnx"
        for d in cls._candidate_model_dirs():
            candidate = d / filename
            try:
                if candidate.is_file() and candidate.stat().st_size > 0:
                    return candidate
            except OSError:
                continue
        return None

    @classmethod
    def verify_model_integrity(
        cls,
        model_path: Path,
        expected_sha256: Optional[str] = None,
    ) -> str:
        """
        Verifica tamaño y SHA-256 de forma lazy y cachea el resultado en el proceso principal
        para evitar re-hashear ~176 MB cuando el worker se reinicia tras expirar su TTL.
        """
        try:
            st = model_path.stat()
        except OSError as err:
            raise BackgroundRemovalError(
                "MODEL_MISSING",
                f"No se pudo acceder al modelo '{model_path}': {err}",
            ) from err

        if st.st_size <= 0:
            raise BackgroundRemovalError(
                "MODEL_CORRUPT",
                f"El archivo del modelo '{model_path.name}' está vacío o corrupto.",
            )

        cache_key = (str(model_path.resolve()), st.st_mtime_ns, st.st_size)
        with cls._state_lock:
            cached = cls._model_hash_cache.get(cache_key)

        if cached is None:
            digest = hashlib.sha256()
            try:
                with open(model_path, "rb") as f:
                    while True:
                        chunk = f.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
            except OSError as err:
                raise BackgroundRemovalError(
                    "MODEL_CORRUPT",
                    f"Error al leer el modelo '{model_path.name}': {err}",
                ) from err
            cached = digest.hexdigest()
            with cls._state_lock:
                cls._model_hash_cache[cache_key] = cached

        if expected_sha256 is not None:
            expected = expected_sha256.strip().lower()
        elif "U2NET_EXPECTED_SHA256" in os.environ:
            expected = os.environ["U2NET_EXPECTED_SHA256"].strip().lower()
        else:
            expected = cls.U2NET_EXPECTED_SHA256.strip().lower()

        if expected and cached.lower() != expected:
            raise BackgroundRemovalError(
                "MODEL_CORRUPT",
                f"Checksum SHA-256 inválido para '{model_path.name}'.",
            )
        return cached

    @staticmethod
    def _is_offline(timeout: float = 1.5) -> bool:
        """Comprueba rápidamente si la máquina carece de conectividad saliente."""
        for host in ("github.com", "1.1.1.1"):
            try:
                with socket.create_connection((host, 443), timeout=timeout):
                    return False
            except OSError:
                continue
        return True

    @classmethod
    def check_model_availability(cls, model_name: str = DEFAULT_MODEL) -> Dict[str, Any]:
        """Devuelve un diagnóstico estructurado sobre la disponibilidad local del modelo IA."""
        local_path = cls.find_local_model(model_name)
        if local_path is not None:
            return {
                "available": True,
                "model_path": str(local_path),
                "offline": False,
                "message": f"Modelo '{model_name}' disponible localmente en {local_path}.",
            }

        offline = cls._is_offline()
        return {
            "available": False,
            "model_path": None,
            "offline": offline,
            "message": (
                f"Modelo de IA ({model_name}.onnx) no disponible localmente en el entorno portable."
            ),
        }

    @classmethod
    def _validate_output_dir_writable(cls, out_dir: Path) -> None:
        """Falla rápido con PERMISSION_DENIED si el directorio destino no es escribible."""
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=str(out_dir), prefix=".perm_chk_", delete=True):
                pass
        except PermissionError as err:
            raise BackgroundRemovalError(
                "PERMISSION_DENIED",
                f"El directorio de salida '{out_dir}' es de solo lectura o está protegido: {err}",
            ) from err
        except OSError as err:
            raise BackgroundRemovalError(
                "PERMISSION_DENIED",
                f"No se puede escribir en '{out_dir}': {err}",
            ) from err

    @classmethod
    def _cancel_ttl_timer_locked(cls) -> None:
        if cls._ttl_timer is not None:
            cls._ttl_timer.cancel()
            cls._ttl_timer = None

    @classmethod
    def _schedule_ttl_timer_locked(cls) -> None:
        cls._cancel_ttl_timer_locked()
        if cls._worker_proc is None or cls._in_flight:
            return
        timer = threading.Timer(cls.WORKER_IDLE_TTL_SECONDS, cls._on_ttl_expired)
        timer.daemon = True
        timer.start()
        cls._ttl_timer = timer

    @classmethod
    def _on_ttl_expired(cls) -> None:
        with cls._state_lock:
            if cls._in_flight:
                return
            cls._terminate_worker_locked(graceful=True)

    @classmethod
    def _terminate_worker_locked(cls, graceful: bool = True) -> None:
        cls._cancel_ttl_timer_locked()
        proc = cls._worker_proc
        req_q = cls._req_queue
        cls._worker_proc = None
        cls._req_queue = None
        cls._res_queue = None
        cls._worker_model_path = None

        if proc is not None:
            try:
                if graceful and req_q is not None and proc.is_alive():
                    req_q.put_nowait(None)
                    proc.join(timeout=2.0)
            except Exception:
                pass
            try:
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=2.0)
            except Exception:
                pass

    @classmethod
    def shutdown_worker(cls) -> None:
        """Detiene el proceso worker de forma segura al cerrar la aplicación."""
        with cls._state_lock:
            cls._terminate_worker_locked(graceful=True)

    @classmethod
    def _ensure_worker_locked(cls, model_path: Path) -> Tuple[Any, Any, Any]:
        if not cls._shutdown_registered:
            atexit.register(cls.shutdown_worker)
            cls._shutdown_registered = True

        if cls._job_handle is None:
            cls._job_handle = _win32_create_kill_on_close_job()

        model_str = str(model_path)
        if (
            cls._worker_proc is not None
            and cls._worker_proc.is_alive()
            and cls._worker_model_path == model_str
        ):
            return cls._worker_proc, cls._req_queue, cls._res_queue

        cls._terminate_worker_locked(graceful=False)
        ctx = multiprocessing.get_context("spawn")
        req_q = ctx.Queue()
        res_q = ctx.Queue()
        proc = ctx.Process(
            target=_worker_loop,
            args=(req_q, res_q, model_str),
            daemon=True,
        )
        proc.start()
        _win32_assign_pid_to_job(cls._job_handle, proc.pid)

        cls._worker_proc = proc
        cls._req_queue = req_q
        cls._res_queue = res_q
        cls._worker_model_path = model_str
        return proc, req_q, res_q

    @classmethod
    def remove_background_structured(
        cls,
        input_path: str | Path,
        output_path: Optional[str | Path] = None,
        output_dir: Optional[str | Path] = None,
        wait_if_busy: bool = True,
    ) -> Dict[str, Any]:
        """
        Punto de entrada principal aislado: valida ruta, permisos e integridad del modelo,
        y delega decodificación + inferencia ONNX al subproceso worker.
        """
        in_p = Path(input_path).resolve()
        if not in_p.is_file():
            raise BackgroundRemovalError(
                "UNSUPPORTED_FORMAT",
                f"Archivo de imagen no encontrado: {in_p}",
            )

        if in_p.suffix.lower() not in cls.SUPPORTED_INPUTS:
            supported = ", ".join(sorted(cls.SUPPORTED_INPUTS))
            raise BackgroundRemovalValueError(
                "UNSUPPORTED_FORMAT",
                f"Formato no soportado para quitar fondo: {in_p.suffix}. Formatos compatibles: {supported}",
            )

        explicit_out: Optional[Path] = Path(output_path).resolve() if output_path else None
        dest_dir = explicit_out.parent if explicit_out is not None else (
            Path(output_dir).resolve() if output_dir else in_p.parent
        )
        cls._validate_output_dir_writable(dest_dir)

        model_path = cls.find_local_model(cls.DEFAULT_MODEL)
        if model_path is None:
            raise BackgroundRemovalError(
                "MODEL_MISSING",
                f"Modelo de IA ({cls.DEFAULT_MODEL}.onnx) no disponible localmente en el entorno portable.",
            )
        cls.verify_model_integrity(model_path)

        acquired = cls._infer_semaphore.acquire(blocking=wait_if_busy)
        if not acquired:
            raise BackgroundRemovalError(
                "BUSY",
                "Ya hay una eliminación de fondo en curso. Intenta de nuevo en unos segundos.",
            )

        try:
            with cls._state_lock:
                cls._cancel_ttl_timer_locked()
                cls._in_flight = True
                proc, req_q, res_q = cls._ensure_worker_locked(model_path)

            req_q.put((
                str(in_p),
                str(dest_dir),
                str(explicit_out) if explicit_out is not None else None,
            ))

            deadline = time.monotonic() + cls.WORKER_TIMEOUT_SECONDS
            result = None
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    with cls._state_lock:
                        cls._terminate_worker_locked(graceful=False)
                    raise BackgroundRemovalError(
                        "WORKER_TIMEOUT",
                        f"La inferencia de IA superó el tiempo límite de {int(cls.WORKER_TIMEOUT_SECONDS)}s.",
                    )
                try:
                    result = res_q.get(timeout=min(0.5, remaining))
                    break
                except queue.Empty:
                    if not proc.is_alive():
                        with cls._state_lock:
                            exit_code = proc.exitcode
                            cls._terminate_worker_locked(graceful=False)
                        raise BackgroundRemovalError(
                            "WORKER_CRASHED",
                            f"El subproceso de inferencia terminó inesperadamente (exitcode={exit_code}).",
                        )
                except (EOFError, BrokenPipeError, OSError) as err:
                    with cls._state_lock:
                        cls._terminate_worker_locked(graceful=False)
                    raise BackgroundRemovalError(
                        "WORKER_CRASHED",
                        f"El subproceso de inferencia terminó inesperadamente: {err}",
                    ) from err

            if not isinstance(result, dict):
                with cls._state_lock:
                    cls._terminate_worker_locked(graceful=False)
                raise BackgroundRemovalError(
                    "WORKER_CRASHED",
                    "Respuesta inválida del subproceso de inferencia.",
                )

            if not result.get("ok"):
                if not proc.is_alive():
                    with cls._state_lock:
                        cls._terminate_worker_locked(graceful=False)
                raise BackgroundRemovalError(
                    result.get("error_code") or "PROCESSING_ERROR",
                    result.get("message") or "Error al procesar la imagen.",
                )

            return result
        finally:
            with cls._state_lock:
                cls._in_flight = False
                cls._schedule_ttl_timer_locked()
            cls._infer_semaphore.release()

    @classmethod
    def remove_background(
        cls,
        input_path: str | Path,
        output_path: Optional[str | Path] = None,
    ) -> Path:
        """Compatibilidad con llamadas existentes que esperan Path como retorno."""
        res = cls.remove_background_structured(input_path=input_path, output_path=output_path)
        return Path(res["output_path"])
