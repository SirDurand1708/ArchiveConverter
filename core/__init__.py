"""ArchiveConverter Core Package."""
from .base import BaseConverter, ConversionResult
from .image_converter import ImageConverter
from .document_converter import DocumentConverter
from .office_converter import OfficeConverter
from .manager import ConverterManager
from .pdf_tools import PDFToolkit
from .bg_remover import BackgroundRemover, BackgroundRemovalError, BackgroundRemovalValueError
from .settings import SettingsManager
from .single_instance import SingleInstanceManager
from .diagnostics import init_logging, export_diagnostic_report, shutdown_logging
from .ocr_engine import OCREngine
from .updater import (
    APP_VERSION,
    check_for_updates,
    download_update,
    apply_update_and_restart,
    verify_release_sha256,
    is_installed_mode,
)

__all__ = [
    "BaseConverter",
    "ConversionResult",
    "ImageConverter",
    "DocumentConverter",
    "OfficeConverter",
    "ConverterManager",
    "PDFToolkit",
    "BackgroundRemover",
    "BackgroundRemovalError",
    "BackgroundRemovalValueError",
    "SettingsManager",
    "SingleInstanceManager",
    "OCREngine",
    "init_logging",
    "export_diagnostic_report",
    "shutdown_logging",
    "APP_VERSION",
    "check_for_updates",
    "download_update",
    "apply_update_and_restart",
    "verify_release_sha256",
    "is_installed_mode",
]
