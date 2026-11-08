import unittest
from pathlib import Path
import pymupdf
import openpyxl
from pptx import Presentation
from pptx.util import Inches, Pt

from core import ConverterManager


class TestOfficeConverters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = ConverterManager()
        cls.test_dir = Path(__file__).parent / "sample_files"
        cls.output_dir = Path(__file__).parent / "output_files"
        cls.test_dir.mkdir(parents=True, exist_ok=True)
        cls.output_dir.mkdir(parents=True, exist_ok=True)

        # 1. Generate Wide Excel sample (8 columns)
        cls.excel_path = cls.test_dir / "sample_sheet.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Reporte_Financiero"

        headers = ["ID", "Nombre", "Departamento", "Cargo", "Ciudad", "Sueldo", "Bono", "Total"]
        ws.append(headers)
        for i in range(1, 15):
            ws.append([f"EMP{i:03d}", f"Empleado {i}", "Tecnologia", "Ingeniero", "Madrid", 3500 + i*100, 500, 4000 + i*100])
        wb.save(cls.excel_path)
        wb.close()

        # 2. Generate PowerPoint sample (2 slides)
        cls.pptx_path = cls.test_dir / "sample_presentation.pptx"
        prs = Presentation()
        # Slide 1
        slide1 = prs.slides.add_slide(prs.slide_layouts[0])
        slide1.shapes.title.text = "ArchiveConverter Presentation"
        slide1.placeholders[1].text = "Diapositiva 1: Introduccion al proyecto"

        # Slide 2
        slide2 = prs.slides.add_slide(prs.slide_layouts[1])
        slide2.shapes.title.text = "Caracteristicas Principales"
        slide2.placeholders[1].text = "100% Offline, Seguro y Privado"

        prs.save(cls.pptx_path)

    def test_excel_to_pdf_autofit(self):
        out = self.output_dir / "excel_converted.pdf"
        res = self.manager.convert_file(
            self.excel_path,
            "pdf",
            output_path=out,
            auto_fit=True,
            orientation="auto"
        )
        self.assertTrue(res.success, f"Fallo al convertir Excel a PDF: {res.error_message}")
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 0)

        # Inspect generated PDF with pymupdf
        with pymupdf.open(str(out)) as doc:
            self.assertGreaterEqual(len(doc), 1)
            first_page = doc[0]
            # Since cols=8 > 6, it should be in Landscape (width > height)
            self.assertGreater(first_page.rect.width, first_page.rect.height)

    def test_pptx_to_pdf(self):
        out = self.output_dir / "presentation_converted.pdf"
        res = self.manager.convert_file(
            self.pptx_path,
            "pdf",
            output_path=out
        )
        self.assertTrue(res.success, f"Fallo al convertir PPTX a PDF: {res.error_message}")
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 0)

        with pymupdf.open(str(out)) as doc:
            self.assertEqual(len(doc), 2)  # Exactly 2 slides converted into 2 pages!


if __name__ == "__main__":
    unittest.main()
