
from . import ctk
from .settings_manager import SettingsManager


class ThemeManager:
    _instance = None

    # Paletas alinhadas ao NavePro: o sorteio passa a usar as MESMAS cores do
    # painel do operador (dourado #f0c040, roxo #6e40c9, azul #1f6feb). No
    # escuro, superfícies #0d1117/#161b22/#21262d; no claro, a hierarquia
    # #eaeef2 (janela) / #f6f8fa (cartões) / #ffffff (entradas). Os nomes dos
    # tokens são mantidos para não tocar nos widgets.
    NEON_DARK = {
        "bg": "#0d1117",
        "bg_secondary": "#161b22",
        "bg_card": "#21262d",
        "primary": "#f0c040",
        "secondary": "#6e40c9",
        "accent": "#58a6ff",
        "text": "#c9d1d9",
        "text_secondary": "#8b949e",
        # Texto claro nos botões: no escuro os botões são superfícies
        # escuras/médias (roxo, azul, verde), onde o branco contrasta bem.
        "btn_text": "#ffffff",
        "success": "#2ea043",
        "warning": "#d29922",
        "error": "#f85149",
        "border": "#30363d",
        "border_active": "#f0c040",
        "glow_primary": "#30363d",
        "glow_secondary": "#2d2438",
        # Tokens específicos de componentes.
        "btn_primary": "#6e40c9",
        "btn_primary_hover": "#8250df",
        "btn_neutral": "#21262d",
        "btn_neutral_hover": "#30363d",
        "btn_start": "#1f6feb",
        "btn_start_hover": "#388bfd",
        "btn_success": "#238636",
        "btn_success_hover": "#2ea043",
        "btn_warning": "#9a6700",
        "btn_warning_hover": "#bb8009",
        "btn_error": "#da3633",
        "btn_error_hover": "#b62324",
        "input_bg": "#0d1117",
        "input_border": "#30363d",
    }

    NEON_LIGHT = {
        # Tema claro com a MESMA hierarquia do escuro, só que em tons claros:
        # a janela é o tom base (cinza-claro), os cartões sobem para o branco
        # e os campos/entradas ficam no tom da janela com borda (como no
        # escuro, em que as entradas usam a cor de fundo da janela).
        "bg": "#eaeef2",
        "bg_secondary": "#f6f8fa",
        "bg_card": "#ffffff",
        "primary": "#8250df",
        "secondary": "#0969da",
        "accent": "#0969da",
        "text": "#1f2328",
        "text_secondary": "#656d76",
        "btn_text": "#ffffff",
        "success": "#1a7f37",
        "warning": "#9a6700",
        "error": "#cf222e",
        "border": "#d0d7de",
        "border_active": "#0969da",
        "glow_primary": "#d0d7de",
        "glow_secondary": "#eaeef2",
        "btn_primary": "#8250df",
        "btn_primary_hover": "#6e40c9",
        "btn_neutral": "#6e7681",
        "btn_neutral_hover": "#57606a",
        "btn_start": "#0969da",
        "btn_start_hover": "#0a5bc4",
        "btn_success": "#1a7f37",
        "btn_success_hover": "#166b2e",
        "btn_warning": "#9a6700",
        "btn_warning_hover": "#7d5300",
        "btn_error": "#cf222e",
        "btn_error_hover": "#a40e26",
        "input_bg": "#eaeef2",
        "input_border": "#d0d7de",
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
        return self.definir_tema(new_theme)

    def definir_tema(self, nome: str) -> str:
        """Seleciona o tema ("dark"/"light") sem alternar.

        Usado pela integração com o NavePro para acompanhar o tema ativo do
        painel do operador. Aceita também "claro"/"escuro".
        """
        nome = "light" if nome in ("light", "claro") else "dark"
        if nome != self._current_theme:
            self._current_theme = nome
            self._apply_theme()
        return self._current_theme

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

        O telão usa sempre a paleta escura do NavePro (``NEON_DARK``),
        independente do tema do operador, para manter a aparência translúcida
        (transparência visível) também quando o app está no tema claro. As cores
        de fundo/títulos/textos podem ser personalizadas pelo operador via
        "Configurações → Tela Pública"; quando existe um override salvo, ele
        vence a paleta escura padrão.
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
