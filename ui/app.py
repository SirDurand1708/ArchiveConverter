from typing import Optional
import customtkinter as ctk
from tkinterdnd2 import TkinterDnD

from core import ConverterManager
from .tabs import ConverterView, PDFToolsView, AboutView


class ArchiveConverterApp(ctk.CTk, TkinterDnD.DnDWrapper):
    """
    Ventana principal de ArchiveConverter.
    - Soporte completo para Drag & Drop nativo en Windows
    - Barra de navegación lateral moderna
    - Conmutador de tema Oscuro / Claro / Sistema
    """

    def __init__(self):
        super().__init__()
        # Inicializar TkinterDnD
        self.TkdndVersion = TkinterDnD._require(self)

        # Configuración de ventana
        self.title("ArchiveConverter - Tu Convertidor Privado y Offline")
        self.geometry("980x660")
        self.minsize(860, 580)

        # Centrar ventana en pantalla
        self._center_window(980, 660)

        # Configurar apariencia inicial
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        # Motor de conversión
        self.manager = ConverterManager()

        self._setup_layout()
        self._show_tab("converter")

    def _center_window(self, width: int, height: int):
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = max(0, int((screen_width - width) / 2))
        y = max(0, int((screen_height - height) / 2))
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _setup_layout(self):
        # 2 Columnas: Barra lateral (0) y Contenido principal (1)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ================= Barra Lateral (Sidebar) =================
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(4, weight=1)  # Empuja el selector de tema hacia abajo

        # Logo / Titulo
        logo_label = ctk.CTkLabel(
            self.sidebar,
            text="⚡ ArchiveConverter",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        logo_label.grid(row=0, column=0, padx=20, pady=(25, 20), sticky="w")

        # Botones de Navegación
        self.btn_converter = ctk.CTkButton(
            self.sidebar,
            text="📁  Convertidor",
            height=40,
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self._show_tab("converter")
        )
        self.btn_converter.grid(row=1, column=0, padx=15, pady=5, sticky="ew")

        self.btn_pdf_tools = ctk.CTkButton(
            self.sidebar,
            text="🛠️  Herramientas PDF",
            height=40,
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="transparent",
            text_color=("gray10", "gray90"),
            hover_color=("gray75", "gray25"),
            command=lambda: self._show_tab("pdf_tools")
        )
        self.btn_pdf_tools.grid(row=2, column=0, padx=15, pady=5, sticky="ew")

        self.btn_about = ctk.CTkButton(
            self.sidebar,
            text="ℹ️  Acerca de",
            height=40,
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="transparent",
            text_color=("gray10", "gray90"),
            hover_color=("gray75", "gray25"),
            command=lambda: self._show_tab("about")
        )
        self.btn_about.grid(row=3, column=0, padx=15, pady=5, sticky="ew")

        # Selector de Tema (Abajo)
        theme_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        theme_frame.grid(row=5, column=0, padx=15, pady=20, sticky="s")

        theme_lbl = ctk.CTkLabel(theme_frame, text="Tema visual:", font=ctk.CTkFont(size=11), text_color="gray60")
        theme_lbl.pack(anchor="w")

        self.theme_menu = ctk.CTkOptionMenu(
            theme_frame,
            values=["Oscuro", "Claro", "Sistema"],
            command=self._change_theme,
            width=190,
            height=30
        )
        self.theme_menu.pack(pady=(4, 0))
        self.theme_menu.set("Oscuro")

        # ================= Contenedor de Vistas =================
        self.content_area = ctk.CTkFrame(self, fg_color="transparent")
        self.content_area.grid(row=0, column=1, sticky="nsew", padx=25, pady=20)
        self.content_area.grid_columnconfigure(0, weight=1)
        self.content_area.grid_rowconfigure(0, weight=1)

        # Instanciar las vistas
        self.views = {
            "converter": ConverterView(self.content_area, self.manager),
            "pdf_tools": PDFToolsView(self.content_area),
            "about": AboutView(self.content_area),
        }

    def _show_tab(self, tab_name: str):
        # Actualizar aspecto de los botones laterales
        buttons = {
            "converter": self.btn_converter,
            "pdf_tools": self.btn_pdf_tools,
            "about": self.btn_about,
        }
        for name, btn in buttons.items():
            if name == tab_name:
                btn.configure(fg_color=["#3B82F6", "#1D4ED8"], text_color="white")
            else:
                btn.configure(fg_color="transparent", text_color=("gray10", "gray90"))

        # Mostrar la vista correspondiente
        for name, view in self.views.items():
            if name == tab_name:
                view.grid(row=0, column=0, sticky="nsew")
            else:
                view.grid_remove()

    def _change_theme(self, mode_str: str):
        mapping = {"Oscuro": "Dark", "Claro": "Light", "Sistema": "System"}
        ctk.set_appearance_mode(mapping.get(mode_str, "Dark"))


def run_gui():
    app = ArchiveConverterApp()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
