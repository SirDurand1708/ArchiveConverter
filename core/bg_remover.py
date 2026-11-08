from pathlib import Path
from typing import Optional
from PIL import Image


class BackgroundRemover:
    """
    Eliminación de fondo de imágenes por IA en local usando rembg (U2-Net / BiRefNet).
    Devuelve un archivo PNG con canal alfa transparente y bordes limpios.
    """

    SUPPORTED_INPUTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}

    @classmethod
    def remove_background(
        cls,
        input_path: str | Path,
        output_path: Optional[str | Path] = None
    ) -> Path:
        # Carga perezosa (lazy import) para no ralentizar el inicio de la app
        from rembg import remove

        in_p = Path(input_path).resolve()
        if not in_p.exists():
            raise FileNotFoundError(f"Archivo de imagen no encontrado: {in_p}")

        if in_p.suffix.lower() not in cls.SUPPORTED_INPUTS:
            raise ValueError(f"Formato no soportado para quitar fondo: {in_p.suffix}")

        out_p = Path(output_path).resolve() if output_path else in_p.with_stem(f"{in_p.stem}_sin_fondo").with_suffix(".png")
        out_p.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(in_p) as img:
            # Asegurar formato compatible
            output_img = remove(img)
            output_img.save(out_p, format="PNG")

        return out_p
