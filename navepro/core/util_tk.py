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
# MAXIMIZAR/RESTAURAR JANELAS SECUNDÁRIAS
# ────────────────────────────────────────────────────────────────────


def _janela_maximizada(janela, area=None) -> bool:
    """Diz se `janela` está maximizada.

    No Windows/macOS o Tk expõe o estado; em alguns ambientes Linux/X11 o
    Tk 8.6 não aceita "zoomed", então, quando `area` é informada, compara a
    geometria com a área do monitor para reconhecer a maximização feita pelo
    gerenciador de janelas.
    """
    try:
        if bool(janela.attributes("-zoomed")):
            return True
    except (tk.TclError, ValueError):
        pass
    try:
        if janela.state() == "zoomed":
            return True
    except tk.TclError:
        pass
    if area is not None:
        try:
            ax, ay, aw, ah = (int(v) for v in area)
            w = janela.winfo_width()
            h = janela.winfo_height()
            x = janela.winfo_x()
            y = janela.winfo_y()
            if aw > 1 and ah > 1:
                if w >= aw * 0.98 and h >= ah * 0.90:
                    return True
                if (w >= aw * 0.90 and h >= ah * 0.85
                        and x <= ax + 8 and y <= ay + 80):
                    return True
        except (tk.TclError, TypeError, ValueError):
            pass
    return False


def _habilitar_maximizar_janela(
        janela, geometria_inicial: str | None = None, area=None,
        ao_mudar_estado=None):
    """Permite maximizar/restaurar `janela` pelo botão do meio da barra de
    título (ou F11), voltando exatamente à geometria normal anterior.

    Em alguns ambientes Linux/X11 o Tk 8.6 ignora ``wm attributes -zoomed``
    e não aceita ``wm state zoomed``; nesse caso a maximização é feita pela
    geometria da área do monitor (quando `area` é informada). Também marca a
    janela como ``normal``: janelas ``transient`` recebem do gerenciador de
    janelas o tipo "diálogo", que desabilita o botão nativo de maximizar.

    `ao_mudar_estado`, se informado, é chamado com ``True``/``False`` sempre
    que o estado maximizado mudar (útil para atualizar o rótulo do botão).
    Devolve a função que alterna maximizado/restaurado e retorna o novo
    estado.
    """
    try:
        janela.attributes("-type", "normal")
    except tk.TclError:
        pass
    try:
        janela.resizable(True, True)
    except tk.TclError:
        pass

    estado = {
        "geo": geometria_inicial or "",
        "maximizada": _janela_maximizada(janela, area),
        "restaurando": False,
        "aplicando": False,
    }

    def _geometria() -> str:
        try:
            geo = janela.geometry()
            if geo and not geo.startswith("1x1"):
                return geo
        except tk.TclError:
            geo = ""
        try:
            janela.update_idletasks()
            w = janela.winfo_width()
            h = janela.winfo_height()
            if w <= 1 or h <= 1:
                w = janela.winfo_reqwidth()
                h = janela.winfo_reqheight()
            return f"{w}x{h}+{janela.winfo_x()}+{janela.winfo_y()}"
        except tk.TclError:
            return geo

    if not estado["geo"]:
        estado["geo"] = _geometria()

    def _notificar() -> None:
        if ao_mudar_estado is not None:
            try:
                ao_mudar_estado(estado["maximizada"])
            except Exception:
                pass

    def _restaurar_geometria() -> None:
        if not estado["geo"] or estado["restaurando"]:
            return
        estado["restaurando"] = True
        try:
            janela.geometry(str(estado["geo"]))
        except tk.TclError:
            pass
        finally:
            try:
                janela.after_idle(
                    lambda: estado.__setitem__("restaurando", False))
            except tk.TclError:
                estado["restaurando"] = False

    def _maximizar_pela_area() -> None:
        try:
            if area is not None:
                x, y, w, h = (int(v) for v in area)
            else:
                x = y = 0
                w = janela.winfo_screenwidth()
                h = janela.winfo_screenheight()
            if w > 1 and h > 1:
                janela.geometry(f"{w}x{h}+{x}+{y}")
        except (tk.TclError, TypeError, ValueError):
            pass

    def _limpar_aplicando() -> None:
        estado["aplicando"] = False

    def _marcar_aplicando() -> None:
        estado["aplicando"] = True
        try:
            janela.after(300, _limpar_aplicando)
        except tk.TclError:
            estado["aplicando"] = False

    def _conferir_maximizacao() -> None:
        """Fallback para WMs que ignoram -zoomed silenciosamente."""
        if not estado["maximizada"]:
            return
        if _janela_maximizada(janela, area):
            return
        _maximizar_pela_area()
        estado["maximizada"] = _janela_maximizada(janela, area)
        _notificar()

    def _definir_maximizada(maximizar: bool) -> None:
        if maximizar == estado["maximizada"]:
            return
        _marcar_aplicando()
        if maximizar:
            atual = _geometria()
            if atual:
                estado["geo"] = atual
            try:
                janela.attributes("-zoomed", True)
            except (tk.TclError, ValueError):
                try:
                    janela.state("zoomed")
                except tk.TclError:
                    _maximizar_pela_area()
            estado["maximizada"] = True
        else:
            try:
                janela.attributes("-zoomed", False)
            except (tk.TclError, ValueError):
                try:
                    janela.state("normal")
                except tk.TclError:
                    pass
            _restaurar_geometria()
            estado["maximizada"] = False
        _notificar()
        if maximizar:
            try:
                janela.after(400, _conferir_maximizacao)
            except tk.TclError:
                pass

    def _alternar(event=None):
        _definir_maximizada(not _janela_maximizada(janela, area))
        return estado["maximizada"]

    def _on_configure(event=None) -> None:
        if event is not None and getattr(event, "widget", janela) is not janela:
            return
        if estado["aplicando"]:
            return
        max_now = _janela_maximizada(janela, area)
        if max_now != estado["maximizada"]:
            estado["maximizada"] = max_now
            _notificar()

    try:
        janela.bind("<F11>", _alternar, add="+")
        janela.bind("<Configure>", _on_configure, add="+")
    except tk.TclError:
        pass
    _notificar()
    return _alternar


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


