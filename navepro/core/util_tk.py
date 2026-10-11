"""Utilitários Tkinter compartilhados.

Extraído de NavePro.py sem alterar o comportamento (ver AGENTS.md).
"""

import tkinter as tk

from navepro.core.log import get_logger

log = get_logger("util_tk")


# ────────────────────────────────────────────────────────────────────
# POSICIONAMENTO DE JANELAS SECUNDÁRIAS
# ────────────────────────────────────────────────────────────────────


def _centralizar_sobre(janela, pai=None) -> None:
    """Posiciona `janela` centralizada sobre `pai` (ou sobre a tela).

    Uma Toplevel criada só com geometry("LxA") (sem coordenadas) deixa o
    posicionamento por conta do window manager: no Windows ele centraliza
    sobre a janela pai, mas no Linux/Wayland ele decide sozinho e em
    multi-monitor abre até no monitor errado (ex.: no telão). Aqui a
    posição é explícita e igual em qualquer SO.

    Mede o tamanho real da janela (com fallback para o tamanho requisitado
    quando ainda não mapeada) e desloca o centro dela para o centro de
    `pai`. Se `pai` não existir mais, centraliza na tela.
    """
    try:
        janela.update_idletasks()
        w = janela.winfo_width()
        h = janela.winfo_height()
        if w <= 1 or h <= 1:
            w = max(w, janela.winfo_reqwidth())
            h = max(h, janela.winfo_reqheight())
        if pai is not None:
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
    except tk.TclError:
        pass


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


