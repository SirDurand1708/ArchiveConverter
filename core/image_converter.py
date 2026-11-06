from pathlib import Path
from typing import Set, Optional
from PIL import Image
from .base import BaseConverter


class ImageConverter(BaseConverter):
    """
    Handles image-to-image and image-to-PDF conversions using Pillow.
    Guarantees color-space safety (e.g. RGBA -> RGB for JPEG/PDF).
    """

    INPUTS: Set[str] = {
        ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif", ".ico"
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
        with Image.open(input_path) as img:
            out_ext = target_ext.lower()
            save_kwargs = {}

            # Formats requiring RGB mode (no alpha channel)
            if out_ext in {".jpg", ".jpeg", ".pdf"}:
                if img.mode in ("RGBA", "LA", "P"):
                    # Create solid white background for transparent images
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    alpha_channel = img.split()[-1] if img.mode in ("RGBA", "LA") else None
                    if alpha_channel:
                        background.paste(img, mask=alpha_channel)
                    else:
                        background.paste(img)
                    img = background
                elif img.mode != "RGB":
                    img = img.convert("RGB")
            
            # Specific format parameters
            if out_ext in {".jpg", ".jpeg", ".webp"}:
                save_kwargs["quality"] = quality
                save_kwargs["optimize"] = True
            elif out_ext == ".png":
                save_kwargs["optimize"] = True
            elif out_ext == ".ico":
                # Ensure appropriate sizes for icon file
                icon_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
                save_kwargs["sizes"] = icon_sizes

            # Save converted file
            img.save(output_path, **save_kwargs)
            return output_path
