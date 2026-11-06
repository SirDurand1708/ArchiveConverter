import unittest
from pathlib import Path
from PIL import Image, ImageDraw
import pymupdf
from core import BackgroundRemover, PDFToolkit


class TestNewFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(__file__).parent / "sample_files"
        cls.output_dir = Path(__file__).parent / "output_files"
        cls.test_dir.mkdir(parents=True, exist_ok=True)
        cls.output_dir.mkdir(parents=True, exist_ok=True)

        # 1. Sample PDF
        cls.sample_pdf = cls.test_dir / "sample_for_watermark.pdf"
        doc = pymupdf.open()
        p = doc.new_page()
        p.insert_text((50, 100), "Documento para probar Marca de Agua y Firma.")
        doc.save(cls.sample_pdf)
        doc.close()

        # 2. Sample signature image (transparent PNG with black stroke)
        cls.sample_sig = cls.test_dir / "signature.png"
        img = Image.new("RGBA", (140, 60), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.line([(10, 40), (70, 15), (130, 40)], fill=(0, 0, 200, 255), width=3)
        img.save(cls.sample_sig)

    def test_watermark(self):
        out = self.output_dir / "watermarked.pdf"
        res = PDFToolkit.add_watermark(self.sample_pdf, "CONFIDENCIAL", output_path=out)
        self.assertTrue(res.exists())
        with pymupdf.open(str(res)) as doc:
            page = doc[0]
            text = page.get_text()
            self.assertIn("CONFIDENCIAL", text)

    def test_signature(self):
        out = self.output_dir / "signed.pdf"
        res = PDFToolkit.add_signature(
            self.sample_pdf,
            self.sample_sig,
            position="bottom-right",
            output_path=out
        )
        self.assertTrue(res.exists())
        with pymupdf.open(str(res)) as doc:
            page = doc[0]
            # Should contain embedded image
            imgs = page.get_images()
            self.assertGreaterEqual(len(imgs), 1)


if __name__ == "__main__":
    unittest.main()
