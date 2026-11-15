import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_SETTINGS: Dict[str, Any] = {
    "theme": "dark",
    "default_output_dir": None,
    "pdf_compression_mode": "balanced",
    "recursive_folder_scan": True,
}

_ALLOWED_THEMES = {"dark", "light"}
_ALLOWED_PDF_MODES = {"balanced", "aggressive_150", "aggressive_96"}


class SettingsManager:
    """Gestiona preferencias de usuario persistentes en %APPDATA%\\ArchiveConverter\\settings.json."""

    _lock = threading.Lock()

    @staticmethod
    def get_settings_path() -> Path:
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else (Path.home() / ".config")
        return base / "ArchiveConverter" / "settings.json"

    @classmethod
    def _sanitize(cls, raw: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(DEFAULT_SETTINGS)
        if not isinstance(raw, dict):
            return merged

        theme = raw.get("theme")
        if theme in _ALLOWED_THEMES:
            merged["theme"] = theme

        out_dir = raw.get("default_output_dir")
        if out_dir is None or (isinstance(out_dir, str) and out_dir.strip()):
            merged["default_output_dir"] = out_dir.strip() if isinstance(out_dir, str) else None

        pdf_mode = raw.get("pdf_compression_mode")
        if pdf_mode in _ALLOWED_PDF_MODES:
            merged["pdf_compression_mode"] = pdf_mode

        if isinstance(raw.get("recursive_folder_scan"), bool):
            merged["recursive_folder_scan"] = raw["recursive_folder_scan"]

        return merged

    @classmethod
    def load(cls, path: Optional[Path] = None) -> Dict[str, Any]:
        target = Path(path) if path else cls.get_settings_path()
        with cls._lock:
            if not target.is_file():
                return dict(DEFAULT_SETTINGS)
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
                return cls._sanitize(data)
            except Exception:
                return dict(DEFAULT_SETTINGS)

    @classmethod
    def save(cls, partial_updates: Dict[str, Any], path: Optional[Path] = None) -> Dict[str, Any]:
        target = Path(path) if path else cls.get_settings_path()
        with cls._lock:
            current = dict(DEFAULT_SETTINGS)
            if target.is_file():
                try:
                    current = cls._sanitize(json.loads(target.read_text(encoding="utf-8")))
                except Exception:
                    current = dict(DEFAULT_SETTINGS)

            if isinstance(partial_updates, dict):
                current.update(partial_updates)
            sanitized = cls._sanitize(current)

            target.parent.mkdir(parents=True, exist_ok=True)
            tmp_path: Optional[Path] = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=str(target.parent),
                    prefix=".tmp_settings_",
                    suffix=".json",
                    delete=False,
                ) as tmp_f:
                    tmp_path = Path(tmp_f.name)
                    json.dump(sanitized, tmp_f, indent=2, ensure_ascii=False)
                    tmp_f.flush()
                    os.fsync(tmp_f.fileno())
                os.replace(str(tmp_path), str(target))
            finally:
                if tmp_path is not None and tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass

            return sanitized
