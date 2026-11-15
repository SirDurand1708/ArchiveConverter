"""ArchiveConverter Core Package."""
from .base import BaseConverter, ConversionResult
from .image_converter import ImageConverter
from .document_converter import DocumentConverter
from .office_converter import OfficeConverter
from .manager import ConverterManager
from .pdf_tools import PDFToolkit
from .bg_remover import BackgroundRemover, BackgroundRemovalError, BackgroundRemovalValueError
from .updater import (
    APP_VERSION,
    check_for_updates,
    download_update,
    apply_update_and_restart,
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
    "APP_VERSION",
    "check_for_updates",
    "download_update",
    "apply_update_and_restart",
]
