"""Camada de compatibilidade ``customtkinter`` -> ``tkinter`` puro.

O Sorteio Profissional foi escrito com ``customtkinter``. Para embutir o
sorteio no NavePro (100% tkinter/Tk 8.6) sem reescrever a interface, este
módulo reimplementa o **subconjunto** da API do customtkinter que o projeto
usa. Os widgets abaixo são widgets tkinter/ttk de verdade; as opções
específicas do customtkinter (``fg_color``, ``text_color``, ``hover_color``,
``corner_radius``, ``placeholder_text`` ...) são traduzidas para as opções
equivalentes do tkinter.

Os módulos do sorteio importam este arquivo como ``from . import ctk`` (no
lugar de ``import customtkinter as ctk``), de modo que nenhum pacote externo
é necessário.
"""

import tkinter as tk
from tkinter import ttk

from ..core.widgets_arredondados import BotaoArredondado

# ──────────────────────────────────────────────────────────────────────
# Estado global (parte da API do customtkinter, sem efeito prático aqui)
# ──────────────────────────────────────────────────────────────────────

_appearance_mode = "dark"
_widget_scaling = 1.0
_window_scaling = 1.0
_default_theme = "dark-blue"

_TEMA_ESCURO = {
    "bg": "#050816",
    "bg_card": "#0d1233",
    "input_bg": "#050816",
    "text": "#ffffff",
    "text_secondary": "#8892b0",
    "btn_text": "#0a0e27",
    "primary": "#00d4ff",
    "border": "#1a1f4e",
}


class _ThemeManager:
    """Substitui ``ctk.ThemeManager`` (o app escreve em ``.theme``)."""

    theme = {
        "color": {
            "button": ["#3B8ED0", "#1F6AA5"],
            "window": ["#DBDBDB", "#242424"],
        }
    }


ThemeManager = _ThemeManager()


def set_appearance_mode(mode: str) -> None:
    global _appearance_mode
    _appearance_mode = mode


def get_appearance_mode() -> str:
    return _appearance_mode


def set_default_color_theme(name: str) -> None:
    global _default_theme
    _default_theme = name


def set_widget_scaling(value: float) -> None:
    global _widget_scaling
    _widget_scaling = value


def set_window_scaling(value: float) -> None:
    global _window_scaling
    _window_scaling = value


# ──────────────────────────────────────────────────────────────────────
# Utilitários
# ──────────────────────────────────────────────────────────────────────


def _bg_of(master) -> str:
    """Cor de fundo efetiva de um widget (para fundos 'transparentes')."""
    for attr in ("bg", "background"):
        try:
            return str(master.cget(attr))
        except Exception:
            continue
    return _TEMA_ESCURO["bg"]


def _resolve_color(master, color) -> str:
    """``fg_color`` -> cor de fundo tk; vazio/'transparent' herda do pai."""
    if color is None or color == "" or color == "transparent":
        return _bg_of(master)
    return str(color)


def _resolve_master(master):
    """Filhos de um CTkScrollableFrame entram no frame interno rolável."""
    if isinstance(master, CTkScrollableFrame):
        return master._inner
    return master


def _round_rect(canvas, x1, y1, x2, y2, radius, fill, outline="", width=0,
                tags=""):
    """Desenha um retângulo de cantos arredondados num Canvas.

    Usa um polígono ``smooth`` (o truque clássico do customtkinter) para
    arredondar sem precisar de imagens. Retorna o id do item criado.
    """
    r = int(max(0, min(radius, (x2 - x1) // 2, (y2 - y1) // 2)))
    if r <= 0:
        return canvas.create_rectangle(
            x1, y1, x2, y2, fill=fill, outline=outline or fill, width=width,
            tags=tags,
        )
    pontos = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(
        pontos, smooth=True, splinesteps=16, fill=fill,
        outline=outline or fill, width=width, tags=tags,
    )


def _safe_configure(widget, kwargs) -> None:
    if kwargs:
        try:
            widget.configure(**kwargs)
        except tk.TclError:
            pass


# ──────────────────────────────────────────────────────────────────────
# Widgets
# ──────────────────────────────────────────────────────────────────────


class CTkBaseClass:
    """Base apenas para ``isinstance``/type hints (compatibilidade)."""


class CTk(CTkBaseClass, tk.Tk):
    def __init__(self, *args, fg_color=None, **kwargs):
        kwargs.pop("className", None)
        tk.Tk.__init__(self, *args, **kwargs)
        self.configure(bg=fg_color or _TEMA_ESCURO["bg"])

    def configure(self, **kwargs):
        if "fg_color" in kwargs:
            kwargs["bg"] = kwargs.pop("fg_color")
        if kwargs:
            tk.Tk.configure(self, **kwargs)


class CTkToplevel(CTkBaseClass, tk.Toplevel):
    def __init__(self, master=None, fg_color=None, **kwargs):
        kwargs.pop("className", None)
        tk.Toplevel.__init__(self, master=master, **kwargs)
        self.configure(bg=fg_color or _TEMA_ESCURO["bg"])

    def configure(self, **kwargs):
        if "fg_color" in kwargs:
            kwargs["bg"] = kwargs.pop("fg_color")
        if kwargs:
            tk.Toplevel.configure(self, **kwargs)


class CTkFrame(CTkBaseClass, tk.Frame):
    def __init__(self, master=None, fg_color=None, corner_radius=0,
                 width=0, height=0, border_width=0, border_color=None,
                 **kwargs):
        master = _resolve_master(master)
        opts = {"bg": _resolve_color(master, fg_color)}
        if width:
            opts["width"] = width
        if height:
            opts["height"] = height
        if border_width:
            opts["highlightthickness"] = border_width
        if border_color:
            opts["highlightbackground"] = border_color
        tk.Frame.__init__(self, master, **opts)

    def configure(self, **kwargs):
        if "fg_color" in kwargs:
            kwargs["bg"] = _resolve_color(self.master, kwargs.pop("fg_color"))
        if "border_width" in kwargs:
            kwargs["highlightthickness"] = kwargs.pop("border_width")
        if "border_color" in kwargs:
            kwargs["highlightbackground"] = kwargs.pop("border_color")
        kwargs.pop("corner_radius", None)
        if kwargs:
            tk.Frame.configure(self, **kwargs)


class CTkLabel(CTkBaseClass, tk.Label):
    def __init__(self, master=None, text="", font=None, text_color=None,
                 fg_color=None, anchor=None, wraplength=0, justify=None,
                 **kwargs):
        master = _resolve_master(master)
        opts = {
            "text": text,
            "bg": _resolve_color(master, fg_color),
            "fg": text_color or _TEMA_ESCURO["text"],
        }
        if font is not None:
            opts["font"] = font
        if anchor is not None:
            opts["anchor"] = anchor
        if wraplength:
            opts["wraplength"] = wraplength
        if justify is not None:
            opts["justify"] = justify
        tk.Label.__init__(self, master, **opts)

    def configure(self, **kwargs):
        if "text_color" in kwargs:
            kwargs["fg"] = kwargs.pop("text_color")
        if "fg_color" in kwargs:
            kwargs["bg"] = _resolve_color(self.master, kwargs.pop("fg_color"))
        kwargs.pop("corner_radius", None)
        if kwargs:
            tk.Label.configure(self, **kwargs)


class CTkButton(CTkBaseClass, BotaoArredondado):
    """Botão arredondado com a API do ``customtkinter``.

    Herda de :class:`BotaoArredondado` (que desenha os cantos num ``Canvas``)
    e traduz ``fg_color``/``hover_color``/``text_color`` para as cores do
    botão, mantendo a atualização dinâmica de tema usada pelo sorteio.
    """

    def __init__(self, master=None, text="", command=None, font=None,
                 fg_color=None, hover_color=None, text_color=None,
                 corner_radius=8, width=0, height=0, state="normal",
                 anchor=None, **kwargs):
        master = _resolve_master(master)
        self._fg_color = _resolve_color(master, fg_color or _TEMA_ESCURO["primary"])
        self._hover_color = _resolve_color(master, hover_color or self._fg_color)
        self._text_color = text_color or _TEMA_ESCURO["btn_text"]
        super().__init__(
            master,
            text=text,
            command=command,
            font=font,
            bg=self._fg_color,
            fg=self._text_color,
            activebackground=self._hover_color,
            activeforeground=self._text_color,
            disabledforeground=_TEMA_ESCURO["text_secondary"],
            state=state,
            cursor="hand2",
            padx=10,
            pady=5,
            corner_radius=corner_radius,
            width=width,
            height=height,
            anchor=anchor or "center",
        )

    def configure(self, **kwargs):
        if "fg_color" in kwargs:
            nova = _resolve_color(self.master, kwargs.pop("fg_color"))
            if nova:
                self._fg_color = nova
            kwargs["bg"] = self._fg_color
        if "hover_color" in kwargs:
            nova = _resolve_color(self.master, kwargs.pop("hover_color"))
            if nova:
                self._hover_color = nova
            kwargs["activebackground"] = self._hover_color
        if "text_color" in kwargs:
            self._text_color = kwargs.pop("text_color") or self._text_color
            kwargs["fg"] = self._text_color
            kwargs["activeforeground"] = self._text_color
        kwargs.pop("corner_radius", None)
        BotaoArredondado.configure(self, **kwargs)

    config = configure


class CTkEntry(CTkBaseClass, tk.Frame):
    """Campo de texto com cantos arredondados.

    O tkinter puro não arredonda ``Entry``. Aqui o campo é um ``Frame`` com
    um ``Canvas`` que desenha o retângulo arredondado (cor de fundo/borda) e
    um ``Entry`` de verdade por cima, recuado o suficiente para que os cantos
    apareçam arredondados. Os métodos ``get``/``insert``/``delete`` são
    repassados ao ``Entry`` interno, de modo que o restante do sorteio
    continua usando o widget como antes.
    """

    def __init__(self, master=None, textvariable=None, font=None,
                 fg_color=None, text_color=None, border_width=0,
                 border_color=None, placeholder_text="", width=0, height=0,
                 corner_radius=10, justify=None, show=None, **kwargs):
        master = _resolve_master(master)
        self._input_bg = (
            _resolve_color(master, fg_color) if fg_color
            else _TEMA_ESCURO["input_bg"]
        )
        self._normal_fg = text_color or _TEMA_ESCURO["text"]
        self._border_color = border_color or _TEMA_ESCURO["border"]
        self._border_width = int(border_width or 0)
        self._radius = int(corner_radius or 0)
        self._placeholder = placeholder_text or ""
        self._show_placeholder = False
        parent_bg = _bg_of(master)

        tk.Frame.__init__(
            self, master, bg=parent_bg, highlightthickness=0, bd=0,
            width=width or 200, height=height or 38,
        )
        self.pack_propagate(False)
        self.grid_propagate(False)

        self._canvas = tk.Canvas(self, bg=parent_bg, highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)

        entry_opts = {
            "bg": self._input_bg,
            "fg": self._normal_fg,
            "insertbackground": self._normal_fg,
            "relief": "flat",
            "bd": 0,
            "highlightthickness": 0,
        }
        if font is not None:
            entry_opts["font"] = font
        if textvariable is not None:
            entry_opts["textvariable"] = textvariable
        if justify is not None:
            entry_opts["justify"] = justify
        if show is not None:
            entry_opts["show"] = show
        self._entry = tk.Entry(self, **entry_opts)

        self._canvas.bind("<Configure>", self._redraw)
        if self._placeholder:
            self._entry.bind("<FocusIn>", self._ph_focus_in, add="+")
            self._entry.bind("<FocusOut>", self._ph_focus_out, add="+")
            self._apply_placeholder()
        self.after(0, self._redraw)

    # ── Desenho dos cantos arredondados ──
    def _redraw(self, _event=None):
        try:
            c = self._canvas
            w = self.winfo_width()
            h = self.winfo_height()
        except tk.TclError:
            return
        if w <= 1 or h <= 1:
            w = self.winfo_reqwidth()
            h = self.winfo_reqheight()
        c.delete("bgshape")
        _round_rect(
            c, 0, 0, w, h, self._radius, self._input_bg,
            outline=self._border_color if self._border_width else "",
            width=self._border_width, tags="bgshape",
        )
        recuo = self._radius + self._border_width
        self._entry.place(
            x=recuo, y=self._border_width,
            width=max(1, w - 2 * recuo),
            height=max(1, h - 2 * self._border_width),
        )

    # ── Placeholder (mantém o comportamento original) ──
    def _apply_placeholder(self):
        if not self._placeholder:
            return
        self._show_placeholder = True
        self._entry.configure(fg=_TEMA_ESCURO["text_secondary"])
        self._entry.insert(0, self._placeholder)

    def _ph_focus_in(self, _event=None):
        if self._show_placeholder:
            self._entry.delete(0, "end")
            self._entry.configure(fg=self._normal_fg)
            self._show_placeholder = False

    def _ph_focus_out(self, _event=None):
        if self._placeholder and not self._entry.get():
            self._apply_placeholder()

    # ── Repasse ao Entry interno ──
    def get(self):
        if self._show_placeholder:
            return ""
        return self._entry.get()

    def insert(self, index, string):
        self._ph_focus_in()
        return self._entry.insert(index, string)

    def delete(self, first, last=None):
        self._show_placeholder = False
        self._entry.configure(fg=self._normal_fg)
        if last is None:
            return self._entry.delete(first)
        return self._entry.delete(first, last)

    def bind(self, sequence=None, func=None, add=None):
        return self._entry.bind(sequence, func, add)

    def focus_set(self):
        return self._entry.focus_set()

    def configure(self, **kwargs):
        if "fg_color" in kwargs:
            novo = _resolve_color(self.master, kwargs.pop("fg_color"))
            if novo:
                self._input_bg = novo
            self._entry.configure(bg=self._input_bg)
        if "text_color" in kwargs:
            self._normal_fg = kwargs.pop("text_color") or self._normal_fg
            self._entry.configure(
                fg=self._normal_fg, insertbackground=self._normal_fg
            )
        if "border_width" in kwargs:
            self._border_width = int(kwargs.pop("border_width") or 0)
        if "border_color" in kwargs:
            self._border_color = kwargs.pop("border_color") or self._border_color
        if "corner_radius" in kwargs:
            self._radius = int(kwargs.pop("corner_radius") or 0)
        kwargs.pop("placeholder_text", None)
        self._redraw()
        if kwargs:
            tk.Frame.configure(self, **kwargs)

    config = configure

    def cget(self, key):
        if key == "fg_color":
            return self._input_bg
        if key == "text_color":
            return self._normal_fg
        return tk.Frame.cget(self, key)


class CTkTextbox(CTkBaseClass, tk.Text):
    def __init__(self, master=None, font=None, fg_color=None, text_color=None,
                 border_width=0, border_color=None, corner_radius=0,
                 width=0, height=0, **kwargs):
        master = _resolve_master(master)
        opts = {
            "bg": _resolve_color(master, fg_color) if fg_color
            else _TEMA_ESCURO["input_bg"],
            "fg": text_color or _TEMA_ESCURO["text"],
            "insertbackground": text_color or _TEMA_ESCURO["text"],
            "relief": "flat",
            "bd": 0,
            "highlightthickness": border_width or 0,
            "highlightbackground": border_color or _TEMA_ESCURO["border"],
        }
        if font is not None:
            opts["font"] = font
        if width:
            opts["width"] = max(1, int(width / 8))
        if height:
            # altura vem em pixels; converte para linhas aproximadas.
            opts["height"] = max(1, int(height / 18))
        tk.Text.__init__(self, master, **opts)

    def configure(self, **kwargs):
        if "fg_color" in kwargs:
            kwargs["bg"] = _resolve_color(self.master, kwargs.pop("fg_color"))
        if "text_color" in kwargs:
            kwargs["fg"] = kwargs.pop("text_color")
            kwargs["insertbackground"] = kwargs["fg"]
        if "border_width" in kwargs:
            kwargs["highlightthickness"] = kwargs.pop("border_width")
        if "border_color" in kwargs:
            kwargs["highlightbackground"] = kwargs.pop("border_color")
        kwargs.pop("corner_radius", None)
        if kwargs:
            tk.Text.configure(self, **kwargs)


class CTkCheckBox(CTkBaseClass, tk.Checkbutton):
    def __init__(self, master=None, text="", variable=None, command=None,
                 font=None, text_color=None, fg_color=None, hover_color=None,
                 checkbox_width=0, checkbox_height=0, **kwargs):
        master = _resolve_master(master)
        bg = _resolve_color(master, None)
        opts = {
            "text": text,
            "variable": variable,
            "command": command,
            "bg": bg,
            "fg": text_color or _TEMA_ESCURO["text"],
            "activebackground": bg,
            "activeforeground": text_color or _TEMA_ESCURO["text"],
            "selectcolor": fg_color or _TEMA_ESCURO["primary"],
            "relief": "flat",
            "bd": 0,
            "highlightthickness": 0,
            "cursor": "hand2",
        }
        if font is not None:
            opts["font"] = font
        tk.Checkbutton.__init__(self, master, **opts)

    def configure(self, **kwargs):
        if "text_color" in kwargs:
            kwargs["fg"] = kwargs.pop("text_color")
        kwargs.pop("corner_radius", None)
        kwargs.pop("checkbox_width", None)
        kwargs.pop("checkbox_height", None)
        if kwargs:
            tk.Checkbutton.configure(self, **kwargs)


class CTkSegmentedButton(CTkBaseClass, tk.Frame):
    def __init__(self, master=None, values=None, command=None, variable=None,
                 font=None, fg_color=None, selected_color=None, **kwargs):
        master = _resolve_master(master)
        tk.Frame.__init__(self, master, bg=_bg_of(master))
        self._values = list(values or [])
        self._command = command
        self._variable = variable
        self._font = font or ("Arial", 12)
        self._selected_color = selected_color or _TEMA_ESCURO["primary"]
        self._value = None
        self._buttons: dict = {}
        for value in self._values:
            btn = tk.Button(
                self, text=value, font=self._font, relief="flat", bd=0,
                highlightthickness=0, cursor="hand2", padx=12, pady=4,
                command=lambda v=value: self._select(v),
            )
            btn.pack(side="left", padx=1, pady=1)
            self._buttons[value] = btn
        if self._values:
            self.set(self._values[0])

    def _select(self, value):
        self.set(value)
        if self._command:
            self._command(value)

    def set(self, value):
        self._value = value
        if self._variable is not None:
            try:
                self._variable.set(value)
            except Exception:
                pass
        for val, btn in self._buttons.items():
            if val == value:
                btn.configure(bg=self._selected_color, fg=_TEMA_ESCURO["btn_text"],
                              activebackground=self._selected_color)
            else:
                btn.configure(bg=_TEMA_ESCURO["bg_card"], fg=_TEMA_ESCURO["text"],
                              activebackground=_TEMA_ESCURO["border"])

    def get(self):
        return self._value


class CTkProgressBar(CTkBaseClass, ttk.Progressbar):
    def __init__(self, master=None, width=200, height=20, mode="determinate",
                 **kwargs):
        master = _resolve_master(master)
        ttk.Progressbar.__init__(self, master, mode=mode, maximum=1.0,
                                 length=width)

    def set(self, value):
        try:
            ttk.Progressbar.configure(self, value=value)
        except tk.TclError:
            pass

    def configure(self, **kwargs):
        for key in ("fg_color", "progress_color", "corner_radius",
                    "border_width"):
            kwargs.pop(key, None)
        if kwargs:
            try:
                ttk.Progressbar.configure(self, **kwargs)
            except tk.TclError:
                pass


class CTkScrollableFrame(CTkBaseClass, tk.Frame):
    def __init__(self, master=None, fg_color=None, corner_radius=0, **kwargs):
        master = _resolve_master(master)
        bg = _resolve_color(master, fg_color)
        tk.Frame.__init__(self, master, bg=bg)
        self._canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self._scrollbar = tk.Scrollbar(
            self, orient="vertical", command=self._canvas.yview,
            bg=bg, troughcolor=bg, bd=0, highlightthickness=0,
        )
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._inner = tk.Frame(self._canvas, bg=bg)
        self._window_id = self._canvas.create_window(
            (0, 0), window=self._inner, anchor="nw"
        )
        self._inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind("<Button-4>", self._on_mousewheel)
        self._canvas.bind("<Button-5>", self._on_mousewheel)

    def _on_inner_configure(self, _event=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfigure(self._window_id, width=event.width)

    def _on_mousewheel(self, event):
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self._canvas.yview_scroll(delta, "units")

    def winfo_children(self):
        return self._inner.winfo_children()

    @property
    def inner(self):
        return self._inner

    def configure(self, **kwargs):
        if "fg_color" in kwargs:
            bg = _resolve_color(self.master, kwargs.pop("fg_color"))
            kwargs["bg"] = bg
            self._canvas.configure(bg=bg)
            self._inner.configure(bg=bg)
        kwargs.pop("corner_radius", None)
        if kwargs:
            tk.Frame.configure(self, **kwargs)
