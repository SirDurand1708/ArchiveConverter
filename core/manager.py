from pathlib import Path
from typing import List, Optional, Set
from .base import BaseConverter, ConversionResult
from .image_converter import ImageConverter
from .document_converter import DocumentConverter
from .office_converter import OfficeConverter


class ConverterManager:
    """
    Central hub that orchestrates all converter modules.
    Automatically finds the appropriate converter for any given file type.
    """

    def __init__(self):
        self.converters: List[BaseConverter] = [
            ImageConverter(),
            DocumentConverter(),
            OfficeConverter(),
        ]

    def register_converter(self, converter: BaseConverter) -> None:
        """Allows registering custom or future converters (e.g. Audio, Video, Data)."""
        self.converters.append(converter)

    def get_supported_target_formats(self, input_file: str | Path) -> Set[str]:
        """
        Given an input file, returns all available output formats.
        Crucial for UI dropdowns and auto-discovery.
        """
        path = Path(input_file)
        ext = path.suffix.lower()
        available_targets: Set[str] = set()

        for conv in self.converters:
            if ext in conv.supported_inputs:
                for target in conv.supported_outputs:
                    # Exclude identical format unless converting options
                    if target != ext:
                        available_targets.add(target.lstrip("."))

        return sorted(available_targets)

    def find_converter(self, input_ext: str, output_ext: str) -> Optional[BaseConverter]:
        """Finds the first converter capable of converting from input_ext to output_ext."""
        for conv in self.converters:
            if conv.can_convert(input_ext, output_ext):
                return conv
        return None

    def convert_file(
        self,
        input_path: str | Path,
        target_format: str,
        output_path: Optional[str | Path] = None,
        **kwargs
    ) -> ConversionResult:
        """
        High-level method: Automatically detects the right converter and runs conversion.
        """
        in_p = Path(input_path)
        out_fmt = target_format.lower() if target_format.startswith(".") else f".{target_format.lower()}"
        
        converter = self.find_converter(in_p.suffix, out_fmt)
        if not converter:
            return ConversionResult(
                success=False,
                error_message=f"No hay ningún convertidor registrado para {in_p.suffix} -> {out_fmt}",
                elapsed_seconds=0.0
            )

        return converter.convert(in_p, out_fmt, output_path=output_path, **kwargs)
