import unittest
from pathlib import Path
import pymupdf
from PIL import Image, ImageDraw
from core import PDFToolkit


class TestPDFToolkit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(__file__).parent / "sample_files"
        cls.output_dir = Path(__file__).parent / "output_files"
        cls.test_dir.mkdir(parents=True, exist_ok=True)
        cls.output_dir.mkdir(parents=True, exist_ok=True)

        # Generate PDF 1 (with 2 pages)
        cls.pdf1 = cls.test_dir / "doc1.pdf"
        doc1 = pymupdf.open()
        p1 = doc1.new_page()
        p1.insert_text((50, 72), "Documento 1 - Pagina 1")
        p2 = doc1.new_page()
        p2.insert_text((50, 72), "Documento 1 - Pagina 2")
        doc1.save(cls.pdf1)
        doc1.close()

        # Generate PDF 2 (with 1 page and 1 embedded image)
        cls.pdf2 = cls.test_dir / "doc2.pdf"
        doc2 = pymupdf.open()
        p = doc2.new_page()
        p.insert_text((50, 72), "Documento 2 con imagen")
        
        # Create a small image in memory
        temp_img_path = cls.test_dir / "temp_embed.png"
        img = Image.new("RGB", (100, 100), color=(255, 0, 0))
        img.save(temp_img_path)
        p.insert_image(pymupdf.Rect(50, 100, 150, 200), filename=str(temp_img_path))
        
        doc2.save(cls.pdf2)
        doc2.close()
        temp_img_path.unlink(missing_ok=True)

    def test_merge(self):
        out = self.output_dir / "merged.pdf"
        res = PDFToolkit.merge([self.pdf1, self.pdf2], out)
        self.assertTrue(res.exists())
        with pymupdf.open(str(res)) as doc:
            self.assertEqual(len(doc), 3)  # 2 pages + 1 page

    def test_split_all_pages(self):
        split_dir = self.output_dir / "split_test"
        files = PDFToolkit.split_all_pages(self.pdf1, split_dir)
        self.assertEqual(len(files), 2)
        for f in files:
            self.assertTrue(f.exists())
            with pymupdf.open(str(f)) as doc:
                self.assertEqual(len(doc), 1)

    def test_split_range(self):
        out = self.output_dir / "range_1_to_1.pdf"
        res = PDFToolkit.split_range(self.pdf1, from_page=1, to_page=1, output_path=out)
        self.assertTrue(res.exists())
        with pymupdf.open(str(res)) as doc:
            self.assertEqual(len(doc), 1)

    def test_compress(self):
        out = self.output_dir / "compressed.pdf"
        res = PDFToolkit.compress(self.pdf1, out)
        self.assertTrue(res.exists())
        self.assertGreater(res.stat().st_size, 0)

    def test_extract_images(self):
        img_dir = self.output_dir / "extracted_imgs"
        extracted = PDFToolkit.extract_images(self.pdf2, img_dir)
        self.assertGreaterEqual(len(extracted), 1)
        self.assertTrue(extracted[0].exists())

    def test_rotate_pages(self):
        out = self.output_dir / "rotated.pdf"
        res = PDFToolkit.rotate_pages(self.pdf1, degrees=90, output_path=out)
        self.assertTrue(res.exists())
        with pymupdf.open(str(res)) as doc:
            self.assertEqual(doc[0].rotation, 90)

    def test_protect_and_unlock(self):
        pwd = "SuperSecretPassword123"
        protected_pdf = self.output_dir / "protected.pdf"
        PDFToolkit.protect(self.pdf1, user_password=pwd, output_path=protected_pdf)
        self.assertTrue(protected_pdf.exists())

        # Verify it requires password
        with pymupdf.open(str(protected_pdf)) as doc:
            self.assertTrue(doc.is_encrypted)
            self.assertFalse(doc.authenticate("WrongPassword"))
            self.assertTrue(doc.authenticate(pwd))

        # Now unlock it
        unlocked_pdf = self.output_dir / "unlocked.pdf"
        PDFToolkit.unlock(protected_pdf, password=pwd, output_path=unlocked_pdf)
        self.assertTrue(unlocked_pdf.exists())
        with pymupdf.open(str(unlocked_pdf)) as doc:
            self.assertFalse(doc.is_encrypted)


if __name__ == "__main__":
    unittest.main()
