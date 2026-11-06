from pathlib import Path
from typing import Callable, List, Optional
import customtkinter as ctk
from tkinterdnd2 import DND_FILES
from tkinter import filedialog


class DropZone(ctk.CTkFrame):
    """
    Componente visual de zona de arrastrar y soltar (Drag & Drop)
    con soporte para clic de exploración manual.
    """

    def __init__(
        self,
        master,
        on_files_dropped: Callable[[List[Path]], None],
        multiple: bool = False,
        file_types: Optional[List[tuple]] = None,
        title: str = "Arrastra tus archivos aquí",
        subtitle: str = "o haz clic en el botón para buscar en tu equipo",
        **kwargs
    ):
        super().__init__(
            master,
            corner_radius=12,
            border_width=2,
            border_color=("#CBD5E1", "#334155"),
            fg_color=("#F8FAFC", "#1E293B"),
            **kwargs
        )
        self.on_files_dropped = on_files_dropped
        self.multiple = multiple
        self.file_types = file_types or [("Todos los archivos soportados", "*.*")]

        self._setup_ui(title, subtitle)
        self._setup_dnd()

    def _setup_ui(self, title: str, subtitle: str):
        self.grid_columnconfigure(0, weight=1)

        self.icon_label = ctk.CTkLabel(
            self,
            text="📂",
            font=ctk.CTkFont(size=40)
        )
        self.icon_label.grid(row=0, column=0, pady=(20, 5))

        self.title_label = ctk.CTkLabel(
            self,
            text=title,
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.title_label.grid(row=1, column=0, pady=2)

        self.sub_label = ctk.CTkLabel(
            self,
            text=subtitle,
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray70")
        )
        self.sub_label.grid(row=2, column=0, pady=(0, 15))

        self.browse_btn = ctk.CTkButton(
            self,
            text="Seleccionar archivo" if not self.multiple else "Seleccionar archivos",
            command=self._on_browse,
            corner_radius=8,
            height=36,
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.browse_btn.grid(row=3, column=0, pady=(0, 20))

    def _setup_dnd(self):
        # Register widget for drag & drop
        try:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)
            self.dnd_bind("<<DragEnter>>", self._on_drag_enter)
            self.dnd_bind("<<DragLeave>>", self._on_drag_leave)
        except Exception:
            pass

    def _on_drag_enter(self, event):
        self.configure(border_color=("#3B82F6", "#2563EB"))

    def _on_drag_leave(self, event):
        self.configure(border_color=("#CBD5E1", "#334155"))

    def _on_drop(self, event):
        self.configure(border_color=("#CBD5E1", "#334155"))
        raw_data = event.data
        paths: List[Path] = []

        # Windows TkinterDnD paths can be enclosed in {curly braces} if they contain spaces
        if "{" in raw_data:
            import re
            matches = re.findall(r"\{([^}]+)\}", raw_data)
            paths = [Path(m) for m in matches if Path(m).exists()]
        else:
            paths = [Path(p) for p in raw_data.split() if Path(p).exists()]

        if paths and self.on_files_dropped:
            if not self.multiple:
                self.on_files_dropped([paths[0]])
            else:
                self.on_files_dropped(paths)

    def _on_browse(self):
        if self.multiple:
            selected = filedialog.askopenfilenames(filetypes=self.file_types)
            if selected:
                self.on_files_dropped([Path(p) for p in selected])
        else:
            selected = filedialog.askopenfilename(filetypes=self.file_types)
            if selected:
                self.on_files_dropped([Path(selected)])
