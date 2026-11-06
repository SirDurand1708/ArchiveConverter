import os
import subprocess
import threading
from pathlib import Path
from typing import List, Optional
import customtkinter as ctk
from tkinter import filedialog, messagebox

from core import PDFToolkit
from ..components.drop_zone import DropZone


class PDFToolsView(ctk.CTkFrame):
    """
    Vista de Herramientas de PDF:
    - Unir (Merge)
    - Dividir (Split)
    - Comprimir (Compress)
    - Extraer imágenes
    - Rotar
    - Proteger / Desbloquear
    """

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._setup_ui()

    def _setup_ui(self):
        self.grid_columnconfigure(0, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(10, 15))

        title = ctk.CTkLabel(
            header,
            text="Caja de Herramientas PDF",
            font=ctk.CTkFont(size=24, weight="bold")
        )
        title.pack(anchor="w")

        subtitle = ctk.CTkLabel(
            header,
            text="Manipula, optimiza y protege documentos PDF sin límites ni subirlos a internet.",
            font=ctk.CTkFont(size=13),
            text_color=("gray50", "gray70")
        )
        subtitle.pack(anchor="w", pady=(2, 0))

        # Tool selector (Segmented Button)
        self.tool_selector = ctk.CTkSegmentedButton(
            self,
            values=["🔗 Unir", "✂️ Dividir", "🗜️ Comprimir", "🖼️ Extraer Imágenes", "🔄 Rotar", "🔒 Seguridad"],
            command=self._on_tool_changed,
            height=36,
            font=ctk.CTkFont(weight="bold")
        )
        self.tool_selector.grid(row=1, column=0, sticky="ew", pady=(0, 15))
        self.tool_selector.set("🔗 Unir")

        # Container for tool cards
        self.container = ctk.CTkFrame(self, corner_radius=12, border_width=1, border_color=("#E2E8F0", "#334155"))
        self.container.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        self.container.grid_columnconfigure(0, weight=1)

        # Status and progress
        self.progress_bar = ctk.CTkProgressBar(self, mode="indeterminate", height=6)
        self.progress_bar.grid(row=3, column=0, sticky="ew", pady=(5, 5))
        self.progress_bar.grid_remove()

        self.status_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=13), anchor="w")
        self.status_label.grid(row=4, column=0, sticky="w", pady=(0, 5))

        # Action button to open result
        self.open_result_btn = ctk.CTkButton(
            self,
            text="Abrir resultado",
            width=140,
            command=self._open_last_result
        )
        self.open_result_btn.grid(row=5, column=0, sticky="w")
        self.open_result_btn.grid_remove()

        self.last_result_path: Optional[Path] = None

        # Build individual tool sub-views
        self._build_merge_view()
        self._build_split_view()
        self._build_compress_view()
        self._build_extract_view()
        self._build_rotate_view()
        self._build_security_view()

        self._show_tool_frame("🔗 Unir")

    # ==================== Tool Views ====================

    def _build_merge_view(self):
        self.merge_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.merge_frame.grid_columnconfigure(0, weight=1)

        self.merge_drop = DropZone(
            self.merge_frame,
            on_files_dropped=self._on_merge_files_selected,
            multiple=True,
            file_types=[("Archivos PDF", "*.pdf")],
            title="Arrastra dos o más PDFs aquí para unirlos",
            subtitle="Los archivos se combinarán en el orden en que los agregues"
        )
        self.merge_drop.grid(row=0, column=0, sticky="ew", padx=15, pady=15)

        self.merge_list_label = ctk.CTkLabel(
            self.merge_frame,
            text="Ningún PDF seleccionado",
            font=ctk.CTkFont(weight="bold")
        )
        self.merge_list_label.grid(row=1, column=0, pady=(0, 10))

        self.merge_btn = ctk.CTkButton(
            self.merge_frame,
            text="Combinar PDFs en uno solo",
            state="disabled",
            height=40,
            command=self._execute_merge
        )
        self.merge_btn.grid(row=2, column=0, pady=(0, 15), padx=15, sticky="ew")
        self.selected_merge_files: List[Path] = []

    def _on_merge_files_selected(self, files: List[Path]):
        pdf_files = [f for f in files if f.suffix.lower() == ".pdf"]
        if pdf_files:
            self.selected_merge_files = pdf_files
            names = ", ".join([f.name for f in pdf_files[:3]])
            if len(pdf_files) > 3:
                names += f" y {len(pdf_files) - 3} más"
            self.merge_list_label.configure(text=f"{len(pdf_files)} PDFs seleccionados: {names}")
            self.merge_btn.configure(state="normal")

    def _execute_merge(self):
        dest = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("Archivo PDF", "*.pdf")],
            title="Guardar PDF unificado como"
        )
        if not dest:
            return
        self._run_async(
            lambda: PDFToolkit.merge(self.selected_merge_files, dest),
            success_msg="¡Archivos PDF unidos exitosamente!"
        )

    # ----------------- Split View -----------------
    def _build_split_view(self):
        self.split_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.split_frame.grid_columnconfigure(0, weight=1)

        self.split_drop = DropZone(
            self.split_frame,
            on_files_dropped=self._on_split_file_selected,
            file_types=[("Archivos PDF", "*.pdf")],
            title="Arrastra el PDF a dividir",
            subtitle="Extrae páginas sueltas o rangos específicos"
        )
        self.split_drop.grid(row=0, column=0, sticky="ew", padx=15, pady=15)

        self.split_file_label = ctk.CTkLabel(self.split_frame, text="Ningún archivo seleccionado")
        self.split_file_label.grid(row=1, column=0, pady=(0, 10))

        options_f = ctk.CTkFrame(self.split_frame, fg_color="transparent")
        options_f.grid(row=2, column=0, pady=(0, 15))

        self.split_mode = ctk.StringVar(value="all")
        r1 = ctk.CTkRadioButton(options_f, text="Separar todas las páginas", variable=self.split_mode, value="all")
        r1.pack(side="left", padx=15)
        r2 = ctk.CTkRadioButton(options_f, text="Extraer rango de páginas:", variable=self.split_mode, value="range")
        r2.pack(side="left", padx=(15, 5))

        self.range_entry = ctk.CTkEntry(options_f, placeholder_text="ej: 1-3", width=80)
        self.range_entry.pack(side="left")

        self.split_btn = ctk.CTkButton(
            self.split_frame,
            text="Dividir PDF",
            state="disabled",
            height=40,
            command=self._execute_split
        )
        self.split_btn.grid(row=3, column=0, pady=(0, 15), padx=15, sticky="ew")
        self.selected_split_file: Optional[Path] = None

    def _on_split_file_selected(self, files: List[Path]):
        if files and files[0].suffix.lower() == ".pdf":
            self.selected_split_file = files[0]
            self.split_file_label.configure(text=f"PDF: {files[0].name}")
            self.split_btn.configure(state="normal")

    def _execute_split(self):
        if not self.selected_split_file:
            return
        mode = self.split_mode.get()
        if mode == "range":
            txt = self.range_entry.get().strip()
            if "-" not in txt:
                messagebox.showerror("Error", "Ingresa un rango válido con guion (ej: 1-3)")
                return
            parts = txt.split("-")
            try:
                fp, tp = int(parts[0]), int(parts[1])
            except ValueError:
                messagebox.showerror("Error", "Los números de página deben ser enteros.")
                return

            self._run_async(
                lambda: PDFToolkit.split_range(self.selected_split_file, fp, tp),
                success_msg=f"¡Rango {txt} extraído exitosamente!"
            )
        else:
            self._run_async(
                lambda: PDFToolkit.split_all_pages(self.selected_split_file),
                success_msg="¡Todas las páginas divididas exitosamente!"
            )

    # ----------------- Compress View -----------------
    def _build_compress_view(self):
        self.compress_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.compress_frame.grid_columnconfigure(0, weight=1)

        self.compress_drop = DropZone(
            self.compress_frame,
            on_files_dropped=self._on_compress_file_selected,
            file_types=[("Archivos PDF", "*.pdf")],
            title="Arrastra el PDF a comprimir",
            subtitle="Reduce el peso del archivo eliminando metadatos y optimizando streams"
        )
        self.compress_drop.grid(row=0, column=0, sticky="ew", padx=15, pady=15)

        self.compress_info_label = ctk.CTkLabel(self.compress_frame, text="Ningún archivo seleccionado")
        self.compress_info_label.grid(row=1, column=0, pady=(0, 10))

        self.compress_btn = ctk.CTkButton(
            self.compress_frame,
            text="Comprimir y Optimizar",
            state="disabled",
            height=40,
            command=self._execute_compress
        )
        self.compress_btn.grid(row=2, column=0, pady=(0, 15), padx=15, sticky="ew")
        self.selected_compress_file: Optional[Path] = None

    def _on_compress_file_selected(self, files: List[Path]):
        if files and files[0].suffix.lower() == ".pdf":
            self.selected_compress_file = files[0]
            sz = files[0].stat().st_size / (1024 * 1024)
            self.compress_info_label.configure(text=f"PDF: {files[0].name} ({sz:.2f} MB)")
            self.compress_btn.configure(state="normal")

    def _execute_compress(self):
        if not self.selected_compress_file:
            return

        def task():
            old_sz = self.selected_compress_file.stat().st_size
            res = PDFToolkit.compress(self.selected_compress_file)
            new_sz = res.stat().st_size
            reduction = (1 - (new_sz / old_sz)) * 100 if old_sz > 0 else 0
            return res, f"¡Comprimido! Reducción: {reduction:.1f}% ({old_sz/1024:.0f} KB -> {new_sz/1024:.0f} KB)"

        self._run_async(task, is_custom_tuple=True)

    # ----------------- Extract Images View -----------------
    def _build_extract_view(self):
        self.extract_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.extract_frame.grid_columnconfigure(0, weight=1)

        self.extract_drop = DropZone(
            self.extract_frame,
            on_files_dropped=self._on_extract_file_selected,
            file_types=[("Archivos PDF", "*.pdf")],
            title="Arrastra el PDF para extraer sus fotos e imágenes",
            subtitle="Guarda cada imagen interna en su formato nativo con máxima resolución"
        )
        self.extract_drop.grid(row=0, column=0, sticky="ew", padx=15, pady=15)

        self.extract_file_label = ctk.CTkLabel(self.extract_frame, text="Ningún archivo seleccionado")
        self.extract_file_label.grid(row=1, column=0, pady=(0, 10))

        self.extract_btn = ctk.CTkButton(
            self.extract_frame,
            text="Extraer Todas las Imágenes",
            state="disabled",
            height=40,
            command=self._execute_extract
        )
        self.extract_btn.grid(row=2, column=0, pady=(0, 15), padx=15, sticky="ew")
        self.selected_extract_file: Optional[Path] = None

    def _on_extract_file_selected(self, files: List[Path]):
        if files and files[0].suffix.lower() == ".pdf":
            self.selected_extract_file = files[0]
            self.extract_file_label.configure(text=f"PDF: {files[0].name}")
            self.extract_btn.configure(state="normal")

    def _execute_extract(self):
        if not self.selected_extract_file:
            return

        def task():
            imgs = PDFToolkit.extract_images(self.selected_extract_file)
            if not imgs:
                raise ValueError("No se encontraron imágenes incrustadas en este PDF.")
            return imgs[0].parent, f"¡Se extrajeron {len(imgs)} imágenes con éxito!"

        self._run_async(task, is_custom_tuple=True)

    # ----------------- Rotate View -----------------
    def _build_rotate_view(self):
        self.rotate_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.rotate_frame.grid_columnconfigure(0, weight=1)

        self.rotate_drop = DropZone(
            self.rotate_frame,
            on_files_dropped=self._on_rotate_file_selected,
            file_types=[("Archivos PDF", "*.pdf")],
            title="Arrastra el PDF a rotar",
            subtitle="Corrige la orientación de tus documentos"
        )
        self.rotate_drop.grid(row=0, column=0, sticky="ew", padx=15, pady=15)

        self.rotate_file_label = ctk.CTkLabel(self.rotate_frame, text="Ningún archivo seleccionado")
        self.rotate_file_label.grid(row=1, column=0, pady=(0, 10))

        degrees_f = ctk.CTkFrame(self.rotate_frame, fg_color="transparent")
        degrees_f.grid(row=2, column=0, pady=(0, 15))

        self.rotate_deg = ctk.IntVar(value=90)
        ctk.CTkRadioButton(degrees_f, text="90° Horario", variable=self.rotate_deg, value=90).pack(side="left", padx=10)
        ctk.CTkRadioButton(degrees_f, text="180° Invertido", variable=self.rotate_deg, value=180).pack(side="left", padx=10)
        ctk.CTkRadioButton(degrees_f, text="270° Antihorario", variable=self.rotate_deg, value=270).pack(side="left", padx=10)

        self.rotate_btn = ctk.CTkButton(
            self.rotate_frame,
            text="Rotar Documento",
            state="disabled",
            height=40,
            command=self._execute_rotate
        )
        self.rotate_btn.grid(row=3, column=0, pady=(0, 15), padx=15, sticky="ew")
        self.selected_rotate_file: Optional[Path] = None

    def _on_rotate_file_selected(self, files: List[Path]):
        if files and files[0].suffix.lower() == ".pdf":
            self.selected_rotate_file = files[0]
            self.rotate_file_label.configure(text=f"PDF: {files[0].name}")
            self.rotate_btn.configure(state="normal")

    def _execute_rotate(self):
        if not self.selected_rotate_file:
            return
        deg = self.rotate_deg.get()
        self._run_async(
            lambda: PDFToolkit.rotate_pages(self.selected_rotate_file, degrees=deg),
            success_msg=f"¡PDF rotado {deg}° exitosamente!"
        )

    # ----------------- Security View -----------------
    def _build_security_view(self):
        self.sec_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.sec_frame.grid_columnconfigure(0, weight=1)

        self.sec_drop = DropZone(
            self.sec_frame,
            on_files_dropped=self._on_sec_file_selected,
            file_types=[("Archivos PDF", "*.pdf")],
            title="Arrastra el PDF para Proteger o Desbloquear",
            subtitle="Cifrado AES-256 o remoción de contraseña"
        )
        self.sec_drop.grid(row=0, column=0, sticky="ew", padx=15, pady=15)

        self.sec_file_label = ctk.CTkLabel(self.sec_frame, text="Ningún archivo seleccionado")
        self.sec_file_label.grid(row=1, column=0, pady=(0, 10))

        pwd_f = ctk.CTkFrame(self.sec_frame, fg_color="transparent")
        pwd_f.grid(row=2, column=0, pady=(0, 15))

        lbl = ctk.CTkLabel(pwd_f, text="Contraseña:", font=ctk.CTkFont(weight="bold"))
        lbl.pack(side="left", padx=(0, 10))

        self.pwd_entry = ctk.CTkEntry(pwd_f, show="*", width=200, placeholder_text="Escribe la contraseña")
        self.pwd_entry.pack(side="left")

        btn_f = ctk.CTkFrame(self.sec_frame, fg_color="transparent")
        btn_f.grid(row=3, column=0, pady=(0, 15))

        self.protect_btn = ctk.CTkButton(
            btn_f,
            text="🔒 Cifrar / Proteger",
            state="disabled",
            height=38,
            width=160,
            command=self._execute_protect
        )
        self.protect_btn.pack(side="left", padx=10)

        self.unlock_btn = ctk.CTkButton(
            btn_f,
            text="🔓 Desbloquear",
            state="disabled",
            height=38,
            width=160,
            fg_color=("gray85", "gray25"),
            text_color=("black", "white"),
            hover_color=("gray75", "gray35"),
            command=self._execute_unlock
        )
        self.unlock_btn.pack(side="left", padx=10)
        self.selected_sec_file: Optional[Path] = None

    def _on_sec_file_selected(self, files: List[Path]):
        if files and files[0].suffix.lower() == ".pdf":
            self.selected_sec_file = files[0]
            self.sec_file_label.configure(text=f"PDF: {files[0].name}")
            self.protect_btn.configure(state="normal")
            self.unlock_btn.configure(state="normal")

    def _execute_protect(self):
        pwd = self.pwd_entry.get().strip()
        if not pwd:
            messagebox.showerror("Error", "Debes ingresar una contraseña.")
            return
        self._run_async(
            lambda: PDFToolkit.protect(self.selected_sec_file, user_password=pwd),
            success_msg="¡PDF protegido con cifrado AES-256!"
        )

    def _execute_unlock(self):
        pwd = self.pwd_entry.get().strip()
        if not pwd:
            messagebox.showerror("Error", "Debes ingresar la contraseña actual del PDF para desbloquearlo.")
            return
        self._run_async(
            lambda: PDFToolkit.unlock(self.selected_sec_file, password=pwd),
            success_msg="¡PDF desbloqueado y sin restricciones!"
        )

    # ==================== Navigation & Execution ====================

    def _on_tool_changed(self, tool_name: str):
        self._show_tool_frame(tool_name)

    def _show_tool_frame(self, tool_name: str):
        frames = {
            "🔗 Unir": self.merge_frame,
            "✂️ Dividir": self.split_frame,
            "🗜️ Comprimir": self.compress_frame,
            "🖼️ Extraer Imágenes": self.extract_frame,
            "🔄 Rotar": self.rotate_frame,
            "🔒 Seguridad": self.sec_frame,
        }
        for name, frame in frames.items():
            if name == tool_name:
                frame.grid(row=0, column=0, sticky="nsew")
            else:
                frame.grid_remove()

    def _run_async(self, fn, success_msg="Operación completada", is_custom_tuple=False):
        self.progress_bar.grid()
        self.progress_bar.start()
        self.status_label.configure(text="Procesando documento...", text_color=("gray40", "gray60"))
        self.open_result_btn.grid_remove()

        def worker():
            try:
                if is_custom_tuple:
                    res_path, msg = fn()
                else:
                    res_path = fn()
                    msg = success_msg

                if isinstance(res_path, list) and res_path:
                    res_path = res_path[0]

                self.after(0, self._on_worker_success, res_path, msg)
            except Exception as e:
                self.after(0, self._on_worker_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_worker_success(self, path: Path, msg: str):
        self.progress_bar.stop()
        self.progress_bar.grid_remove()
        self.last_result_path = path
        self.status_label.configure(text=f"✔ {msg}", text_color=("#16A34A", "#4ADE80"))
        self.open_result_btn.grid()

    def _on_worker_error(self, err_msg: str):
        self.progress_bar.stop()
        self.progress_bar.grid_remove()
        self.status_label.configure(text=f"✖ Error: {err_msg}", text_color=("#DC2626", "#F87171"))

    def _open_last_result(self):
        if self.last_result_path and self.last_result_path.exists():
            if self.last_result_path.is_dir():
                os.startfile(str(self.last_result_path))
            else:
                os.startfile(str(self.last_result_path))
