from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Set
import time


@dataclass
class ConversionResult:
    """Standard result returned by any conversion operation."""
    success: bool
    output_path: Optional[Path] = None
    error_message: Optional[str] = None
    elapsed_seconds: float = 0.0


class BaseConverter(ABC):
    """Abstract base class that all file converters must implement."""

    @property
    @abstractmethod
    def supported_inputs(self) -> Set[str]:
        """Set of supported input file extensions (including leading dot, e.g. {'.png', '.jpg'})."""
        pass

    @property
    @abstractmethod
    def supported_outputs(self) -> Set[str]:
        """Set of supported output file extensions (including leading dot, e.g. {'.pdf', '.webp'})."""
        pass

    def can_convert(self, input_extension: str, output_extension: str) -> bool:
        """Checks if this converter can handle the requested transition."""
        in_ext = input_extension.lower() if input_extension.startswith(".") else f".{input_extension.lower()}"
        out_ext = output_extension.lower() if output_extension.startswith(".") else f".{output_extension.lower()}"
        return in_ext in self.supported_inputs and out_ext in self.supported_outputs

    def convert(
        self,
        input_path: str | Path,
        output_format: str,
        output_path: Optional[str | Path] = None,
        **kwargs
    ) -> ConversionResult:
        """
        Executes conversion with timing and error isolation.
        Wraps internal `_do_convert` method.
        """
        start_time = time.perf_counter()
        in_path = Path(input_path).resolve()
        
        # Validation
        if not in_path.exists():
            return ConversionResult(
                success=False,
                error_message=f"El archivo de entrada no existe: {in_path}",
                elapsed_seconds=0.0
            )

        target_ext = output_format.lower() if output_format.startswith(".") else f".{output_format.lower()}"
        
        if not self.can_convert(in_path.suffix, target_ext):
            return ConversionResult(
                success=False,
                error_message=f"Conversión no soportada de {in_path.suffix} hacia {target_ext}",
                elapsed_seconds=0.0
            )

        if output_path is None:
            out_path = in_path.with_suffix(target_ext)
            # Avoid overwriting input if input and output have same extension
            if out_path == in_path:
                out_path = in_path.with_stem(f"{in_path.stem}_converted").with_suffix(target_ext)
        else:
            out_path = Path(output_path).resolve()

        # Ensure destination directory exists
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            generated_path = self._do_convert(in_path, out_path, target_ext, **kwargs)
            elapsed = time.perf_counter() - start_time
            return ConversionResult(
                success=True,
                output_path=generated_path or out_path,
                elapsed_seconds=round(elapsed, 3)
            )
        except Exception as exc:
            elapsed = time.perf_counter() - start_time
            return ConversionResult(
                success=False,
                error_message=str(exc),
                elapsed_seconds=round(elapsed, 3)
            )

    @abstractmethod
    def _do_convert(self, input_path: Path, output_path: Path, target_ext: str, **kwargs) -> Path:
        """Internal implementation of the conversion logic."""
        pass
