from pathlib import Path
from typing import Optional
from PIL import Image


class BackgroundRemover:
    """
    Eliminación de fondo de imágenes por IA en local usando rembg (U2-Net / BiRefNet).
    Devuelve un archivo PNG con canal alfa transparente y bordes limpios.
    Utiliza una sesión persistente para evitar recargar el modelo ONNX en cada operación.
    """

    SUPPORTED_INPUTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
    _session = None

    @classmethod
    def get_session(cls):
        """Obtiene o reutiliza la sesión ONNX en memoria para máxima velocidad."""
        if cls._session is None:
            try:
                from rembg import new_session
                cls._session = new_session()
            except Exception:
                pass
        return cls._session

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

        session = cls.get_session()

        with Image.open(in_p) as img:
            # Asegurar formato compatible y reutilizar sesión si está disponible
            if session is not None:
                output_img = remove(img, session=session)
            else:
                output_img = remove(img)
            output_img.save(out_p, format="PNG")

        return out_p
