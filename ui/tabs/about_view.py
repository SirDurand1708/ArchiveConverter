import webbrowser
import customtkinter as ctk


class AboutView(ctk.CTkFrame):
    """
    Vista informativa de la aplicación:
    - Garantía de privacidad y procesamiento local
    - Enlace al repositorio de GitHub
    - Información de versión y licencia
    """

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._setup_ui()

    def _setup_ui(self):
        self.grid_columnconfigure(0, weight=1)

        card = ctk.CTkFrame(self, corner_radius=16, border_width=1, border_color=("#E2E8F0", "#334155"))
        card.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        card.grid_columnconfigure(0, weight=1)

        # Logo / Badge
        badge = ctk.CTkLabel(card, text="🛡️", font=ctk.CTkFont(size=48))
        badge.pack(pady=(30, 10))

        title = ctk.CTkLabel(
            card,
            text="ArchiveConverter",
            font=ctk.CTkFont(size=26, weight="bold")
        )
        title.pack(pady=2)

        ver = ctk.CTkLabel(
            card,
            text="Versión 1.0.0 Open Source",
            font=ctk.CTkFont(size=13),
            text_color=("gray50", "gray70")
        )
        ver.pack(pady=(0, 20))

        # Description
        desc_text = (
            "ArchiveConverter nació como una respuesta a los sitios web de conversión "
            "que recopilan información privada, insertan publicidad intrusiva o imponen "
            "límites de tamaño arbitrarios.\n\n"
            "✨ Todo el procesamiento ocurre 100% en tu máquina (sin internet).\n"
            "✨ Cero anuncios, cero telemetría y sin costos ocultos.\n"
            "✨ Conversión estructural fiel de documentos e imágenes."
        )
        desc = ctk.CTkLabel(
            card,
            text=desc_text,
            font=ctk.CTkFont(size=14),
            justify="center",
            wraplength=520
        )
        desc.pack(padx=20, pady=(0, 25))

        # GitHub Button
        gh_btn = ctk.CTkButton(
            card,
            text="Ver Proyecto en GitHub",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40,
            width=220,
            command=lambda: webbrowser.open("https://github.com")
        )
        gh_btn.pack(pady=(0, 30))
