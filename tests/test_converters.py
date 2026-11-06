import unittest
from pathlib import Path
from PIL import Image, ImageDraw
import pymupdf
import docx
from core import ConverterManager


class TestConverterCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = ConverterManager()
        cls.test_dir = Path(__file__).parent / "sample_files"
        cls.output_dir = Path(__file__).parent / "output_files"
        cls.test_dir.mkdir(parents=True, exist_ok=True)
        cls.output_dir.mkdir(parents=True, exist_ok=True)

        # 1. Generate sample PNG image
        cls.sample_png = cls.test_dir / "sample.png"
        img = Image.new("RGBA", (300, 300), color=(73, 109, 137, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([(50, 50), (250, 250)], fill=(255, 255, 0, 255))
        img.save(cls.sample_png)

        # 2. Generate sample PDF with text and table
        cls.sample_pdf = cls.test_dir / "sample_doc.pdf"
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text(
            (50, 72),
            "Documento de Prueba Oficial - ArchiveConverter\n\n"
            "Este es un parrafo de texto real con formato semantico.\n"
            "El objetivo es comprobar que pdf2docx extrae texto editable y no una simple imagen.",
            fontsize=12,
        )
        doc.save(cls.sample_pdf)
        doc.close()

    def test_image_to_webp(self):
        out = self.output_dir / "converted.webp"
        res = self.manager.convert_file(self.sample_png, "webp", output_path=out)
        self.assertTrue(res.success, f"Fallo al convertir a WEBP: {res.error_message}")
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 0)

    def test_image_to_pdf(self):
        out = self.output_dir / "converted_img.pdf"
        res = self.manager.convert_file(self.sample_png, "pdf", output_path=out)
        self.assertTrue(res.success, f"Fallo al convertir imagen a PDF: {res.error_message}")
        self.assertTrue(out.exists())

    def test_pdf_to_docx_structural(self):
        """Validates that PDF is converted to real editable DOCX with text."""
        out = self.output_dir / "converted_doc.docx"
        res = self.manager.convert_file(self.sample_pdf, "docx", output_path=out)
        self.assertTrue(res.success, f"Fallo al convertir PDF a DOCX: {res.error_message}")
        self.assertTrue(out.exists())
        
        # Verify Word document contains editable text
        doc = docx.Document(str(out))
        all_text = " ".join([p.text for p in doc.paragraphs])
        self.assertIn("Documento de Prueba Oficial", all_text)

    def test_pdf_to_images(self):
        out = self.output_dir / "rendered_page.png"
        res = self.manager.convert_file(self.sample_pdf, "png", output_path=out)
        self.assertTrue(res.success, f"Fallo al renderizar PDF a PNG: {res.error_message}")
        self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
