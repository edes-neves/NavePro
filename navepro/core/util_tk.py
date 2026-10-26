"""Utilitários Tkinter compartilhados.

Extraído de NavePro.py sem alterar o comportamento (ver AGENTS.md).
"""

import tkinter as tk

from navepro.core.log import get_logger

log = get_logger("util_tk")


# ────────────────────────────────────────────────────────────────────
# POSICIONAMENTO DE JANELAS SECUNDÁRIAS
# ────────────────────────────────────────────────────────────────────


def _centralizar_sobre(janela, pai=None, area=None) -> None:
    """Posiciona `janela` centralizada sobre `pai` (ou sobre a tela).

    Uma Toplevel criada só com geometry("LxA") (sem coordenadas) deixa o
    posicionamento por conta do window manager: no Windows ele centraliza
    sobre a janela pai, mas no Linux/Wayland ele decide sozinho e em
    multi-monitor abre até no monitor errado (ex.: no telão). Aqui a
    posição é explícita e igual em qualquer SO.

    Mede o tamanho real da janela (com fallback para o tamanho requisitado
    quando ainda não mapeada) e desloca o centro dela para o centro de
    `pai`. Se `pai` não existir mais, centraliza na tela.

    `area`, quando informada, é um retângulo `(x, y, largura, altura)` — por
    exemplo, a geometria do monitor do operador. Nesse caso a janela é
    centralizada nessa área, mesmo que `pai` esteja maximizado por vários
    monitores (no X11, `winfo_width()` pode somar a tela inteira).
    """
    try:
        janela.update_idletasks()
        w = janela.winfo_width()
        h = janela.winfo_height()
        if w <= 1 or h <= 1:
            w = max(w, janela.winfo_reqwidth())
            h = max(h, janela.winfo_reqheight())
        if area is not None:
            px, py, pw, ph = (int(v) for v in area)
        elif pai is not None:
            try:
                if pai.winfo_exists():
                    px, py = pai.winfo_x(), pai.winfo_y()
                    pw, ph = pai.winfo_width(), pai.winfo_height()
                else:
                    raise tk.TclError
            except tk.TclError:
                px = py = 0
                pw = janela.winfo_screenwidth()
                ph = janela.winfo_screenheight()
        else:
            px = py = 0
            pw = janela.winfo_screenwidth()
            ph = janela.winfo_screenheight()
        if pw <= 1 or ph <= 1:
            return
        x = px + max(0, (pw - w) // 2)
        y = py + max(0, (ph - h) // 2)
        janela.geometry(f"+{x}+{y}")
    except (tk.TclError, TypeError, ValueError):
        pass


# ────────────────────────────────────────────────────────────────────
# JANELAS QUE PRECISAM CABER EM 1024x768
# ────────────────────────────────────────────────────────────────────


def _limitar_ao_monitor(
        janela, w: int, h: int, margem: int = 48,
        area=None) -> tuple[int, int]:
    """Define apenas o tamanho `w`x`h` de `janela`, limitado ao monitor.

    O NavePro precisa funcionar de 1024x768 até as resoluções mais altas.
    Janelas com tamanho fixo maior que a tela (ex.: 680x980 num monitor de
    1024x768) ficariam cortadas. Aqui o tamanho pedido é limitado à tela
    com uma margem de segurança (para decoração/barra de tarefas). Nunca
    aumenta além do pedido nem diminui abaixo de um mínimo utilizável.

    A posição NÃO é definida aqui de propósito: em multi-monitor,
    `winfo_screenwidth()`/`winfo_screenheight()` devolvem a tela virtual
    inteira e centralizar por eles jogaria o diálogo no monitor do
    telão. Chame `_centralizar_sobre(janela, pai, area=...)` depois, informando a
    área do monitor do operador.

    `area`, quando informada, é o retângulo `(x, y, largura, altura)` do
    monitor do operador: o tamanho é limitado por ele (e não pela tela
    virtual, que pode ser bem maior com dois monitores).

    Devolve o tamanho realmente aplicado `(w, h)`.
    """
    try:
        if area is not None:
            aw, ah = int(area[2]), int(area[3])
        else:
            aw = janela.winfo_screenwidth()
            ah = janela.winfo_screenheight()
        max_w = max(320, aw - margem)
        max_h = max(240, ah - margem)
        w = max(320, min(w, max_w))
        h = max(240, min(h, max_h))
        janela.geometry(f"{w}x{h}")
        return w, h
    except tk.TclError:
        return w, h


# ────────────────────────────────────────────────────────────────────
# TELÃO - JANELA DE PROJEÇÃO (mantido)
# ────────────────────────────────────────────────────────────────────


def _normalizar_escala_tk(root) -> float:
    """Garante texto legível e consistente entre Python/Tk diferentes.

    O AppImage usa o python do sistema (AppRun), que pode ter um Tk com
    'tk scaling' baixo (ex.: dpi desconhecido), deixando botões e fontes
    minúsculos no monitor 1 e as letras pequenas no telão. Este ajuste
    aplica um piso de zoom (1.3 px/ponto, ≈96dpi) em qualquer interpretador.
    """
    escala_min = 1.3
    try:
        pixels_por_pol = float(root.winfo_fpixels('1i'))
        escala = pixels_por_pol / 72.0
        if escala < escala_min:
            escala = escala_min
        root.tk.call('tk', 'scaling', escala)
        return escala
    except Exception:
        try:
            root.tk.call('tk', 'scaling', escala_min)
        except Exception:
            pass
        return escala_min


