import os
import subprocess
import threading
from pathlib import Path
from typing import Optional, List
import customtkinter as ctk
from tkinter import filedialog, messagebox

from core import ConverterManager
from ..components.drop_zone import DropZone


class ConverterView(ctk.CTkFrame):
    """
    Vista del Convertidor Universal:
    - Arrastrar y soltar archivos
    - Detección automática de formatos compatibles
    - Barra de estado / progreso
    - Acceso directo para abrir el archivo generado o su carpeta
    """

    def __init__(self, master, manager: ConverterManager, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.manager = manager
        self.current_file: Optional[Path] = None
        self.target_format: Optional[str] = None
        self.output_directory: Optional[Path] = None

        self._setup_ui()

    def _setup_ui(self):
        self.grid_columnconfigure(0, weight=1)

        # Header
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", pady=(10, 15))
        
        title = ctk.CTkLabel(
            header_frame,
            text="Convertidor Universal",
            font=ctk.CTkFont(size=24, weight="bold")
        )
        title.pack(anchor="w")

        subtitle = ctk.CTkLabel(
            header_frame,
            text="Convierte documentos e imágenes de forma 100% privada y local en tu equipo.",
            font=ctk.CTkFont(size=13),
            text_color=("gray50", "gray70")
        )
        subtitle.pack(anchor="w", pady=(2, 0))

        # DropZone
        self.drop_zone = DropZone(
            self,
            on_files_dropped=self._on_file_selected,
            title="Arrastra tu archivo aquí para convertir",
            subtitle="Soporta PDF, DOCX, PNG, JPG, WEBP, ICO y más"
        )
        self.drop_zone.grid(row=1, column=0, sticky="ew", pady=(0, 15))

        # File Details & Conversion Options Card
        self.options_card = ctk.CTkFrame(self, corner_radius=12, border_width=1, border_color=("#E2E8F0", "#334155"))
        self.options_card.grid(row=2, column=0, sticky="ew", pady=(0, 15))
        self.options_card.grid_columnconfigure(1, weight=1)

        # File Info Row
        self.file_icon_label = ctk.CTkLabel(self.options_card, text="📄", font=ctk.CTkFont(size=28))
        self.file_icon_label.grid(row=0, column=0, padx=(15, 10), pady=15)

        self.file_name_label = ctk.CTkLabel(
            self.options_card,
            text="Ningún archivo seleccionado",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w"
        )
        self.file_name_label.grid(row=0, column=1, sticky="w", pady=15)

        self.file_size_label = ctk.CTkLabel(
            self.options_card,
            text="-",
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray70"),
            anchor="e"
        )
        self.file_size_label.grid(row=0, column=2, padx=15, pady=15)

        # Separator
        sep = ctk.CTkProgressBar(self.options_card, height=1, progress_color=("#E2E8F0", "#334155"))
        sep.set(1)
        sep.grid(row=1, column=0, columnspan=3, sticky="ew", padx=15)

        # Controls Row (Format Selector & Destination)
        controls_frame = ctk.CTkFrame(self.options_card, fg_color="transparent")
        controls_frame.grid(row=2, column=0, columnspan=3, sticky="ew", padx=15, pady=15)
        controls_frame.grid_columnconfigure(1, weight=1)

        lbl_format = ctk.CTkLabel(controls_frame, text="Convertir a:", font=ctk.CTkFont(weight="bold"))
        lbl_format.grid(row=0, column=0, sticky="w", padx=(0, 10))

        self.format_menu = ctk.CTkOptionMenu(
            controls_frame,
            values=["Selecciona archivo primero"],
            state="disabled",
            width=180
        )
        self.format_menu.grid(row=0, column=1, sticky="w")

        lbl_dest = ctk.CTkLabel(controls_frame, text="Guardar en:", font=ctk.CTkFont(weight="bold"))
        lbl_dest.grid(row=0, column=2, sticky="e", padx=(20, 10))

        self.dest_btn = ctk.CTkButton(
            controls_frame,
            text="Misma carpeta",
            command=self._choose_output_dir,
            width=150,
            fg_color=("gray85", "gray25"),
            text_color=("black", "white"),
            hover_color=("gray75", "gray35")
        )
        self.dest_btn.grid(row=0, column=3, sticky="e")

        # Convert Action Button & Status
        action_frame = ctk.CTkFrame(self, fg_color="transparent")
        action_frame.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        action_frame.grid_columnconfigure(0, weight=1)

        self.convert_btn = ctk.CTkButton(
            action_frame,
            text="⚡ Iniciar Conversión",
            command=self._start_conversion,
            height=44,
            corner_radius=10,
            font=ctk.CTkFont(size=15, weight="bold"),
            state="disabled"
        )
        self.convert_btn.pack(fill="x")

        # Progress & Result Bar
        self.progress_bar = ctk.CTkProgressBar(self, mode="indeterminate", height=6)
        self.progress_bar.grid(row=4, column=0, sticky="ew", pady=(5, 5))
        self.progress_bar.grid_remove()  # Hidden by default

        self.status_label = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=13),
            anchor="w"
        )
        self.status_label.grid(row=5, column=0, sticky="w", pady=(0, 5))

        # Result Action Buttons (Open file, Open Folder)
        self.result_actions_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.result_actions_frame.grid(row=6, column=0, sticky="w")
        self.result_actions_frame.grid_remove()

        self.open_file_btn = ctk.CTkButton(
            self.result_actions_frame,
            text="Abrir archivo",
            width=130,
            command=self._open_converted_file
        )
        self.open_file_btn.pack(side="left", padx=(0, 10))

        self.open_folder_btn = ctk.CTkButton(
            self.result_actions_frame,
            text="Abrir carpeta",
            width=130,
            fg_color=("gray85", "gray25"),
            text_color=("black", "white"),
            hover_color=("gray75", "gray35"),
            command=self._open_output_folder
        )
        self.open_folder_btn.pack(side="left")

        self.last_generated_path: Optional[Path] = None

    def _on_file_selected(self, paths: List[Path]):
        if not paths:
            return
        file_path = paths[0]
        self.current_file = file_path
        self.output_directory = file_path.parent

        # Update File Info Display
        self.file_name_label.configure(text=file_path.name)
        size_bytes = file_path.stat().st_size
        if size_bytes < 1024 * 1024:
            size_str = f"{size_bytes / 1024:.1f} KB"
        else:
            size_str = f"{size_bytes / (1024 * 1024):.2f} MB"
        self.file_size_label.configure(text=size_str)

        # Get available formats
        formats = self.manager.get_supported_target_formats(file_path)
        if formats:
            self.format_menu.configure(
                values=formats,
                state="normal"
            )
            self.format_menu.set(formats[0])
            self.convert_btn.configure(state="normal")
            self.status_label.configure(text="Listo para convertir", text_color=("gray40", "gray60"))
        else:
            self.format_menu.configure(
                values=["Formato no soportado"],
                state="disabled"
            )
            self.convert_btn.configure(state="disabled")
            self.status_label.configure(
                text=f"Aún no hay soporte para convertir archivos {file_path.suffix}",
                text_color="orange"
            )

        self.result_actions_frame.grid_remove()

    def _choose_output_dir(self):
        chosen = filedialog.askdirectory(title="Seleccionar carpeta de destino")
        if chosen:
            self.output_directory = Path(chosen)
            self.dest_btn.configure(text=self.output_directory.name)

    def _start_conversion(self):
        if not self.current_file:
            return

        target_fmt = self.format_menu.get()
        if not target_fmt or target_fmt == "Formato no soportado":
            return

        # Disable controls during conversion
        self.convert_btn.configure(state="disabled", text="⏳ Convirtiendo...")
        self.progress_bar.grid()
        self.progress_bar.start()
        self.status_label.configure(text="Procesando archivo localmente...", text_color=("gray40", "gray60"))
        self.result_actions_frame.grid_remove()

        # Run conversion in background thread so UI stays 100% responsive
        target_path = None
        if self.output_directory:
            ext = f".{target_fmt.lower()}"
            target_path = self.output_directory / f"{self.current_file.stem}{ext}"
            if target_path == self.current_file:
                target_path = self.output_directory / f"{self.current_file.stem}_convertido{ext}"

        threading.Thread(
            target=self._run_conversion_worker,
            args=(self.current_file, target_fmt, target_path),
            daemon=True
        ).start()

    def _run_conversion_worker(self, input_file: Path, target_fmt: str, target_path: Optional[Path]):
        result = self.manager.convert_file(
            input_path=input_file,
            target_format=target_fmt,
            output_path=target_path
        )
        # Post back to main UI thread
        self.after(0, self._on_conversion_complete, result)

    def _on_conversion_complete(self, result):
        self.progress_bar.stop()
        self.progress_bar.grid_remove()
        self.convert_btn.configure(state="normal", text="⚡ Iniciar Conversión")

        if result.success:
            self.last_generated_path = result.output_path
            self.status_label.configure(
                text=f"✔ ¡Conversión exitosa en {result.elapsed_seconds}s! ({result.output_path.name})",
                text_color=("#16A34A", "#4ADE80")
            )
            self.result_actions_frame.grid()
        else:
            self.status_label.configure(
                text=f"✖ Error: {result.error_message}",
                text_color=("#DC2626", "#F87171")
            )

    def _open_converted_file(self):
        if self.last_generated_path and self.last_generated_path.exists():
            os.startfile(str(self.last_generated_path))

    def _open_output_folder(self):
        if self.last_generated_path and self.last_generated_path.exists():
            folder = self.last_generated_path.parent
            subprocess.Popen(f'explorer /select,"{str(self.last_generated_path)}"')
