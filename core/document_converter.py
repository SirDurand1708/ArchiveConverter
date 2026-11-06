from pathlib import Path
from typing import Set, Optional
from .base import BaseConverter


class DocumentConverter(BaseConverter):
    """
    Handles document conversions:
    - PDF -> DOCX (True structural reconstruction using pdf2docx, not flat images)
    - DOCX -> PDF (High fidelity conversion using docx2pdf / Word COM automation)
    - PDF -> PNG / JPG (Renders pages to images via PyMuPDF)
    """

    INPUTS: Set[str] = {".pdf", ".docx"}
    OUTPUTS: Set[str] = {".pdf", ".docx", ".png", ".jpg"}

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
        dpi: int = 150,
        **kwargs
    ) -> Path:
        in_ext = input_path.suffix.lower()
        out_ext = target_ext.lower()

        # 1. PDF -> DOCX (Semantic/Structural conversion)
        if in_ext == ".pdf" and out_ext == ".docx":
            from pdf2docx import Converter
            cv = Converter(str(input_path))
            try:
                cv.convert(str(output_path), start=0, end=None)
            finally:
                cv.close()
            return output_path

        # 2. DOCX -> PDF
        if in_ext == ".docx" and out_ext == ".pdf":
            from docx2pdf import convert as docx_to_pdf
            docx_to_pdf(str(input_path), str(output_path))
            return output_path

        # 3. PDF -> PNG or JPG (Render pages)
        if in_ext == ".pdf" and out_ext in {".png", ".jpg"}:
            import pymupdf
            doc = pymupdf.open(str(input_path))
            try:
                # If single page, save directly to output_path
                # If multi-page, save as output_stem_page_1.png, etc.
                total_pages = len(doc)
                zoom = dpi / 72.0
                mat = pymupdf.Matrix(zoom, zoom)

                if total_pages == 1:
                    page = doc[0]
                    pix = page.get_pixmap(matrix=mat)
                    pix.save(str(output_path))
                    return output_path
                else:
                    # Multi-page export
                    base_dir = output_path.parent
                    stem = output_path.stem
                    first_page_path = None
                    for page_num in range(total_pages):
                        page = doc[page_num]
                        pix = page.get_pixmap(matrix=mat)
                        page_file = base_dir / f"{stem}_page_{page_num + 1}{out_ext}"
                        pix.save(str(page_file))
                        if first_page_path is None:
                            first_page_path = page_file
                    return first_page_path or output_path
            finally:
                doc.close()

        raise NotImplementedError(f"No hay implementación para {in_ext} -> {out_ext}")
