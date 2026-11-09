import sys
from pathlib import Path
from typing import Optional
import webview
from .api import DesktopAPI


def get_html_path() -> Path:
    """Obtiene la ruta absoluta a index.html tanto en desarrollo como en ejecutable PyInstaller."""
    if hasattr(sys, '_MEIPASS'):
        p = Path(sys._MEIPASS) / "ui_web" / "index.html"
        if p.exists():
            return p.resolve()
        p2 = Path(sys._MEIPASS) / "index.html"
        if p2.exists():
            return p2.resolve()
    return (Path(__file__).parent / "index.html").resolve()


def run_modern_gui(initial_file: Optional[str] = None):
    """Lanza la aplicación de escritorio moderna con WebView2."""
    html_file = get_html_path()
    api = DesktopAPI(initial_file=initial_file)

    window = webview.create_window(
        title="ArchiveConverter - Tu Convertidor Privado y Offline",
        url=str(html_file),
        js_api=api,
        width=1020,
        height=680,
        min_size=(840, 560),
        background_color="#090D16"
    )
    api.set_window(window)
    webview.start()


if __name__ == "__main__":
    run_modern_gui()
