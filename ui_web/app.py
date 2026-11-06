from pathlib import Path
import webview
from .api import DesktopAPI


def run_modern_gui():
    """Lanza la aplicación de escritorio moderna con WebView2."""
    html_file = (Path(__file__).parent / "index.html").resolve()
    api = DesktopAPI()

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
