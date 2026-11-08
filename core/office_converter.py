import os
import shutil
import subprocess
from pathlib import Path
from typing import Set, Optional, List
from .base import BaseConverter


class OfficeConverter(BaseConverter):
    """
    Convierte archivos de Microsoft Office (Excel y PowerPoint) a PDF:
    - Excel (.xlsx, .xls) -> PDF con auto-ajuste inteligente de columnas y orientación.
    - PowerPoint (.pptx, .ppt) -> PDF con diapositivas en alta fidelidad vectorial.

    Implementa una arquitectura híbrida de 3 niveles:
    1. Microsoft Office COM Automation (para fidelidad nativa).
    2. Fallback a LibreOffice headless si está disponible.
    3. Fallback puro en Python (OpenPyXL + ReportLab) para Excel que garantiza
       que la conversión SIEMPRE funcione, incluso sin impresoras o sin Office instalado.
    """

    INPUTS: Set[str] = {".xlsx", ".xls", ".pptx", ".ppt"}
    OUTPUTS: Set[str] = {".pdf"}

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
        auto_fit: bool = True,
        orientation: str = "auto",
        **kwargs
    ) -> Path:
        in_ext = input_path.suffix.lower()

        if in_ext in {".xlsx", ".xls"}:
            return self._convert_excel_to_pdf(input_path, output_path, auto_fit, orientation)
        elif in_ext in {".pptx", ".ppt"}:
            return self._convert_powerpoint_to_pdf(input_path, output_path)

        raise NotImplementedError(f"Conversión no soportada para {in_ext} -> {target_ext}")

    # ================= Excel a PDF =================

    def _convert_excel_to_pdf(
        self,
        input_path: Path,
        output_path: Path,
        auto_fit: bool = True,
        orientation: str = "auto"
    ) -> Path:
        # Intento 1: Office COM (si tiene Excel y controladores de impresora configurados)
        try:
            return self._excel_via_com(input_path, output_path, auto_fit, orientation)
        except Exception as com_err:
            # Intento 2: LibreOffice (si está instalado)
            libreoffice = self._find_libreoffice()
            if libreoffice:
                try:
                    return self._convert_via_libreoffice(libreoffice, input_path, output_path)
                except Exception:
                    pass

            # Intento 3: Motor puro en Python (OpenPyXL + ReportLab) con auto-ajuste garantizado
            return self._excel_via_reportlab(input_path, output_path, auto_fit, orientation)

    def _excel_via_com(
        self,
        input_path: Path,
        output_path: Path,
        auto_fit: bool,
        orientation: str
    ) -> Path:
        import win32com.client
        import pythoncom

        pythoncom.CoInitialize()
        excel = None
        wb = None
        try:
            xlTypePDF = 0
            xlPortrait = 1
            xlLandscape = 2

            excel = win32com.client.DispatchEx("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False
            excel.ScreenUpdating = False

            wb = excel.Workbooks.Open(str(input_path.resolve()), ReadOnly=True)

            for ws in wb.Worksheets:
                used_cols = 0
                try:
                    used_cols = ws.UsedRange.Columns.Count
                except Exception:
                    pass

                # Orientación inteligente
                if orientation == "auto":
                    if used_cols > 6:
                        ws.PageSetup.Orientation = xlLandscape
                    else:
                        ws.PageSetup.Orientation = xlPortrait
                elif orientation == "landscape":
                    ws.PageSetup.Orientation = xlLandscape
                elif orientation == "portrait":
                    ws.PageSetup.Orientation = xlPortrait

                # Auto-ajuste de columnas al ancho de la hoja
                if auto_fit:
                    ws.PageSetup.Zoom = False
                    ws.PageSetup.FitToPagesWide = 1
                    ws.PageSetup.FitToPagesTall = False

            wb.ExportAsFixedFormat(xlTypePDF, str(output_path.resolve()))
            return output_path
        finally:
            if wb:
                try:
                    wb.Close(SaveChanges=False)
                except Exception:
                    pass
            if excel:
                try:
                    excel.Quit()
                except Exception:
                    pass
            pythoncom.CoUninitialize()

    def _excel_via_reportlab(
        self,
        input_path: Path,
        output_path: Path,
        auto_fit: bool = True,
        orientation: str = "auto"
    ) -> Path:
        """
        Motor alternativo 100% autónomo y offline para convertir Excel a PDF.
        Garantiza que todas las columnas encajen en el ancho de la hoja sin cortarse.
        """
        import openpyxl
        from reportlab.lib import pagesizes, colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

        wb = openpyxl.load_workbook(str(input_path), data_only=True)
        elements = []
        styles = getSampleStyleSheet()

        # Estilo para celdas con ajuste de línea
        cell_style = ParagraphStyle(
            'CellText',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=8,
            leading=10,
            textColor=colors.HexColor('#0F172A')
        )
        header_style = ParagraphStyle(
            'HeaderCellText',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=8.5,
            leading=11,
            textColor=colors.white
        )
        sheet_title_style = ParagraphStyle(
            'SheetTitle',
            parent=styles['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=13,
            leading=16,
            textColor=colors.HexColor('#1E293B'),
            spaceAfter=8
        )

        overall_max_cols = 0
        all_sheets_data = []

        for sheet in wb.worksheets:
            rows = []
            for row in sheet.iter_rows(values_only=True):
                if any(cell is not None for cell in row):
                    rows.append([str(c) if c is not None else "" for c in row])
            if rows:
                max_c = max(len(r) for r in rows)
                overall_max_cols = max(overall_max_cols, max_c)
                all_sheets_data.append((sheet.title, rows, max_c))

        if not all_sheets_data:
            raise ValueError("El archivo Excel no contiene datos para convertir.")

        # Determinar orientación de página
        if orientation == "landscape" or (orientation == "auto" and overall_max_cols > 6):
            page_size = pagesizes.landscape(pagesizes.A4)
        else:
            page_size = pagesizes.portrait(pagesizes.A4)

        margin = 28
        usable_width = page_size[0] - (margin * 2)

        for sheet_title, raw_rows, num_cols in all_sheets_data:
            if len(all_sheets_data) > 1:
                elements.append(Paragraph(f"Hoja: {sheet_title}", sheet_title_style))

            # Calcular anchos proporcionales de columnas basados en longitud de texto
            col_max_lengths = [3] * num_cols
            for row in raw_rows:
                for c_idx, val in enumerate(row):
                    if c_idx < num_cols:
                        col_max_lengths[c_idx] = max(col_max_lengths[c_idx], min(len(val), 40))

            total_weight = sum(col_max_lengths) or 1
            if auto_fit:
                col_widths = [(weight / total_weight) * usable_width for weight in col_max_lengths]
            else:
                col_widths = [usable_width / num_cols] * num_cols

            # Empaquetar celdas como Paragraphs para salto de línea automático
            table_data = []
            for r_idx, row in enumerate(raw_rows):
                formatted_row = []
                # Rellenar columnas faltantes si las hay
                row_vals = list(row) + [""] * (num_cols - len(row))
                for c_idx, val in enumerate(row_vals[:num_cols]):
                    st = header_style if r_idx == 0 else cell_style
                    formatted_row.append(Paragraph(val, st))
                table_data.append(formatted_row)

            t = Table(table_data, colWidths=col_widths, repeatRows=1)
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E293B')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ]))
            elements.append(t)
            elements.append(Spacer(1, 15))

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=page_size,
            leftMargin=margin,
            rightMargin=margin,
            topMargin=margin,
            bottomMargin=margin
        )
        doc.build(elements)
        return output_path

    # ================= PowerPoint a PDF =================

    def _convert_powerpoint_to_pdf(self, input_path: Path, output_path: Path) -> Path:
        """Convierte presentaciones PPT / PPTX a PDF con fidelidad vectorial nativa."""
        try:
            return self._powerpoint_via_com(input_path, output_path)
        except Exception as com_err:
            libreoffice = self._find_libreoffice()
            if libreoffice:
                return self._convert_via_libreoffice(libreoffice, input_path, output_path)
            raise RuntimeError(
                f"No se pudo convertir la presentación: {com_err}. "
                "Asegúrate de tener Microsoft PowerPoint o LibreOffice instalado."
            )

    def _powerpoint_via_com(self, input_path: Path, output_path: Path) -> Path:
        import win32com.client
        import pythoncom

        pythoncom.CoInitialize()
        ppt = None
        pres = None
        try:
            ppSaveAsPDF = 32

            ppt = win32com.client.DispatchEx("PowerPoint.Application")
            pres = ppt.Presentations.Open(str(input_path.resolve()), WithWindow=False, ReadOnly=True)
            pres.SaveAs(str(output_path.resolve()), ppSaveAsPDF)
            return output_path
        finally:
            if pres:
                try:
                    pres.Close()
                except Exception:
                    pass
            if ppt:
                try:
                    ppt.Quit()
                except Exception:
                    pass
            pythoncom.CoUninitialize()

    # ================= Fallback LibreOffice =================

    def _find_libreoffice(self) -> Optional[str]:
        soffice = shutil.which("soffice")
        if soffice:
            return soffice

        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "LibreOffice" / "program" / "soffice.exe",
        ]
        for c in candidates:
            p = Path(c)
            if p.exists():
                return str(p)
        return None

    def _convert_via_libreoffice(self, soffice_path: str, input_path: Path, output_path: Path) -> Path:
        out_dir = output_path.parent
        cmd = [
            soffice_path,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(input_path)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        if res.returncode != 0:
            raise RuntimeError(f"Error de LibreOffice: {res.stderr.decode('utf-8', errors='ignore')}")

        expected = out_dir / f"{input_path.stem}.pdf"
        if expected.exists() and expected != output_path:
            shutil.move(str(expected), str(output_path))

        return output_path
