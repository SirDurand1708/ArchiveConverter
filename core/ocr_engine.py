import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pymupdf
from PIL import Image, ImageOps


class OCREngine:
    """
    Motor OCR local ligero basado en rapidocr_onnxruntime sobre CPUExecutionProvider.
    Procesa en streaming por página con tope máximo de 3500 px, soporta cancelación
    cooperativa y genera .txt, .docx o PDF buscable con capa de texto invisible.
    """

    MAX_RENDER_DIM = 3500
    DEFAULT_DPI = 200
    SUPPORTED_OUTPUTS = {"txt", "docx", "pdf"}

    _engine_lock = threading.Lock()
    _engine: Any = None

    @classmethod
    def get_engine(cls) -> Any:
        with cls._engine_lock:
            if cls._engine is None:
                try:
                    from rapidocr_onnxruntime import RapidOCR
                except ImportError as err:
                    raise RuntimeError(
                        "El módulo 'rapidocr_onnxruntime' no está instalado. "
                        "Instálalo con: pip install rapidocr-onnxruntime"
                    ) from err
                cls._engine = RapidOCR()
            return cls._engine

    @classmethod
    def _compute_render_matrix(cls, page: "pymupdf.Page", target_dpi: int = DEFAULT_DPI) -> "pymupdf.Matrix":
        zoom = float(target_dpi) / 72.0
        rect = page.rect
        max_side_pts = max(rect.width, rect.height, 1.0)
        if max_side_pts * zoom > cls.MAX_RENDER_DIM:
            zoom = cls.MAX_RENDER_DIM / max_side_pts
        return pymupdf.Matrix(zoom, zoom)

    @classmethod
    def _ocr_numpy_image(cls, img_arr: np.ndarray) -> List[Dict[str, Any]]:
        engine = cls.get_engine()
        result, _ = engine(img_arr)
        items: List[Dict[str, Any]] = []
        if not result:
            return items
        for entry in result:
            if not entry or len(entry) < 2:
                continue
            box, text = entry[0], str(entry[1])
            items.append({"box": box, "text": text})
        return items

    @classmethod
    def extract_text_from_image(
        cls,
        image_path: str | Path,
        cancel_event: Optional[threading.Event] = None,
    ) -> str:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("OCR cancelado por el usuario.")
        in_p = Path(image_path).resolve()
        with Image.open(in_p) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            if max(img.size) > cls.MAX_RENDER_DIM:
                img.thumbnail((cls.MAX_RENDER_DIM, cls.MAX_RENDER_DIM), Image.Resampling.LANCZOS)
            arr = np.asarray(img)
        items = cls._ocr_numpy_image(arr)
        return "\n".join(it["text"] for it in items if it["text"])

    @classmethod
    def process_pdf(
        cls,
        input_path: str | Path,
        output_format: str = "txt",
        output_path: Optional[str | Path] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Path:
        fmt = output_format.lower().lstrip(".")
        if fmt not in cls.SUPPORTED_OUTPUTS:
            raise ValueError(f"Formato de salida OCR no soportado: {output_format}")

        in_p = Path(input_path).resolve()
        if not in_p.is_file():
            raise FileNotFoundError(f"Archivo no encontrado: {in_p}")

        out_p = (
            Path(output_path).resolve()
            if output_path
            else in_p.with_stem(f"{in_p.stem}_ocr").with_suffix(f".{fmt}")
        )
        out_p.parent.mkdir(parents=True, exist_ok=True)

        if in_p.suffix.lower() != ".pdf":
            text = cls.extract_text_from_image(in_p, cancel_event=cancel_event)
            return cls._write_text_output(text, out_p, fmt)

        page_texts: List[str] = []
        with pymupdf.open(str(in_p)) as doc:
            if doc.is_encrypted:
                raise PermissionError(f"El archivo '{in_p.name}' está protegido con contraseña.")

            for page in doc:
                if cancel_event is not None and cancel_event.is_set():
                    raise InterruptedError("OCR cancelado por el usuario.")

                mat = cls._compute_render_matrix(page)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                try:
                    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                    items = cls._ocr_numpy_image(arr)
                finally:
                    pix = None

                if fmt == "pdf":
                    inv_mat = ~mat
                    derot = page.derotation_matrix
                    for item in items:
                        box = item["box"]
                        txt = item["text"]
                        if not txt or not box:
                            continue
                        x0, y0 = float(box[0][0]), float(box[3][1]) if len(box) > 3 else float(box[0][1])
                        pt = pymupdf.Point(x0, y0) * inv_mat * derot
                        page.insert_text(
                            pt,
                            txt,
                            fontsize=10,
                            fontname="helv",
                            render_mode=3,
                        )
                else:
                    page_texts.append("\n".join(it["text"] for it in items if it["text"]))

            if fmt == "pdf":
                if cancel_event is not None and cancel_event.is_set():
                    raise InterruptedError("OCR cancelado por el usuario.")
                from .pdf_tools import _safe_save_pdf
                _safe_save_pdf(doc, out_p, garbage=3, deflate=True)
                return out_p

        return cls._write_text_output("\n\n".join(page_texts), out_p, fmt)

    @staticmethod
    def _write_text_output(text: str, out_p: Path, fmt: str) -> Path:
        tmp_path: Optional[Path] = None
        try:
            if fmt == "txt":
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=str(out_p.parent),
                    prefix=".tmp_ocr_",
                    suffix=".txt",
                    delete=False,
                ) as f:
                    tmp_path = Path(f.name)
                    f.write(text)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(str(tmp_path), str(out_p))
                return out_p

            # fmt == "docx"
            from docx import Document
            doc = Document()
            for para in text.splitlines():
                doc.add_paragraph(para)
            with tempfile.NamedTemporaryFile(
                dir=str(out_p.parent),
                prefix=".tmp_ocr_",
                suffix=".docx",
                delete=False,
            ) as f:
                tmp_path = Path(f.name)
            doc.save(str(tmp_path))
            os.replace(str(tmp_path), str(out_p))
            return out_p
        finally:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
