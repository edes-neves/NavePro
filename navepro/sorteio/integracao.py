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
from navepro.core.util_tk import _centralizar_sobre, _limitar_ao_monitor

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


def _tema_navepro(app_interface) -> str:
    """Tema do NavePro no formato do sorteio ("light"/"dark")."""
    return "light" if getattr(app_interface, "tema", "escuro") == "claro" else "dark"


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
    # A árvore do sorteio tem tema próprio (cores do NavePro, mas com regras
    # de cartão/faixa do sorteio). A marca impede que a recoloração genérica
    # de tema do NavePro repinte esta janela no tema claro.
    janela._navepro_tema_proprio = True
    # Precisa caber de 1024x768 até resoluções maiores: limita o tamanho
    # inicial ao monitor e permite reduzir até um mínimo que caiba em 768.
    _limitar_ao_monitor(janela, width, height)
    janela.minsize(880, 620)
    _centralizar_sobre(janela, root)

    public_rect, public_master = _geometria_telao(app_interface)

    app = App()
    # Inicia o sorteio já no tema atual do NavePro.
    app._theme.definir_tema(_tema_navepro(app_interface))

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
        app_interface._sorteio_sync_tema = None
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

    # O NavePro dispara este callback sempre que o tema ativo muda (ver
    # _aplicar_tema), mantendo o sorteio em sincronia enquanto estiver aberto.
    app_interface._sorteio_sync_tema = lambda: sincronizar_tema(app_interface)

    try:
        janela.lift()
        janela.focus_force()
    except tk.TclError:
        pass


def _buscar_app_aberto(app_interface):
    """Retorna o :class:`App` do sorteio aberto, ou None se não houver."""
    root = getattr(app_interface, "root", None)
    if root is None:
        return None
    estado = _aberto.get(id(root))
    if not estado:
        return None
    return estado.get("app")


def _estado_do_app(app) -> dict:
    """Fotografia do sorteio para o controle remoto (números ou nomes)."""
    engine = getattr(app, "_engine", None)
    if engine is None:  # pragma: no cover - defensivo
        return {"aberto": True}
    return {
        "aberto": True,
        "modo": engine.mode,
        "estado": engine.state,
        "pronto": bool(engine.is_ready()),
        "concluido": bool(engine.is_completed()),
        "total": int(engine.total_numbers),
        "restantes": int(engine.remaining),
        "sorteados": list(engine.drawn_numbers),
        "config": _config_da_janela(getattr(app, "_main_window", None), engine),
    }


def _config_da_janela(mw, engine) -> dict:
    """Configuração atual (faixa/nomes e "por vez") para preencher o celular."""
    conf = {"inicio": 0, "fim": 0, "por_vez": 1, "nomes": []}
    if engine is not None:
        conf["inicio"] = int(getattr(engine, "start", 0) or 0)
        conf["fim"] = int(getattr(engine, "end", 0) or 0)
    if mw is None:
        return conf
    try:
        if getattr(mw, "_mode", "numbers") == "names":
            conf["por_vez"] = int(mw._names_per_draw())
            conf["nomes"] = list(
                getattr(mw, "_stored_names", None) or mw._names_from_input()
            )
        else:
            conf["por_vez"] = int(mw._numbers_per_draw())
    except Exception:  # pragma: no cover - defensivo
        pass
    return conf


def estado_sorteio(app_interface) -> dict:
    """Estado atual do sorteio, ou ``{"aberto": False}`` se estiver fechado."""
    app = _buscar_app_aberto(app_interface)
    if app is None:
        return {"aberto": False}
    return _estado_do_app(app)


def _erro_da_janela(app) -> str:
    """Texto do rótulo de erro da janela do operador (vazio se não houver)."""
    janela = getattr(app, "_main_window", None)
    label = getattr(janela, "_error_label", None)
    if label is None:
        return ""
    try:
        return str(label.cget("text") or "").strip()
    except Exception:  # pragma: no cover - defensivo
        return ""


def configurar_sorteio(app_interface, dados) -> dict:
    """Configura o sorteio (faixa de números ou lista de nomes) pelo celular.

    ``dados`` traz ``modo`` (``"numeros"``/``"nomes"``), ``por_vez`` e, para
    números, ``inicio``/``fim``; para nomes, ``nomes`` (texto com um nome por
    linha, aceitando também vírgulas). Reinicia o sorteio para a nova
    configuração valer já no próximo "Sortear".
    """
    app = _buscar_app_aberto(app_interface)
    if app is None:
        return {"ok": False, "erro": "Abra o Sorteio primeiro."}
    mw = getattr(app, "_main_window", None)
    if mw is None:  # pragma: no cover - defensivo
        return {"ok": False, "erro": "A janela do Sorteio não está pronta."}

    try:
        por_vez = int(dados.get("por_vez") or 1)
    except (TypeError, ValueError):
        por_vez = 1
    por_vez = max(1, min(5, por_vez))

    modo = str(dados.get("modo") or "").strip().lower()
    if modo in ("nomes", "names", "nome"):
        nomes = _lista_de_nomes(dados.get("nomes"))
        if not nomes:
            return {"ok": False, "erro": "Informe ao menos um nome para o sorteio."}
        try:
            mw.configurar_nomes(nomes, por_vez)
        except Exception as e:  # pragma: no cover - defensivo
            log.warning("Falha ao configurar os nomes pelo controle remoto: %s", e)
            return {"ok": False, "erro": "Não foi possível configurar os nomes."}
        return {"ok": True, **_estado_do_app(app)}

    from .validator import ValidationError, Validator

    try:
        inicio, fim = Validator.validate_range(
            str(dados.get("inicio") or ""), str(dados.get("fim") or "")
        )
    except ValidationError as e:
        return {"ok": False, "erro": str(e)}
    try:
        mw.configurar_numeros(inicio, fim, por_vez)
    except Exception as e:  # pragma: no cover - defensivo
        log.warning("Falha ao configurar a faixa pelo controle remoto: %s", e)
        return {"ok": False, "erro": "Não foi possível configurar o intervalo."}
    return {"ok": True, **_estado_do_app(app)}


def _lista_de_nomes(valor) -> list:
    """Normaliza a lista de nomes vinda do celular (linhas e/ou vírgulas)."""
    if isinstance(valor, (list, tuple)):
        linhas: list = []
        for item in valor:
            linhas.extend(str(item).splitlines())
    else:
        linhas = str(valor or "").splitlines()
    nomes: list = []
    for linha in linhas:
        for parte in str(linha).split(","):
            nome = parte.strip()
            if nome and nome not in nomes:
                nomes.append(nome)
    return nomes


def sortear(app_interface) -> dict:
    """Faz o próximo sorteio pelo controle remoto.

    Usa a mesma alternância do botão da janela do operador (inicia na
    primeira vez, sorteia o próximo depois). O intervalo/nomes precisam ter
    sido configurados na janela do Sorteio, no computador.
    """
    app = _buscar_app_aberto(app_interface)
    if app is None:
        return {"ok": False, "erro": "Abra o Sorteio primeiro."}
    janela = getattr(app, "_main_window", None)
    engine = getattr(app, "_engine", None)
    if janela is None or engine is None:  # pragma: no cover - defensivo
        return {"ok": False, "erro": "A janela do Sorteio não está pronta."}
    antes = engine.drawn_count
    try:
        janela._on_draw_toggle()
    except Exception as e:  # pragma: no cover - defensivo
        log.warning("Falha ao sortear pelo controle remoto: %s", e)
        return {"ok": False, "erro": "Não foi possível sortear."}
    if engine.drawn_count <= antes:
        msg = _erro_da_janela(app) or (
            "Não foi possível sortear. Configure o intervalo/nomes na janela "
            "do Sorteio (computador)."
        )
        return {"ok": False, "erro": msg}
    return {"ok": True, "desenhou": engine.drawn_count - antes, **_estado_do_app(app)}


def reiniciar(app_interface) -> dict:
    """Reinicia o sorteio (limpa os sorteados) pelo controle remoto."""
    app = _buscar_app_aberto(app_interface)
    if app is None:
        return {"ok": False, "erro": "Abra o Sorteio primeiro."}
    janela = getattr(app, "_main_window", None)
    if janela is None:  # pragma: no cover - defensivo
        return {"ok": False, "erro": "A janela do Sorteio não está pronta."}
    try:
        janela._on_clear_toggle()
    except Exception as e:  # pragma: no cover - defensivo
        log.warning("Falha ao reiniciar o sorteio pelo controle remoto: %s", e)
        return {"ok": False, "erro": "Não foi possível reiniciar."}
    return {"ok": True, **_estado_do_app(app)}


def sincronizar_tema(app_interface) -> None:
    """Aplica ao sorteio aberto o tema ativo do NavePro (chamado no toggle)."""
    root = getattr(app_interface, "root", None)
    if root is None:
        return
    estado = _aberto.get(id(root))
    if not estado:
        return
    app = estado.get("app")
    if app is None:
        return
    try:
        app.definir_tema(_tema_navepro(app_interface))
    except Exception as e:  # pragma: no cover - defensivo
        log.warning("Não foi possível sincronizar o tema do sorteio: %s", e)
