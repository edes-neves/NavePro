
from . import ctk
from .settings_manager import SettingsManager


class ThemeManager:
    _instance = None

    NEON_DARK = {
        "bg": "#050816",
        "bg_secondary": "#0a0e27",
        "bg_card": "#0d1233",
        "primary": "#00d4ff",
        "secondary": "#ff00ff",
        "accent": "#00fff7",
        "text": "#ffffff",
        "text_secondary": "#8892b0",
        "btn_text": "#0a0e27",
        "success": "#00ff88",
        "warning": "#ffaa00",
        "error": "#ff3355",
        "border": "#1a1f4e",
        "border_active": "#00d4ff",
        "glow_primary": "#005577",
        "glow_secondary": "#550055",
        # Tokens específicos de componentes. No Dark Mode os valores são
        # idênticos aos que já eram renderizados, então nada muda ali.
        "btn_primary": "#00d4ff",
        "btn_primary_hover": "#8892b0",
        "btn_neutral": "#8892b0",
        "btn_neutral_hover": "#00d4ff",
        "btn_start": "#00fff7",
        "btn_start_hover": "#8892b0",
        "btn_success": "#00ff88",
        "btn_success_hover": "#8892b0",
        "btn_warning": "#ffaa00",
        "btn_warning_hover": "#8892b0",
        "btn_error": "#ff3355",
        "btn_error_hover": "#8892b0",
        "input_bg": "#050816",
        "input_border": "#1a1f4e",
    }

    NEON_LIGHT = {
        "bg": "#e8ecf5",
        "bg_secondary": "#f2f4fa",
        "bg_card": "#ffffff",
        "primary": "#0066ff",
        "secondary": "#cc00cc",
        "accent": "#00a896",
        "text": "#0f172a",
        "text_secondary": "#5b6478",
        "btn_text": "#0f172a",
        "success": "#00aa55",
        "warning": "#cc8800",
        "error": "#cc2244",
        "border": "#c4cde0",
        "border_active": "#7b8cff",
        "glow_primary": "#b9cefb",
        "glow_secondary": "#f6cdf2",
        "btn_primary": "#2563eb",
        "btn_primary_hover": "#1d4ed8",
        "btn_neutral": "#e3e9f4",
        "btn_neutral_hover": "#ccd6e8",
        "btn_start": "#0e9488",
        "btn_start_hover": "#0f766e",
        "btn_success": "#059669",
        "btn_success_hover": "#047857",
        "btn_warning": "#d97706",
        "btn_warning_hover": "#b45309",
        "btn_error": "#dc2626",
        "btn_error_hover": "#b91c1c",
        "input_bg": "#f6f8fc",
        "input_border": "#cdd7e6",
    }

    def __init__(self, settings: SettingsManager | None = None) -> None:
        self._settings = settings or SettingsManager()
        # O app SEMPRE inicia no tema escuro; o tema claro só entra se o
        # usuário escolher via seletor (não é persistido entre sessões).
        self._current_theme: str = "dark"
        self._colors: dict[str, str] = dict(self.NEON_DARK)
        self._apply_theme()

    def _apply_theme(self) -> None:
        theme_name = self._current_theme
        if theme_name == "light":
            self._colors = dict(self.NEON_LIGHT)
        else:
            self._colors = dict(self.NEON_DARK)

        ctk.set_appearance_mode(theme_name)

        primary = self._colors["primary"]
        ctk.set_default_color_theme("dark-blue")
        try:
            ctk.ThemeManager.theme["color"]["button"] = [primary, primary]
        except Exception:
            pass

    def toggle_theme(self) -> str:
        new_theme = "light" if self._current_theme == "dark" else "dark"
        self._current_theme = new_theme
        self._apply_theme()
        return new_theme

    @property
    def colors(self) -> dict[str, str]:
        return dict(self._colors)

    @property
    def theme_name(self) -> str:
        return self._current_theme

    def c(self, name: str) -> str:
        return self._colors.get(name, "#ffffff")

    def public(self, name: str) -> str:
        """Cor do telão (monitor público).

        O telão usa sempre a paleta escura/neon, independente do tema do
        operador, para manter a aparência translúcida (transparência
        visível) também quando o app está no tema claro. As cores de
        fundo/títulos/textos podem ser personalizadas pelo operador via
        "Configurações → Tela Pública"; quando existe um override salvo,
        ele vence a paleta neon padrão.
        """
        overrides = {
            "bg": "public_bg",
            "primary": "public_primary",
            "text": "public_text",
            "text_secondary": "public_text_secondary",
        }
        key = overrides.get(name)
        if key:
            val = self._settings.get("display", key)
            if val:
                return str(val)
        if name in self.NEON_DARK:
            return self.NEON_DARK[name]
        return self._colors.get(name, "#ffffff")

    def configure_widget(self, widget: ctk.CTkBaseClass, **kwargs) -> None:
        for key, value in kwargs.items():
            try:
                widget.configure(**{key: value})
            except Exception:
                pass
