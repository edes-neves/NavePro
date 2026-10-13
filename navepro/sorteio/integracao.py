"""Integração do Sorteio Profissional com o NavePro.

Expõe :func:`abrir_sorteio`, chamada pelo botão "Sorteio" do painel do
operador. A janela do sorteio (operador) abre sobre o painel do NavePro e a
tela pública (telão) é desenhada por cima do relógio, no monitor do telão.

O sorteio roda no mesmo processo/Tk do NavePro: nada de ``mainloop`` novo.
Ao fechar a janela do sorteio, a tela pública do telão é destruída e o
relógio do NavePro reaparece.
"""

import tkinter as tk

from navepro.core.log import get_logger
from navepro.core.monitores import get_monitors_config
from navepro.core.util_tk import _centralizar_sobre

from . import ctk

log = get_logger("sorteio")

_TAMANHO_JANELA = (1200, 880)

# Mantém referência viva do sorteio aberto (evita GC) por root do NavePro.
_aberto: dict[int, dict] = {}


def _geometria_telao(app_interface):
    """Retorna ``(public_rect, public_master)`` do telão do NavePro.

    ``public_rect`` é ``(x, y, w, h)`` do monitor do telão; ``public_master``
    é o root Tk do telão (para a tela pública ser filha dele). Ambos None se
    o telão ainda não existe ou se só há um monitor (nesse caso a tela
    pública cobriria o próprio painel do operador).
    """
    try:
        if len(get_monitors_config()) < 2:
            return None, None
    except Exception as e:  # pragma: no cover - defensivo
        log.debug("Não foi possível contar monitores: %s", e)

    player = getattr(app_interface, "player", None)
    telao = getattr(player, "telao", None) if player is not None else None
    if telao is None and player is not None:
        try:
            player._garantir_telao()  # type: ignore[attr-defined]
        except Exception as e:  # pragma: no cover - defensivo
            log.warning("Não foi possível garantir o telão: %s", e)
        telao = getattr(player, "telao", None)
    if telao is None:
        return None, None
    master = getattr(telao, "root", None)
    monitor = getattr(telao, "_monitor", None)
    rect = None
    if monitor is not None:
        rect = (monitor.x, monitor.y, monitor.width, monitor.height)
    return rect, master


def abrir_sorteio(app_interface) -> None:
    """Abre (ou traz para frente) a janela do Sorteio Profissional."""
    root = getattr(app_interface, "root", None)
    if root is None:
        return

    chave = id(root)
    estado = _aberto.get(chave)
    if estado is not None:
        janela = estado.get("janela")
        try:
            if janela is not None and janela.winfo_exists():
                janela.deiconify()
                janela.lift()
                janela.focus_force()
                return
        except tk.TclError:
            pass
        _aberto.pop(chave, None)

    from .app import App

    width, height = _TAMANHO_JANELA
    janela = ctk.CTkToplevel(root)
    janela.title("🎲 Sorteio Profissional")
    janela.minsize(width, height)
    janela.geometry(f"{width}x{height}")
    _centralizar_sobre(janela, root)

    public_rect, public_master = _geometria_telao(app_interface)

    app = App()

    def _fechar() -> None:
        try:
            if getattr(app, "_public_window", None) is not None:
                app._public_window.close()
                app._public_window = None
        except Exception:
            pass
        try:
            if janela.winfo_exists():
                janela.destroy()
        except tk.TclError:
            pass
        estado_atual = _aberto.get(chave)
        if estado_atual is not None and estado_atual.get("janela") is janela:
            _aberto.pop(chave, None)

    app.start_embedded(
        janela,
        public_rect=public_rect,
        public_master=public_master,
        on_close=_fechar,
    )

    _aberto[chave] = {"janela": janela, "app": app}

    try:
        janela.lift()
        janela.focus_force()
    except tk.TclError:
        pass
