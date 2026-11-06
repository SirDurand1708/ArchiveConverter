from pathlib import Path
from typing import List, Optional, Sequence
import pymupdf


class PDFToolkit:
    """
    Herramientas avanzadas de manipulación de archivos PDF.
    - Unir (Merge) múltiples PDFs
    - Dividir (Split) PDF en páginas individuales o por rangos
    - Comprimir (Compress) reduciendo peso y limpiando objetos basura
    - Extraer imágenes incrustadas dentro del PDF
    - Rotar páginas (90, 180, 270 grados)
    - Proteger con contraseña (Cifrado AES-256) o desbloquear
    """

    @staticmethod
    def merge(pdf_paths: Sequence[str | Path], output_path: str | Path) -> Path:
        """Une múltiples archivos PDF en uno solo en el orden especificado."""
        out_p = Path(output_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)

        merged = pymupdf.open()
        try:
            for p in pdf_paths:
                file_p = Path(p).resolve()
                if not file_p.exists():
                    raise FileNotFoundError(f"Archivo no encontrado: {file_p}")
                with pymupdf.open(str(file_p)) as doc:
                    merged.insert_pdf(doc)
            
            merged.save(str(out_p))
            return out_p
        finally:
            merged.close()

    @staticmethod
    def split_all_pages(input_path: str | Path, output_dir: Optional[str | Path] = None) -> List[Path]:
        """Divide un PDF guardando cada página como un archivo PDF individual."""
        in_p = Path(input_path).resolve()
        out_d = Path(output_dir).resolve() if output_dir else in_p.parent
        out_d.mkdir(parents=True, exist_ok=True)

        generated_files: List[Path] = []
        with pymupdf.open(str(in_p)) as doc:
            total_pages = len(doc)
            for page_num in range(total_pages):
                new_doc = pymupdf.open()
                try:
                    new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
                    page_path = out_d / f"{in_p.stem}_pagina_{page_num + 1}.pdf"
                    new_doc.save(str(page_path))
                    generated_files.append(page_path)
                finally:
                    new_doc.close()

        return generated_files

    @staticmethod
    def split_range(
        input_path: str | Path,
        from_page: int,
        to_page: int,
        output_path: Optional[str | Path] = None
    ) -> Path:
        """
        Extrae un rango específico de páginas (índices 1-based, ej: página 1 a 3).
        """
        in_p = Path(input_path).resolve()
        out_p = Path(output_path).resolve() if output_path else in_p.with_stem(f"{in_p.stem}_pag_{from_page}-{to_page}")
        out_p.parent.mkdir(parents=True, exist_ok=True)

        with pymupdf.open(str(in_p)) as doc:
            total = len(doc)
            if from_page < 1 or to_page > total or from_page > to_page:
                raise ValueError(f"Rango inválido: {from_page}-{to_page}. El documento tiene {total} páginas.")

            new_doc = pymupdf.open()
            try:
                # pymupdf es 0-indexed
                new_doc.insert_pdf(doc, from_page=from_page - 1, to_page=to_page - 1)
                new_doc.save(str(out_p))
                return out_p
            finally:
                new_doc.close()

    @staticmethod
    def compress(input_path: str | Path, output_path: Optional[str | Path] = None) -> Path:
        """
        Optimiza y reduce el tamaño de un PDF aplicando deflación de streams
        y eliminando objetos no utilizados (garbage collection).
        """
        in_p = Path(input_path).resolve()
        out_p = Path(output_path).resolve() if output_path else in_p.with_stem(f"{in_p.stem}_comprimido")
        out_p.parent.mkdir(parents=True, exist_ok=True)

        with pymupdf.open(str(in_p)) as doc:
            doc.save(
                str(out_p),
                garbage=4,   # Nivel máximo de eliminación de objetos huérfanos/inutilizados
                deflate=True, # Comprime flujos de datos sin pérdida
                clean=True    # Sanitiza y optimiza contenido de página
            )
        return out_p

    @staticmethod
    def extract_images(input_path: str | Path, output_dir: Optional[str | Path] = None) -> List[Path]:
        """
        Extrae todas las imágenes incrustadas dentro del PDF a una carpeta.
        """
        in_p = Path(input_path).resolve()
        out_d = Path(output_dir).resolve() if output_dir else in_p.parent / f"{in_p.stem}_imagenes"
        out_d.mkdir(parents=True, exist_ok=True)

        extracted_paths: List[Path] = []
        with pymupdf.open(str(in_p)) as doc:
            for page_idx, page in enumerate(doc):
                image_list = page.get_images(full=True)
                for img_idx, img in enumerate(image_list):
                    xref = img[0]
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    image_ext = base_image["ext"]
                    
                    img_file = out_d / f"img_pag_{page_idx + 1}_{img_idx + 1}.{image_ext}"
                    img_file.write_bytes(image_bytes)
                    extracted_paths.append(img_file)

        return extracted_paths

    @staticmethod
    def rotate_pages(
        input_path: str | Path,
        degrees: int = 90,
        output_path: Optional[str | Path] = None
    ) -> Path:
        """
        Rota todas las páginas del PDF por los grados indicados (90, 180, 270).
        """
        if degrees % 90 != 0:
            raise ValueError("Los grados de rotación deben ser múltiplos de 90 (ej: 90, 180, 270).")

        in_p = Path(input_path).resolve()
        out_p = Path(output_path).resolve() if output_path else in_p.with_stem(f"{in_p.stem}_rotado")
        out_p.parent.mkdir(parents=True, exist_ok=True)

        with pymupdf.open(str(in_p)) as doc:
            for page in doc:
                page.set_rotation((page.rotation + degrees) % 360)
            doc.save(str(out_p))
        return out_p

    @staticmethod
    def protect(
        input_path: str | Path,
        user_password: str,
        owner_password: Optional[str] = None,
        output_path: Optional[str | Path] = None
    ) -> Path:
        """
        Protege un PDF con contraseña mediante cifrado AES-256.
        """
        in_p = Path(input_path).resolve()
        out_p = Path(output_path).resolve() if output_path else in_p.with_stem(f"{in_p.stem}_protegido")
        out_p.parent.mkdir(parents=True, exist_ok=True)

        with pymupdf.open(str(in_p)) as doc:
            doc.save(
                str(out_p),
                encryption=pymupdf.PDF_ENCRYPT_AES_256,
                user_pw=user_password,
                owner_pw=owner_password or user_password
            )
        return out_p

    @staticmethod
    def unlock(
        input_path: str | Path,
        password: str,
        output_path: Optional[str | Path] = None
    ) -> Path:
        """
        Elimina la contraseña de un PDF protegido si se proporciona la clave correcta.
        """
        in_p = Path(input_path).resolve()
        out_p = Path(output_path).resolve() if output_path else in_p.with_stem(f"{in_p.stem}_desbloqueado")
        out_p.parent.mkdir(parents=True, exist_ok=True)

        with pymupdf.open(str(in_p)) as doc:
            if doc.is_encrypted:
                auth_ok = doc.authenticate(password)
                if not auth_ok:
                    raise PermissionError("Contraseña incorrecta para el archivo PDF.")
            # Guardar sin encriptación
            doc.save(str(out_p))
        return out_p

    @staticmethod
    def add_watermark(
        input_path: str | Path,
        watermark_text: str,
        output_path: Optional[str | Path] = None,
        font_size: int = 38,
        rotate: int = 45,
        opacity: float = 0.25
    ) -> Path:
        """
        Añade una marca de agua de texto en diagonal en todas las páginas del PDF.
        """
        in_p = Path(input_path).resolve()
        out_p = Path(output_path).resolve() if output_path else in_p.with_stem(f"{in_p.stem}_marca_agua")
        out_p.parent.mkdir(parents=True, exist_ok=True)

        with pymupdf.open(str(in_p)) as doc:
            for page in doc:
                rect = page.rect
                # Center-diagonal anchor point
                p = pymupdf.Point(rect.width * 0.15, rect.height * 0.65)
                page.insert_text(
                    p,
                    watermark_text,
                    fontsize=font_size,
                    color=(0.55, 0.55, 0.55),
                    fill_opacity=opacity,
                    morph=(p, pymupdf.Matrix(rotate))
                )
            doc.save(str(out_p))
        return out_p

    @staticmethod
    def add_signature(
        input_path: str | Path,
        signature_path: str | Path,
        page_num: int = -1,
        position: str = "bottom-right",
        width: int = 150,
        height: int = 65,
        output_path: Optional[str | Path] = None
    ) -> Path:
        """
        Estampa una imagen de firma o sello sobre una página específica del PDF.
        - page_num: número de página (1-based, o -1 para la última página).
        - position: 'bottom-right', 'bottom-left', 'center'.
        """
        in_p = Path(input_path).resolve()
        sig_p = Path(signature_path).resolve()
        if not sig_p.exists():
            raise FileNotFoundError(f"Archivo de firma no encontrado: {sig_p}")

        out_p = Path(output_path).resolve() if output_path else in_p.with_stem(f"{in_p.stem}_firmado")
        out_p.parent.mkdir(parents=True, exist_ok=True)

        with pymupdf.open(str(in_p)) as doc:
            total = len(doc)
            target_idx = (total - 1) if page_num == -1 else (page_num - 1)
            if target_idx < 0 or target_idx >= total:
                raise ValueError(f"Página inválida: {page_num}. El documento tiene {total} páginas.")

            page = doc[target_idx]
            rect = page.rect

            margin = 35
            if position == "bottom-right":
                x0 = rect.width - width - margin
                y0 = rect.height - height - margin
            elif position == "bottom-left":
                x0 = margin
                y0 = rect.height - height - margin
            else:  # center
                x0 = (rect.width - width) / 2
                y0 = (rect.height - height) / 2

            sig_rect = pymupdf.Rect(x0, y0, x0 + width, y0 + height)
            page.insert_image(sig_rect, filename=str(sig_p), overlay=True)
            doc.save(str(out_p))

        return out_p
