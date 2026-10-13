import random
import tkinter as tk
from typing import TYPE_CHECKING, Optional

from . import APP_VERSION, ctk
from .font_manager import ui_font
from .theme_manager import ThemeManager

if TYPE_CHECKING:
    from .monitor_manager import MonitorInfo


class SplashScreen(ctk.CTkToplevel):

    def __init__(
        self,
        parent: ctk.CTk,
        theme: ThemeManager | None = None,
        monitor: Optional["MonitorInfo"] = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme or ThemeManager()
        self._parent = parent
        self._monitor = monitor
        self._progress = 0.0

        self._setup_window()
        self._create_widgets()

        self.after(50, self._animate_progress)

    def _setup_window(self) -> None:
        w, h = 500, 350

        if self._monitor is not None:
            x = self._monitor.x + (self._monitor.width - w) // 2
            y = self._monitor.y + (self._monitor.height - h) // 2
        else:
            sw = self._parent.winfo_screenwidth()
            sh = self._parent.winfo_screenheight()
            x = (sw - w) // 2
            y = (sh - h) // 2

        self.geometry(f"{w}x{h}+{x}+{y}")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color=self._theme.c("bg"))

        self._canvas = tk.Canvas(
            self,
            width=w,
            height=h,
            highlightthickness=0,
            bg=self._theme.c("bg"),
        )
        self._canvas.pack(fill="both", expand=True)

    def _create_widgets(self) -> None:
        c = self._canvas
        cw, ch = 500, 350

        c.create_text(
            cw // 2, 80,
            text="SORTEIO",
            font=(ui_font(), 48, "bold"),
            fill=self._theme.c("primary"),
            tags="title",
        )

        c.create_text(
            cw // 2, 130,
            text="Sistema Profissional de Sorteios",
            font=(ui_font(), 14),
            fill=self._theme.c("text_secondary"),
            tags="subtitle",
        )

        c.create_text(
            cw // 2, 170,
            text=f"v{APP_VERSION}",
            font=(ui_font(), 10),
            fill=self._theme.c("text_secondary"),
            tags="version",
        )

        bar_x, bar_y, bar_w, bar_h = 50, 240, 400, 20
        self._bar_outline = c.create_rectangle(
            bar_x, bar_y, bar_x + bar_w, bar_y + bar_h,
            outline=self._theme.c("border"),
            fill=self._theme.c("bg_card"),
            tags="bar_outline",
        )

        self._bar_fill = c.create_rectangle(
            bar_x + 2, bar_y + 2,
            bar_x + 2, bar_y + bar_h - 2,
            fill=self._theme.c("primary"),
            outline="",
            tags="bar_fill",
        )

        self._loading_text = c.create_text(
            cw // 2, 280,
            text="Inicializando...",
            font=(ui_font(), 10),
            fill=self._theme.c("text_secondary"),
            tags="loading_text",
        )

        self._decorative_particles(c, cw, ch)

    def _decorative_particles(
        self, canvas: tk.Canvas, w: int, h: int
    ) -> None:
        for _ in range(20):
            x = random.randint(0, w)
            y = random.randint(0, h)
            canvas.create_oval(
                x, y, x + 2, y + 2,
                fill=self._theme.c("primary"),
                outline="",
                tags="particles",
            )

    def _animate_progress(self) -> None:
        self._progress += random.uniform(0.28, 0.4)

        if self._progress >= 1.0:
            self._progress = 1.0
            self._update_bar()
            self._canvas.itemconfig(
                self._loading_text,
                text="Pronto!",
                fill=self._theme.c("success"),
            )
            self.after(200, self.destroy)
            return

        self._update_bar()
        self.after(70, self._animate_progress)

    def _update_bar(self) -> None:
        c = self._canvas
        bar_x, bar_y, bar_w, bar_h = 50, 240, 400, 20
        fill_width = int((bar_w - 4) * self._progress)
        c.coords(
            self._bar_fill,
            bar_x + 2, bar_y + 2,
            bar_x + 2 + fill_width, bar_y + bar_h - 2,
        )

        msgs = [
            "Inicializando...",
            "Carregando módulos...",
            "Configurando temas...",
            "Detectando monitores...",
            "Preparando interface...",
            "Pronto!",
        ]
        idx = min(int(self._progress * len(msgs)), len(msgs) - 1)
        self._canvas.itemconfig(self._loading_text, text=msgs[idx])
