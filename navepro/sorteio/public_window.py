import random
import tkinter as tk
from collections.abc import Callable

from .animation_engine import AnimationEngine
from .font_manager import ui_font
from .settings_manager import SettingsManager
from .theme_manager import ThemeManager

FALLBACK_WIDTH = 1920
FALLBACK_HEIGHT = 1080


class PublicWindow:

    def __init__(
        self,
        theme: ThemeManager | None = None,
        settings: SettingsManager | None = None,
    ) -> None:
        self._theme = theme or ThemeManager()
        self._settings = settings or SettingsManager()
        self._window: tk.Toplevel | None = None
        self._canvas: tk.Canvas | None = None
        self._animator: AnimationEngine | None = None
        self._on_animation_end: Callable | None = None
        self._state: str = "idle"
        self._resize_after_id: int | None = None
        self._minimized: bool = False
        self._idle_ellipsis_after: int | None = None

    def create(
        self,
        x: int, y: int, w: int, h: int,
        fullscreen: bool = True,
        master=None,
        borderless: bool = False,
    ) -> None:
        self._fullscreen = fullscreen
        self._borderless = borderless
        self._window = tk.Toplevel(master, class_="SorteioProfissional")
        self._window.title("Sorteio - Público")
        self._window.geometry(f"{w}x{h}+{x}+{y}")
        self._window.configure(bg=self._theme.public("bg"))

        if borderless:
            # Tela cheia emulada (sem bordas) presa à geometria do monitor.
            # Necessário no Windows, onde o `-fullscreen` do Tk ignora a
            # posição e joga a janela no monitor primário.
            self._window.overrideredirect(True)
            self._window.attributes("-topmost", True)
        elif fullscreen:
            self._window.attributes("-fullscreen", True)

        self._canvas = tk.Canvas(
            self._window,
            width=w,
            height=h,
            highlightthickness=0,
            bg=self._theme.public("bg"),
        )
        self._canvas.pack(fill="both", expand=True)

        self._animator = AnimationEngine(
            self._canvas, self._settings, self._theme
        )

        self._canvas.bind("<Configure>", lambda e: self._on_canvas_resize())

        self._window.update_idletasks()

        try:
            transparent = self._settings.get("display", "public_transparent")
            alpha = self._settings.get("display", "public_alpha")
            if transparent is not False and alpha is not None and float(alpha) < 1.0:
                self._window.attributes("-alpha", float(alpha))
        except (tk.TclError, ValueError):
            pass

        self._show_idle()

        self._window.bind("<Escape>", lambda e: self._on_escape())
        self._window.bind("<F11>", lambda e: self.toggle_fullscreen())

    def _canvas_size(self) -> tuple[int, int]:
        """Returns the current canvas size in pixels, falling back to a
        reasonable default when the widget is not mapped yet (winfo_width
        returns 1 before the window is shown on screen)."""
        if self._canvas is None:
            return FALLBACK_WIDTH, FALLBACK_HEIGHT

        w = self._canvas.winfo_width()
        h = self._canvas.winfo_height()
        if w <= 1:
            w = FALLBACK_WIDTH
        if h <= 1:
            h = FALLBACK_HEIGHT
        return w, h

    def _scale(self) -> float:
        """Fator responsivo do telão: 1.0 no desenho de referência (1920x1080),
        menor em telas pequenas (ex.: 1024x768) e maior nas resoluções novas
        (Full HD, 2K, 4K, ultrawide). Clamp para não distorcer em extremos.
        """
        w, h = self._canvas_size()
        s = min(w / 1920.0, h / 1080.0)
        return max(0.5, min(4.0, s))

    def _cancel_idle_ellipsis(self) -> None:
        """Cancela o loop da animação dos pontos de 'AGUARDANDO SORTEIO...'."""
        if self._idle_ellipsis_after is not None:
            try:
                if self._canvas is not None:
                    self._canvas.after_cancel(self._idle_ellipsis_after)
            except tk.TclError:
                pass
            self._idle_ellipsis_after = None

    def _animate_idle_ellipsis(self, step: int = 0) -> None:
        """Anima os '...' de 'AGUARDANDO SORTEIO...' no telão durante o idle."""
        if self._state != "idle" or self._canvas is None:
            self._idle_ellipsis_after = None
            return
        try:
            items = self._canvas.find_withtag("idle_title")
            if items:
                self._canvas.itemconfigure(
                    items[0],
                    text="AGUARDANDO SORTEIO" + "." * (step % 4),
                )
        except tk.TclError:
            self._idle_ellipsis_after = None
            return
        self._idle_ellipsis_after = self._canvas.after(
            450, lambda: self._animate_idle_ellipsis((step + 1) % 4)
        )

    def _show_idle(self) -> None:
        if not self._canvas:
            return

        if self._animator:
            self._animator.stop()
        self._cancel_idle_ellipsis()

        c = self._canvas
        w, h = self._canvas_size()
        s = self._scale()

        c.delete("all")
        c.create_rectangle(0, 0, w, h, fill=self._theme.public("bg"), outline="")

        for _ in range(20):
            sx = random.randint(0, w)
            sy = random.randint(0, h)
            c.create_oval(
                sx, sy, sx + 1, sy + 1,
                fill=self._theme.public("primary"),
                outline="",
            )

        c.create_text(
            w // 2, int(h // 2 - 40 * s),
            text="AGUARDANDO SORTEIO...",
            font=(ui_font(), max(1, int(72 * s)), "bold"),
            fill=self._theme.public("primary"),
            tags="idle_title",
        )

        c.create_text(
            w // 2, int(h // 2 + 40 * s),
            text="A CONFIGURAÇÃO DO SORTEIO É FEITA PELO OPERADOR NO MONITOR PRINCIPAL.",
            font=(ui_font(), max(1, int(32 * s)), "bold"),
            fill=self._theme.public("text"),
        )

        c.create_text(
            w // 2, int(h // 2 + 95 * s),
            text="ALGUÉM VAI GANHAR!",
            font=(ui_font(), max(1, int(30 * s))),
            fill=self._theme.public("text_secondary"),
        )

        self._state = "idle"
        if self._animator:
            self._animator.start_ambient()
        self._animate_idle_ellipsis(3)

    def show_idle(self) -> None:
        self._show_idle()

    def start_draw(
        self,
        numbers,
        range_min: int = 0,
        range_max: int = 9999,
        on_end: Callable | None = None,
    ) -> None:
        if isinstance(numbers, int):
            numbers = [numbers]
        if self._minimized:
            self.restore()
        self._state = "drawing"
        self._on_animation_end = on_end
        self._cancel_idle_ellipsis()
        if self._animator:
            self._animator.stop()
            self._animator.start_draw_animation(
                numbers,
                on_complete=self._on_animation_done,
                range_min=range_min,
                range_max=range_max,
            )

    def start_draw_names(
        self,
        names,
        name_pool=None,
        on_end: Callable | None = None,
    ) -> None:
        """Starts the rolling names animation on the public screen."""
        if isinstance(names, str):
            names = [names]
        if self._minimized:
            self.restore()
        self._state = "drawing"
        self._on_animation_end = on_end
        self._cancel_idle_ellipsis()
        if self._animator:
            self._animator.stop()
            self._animator.start_draw_names(
                names,
                name_pool=name_pool,
                on_complete=self._on_animation_done,
            )

    def _on_animation_done(self) -> None:
        self._state = "winner"
        if self._on_animation_end:
            self._on_animation_end()

    def show_winner(
        self,
        numbers,
        range_min: int = 0,
        range_max: int = 9999,
    ) -> None:
        self.start_draw(
            numbers,
            range_min=range_min,
            range_max=range_max,
        )

    def show_completed(self, is_names: bool = False) -> None:
        if not self._canvas:
            return

        if self._animator:
            self._animator.stop()
        self._cancel_idle_ellipsis()

        c = self._canvas
        w, h = self._canvas_size()
        s = self._scale()

        c.delete("all")
        c.create_rectangle(0, 0, w, h, fill=self._theme.public("bg"), outline="")

        c.create_text(
            w // 2, h // 2,
            text="SORTEIO ENCERRADO",
            font=(ui_font(), max(1, int(64 * s)), "bold"),
            fill=self._theme.public("primary"),
        )

        c.create_text(
            w // 2, int(h // 2 + 80 * s),
            text=(
                "Todas as pessoas foram sorteadas!"
                if is_names
                else "Todos os números foram sorteados!"
            ),
            font=(ui_font(), max(1, int(24 * s))),
            fill=self._theme.public("success"),
        )

        self._state = "completed"

    def _on_canvas_resize(self) -> None:
        """Re-centers the idle screen when the window is mapped or resized."""
        if self._state != "idle" or self._canvas is None:
            return
        if self._resize_after_id is not None:
            try:
                self._canvas.after_cancel(self._resize_after_id)
            except tk.TclError:
                pass
        self._resize_after_id = self._canvas.after(100, self._on_resize_idle)

    def _on_resize_idle(self) -> None:
        """Runs after the resize debounce, but only when the window is still
        idle. Guards against a pending resize callback killing a draw that
        started while the window was being mapped/resized."""
        self._resize_after_id = None
        if self._state == "idle":
            self._show_idle()

    def close(self) -> None:
        if self._animator:
            self._animator.stop()
        self._cancel_idle_ellipsis()
        if self._window:
            try:
                self._window.destroy()
            except tk.TclError:
                pass
        self._window = None
        self._canvas = None
        self._animator = None

    def _on_escape(self) -> None:
        if self._window:
            try:
                self._window.attributes("-fullscreen", False)
            except tk.TclError:
                pass

    def toggle_fullscreen(self) -> None:
        if self._window:
            try:
                current = self._window.attributes("-fullscreen")
                self._window.attributes("-fullscreen", not current)
                self._fullscreen = not current
            except tk.TclError:
                pass

    def minimize(self) -> None:
        if self._window and self._window.winfo_exists():
            try:
                self._window.withdraw()
            except tk.TclError:
                return
            self._minimized = True

    def restore(self) -> None:
        if self._window and self._window.winfo_exists():
            try:
                self._window.deiconify()
                if self._fullscreen:
                    self._window.attributes("-fullscreen", True)
                self._window.lift()
            except tk.TclError:
                pass
            self._minimized = False

    def toggle_minimize(self) -> bool:
        if self._minimized:
            self.restore()
        else:
            self.minimize()
        return self._minimized

    def set_alpha(self, alpha: float) -> None:
        if self._window and self._window.winfo_exists():
            try:
                transparent = self._settings.get("display", "public_transparent")
                if transparent is False:
                    alpha = 1.0
                self._window.attributes(
                    "-alpha", max(0.1, min(1.0, float(alpha)))
                )
            except (tk.TclError, ValueError):
                pass

    def refresh_public(self) -> None:
        """Reaplica fundo/cores do telão após mudanças de configuração.

        Atualiza apenas o estado idle (re-renderiza a tela de espera com as
        novas cores); durante um sorteio/vencedor nada é interrompido."""
        if self._canvas is None or self._window is None:
            return
        try:
            self._window.configure(bg=self._theme.public("bg"))
            self._canvas.configure(bg=self._theme.public("bg"))
        except tk.TclError:
            pass
        if self._state == "idle":
            self._show_idle()

    @property
    def is_open(self) -> bool:
        return self._window is not None and self._window.winfo_exists()

    @property
    def window(self) -> tk.Toplevel | None:
        return self._window
