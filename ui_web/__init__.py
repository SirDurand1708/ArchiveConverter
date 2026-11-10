from .api import DesktopAPI


def run_modern_gui(*args, **kwargs):
    """Lanza la interfaz gráfica de usuario moderna."""
    from .app import run_modern_gui as _run
    return _run(*args, **kwargs)


__all__ = ["run_modern_gui", "DesktopAPI"]
