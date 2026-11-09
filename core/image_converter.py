from pathlib import Path
from typing import Set, Optional, Tuple
from PIL import Image
from .base import BaseConverter

# Registrar soporte nativo para fotos de iPhone (.heic, .heif)
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass


class ImageConverter(BaseConverter):
    """
    Maneja conversiones de imágenes incluyendo soporte nativo para fotos de iPhone (.heic, .heif),
    garantizando espacios de color limpios (RGBA -> RGB) y compresión inteligente.
    """

    INPUTS: Set[str] = {
        ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif", ".ico", ".heic", ".heif"
    }
    OUTPUTS: Set[str] = {
        ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".ico", ".pdf"
    }

    @property
    def supported_inputs(self) -> Set[str]:
        return self.INPUTS

    @property
    def supported_outputs(self) -> Set[str]:
        return self.OUTPUTS

    def _do_convert(
        self,
        input_path: Path,
        output_path: Path,
        target_ext: str,
        quality: int = 95,
        **kwargs
    ) -> Path:
        try:
            with Image.open(input_path) as img:
                out_ext = target_ext.lower()
                save_kwargs = {}

                # Formatos que requieren modo RGB sin canal alfa (fondo blanco)
                if out_ext in {".jpg", ".jpeg", ".pdf"}:
                    if img.mode in ("RGBA", "LA", "P"):
                        background = Image.new("RGB", img.size, (255, 255, 255))
                        alpha_channel = img.split()[-1] if img.mode in ("RGBA", "LA") else None
                        if alpha_channel:
                            background.paste(img, mask=alpha_channel)
                        else:
                            background.paste(img)
                        img = background
                    elif img.mode != "RGB":
                        img = img.convert("RGB")
                
                # Parámetros según formato
                if out_ext in {".jpg", ".jpeg", ".webp"}:
                    save_kwargs["quality"] = quality
                    save_kwargs["optimize"] = True
                elif out_ext == ".png":
                    save_kwargs["optimize"] = True
                elif out_ext == ".ico":
                    icon_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
                    save_kwargs["sizes"] = icon_sizes

                img.save(output_path, **save_kwargs)
                return output_path
        except Image.DecompressionBombError:
            raise ValueError("La imagen es excesivamente grande y excede los límites seguros de memoria.")

    @classmethod
    def compress_image(
        cls,
        input_path: str | Path,
        output_path: Optional[str | Path] = None,
        max_size_kb: Optional[int] = None,
        target_quality: int = 80
    ) -> Tuple[Path, int, int]:
        """
        Comprime una imagen reduciendo su peso.
        Si se especifica max_size_kb (ej: 1024 para 1MB), ajusta iterativamente
        la calidad y las dimensiones hasta cumplir el objetivo de tamaño.
        Devuelve: (output_path, tamaño_anterior_bytes, tamaño_nuevo_bytes)
        """
        in_p = Path(input_path).resolve()
        if not in_p.exists():
            raise FileNotFoundError(f"Archivo de imagen no encontrado: {in_p}")

        orig_size = in_p.stat().st_size
        out_ext = in_p.suffix.lower()
        if out_ext in {".heic", ".heif", ".bmp", ".tiff", ".tif"}:
            out_ext = ".jpg"  # Formato óptimo para compresión

        out_p = Path(output_path).resolve() if output_path else in_p.with_stem(f"{in_p.stem}_comprimido").with_suffix(out_ext)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        try:
            with Image.open(in_p) as img:
                # Asegurar modo RGB si se guarda como JPEG
                if out_ext in {".jpg", ".jpeg"} and img.mode in ("RGBA", "LA", "P"):
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    alpha = img.split()[-1] if img.mode in ("RGBA", "LA") else None
                    bg.paste(img, mask=alpha) if alpha else bg.paste(img)
                    img = bg
                elif img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")

                # Si no hay límite de tamaño, aplicar compresión simple por calidad
                if not max_size_kb:
                    save_kwargs = {"optimize": True}
                    if out_ext in {".jpg", ".jpeg", ".webp"}:
                        save_kwargs["quality"] = target_quality
                    img.save(out_p, **save_kwargs)
                    return out_p, orig_size, out_p.stat().st_size

                # Compresión adaptativa orientada a objetivo (Target Size en KB)
                target_bytes = max_size_kb * 1024
                current_quality = target_quality
                current_img = img.copy()

                for step in range(5):
                    save_kwargs = {"optimize": True}
                    if out_ext in {".jpg", ".jpeg", ".webp"}:
                        save_kwargs["quality"] = current_quality
                    current_img.save(out_p, **save_kwargs)

                    current_size = out_p.stat().st_size
                    if current_size <= target_bytes:
                        break

                    # Si aún pesa más de lo pedido, reducir calidad y luego dimensiones
                    if current_quality > 40:
                        current_quality -= 15
                    else:
                        # Reducir dimensiones al 80%
                        new_w = int(current_img.width * 0.8)
                        new_h = int(current_img.height * 0.8)
                        if new_w < 200 or new_h < 200:
                            break  # No reducir más para evitar distorsión
                        current_img = current_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

                return out_p, orig_size, out_p.stat().st_size
        except Image.DecompressionBombError:
            raise ValueError("La imagen es excesivamente grande y excede los límites seguros de memoria.")
