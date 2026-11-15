import os
import shutil
import subprocess
import threading
import gc
from pathlib import Path
from typing import Set, Optional, List, Any
from .base import BaseConverter

# Bloqueo global de exclusión mutua para automatización COM de Microsoft Office (STA)
# Evita colisiones de memoria, errores RPC_E_DISCONNECTED (0x80010108) y bloqueos en hilos concurrentes.
OFFICE_COM_LOCK = threading.RLock()


def _snapshot_pids(process_name: str) -> Set[int]:
    """Captura los PIDs activos de un ejecutable (ej: EXCEL.EXE) antes de lanzar COM."""
    pids: Set[int] = set()
    try:
        import psutil
        target = process_name.lower()
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name == target:
                    pids.add(int(proc.info["pid"]))
            except Exception:
                continue
    except Exception:
        pass
    return pids


def _resolve_com_pid(app_obj: Any, process_name: str, before_pids: Set[int]) -> Optional[int]:
    """Obtiene el PID exacto de la instancia COM recién creada vía HWND o delta de psutil."""
    try:
        import win32process
        hwnd = getattr(app_obj, "Hwnd", None) or getattr(app_obj, "HWND", None)
        if hwnd:
            _, pid = win32process.GetWindowThreadProcessId(int(hwnd))
            if pid and pid > 0:
                return int(pid)
    except Exception:
        pass

    try:
        after_pids = _snapshot_pids(process_name)
        new_pids = after_pids - before_pids
        if new_pids:
            return next(iter(new_pids))
    except Exception:
        pass
    return None


def _terminate_orphaned_pid(pid: Optional[int]) -> None:
    """
    Liquida de inmediato un proceso COM huérfano (EXCEL.EXE / POWERPNT.EXE)
    cuando ocurre un fallo, timeout o el proceso no cierra tras Quit().
    """
    if not pid or pid <= 0:
        return
    try:
        import psutil
        if psutil.pid_exists(pid):
            proc = psutil.Process(pid)
            if proc.is_running():
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except psutil.TimeoutExpired:
                    proc.kill()
        return
    except Exception:
        pass

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
        except Exception:
            pass


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

        with OFFICE_COM_LOCK:
            com_initialized = False
            try:
                pythoncom.CoInitialize()
                com_initialized = True
            except Exception:
                pass

            excel = None
            wb = None
            com_pid: Optional[int] = None
            com_failed = False
            before_pids = _snapshot_pids("EXCEL.EXE")
            try:
                xlTypePDF = 0
                xlPortrait = 1
                xlLandscape = 2

                excel = win32com.client.DispatchEx("Excel.Application")
                com_pid = _resolve_com_pid(excel, "EXCEL.EXE", before_pids)
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
            except Exception:
                com_failed = True
                raise
            finally:
                if 'ws' in locals():
                    del ws
                if wb is not None:
                    try:
                        wb.Close(SaveChanges=False)
                    except Exception:
                        pass
                    wb = None
                gc.collect()
                if excel is not None:
                    try:
                        excel.Quit()
                    except Exception:
                        com_failed = True

                # Deshabilitar faulthandler durante la liberación del stub COM desconectado
                # para evitar falsas alarmas VEH de RPC_E_DISCONNECTED (0x80010108) en Python/Windows.
                fh_enabled = False
                try:
                    import faulthandler
                    fh_enabled = faulthandler.is_enabled()
                    if fh_enabled:
                        faulthandler.disable()
                except Exception:
                    pass

                try:
                    excel = None
                    gc.collect()
                    if com_initialized:
                        try:
                            pythoncom.CoUninitialize()
                        except Exception:
                            pass
                finally:
                    if fh_enabled:
                        try:
                            faulthandler.enable()
                        except Exception:
                            pass

                # Si falló la exportación o Quit() falló, liquidar proceso EXCEL.EXE huérfano
                if com_failed and com_pid:
                    _terminate_orphaned_pid(com_pid)

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
        import html
        import openpyxl
        from reportlab.lib import pagesizes, colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

        wb = openpyxl.load_workbook(str(input_path), data_only=True)
        try:
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
        finally:
            wb.close()

        if not all_sheets_data:
            raise ValueError("El archivo Excel no contiene datos para convertir.")

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

        # Determinar orientación de página
        if orientation == "landscape" or (orientation == "auto" and overall_max_cols > 6):
            page_size = pagesizes.landscape(pagesizes.A4)
        else:
            page_size = pagesizes.portrait(pagesizes.A4)

        margin = 28
        usable_width = page_size[0] - (margin * 2)

        for sheet_title, raw_rows, num_cols in all_sheets_data:
            if len(all_sheets_data) > 1:
                elements.append(Paragraph(f"Hoja: {html.escape(sheet_title)}", sheet_title_style))

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
                    formatted_row.append(Paragraph(html.escape(val), st))
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

        with OFFICE_COM_LOCK:
            com_initialized = False
            try:
                pythoncom.CoInitialize()
                com_initialized = True
            except Exception:
                pass

            ppt = None
            pres = None
            com_pid: Optional[int] = None
            com_failed = False
            before_pids = _snapshot_pids("POWERPNT.EXE")
            try:
                ppSaveAsPDF = 32

                ppt = win32com.client.DispatchEx("PowerPoint.Application")
                com_pid = _resolve_com_pid(ppt, "POWERPNT.EXE", before_pids)
                pres = ppt.Presentations.Open(str(input_path.resolve()), WithWindow=False, ReadOnly=True)
                pres.SaveAs(str(output_path.resolve()), ppSaveAsPDF)
                return output_path
            except Exception:
                com_failed = True
                raise
            finally:
                if pres is not None:
                    try:
                        pres.Close()
                    except Exception:
                        pass
                    pres = None
                gc.collect()
                if ppt is not None:
                    try:
                        ppt.Quit()
                    except Exception:
                        com_failed = True

                fh_enabled = False
                try:
                    import faulthandler
                    fh_enabled = faulthandler.is_enabled()
                    if fh_enabled:
                        faulthandler.disable()
                except Exception:
                    pass

                try:
                    ppt = None
                    gc.collect()
                    if com_initialized:
                        try:
                            pythoncom.CoUninitialize()
                        except Exception:
                            pass
                finally:
                    if fh_enabled:
                        try:
                            faulthandler.enable()
                        except Exception:
                            pass

                # Si falló la exportación o Quit() falló, liquidar proceso POWERPNT.EXE huérfano
                if com_failed and com_pid:
                    _terminate_orphaned_pid(com_pid)

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
