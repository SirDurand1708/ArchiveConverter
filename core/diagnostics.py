import getpass
import logging
import os
import platform
import re
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


_LOG_LOCK = threading.Lock()
_LOGGER_INITIALIZED = False


def get_log_file_path() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    base = Path(local_appdata) if local_appdata else (Path.home() / ".local" / "share")
    return base / "ArchiveConverter" / "logs" / "app.log"


def init_logging(is_primary: bool = True, log_path: Optional[Path] = None) -> logging.Logger:
    """
    Inicializa el RotatingFileHandler únicamente en la instancia primaria
    para evitar PermissionError durante la rotación en Windows.
    """
    global _LOGGER_INITIALIZED
    logger = logging.getLogger("ArchiveConverter")
    logger.setLevel(logging.INFO)

    if not is_primary:
        return logger

    with _LOG_LOCK:
        if _LOGGER_INITIALIZED:
            return logger

        target = Path(log_path) if log_path else get_log_file_path()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                str(target),
                maxBytes=2 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            handler.setFormatter(fmt)
            logger.addHandler(handler)
            _LOGGER_INITIALIZED = True
        except OSError:
            pass

    return logger


def sanitize_log_text(text: str) -> str:
    """Enmascara nombre de usuario del SO y rutas completas de archivos personales."""
    if not text:
        return ""
    # Enmascarar rutas Windows/POSIX dejando únicamente extensión para diagnóstico sin PII
    out = re.sub(
        r"(?:[A-Za-z]:\\|\\\\[^\\\s]+\\)[^\r\n\"'<>|]+?(\.[A-Za-z0-9]{1,8})\b",
        r"<FILE\1>",
        text,
    )
    try:
        user = getpass.getuser()
        if user and len(user) > 1:
            out = re.sub(
                rf"([\\/:])({re.escape(user)})([\\/:])",
                r"\1<USER>\3",
                out,
                flags=re.IGNORECASE,
            )
            out = re.sub(rf"\b{re.escape(user)}\b", "<USER>", out, flags=re.IGNORECASE)
    except Exception:
        pass
    return out


def shutdown_logging() -> None:
    """Cierra y libera handlers de ArchiveConverter (útil en tests y apagado limpio)."""
    global _LOGGER_INITIALIZED
    with _LOG_LOCK:
        logger = logging.getLogger("ArchiveConverter")
        for h in list(logger.handlers):
            try:
                h.close()
            except Exception:
                pass
            logger.removeHandler(h)
        _LOGGER_INITIALIZED = False


def export_diagnostic_report(
    output_path: Optional[Path] = None,
    app_version: str = "unknown",
    log_path: Optional[Path] = None,
) -> Path:
    """Genera un reporte de diagnóstico offline sanitizado (máx. últimas 150 líneas de log)."""
    target_log = Path(log_path) if log_path else get_log_file_path()
    if output_path is None:
        desktop = Path.home() / "Desktop"
        dest_dir = desktop if desktop.is_dir() else Path.home()
        output_path = dest_dir / "ArchiveConverter_diagnostico.txt"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    mem_info = "no disponible"
    try:
        import psutil
        vm = psutil.virtual_memory()
        mem_info = f"total={vm.total // (1024 ** 2)} MB, disponible={vm.available // (1024 ** 2)} MB ({vm.percent}% usado)"
    except Exception:
        pass

    ai_status = "desconocido"
    try:
        from .bg_remover import BackgroundRemover
        st = BackgroundRemover.check_model_availability()
        ai_status = f"available={st.get('available')}, offline={st.get('offline')}"
    except Exception as err:
        ai_status = f"error={err}"

    tail_lines = []
    if target_log.is_file():
        try:
            lines = target_log.read_text(encoding="utf-8", errors="replace").splitlines()
            tail_lines = [sanitize_log_text(ln) for ln in lines[-150:]]
        except OSError as err:
            tail_lines = [f"<No se pudo leer el log: {err}>"]
    else:
        tail_lines = ["<Sin registros previos en app.log>"]

    report = [
        "=== ArchiveConverter Diagnostic Report ===",
        f"App Version: {app_version}",
        f"OS: {platform.system()} {platform.release()} ({platform.machine()})",
        f"Python: {platform.python_version()}",
        f"RAM: {mem_info}",
        f"AI Model Status: {ai_status}",
        "",
        "=== Ultimas 150 lineas de log (sanitizadas) ===",
        *tail_lines,
        "",
    ]
    output_path.write_text("\n".join(report), encoding="utf-8")
    return output_path
