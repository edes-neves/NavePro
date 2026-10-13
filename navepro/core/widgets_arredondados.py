"""Widgets de botão e campo de digitação com cantos arredondados.

O Tk 8.6 não desenha cantos arredondados nativamente em ``Button``/``Entry``.
Este módulo oferece substitutos que imitam a API dos widgets originais
(``text``/``bg``/``fg``/``state``/``command``/``get``/``insert``/``bind`` ...)
mas desenham o fundo arredondado num ``Canvas`` (o truque do polígono
``smooth``).

São usados de forma transparente pelo NavePro: no topo do ``NavePro.py`` o
módulo ``tk`` é envolvido por :class:`TkArredondado`, que troca ``tk.Button`` e
``tk.Entry`` por :class:`BotaoArredondado` e :class:`CampoArredondado` sem
alterar nenhuma chamada existente.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont

_COR_TEXTO_PADRAO = "#c9d1d9"
_COR_TEXTO_DESABILITADO = "#8b949e"
_BG_PADRAO = "#0d1117"


def _texto(valor):
    """Converte ``Tcl_Obj`` (devolvido por alguns ``cget``) em ``str``."""
    interno = getattr(valor, "string", None)
    if interno is not None:
        return str(interno)
    return valor


def _cor_do_pai(master) -> str:
    """Cor de fundo efetiva do pai (para o fundo 'herdar' e os cantos
    arredondados aparecerem)."""
    for attr in ("bg", "background"):
        try:
            return str(master.cget(attr))
        except Exception:
            continue
    return _BG_PADRAO


def _round_rect(canvas, x1, y1, x2, y2, radius, fill, outline="", width=0,
                tags=""):
    """Desenha um retângulo de cantos arredondados num ``Canvas``."""
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


class BotaoArredondado(tk.Frame):
    """Botão com cantos arredondados compatível com a API do ``tk.Button``.

    Aceita as opções usadas pelo projeto (``text``, ``command``, ``font``,
    ``bg``, ``fg``, ``activebackground``, ``activeforeground``, ``state``,
    ``cursor``, ``padx``, ``pady``, ``anchor``, ``justify``, ``image``) e pode
    ser reconfigurado em tempo de execução (``configure(text=..., bg=...,
    fg=..., state=..., command=...)``).
    """

    def __init__(self, master=None, text="", command=None, font=None,
                 bg=None, fg=None, activebackground=None, activeforeground=None,
                 state="normal", cursor="hand2", padx=8, pady=4, bd=0,
                 highlightthickness=0, anchor="center", justify="center",
                 image=None, compound="center", disabledforeground=None,
                 relief="flat", corner_radius=8, width=0, height=0, **kwargs):
        parent_bg = _cor_do_pai(master)
        self._bg = str(bg) if bg else parent_bg
        self._fg = str(fg) if fg else _COR_TEXTO_PADRAO
        self._active_bg = str(activebackground) if activebackground else self._bg
        self._active_fg = (
            str(activeforeground) if activeforeground else self._fg
        )
        self._disabled_fg = disabledforeground or _COR_TEXTO_DESABILITADO
        self._text = text
        self._command = command
        self._image = image
        self._state = state or "normal"
        self._padx = int(padx or 0)
        self._pady = int(pady or 0)
        self._anchor = anchor or "center"
        self._justify = justify or "center"
        self._radius = int(corner_radius or 0)
        self._font_spec = font
        self._hovered = False
        self._largura_fixa = int(width or 0)
        self._altura_fixa = int(height or 0)
        self._cores_extra = {}

        tk.Frame.__init__(self, master, bg=parent_bg, highlightthickness=0, bd=0)
        self.configure(cursor=cursor)

        self._canvas = tk.Canvas(self, bg=parent_bg, highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)

        self._canvas.bind("<Configure>", self._redraw)
        self._canvas.bind("<Enter>", self._on_enter)
        self._canvas.bind("<Leave>", self._on_leave)
        self._canvas.bind("<Button-1>", self._on_press)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)

        self._configurar_tamanho(width, height)

    # ── Fonte / medição ──
    def _fonte(self):
        try:
            if self._font_spec is not None:
                return tkfont.Font(root=self, font=self._font_spec)
            return tkfont.nametofont("TkDefaultFont")
        except Exception:
            return tkfont.Font(root=self)

    def _medida(self) -> tuple[int, int]:
        largura = altura = 0
        if self._text:
            f = self._fonte()
            largura = f.measure(self._text)
            altura = f.metrics("linespace")
        if self._image is not None:
            try:
                largura = max(largura, self._image.width())
                altura = max(altura, self._image.height())
            except Exception:
                pass
        return int(largura) + 2 * self._padx + 6, int(altura) + 2 * self._pady + 6

    def _configurar_tamanho(self, width=None, height=None) -> None:
        largura, altura = self._medida()
        largura = int(width) if width else self._largura_fixa or largura
        altura = int(height) if height else self._altura_fixa or altura
        self._canvas.configure(width=max(1, int(largura)),
                               height=max(1, int(altura)))

    # ── Desenho ──
    def _redraw(self, _event=None) -> None:
        try:
            c = self._canvas
            w = self.winfo_width()
            h = self.winfo_height()
            if w <= 1 or h <= 1:
                w = c.winfo_reqwidth()
                h = c.winfo_reqheight()
        except tk.TclError:
            return
        if w <= 1 or h <= 1:
            return

        desabilitado = self._state == "disabled"
        preenchimento = self._bg
        cor_texto = self._fg
        if desabilitado:
            cor_texto = self._disabled_fg
        elif self._hovered:
            preenchimento = self._active_bg
            cor_texto = self._active_fg

        c.delete("all")
        _round_rect(c, 1, 1, w - 1, h - 1, self._radius, preenchimento,
                    tags="bgshape")

        if self._text:
            x, anchor = self._posicao_texto(w)
            c.create_text(x, h // 2, text=self._text, fill=cor_texto,
                          font=self._font_spec, anchor=anchor,
                          justify=self._justify)
        if self._image is not None:
            c.create_image(w // 2, h // 2, image=self._image)

    def _posicao_texto(self, w: int):
        # Comparação exata: "center" contém a letra "e", então o teste por
        # substring antigo alinhava todo botão centralizado à direita.
        a = str(self._anchor)
        if a in ("w", "nw", "sw"):
            return self._padx + 2, "w"
        if a in ("e", "ne", "se"):
            return w - self._padx - 2, "e"
        return w // 2, "center"

    # ── Eventos ──
    def _on_enter(self, _event=None) -> None:
        self._hovered = True
        self._redraw()

    def _on_leave(self, _event=None) -> None:
        self._hovered = False
        self._redraw()

    def _on_press(self, _event=None) -> None:
        if self._state == "disabled":
            return
        self._redraw()

    def _on_release(self, event=None) -> None:
        if self._state == "disabled":
            return
        try:
            if event is not None:
                x, y = event.x, event.y
                if x < 0 or y < 0 or x > self._canvas.winfo_width() \
                        or y > self._canvas.winfo_height():
                    return
        except Exception:
            pass
        self.invoke()

    def invoke(self):
        if self._state == "disabled":
            return None
        if self._command is not None:
            return self._command()
        return None

    def flash(self) -> None:
        return None

    # O ``Canvas`` cobre o frame, então os eventos de mouse chegam nele.
    # Repassamos ``<Enter>``/``<Leave>`` para o canvas (tooltips do app são
    # registradas no botão-fachada).
    def bind(self, sequence=None, func=None, add=None):
        resultado = tk.Frame.bind(self, sequence, func, add)
        if sequence in ("<Enter>", "<Leave>") and hasattr(self, "_canvas"):
            self._canvas.bind(sequence, func, add="+")
        return resultado

    def unbind(self, sequence, funcid=None):
        try:
            self._canvas.unbind(sequence, funcid)
        except tk.TclError:
            pass
        return tk.Frame.unbind(self, sequence, funcid)

    # ── Compatibilidade de configuração ──
    def configure(self, **kwargs):
        redesenhar = False
        remedir = False
        if "text" in kwargs:
            self._text = kwargs.pop("text")
            redesenhar = True
            remedir = True
        if "bg" in kwargs or "background" in kwargs:
            novo = kwargs.pop("bg", None) or kwargs.pop("background", None)
            if novo:
                self._bg = str(novo)
                redesenhar = True
        if "fg" in kwargs or "foreground" in kwargs:
            novo = kwargs.pop("fg", None) or kwargs.pop("foreground", None)
            if novo:
                self._fg = str(novo)
                redesenhar = True
        if "activebackground" in kwargs:
            novo = kwargs.pop("activebackground")
            if novo:
                self._active_bg = str(novo)
        if "activeforeground" in kwargs:
            novo = kwargs.pop("activeforeground")
            if novo:
                self._active_fg = str(novo)
        if "disabledforeground" in kwargs:
            self._disabled_fg = kwargs.pop("disabledforeground")
        if "state" in kwargs:
            self._state = kwargs.pop("state") or "normal"
            redesenhar = True
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        if "font" in kwargs:
            self._font_spec = kwargs.pop("font")
            remedir = True
            redesenhar = True
        if "cursor" in kwargs:
            cursor = kwargs.pop("cursor")
            try:
                tk.Frame.configure(self, cursor=cursor)
            except tk.TclError:
                pass
        if "anchor" in kwargs:
            self._anchor = kwargs.pop("anchor") or "center"
            redesenhar = True
        if "justify" in kwargs:
            self._justify = kwargs.pop("justify") or "center"
            redesenhar = True
        if "image" in kwargs:
            self._image = kwargs.pop("image")
            redesenhar = True
        if "compound" in kwargs:
            kwargs.pop("compound")
        if "corner_radius" in kwargs:
            self._radius = int(kwargs.pop("corner_radius") or 0)
            redesenhar = True
        if "textvariable" in kwargs:
            kwargs.pop("textvariable")
        for extra in ("highlightbackground", "highlightcolor", "selectcolor",
                      "selectbackground", "selectforeground", "troughcolor",
                      "arrowcolor"):
            if extra in kwargs:
                self._cores_extra[extra] = kwargs.pop(extra)
        if remedir:
            self._configurar_tamanho()
        if redesenhar:
            self._redraw()
        if kwargs:
            for ignorar in ("bd", "highlightthickness", "relief", "takefocus",
                            "overrelief", "underline", "wraplength", "width",
                            "height"):
                kwargs.pop(ignorar, None)
        if kwargs:
            try:
                tk.Frame.configure(self, **kwargs)
            except tk.TclError:
                pass

    config = configure

    def keys(self):
        return [
            "text", "command", "font", "state", "cursor", "anchor", "justify",
            "background", "foreground", "activebackground", "activeforeground",
            "disabledforeground", "highlightbackground", "highlightcolor",
            "selectcolor", "padx", "pady", "bd", "relief", "corner_radius",
            "image", "compound",
        ]

    def cget(self, key):
        if key in ("bg", "background"):
            return self._bg
        if key in ("fg", "foreground"):
            return self._fg
        if key == "text":
            return self._text
        if key == "state":
            return self._state
        if key == "command":
            return self._command
        if key == "activebackground":
            return self._active_bg
        if key == "activeforeground":
            return self._active_fg
        if key == "disabledforeground":
            return self._disabled_fg
        if key == "font":
            return self._font_spec
        if key in self._cores_extra:
            return self._cores_extra[key]
        return _texto(tk.Frame.cget(self, key))

    def __setitem__(self, key, value):
        self.configure(**{key: value})

    def __getitem__(self, key):
        return self.cget(key)


class CampoArredondado(tk.Frame):
    """Campo de digitação com cantos arredondados compatível com ``tk.Entry``.

    É um ``Frame`` com um ``Canvas`` que desenha o retângulo arredondado e um
    ``tk.Entry`` de verdade por cima, recuado o suficiente para os cantos
    aparecerem. Os métodos do ``Entry`` (``get``/``insert``/``delete``/
    ``bind``/``icursor``/``selection_range`` ...) são repassados ao widget
    interno, de modo que o restante do código continua igual.
    """

    def __init__(self, master=None, bg=None, fg=None, insertbackground=None,
                 bd=0, highlightthickness=0, textvariable=None, width=0,
                 justify=None, relief="flat", readonlybackground=None,
                 show=None, state="normal", font=None, corner_radius=6,
                 **kwargs):
        parent_bg = _cor_do_pai(master)
        self._bg = str(bg) if bg else parent_bg
        self._fg = str(fg) if fg else _COR_TEXTO_PADRAO
        self._radius = int(corner_radius or 0)
        self._border_w = 1 if (bd or highlightthickness) else 0
        self._border_color = "#30363d"
        self._readonly_bg = str(readonlybackground) if readonlybackground \
            else self._bg
        self._em_redesenho = False

        tk.Frame.__init__(self, master, bg=parent_bg, highlightthickness=0, bd=0)

        self._canvas = tk.Canvas(self, bg=parent_bg, highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)

        entry_opts = {
            "bg": self._bg,
            "fg": self._fg,
            "insertbackground": str(insertbackground) if insertbackground
            else self._fg,
            "relief": "flat",
            "bd": 0,
            "highlightthickness": 0,
        }
        if font is not None:
            entry_opts["font"] = font
        if textvariable is not None:
            entry_opts["textvariable"] = textvariable
        if width:
            entry_opts["width"] = width
        if justify is not None:
            entry_opts["justify"] = justify
        if show is not None:
            entry_opts["show"] = show
        if readonlybackground is not None:
            entry_opts["readonlybackground"] = self._readonly_bg
        self._entry = tk.Entry(self, **entry_opts)
        if state and state != "normal":
            try:
                self._entry.configure(state=state)
            except tk.TclError:
                pass
        self._state = state or "normal"
        self._entry.bind("<Configure>", lambda _e: self._redraw(), add="+")
        self._canvas.bind("<Configure>", self._redraw)
        self.after(0, lambda: self._configurar_tamanho())

    # ── Tamanho ──
    def _configurar_tamanho(self) -> None:
        try:
            if not self.winfo_exists():
                return
            self.update_idletasks()
            lw = self._entry.winfo_reqwidth()
            lh = self._entry.winfo_reqheight()
            self._canvas.configure(
                width=max(1, lw + 2 * self._radius + 4),
                height=max(1, lh + 2 * self._border_w + 6),
            )
        except tk.TclError:
            return

    # ── Desenho ──
    def _redraw(self, _event=None) -> None:
        if self._em_redesenho:
            return
        try:
            c = self._canvas
            w = self.winfo_width()
            h = self.winfo_height()
            if w <= 1 or h <= 1:
                w = c.winfo_reqwidth()
                h = c.winfo_reqheight()
        except tk.TclError:
            return
        if w <= 1 or h <= 1:
            return
        self._em_redesenho = True
        try:
            c.delete("all")
            fill = self._readonly_bg if self._state == "readonly" else self._bg
            _round_rect(
                c, 0, 0, w, h, self._radius, fill,
                outline=self._border_color if self._border_w else "",
                width=self._border_w, tags="bgshape",
            )
            recuo = self._radius + self._border_w
            self._entry.place(
                x=recuo, y=self._border_w,
                width=max(1, w - 2 * recuo),
                height=max(1, h - 2 * self._border_w),
            )
        finally:
            self._em_redesenho = False

    # ── Repasse para o Entry interno ──
    def get(self):
        return self._entry.get()

    def insert(self, index, string):
        return self._entry.insert(index, string)

    def delete(self, first, last=None):
        if last is None:
            return self._entry.delete(first)
        return self._entry.delete(first, last)

    def bind(self, sequence=None, func=None, add=None):
        return self._entry.bind(sequence, func, add)

    def unbind(self, sequence, funcid=None):
        return self._entry.unbind(sequence, funcid)

    def focus_set(self):
        return self._entry.focus_set()

    def focus_force(self):
        return self._entry.focus_force()

    def configure(self, **kwargs):
        redesenhar = False
        if "bg" in kwargs or "background" in kwargs:
            novo = kwargs.pop("bg", None) or kwargs.pop("background", None)
            if novo:
                self._bg = str(novo)
                self._entry.configure(bg=self._bg)
                redesenhar = True
        if "fg" in kwargs or "foreground" in kwargs:
            novo = kwargs.pop("fg", None) or kwargs.pop("foreground", None)
            if novo:
                self._fg = str(novo)
                self._entry.configure(fg=self._fg, insertbackground=self._fg)
                redesenhar = True
        if "insertbackground" in kwargs:
            self._entry.configure(insertbackground=kwargs.pop("insertbackground"))
        if "state" in kwargs:
            self._state = kwargs.pop("state") or "normal"
            self._entry.configure(state=self._state)
            redesenhar = True
        if "font" in kwargs:
            self._entry.configure(font=kwargs.pop("font"))
            self._configurar_tamanho()
        if "textvariable" in kwargs:
            self._entry.configure(textvariable=kwargs.pop("textvariable"))
        if "show" in kwargs:
            self._entry.configure(show=kwargs.pop("show"))
        if "justify" in kwargs:
            self._entry.configure(justify=kwargs.pop("justify"))
        if "readonlybackground" in kwargs:
            self._readonly_bg = kwargs.pop("readonlybackground") or self._bg
            self._entry.configure(readonlybackground=self._readonly_bg)
            redesenhar = True
        kwargs.pop("corner_radius", None)
        for ignorar in ("bd", "highlightthickness", "relief", "takefocus"):
            kwargs.pop(ignorar, None)
        if redesenhar:
            self._redraw()
        for chave, valor in kwargs.items():
            try:
                self._entry.configure(**{chave: valor})
            except tk.TclError:
                pass

    config = configure

    def keys(self):
        try:
            return list(self._entry.keys())
        except tk.TclError:
            return list(tk.Frame.keys(self))

    def cget(self, key):
        if key in ("bg", "background"):
            return self._bg
        if key in ("fg", "foreground"):
            return self._fg
        if key == "state":
            return self._state
        try:
            return _texto(self._entry.cget(key))
        except tk.TclError:
            return _texto(tk.Frame.cget(self, key))

    def __setitem__(self, key, value):
        self.configure(**{key: value})

    def __getitem__(self, key):
        return self.cget(key)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        entry = self.__dict__.get("_entry")
        if entry is not None:
            return getattr(entry, name)
        raise AttributeError(name)


class TkArredondado:
    """Fachada do módulo ``tkinter`` que troca ``Button``/``Entry`` por
    versões arredondadas, repassando todo o resto para o módulo real."""

    def __init__(self, modulo):
        self._modulo = modulo
        self.Button = BotaoArredondado
        self.Entry = CampoArredondado

    def __getattr__(self, name):
        return getattr(self._modulo, name)
