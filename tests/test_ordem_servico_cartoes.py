#!/usr/bin/env python3
"""Regressões de desempenho dos cartões da Ordem de Projeção.

Cobre as correções feitas para o "piscar"/travar ao abrir programações com
muitos itens:

1. durante a montagem dos cartões o estilo "reproduzido" não dispara a
   passada de seleção em todos os cartões (era O(n²) de ``configure``);
2. o ``<Configure>`` do canvas é debounced e só reaplica ``wraplength``
   quando a largura realmente muda;
3. as consultas de duração rodam com concorrência limitada (2 por vez);
4. o arraste pré-calcula a geometria dos cartões e usa busca binária;
5. seleção/reproduzido atualizam só os cartões que mudaram de estado;
6. referências de mídia/anúncio são resolvidas numa passada só;
7. marcações de "reproduzido" são agrupadas num único salvamento;
8. o tick da contagem só faz o trabalho pesado quando há player tocando;
9. o layout ignora o canvas antes de ele ter largura real.

As funções internas são extraídas via AST e executadas com dublês, como nos
demais testes headless.
"""

import ast
import copy
import os
import sys
import tempfile
import types

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

_MOD = os.path.join(RAIZ, "navepro", "ui", "janela_ordem_servico.py")
_SRC = open(_MOD, encoding="utf-8").read()
_TREE = ast.parse(_SRC)
_JANELA = next(
    no for no in ast.walk(_TREE)
    if isinstance(no, ast.FunctionDef) and no.name == "janela_ordem_servico")
_FUNCS = {
    no.name: no for no in ast.walk(_JANELA)
    if isinstance(no, ast.FunctionDef)
}


class TclError(Exception):
    pass


class _Var:
    def __init__(self, valor=False):
        self.valor = valor

    def get(self):
        return self.valor


def _carregar_ns(*nomes, **ns):
    for nome in nomes:
        codigo = ast.get_source_segment(_SRC, _FUNCS[nome])
        exec(compile(ast.parse(codigo), f"<{nome}>", "exec"), ns)  # noqa: S102
    ns.setdefault("tk", types.SimpleNamespace(TclError=TclError))
    return ns


class _Widget:
    def __init__(self, nome=""):
        self.nome = nome
        self.configs = []

    def configure(self, **kw):
        self.configs.append(kw)

    def get(self):  # só para o BooleanVar falso
        return False


class _Canvas(_Widget):
    def __init__(self, largura=1000):
        super().__init__("canvas")
        self.largura = largura
        self.itens = []
        self.timers = {}
        self._seq = 0

    def winfo_width(self):
        return self.largura

    def itemconfigure(self, item, **kw):
        self.itens.append((item, kw))

    def bbox(self, _tag):
        return (0, 0, self.largura, 500)

    def after(self, ms, callback):
        self._seq += 1
        self.timers[str(self._seq)] = (ms, callback)
        return str(self._seq)

    def after_cancel(self, timer):
        self.timers.pop(str(timer), None)


def _ns_reproduzido():
    chamadas = []
    widget = _Widget()

    def _selecao(*args):
        chamadas.append(args)

    ns = {
        "_cards": {"1": {"check_var": _Var(True),
                         "fontes": [(widget, ("Arial", 11, "bold"))]}},
        "_atualizar_selecao_visual": _selecao,
    }
    ns = _carregar_ns("_fonte_com_risco", "_aplicar_estilo_reproduzido", **ns)
    return ns, widget, chamadas


def _ns_layout(largura=1000):
    canvas = _Canvas(largura)
    labels = [_Widget("t1"), _Widget("t2")]
    ns = {
        "lista_canvas": canvas,
        "_canvas_window": 1,
        "_cards": {
            "1": {"titulo": labels[0], "url": None},
            "2": {"titulo": labels[1], "url": None},
        },
        "_layout": {"largura": None, "wrap": None, "timer": None},
    }
    ns = _carregar_ns("_cancelar_layout_agendado", "_atualizar_layout_canvas",
                      "_agendar_layout_canvas", **ns)
    return ns, canvas, labels


def _ns_cartao():
    acoes = []
    ns = {
        "_ordem": ["1", "2", "3"],
        "_cards": {"1": {}, "2": {}, "3": {}},
        "_selecionados": {"2"},
        "_foco": {"id": "2"},
        "_ancora": {"id": "2"},
    }

    def destruir(iid):
        ns["_cards"].pop(iid, None)
        if iid in ns["_ordem"]:
            ns["_ordem"].remove(iid)
        acoes.append(("destruir", iid))

    def criar(it, indice, pos=None):
        iid = str(it.get("id"))
        if pos is None or pos >= len(ns["_ordem"]):
            ns["_ordem"].append(iid)
        else:
            ns["_ordem"].insert(pos, iid)
        ns["_cards"][iid] = {}
        acoes.append(("criar", indice, pos))

    ns.update({
        "_destruir_card": destruir,
        "_criar_card": criar,
        "_atualizar_selecao_visual": lambda *args: acoes.append("selecao"),
        "_cancelar_layout_agendado": lambda: acoes.append("cancelar"),
        "_atualizar_layout_canvas": lambda: acoes.append("layout"),
    })
    ns = _carregar_ns("_indice_do_card", "_atualizar_cartao_item", **ns)
    ns["_acoes"] = acoes
    return ns


def _ns_duracao():
    chamadas = []

    class _Root:
        def __init__(self):
            self.idles = []

        def after_idle(self, cb):
            self.idles.append(cb)
            return f"idle{len(self.idles)}"

    class _Thread:
        criadas = []

        def __init__(self, target, args, daemon, name):
            self.args = args
            _Thread.criadas.append(self)

        def start(self):
            pass

    root = _Root()
    ns = {
        "_duracao_cache": {},
        "_duracao_pendente": set(),
        "_duracao_fila": {},
        "_duracao_jobs": {},
        "_duracao_timers": {"inicio": None, "poll": None},
        "_DURACAO_MAX_WORKERS": 2,
        "_eh_url_youtube": lambda c: c.startswith("https://"),
        "os": os,
        "self": types.SimpleNamespace(root=root, player=object()),
        "threading": types.SimpleNamespace(Thread=_Thread),
        "_trabalho_duracao": lambda *a: None,
        "_agendar_poll_duracoes": lambda: chamadas.append("poll"),
    }
    ns = _carregar_ns("_agendar_inicio_duracoes", "_iniciar_duracoes",
                      "_despachar_duracoes", "_pedir_duracao", **ns)
    ns["_root"] = root
    ns["_thread"] = _Thread
    ns["_chamadas"] = chamadas
    return ns


def _ns_definir_selecao():
    chamadas = []

    def _selecao(iids=None):
        chamadas.append(iids)

    ns = {
        "_cards": {"1": {}, "2": {}, "3": {}},
        "_selecionados": {"1"},
        "_foco": {"id": "1"},
        "_atualizar_selecao_visual": _selecao,
    }
    ns = _carregar_ns("_definir_selecao", **ns)
    return ns, chamadas


def _ns_posicao():
    ns = {
        "_ordem": [],
        "_cards": {},
        "_geometria_dos_cards": lambda: [],
    }
    return _carregar_ns("_calcular_posicao", **ns)


def _ns_referencias():
    consultas = []
    buscas = []
    anuncios = [
        {"id": 7, "arquivo_midia": "/anuncios/7.mp4"},
        {"id": 8, "arquivo_midia": "/anuncios/8.mp4"},
        {"id": 9, "arquivo_midia": "/anuncios/9.mp4"},
    ]

    def _db_query(_query, params=()):
        consultas.append(params)
        return [{"id": 10, "caminho_arquivo": "/midia/10.mp4"},
                {"id": 11, "caminho_arquivo": "/midia/11.mp3"}]

    def _buscar(ref):
        buscas.append(ref)
        return next((a for a in anuncios if a["id"] == ref), None)

    ns = {
        "db_query": _db_query,
        "_listar_anuncios_db": lambda: list(anuncios),
        "_buscar_anuncio_por_ref": _buscar,
        "_extensao_midia": lambda _p: True,
        "os": os,
    }
    ns = _carregar_ns("_precarregar_referencias", "_caminho_item", **ns)
    return ns, consultas, buscas


def _ns_marcacoes(disco, pendentes=None, salvar_ok=True):
    if pendentes is None:
        pendentes = {("1", "10"): (True, False),
                     ("1", "11"): (True, False)}
    pendentes = dict(pendentes)
    dados = copy.deepcopy(disco)
    for (sid, iid), (marcado, _anterior) in pendentes.items():
        serv = next((s for s in (dados.get("servicos") or [])
                     if str(s.get("id")) == str(sid)), None)
        item = next((x for x in ((serv or {}).get("itens") or [])
                     if str(x.get("id")) == str(iid)), None)
        if item is not None:
            item["reproduzido"] = marcado

    salvos = []
    avisos = []
    estilos = []

    class _VarMarcada:
        def __init__(self, valor):
            self.valor = valor

        def get(self):
            return self.valor

        def set(self, valor):
            self.valor = valor

    class _Janela:
        def after_cancel(self, _timer):
            pass

        def winfo_exists(self):
            return True

    def _salvar(dados_novos):
        if salvar_ok:
            salvos.append(copy.deepcopy(dados_novos))
        return salvar_ok

    ns = {
        "_marcacoes_pendentes": pendentes,
        "_marcacao_timer": {"id": None},
        "janela": _Janela(),
        "_carregar_servicos_json": lambda: copy.deepcopy(disco),
        "_salvar_servicos_json": _salvar,
        "_servico_atual": lambda: {"id": 1},
        "log": types.SimpleNamespace(debug=lambda *a, **k: None),
        "dados": dados,
        "_cards": {
            iid: {"check_var": _VarMarcada(marcado)}
            for (_sid, iid), (marcado, _ant) in pendentes.items()
        },
        "_aplicar_estilo_reproduzido": lambda iid: estilos.append(iid),
        "tkinter": types.SimpleNamespace(
            messagebox=types.SimpleNamespace(
                showwarning=lambda *a, **k: avisos.append(a))),
    }
    ns = _carregar_ns("_cancelar_salvamento_marcacoes",
                      "_salvar_marcacoes_pendentes", **ns)
    ns["_salvos"] = salvos
    ns["_avisos"] = avisos
    ns["_estilos"] = estilos
    ns["_dados"] = dados
    return ns


def _ns_tick(tocando, iid=None):
    atrasos = []
    atualizou = []

    class _Janela:
        def winfo_exists(self):
            return True

        def after(self, ms, _callback):
            atrasos.append(ms)
            return f"t{len(atrasos)}"

    ns = {
        "_timers": {"contagem": None},
        "janela": _Janela(),
        "self": types.SimpleNamespace(
            player=types.SimpleNamespace(is_playing=tocando)),
        "_contagem": {"iid": iid},
        "_atualizar_contagem": lambda: atualizou.append(True),
        "log": types.SimpleNamespace(debug=lambda *a, **k: None),
        "_CONTAGEM_ATIVA_MS": 500,
        "_CONTAGEM_REPOUSO_MS": 1000,
    }
    ns = _carregar_ns("_tick_contagem", **ns)
    ns["_atrasos"] = atrasos
    ns["_atualizou"] = atualizou
    return ns


def _rodar():
    falhas = []

    def check(nome, cond, extra=""):
        print(f"{'OK ' if cond else 'FALHA'} {nome}"
              f"{(' -> ' + str(extra)) if extra else ''}")
        if not cond:
            falhas.append(nome)

    # ── 1) Estilo "reproduzido" sem varredura de seleção na montagem ──
    ns, widget, chamadas = _ns_reproduzido()
    ns["_aplicar_estilo_reproduzido"]("1", atualizar_selecao=False)
    check("montagem não percorre a seleção de todos os cartões",
          "selecao" not in chamadas, chamadas)
    check("montagem ainda aplica o risco de reproduzido",
          widget.configs and "overstrike" in str(widget.configs[-1]),
          widget.configs)

    widget.configs.clear()
    chamadas.clear()
    ns["_aplicar_estilo_reproduzido"]("1")
    check("clique do operador continua atualizando a seleção",
          chamadas, chamadas)
    check("reproduzido atualiza só o cartão alterado",
          chamadas[-1] == (("1",),), chamadas)

    src_criar = ast.get_source_segment(_SRC, _FUNCS["_criar_card"])
    check("_criar_card usa a versão sem varredura de seleção",
          "_aplicar_estilo_reproduzido(iid, atualizar_selecao=False)"
          in src_criar)

    src_carregar = ast.get_source_segment(_SRC, _FUNCS["_carregar_itens"])
    check("_carregar_itens força reaplicar o wrap dos cartões novos",
          '_layout["wrap"] = None' in src_carregar)

    # ── 2) Debounce e deduplicação do layout ──
    ns, canvas, labels = _ns_layout()
    ns["_atualizar_layout_canvas"]()
    check("primeiro layout aplica a largura e o wrap",
          len(canvas.itens) == 1
          and all(len(w.configs) == 1 for w in labels),
          (canvas.itens, [w.configs for w in labels]))

    ns["_atualizar_layout_canvas"]()
    check("mesma largura não reaplica wrap (sem repintura à toa)",
          len(canvas.itens) == 1
          and all(len(w.configs) == 1 for w in labels),
          (canvas.itens, [w.configs for w in labels]))

    canvas.largura = 800
    ns["_atualizar_layout_canvas"]()
    check("mudar a largura reaplica o wrap uma vez",
          len(canvas.itens) == 2
          and all(len(w.configs) == 2 for w in labels),
          (canvas.itens, [w.configs for w in labels]))

    antes = (len(canvas.itens), [len(w.configs) for w in labels])
    canvas.largura = 1
    ns["_atualizar_layout_canvas"]()
    check("layout ignora o canvas antes de ele ter largura real",
          (len(canvas.itens), [len(w.configs) for w in labels]) == antes,
          (canvas.itens, [w.configs for w in labels]))

    ns["_agendar_layout_canvas"]()
    primeiro = dict(canvas.timers)
    ns["_agendar_layout_canvas"]()
    check("debounce mantém só um timer pendente",
          len(canvas.timers) == 1, canvas.timers)
    check("debounce agenda para 60 ms",
          all(ms == 60 for ms, _cb in canvas.timers.values()),
          canvas.timers)
    check("debounce substitui o timer anterior",
          set(primeiro) != set(canvas.timers),
          (primeiro, canvas.timers))

    ns["_cancelar_layout_agendado"]()
    check("cancelar o layout agendado limpa o timer",
          not canvas.timers, canvas.timers)

    # ── 3) Montagem oculta e revelação no fim ──
    canvas = _Canvas()
    ns3 = _carregar_ns("_mostrar_cartoes", lista_canvas=canvas,
                       _canvas_window=7)
    ns3["_mostrar_cartoes"](False)
    ns3["_mostrar_cartoes"](True)
    check("montagem oculta a lista e só revela no fim",
          canvas.itens == [(7, {"state": "hidden"}),
                           (7, {"state": "normal"})], canvas.itens)

    # ── 4) Durações adiadas para o idle e iniciadas em lote ──
    local = os.path.abspath(__file__)
    ns4 = _ns_duracao()
    ns4["_pedir_duracao"]("/caminho/que/nao/existe.mp4")
    check("arquivo inexistente não entra na fila de duração",
          not ns4["_duracao_fila"], ns4["_duracao_fila"])

    ns4["_pedir_duracao"](local)
    check("arquivo local entra na fila e agenda o início no idle",
          local in ns4["_duracao_fila"] and len(ns4["_root"].idles) == 1,
          (ns4["_duracao_fila"], ns4["_root"].idles))

    ns4["_pedir_duracao"]("https://youtu.be/abc")
    check("URL do YouTube entra na fila sem duplicar o timer",
          "https://youtu.be/abc" in ns4["_duracao_fila"]
          and len(ns4["_root"].idles) == 1,
          (ns4["_duracao_fila"], ns4["_root"].idles))
    check("nenhuma thread nasce durante a montagem",
          not ns4["_thread"].criadas)

    ns4["_iniciar_duracoes"]()
    check("no idle as consultas começam e a fila esvazia",
          not ns4["_duracao_fila"]
          and len(ns4["_thread"].criadas) == 2
          and ns4["_duracao_pendente"] == {local, "https://youtu.be/abc"},
          (ns4["_duracao_fila"], len(ns4["_thread"].criadas),
           ns4["_duracao_pendente"]))
    check("o timer de início é limpo ao iniciar as consultas",
          ns4["_duracao_timers"]["inicio"] is None)

    # ── 5) Concorrência limitada das durações ──
    ns4b = _ns_duracao()
    temporarios = []
    try:
        for _ in range(5):
            descritor, caminho = tempfile.mkstemp(suffix=".mp4")
            os.close(descritor)
            temporarios.append(caminho)
            ns4b["_pedir_duracao"](caminho)
        ns4b["_iniciar_duracoes"]()
        check("no máximo 2 consultas de duração rodam por vez",
              len(ns4b["_thread"].criadas) == 2,
              len(ns4b["_thread"].criadas))
        check("as demais consultas esperam na fila de jobs",
              len(ns4b["_duracao_jobs"]) == 3, ns4b["_duracao_jobs"])

        liberado = next(iter(ns4b["_duracao_pendente"]))
        ns4b["_duracao_pendente"].discard(liberado)
        ns4b["_despachar_duracoes"]()
        check("um resultado liberado inicia a próxima consulta",
              len(ns4b["_thread"].criadas) == 3
              and len(ns4b["_duracao_jobs"]) == 2,
              (len(ns4b["_thread"].criadas),
               len(ns4b["_duracao_jobs"])))
    finally:
        for caminho in temporarios:
            os.unlink(caminho)

    # ── 6) Atualização só do cartão afetado ──
    ns5 = _ns_cartao()
    ns5["_atualizar_cartao_item"]({"id": 2, "tipo": "slide"})
    check("edição recria só o cartão na mesma posição",
          ("criar", 2, 1) in ns5["_acoes"]
          and ns5["_ordem"] == ["1", "2", "3"], ns5["_acoes"])
    check("edição preserva seleção, foco e âncora",
          "2" in ns5["_selecionados"] and ns5["_foco"]["id"] == "2"
          and ns5["_ancora"]["id"] == "2")

    ns5 = _ns_cartao()
    ns5["_atualizar_cartao_item"]({"id": 4, "tipo": "slide"})
    check("novo item entra só no fim da lista",
          ("criar", 4, None) in ns5["_acoes"]
          and ns5["_ordem"] == ["1", "2", "3", "4"], ns5["_acoes"])

    # ── 7) Seleção atualiza só o diff ──
    ns7, chamadas = _ns_definir_selecao()
    ns7["_definir_selecao"]({"2", "3"})
    check("seleção atualiza só os cartões que mudaram",
          chamadas == [{"1", "2", "3"}], chamadas)

    ns7["_definir_selecao"]({"2", "3"})
    check("repetir a mesma seleção não redesenha nada",
          len(chamadas) == 1, chamadas)

    ns7["_definir_selecao"]({"2", "9"})
    check("ids fora da lista são ignorados no diff",
          chamadas[-1] == {"3"}, chamadas)

    # ── 8) Arraste com geometria pré-calculada e busca binária ──
    ns8 = _ns_posicao()
    geometria = [("a", 0, 100), ("b", 100, 100), ("c", 200, 100)]
    check("posição antes do primeiro cartão",
          ns8["_calcular_posicao"](10, geometria) == (0, 0))
    check("posição no limite inferior usa o cartão seguinte",
          ns8["_calcular_posicao"](50, geometria) == (1, 100))
    check("posição entre cartões",
          ns8["_calcular_posicao"](175, geometria) == (2, 200))
    check("posição depois do último cartão",
          ns8["_calcular_posicao"](999, geometria) == (3, 300))
    check("lista vazia não calcula posição",
          ns8["_calcular_posicao"](10, []) is None)

    # ── 9) Referências de banco resolvidas numa passada só ──
    ns9, consultas, buscas = _ns_referencias()
    itens_ref = [
        {"id": 1, "tipo": "video", "referencia_id": 10},
        {"id": 2, "tipo": "audio", "referencia_id": 11},
        {"id": 3, "tipo": "video", "referencia_id": 10},
        {"id": 4, "tipo": "anuncio", "referencia_id": 7},
        {"id": 5, "tipo": "anuncio", "referencia_id": 8},
    ]
    refs = ns9["_precarregar_referencias"](itens_ref)
    check("mídias da lista são consultadas de uma vez (ids deduplicados)",
          len(consultas) == 1, consultas)
    check("anúncios são lidos uma vez e só os referenciados entram no mapa",
          len(refs[1]) == 2 and not buscas, (refs[1], buscas))
    check("caminho de mídia usa o mapa pré-carregado",
          ns9["_caminho_item"](itens_ref[0], refs) == "/midia/10.mp4")
    check("caminho de anúncio usa o mapa pré-carregado",
          ns9["_caminho_item"](itens_ref[3], refs) == "/anuncios/7.mp4")
    check("pré-carga não dispara consultas extras nos cartões",
          len(consultas) == 1 and not buscas, (consultas, buscas))
    ns9["_caminho_item"](itens_ref[0])
    check("sem pré-carga mantém a consulta item a item",
          len(consultas) == 2, consultas)

    # ── 10) Marcações de reproduzido agrupadas ──
    disco = {"servicos": [{"id": 1, "itens": [
        {"id": "10", "reproduzido": False},
        {"id": "11", "reproduzido": False},
    ]}]}
    ns10 = _ns_marcacoes(disco)
    ns10["_salvar_marcacoes_pendentes"]()
    check("duas marcações geram um único salvamento",
          len(ns10["_salvos"]) == 1, ns10["_salvos"])
    itens_salvos = ns10["_salvos"][0]["servicos"][0]["itens"]
    check("lote aplica todas as marcações pendentes",
          all(it["reproduzido"] for it in itens_salvos), itens_salvos)
    check("fila de marcações fica vazia após salvar",
          not ns10["_marcacoes_pendentes"])

    ns10b = _ns_marcacoes(
        {"servicos": [{"id": 1, "itens": [
            {"id": "10", "reproduzido": True},
            {"id": "11", "reproduzido": False},
        ]}]},
        pendentes={("1", "10"): (False, False),
                   ("1", "11"): (True, False)})
    ns10b["_salvar_marcacoes_pendentes"]()
    itens10b = ns10b["_salvos"][0]["servicos"][0]["itens"]
    check("marcação alterada por outra via não é sobrescrita",
          itens10b[0]["reproduzido"] is True
          and itens10b[1]["reproduzido"] is True, itens10b)

    ns10c = _ns_marcacoes(disco, salvar_ok=False)
    ns10c["_salvar_marcacoes_pendentes"](avisar=False)
    itens_dados = ns10c["_dados"]["servicos"][0]["itens"]
    check("falha no salvamento devolve as marcações na memória",
          all(not it["reproduzido"] for it in itens_dados), itens_dados)
    check("falha no salvamento devolve as caixinhas da tela",
          all(not dados_card["check_var"].get()
              for dados_card in ns10c["_cards"].values()),
          ns10c["_cards"])
    check("fechar a janela não mostra aviso de falha",
          not ns10c["_avisos"], ns10c["_avisos"])

    # ── 11) Tick da contagem só pesa com player tocando ──
    ns11 = _ns_tick(tocando=False)
    ns11["_tick_contagem"]()
    check("em repouso não recalcula a contagem",
          not ns11["_atualizou"], ns11["_atualizou"])
    check("em repouso o próximo tick é mais espaçado",
          ns11["_atrasos"] == [1000], ns11["_atrasos"])

    ns11b = _ns_tick(tocando=True)
    ns11b["_tick_contagem"]()
    check("com player tocando a contagem é recalculada",
          ns11b["_atualizou"], ns11b["_atualizou"])
    check("com player tocando o tick continua em 500 ms",
          ns11b["_atrasos"] == [500], ns11b["_atrasos"])

    ns11c = _ns_tick(tocando=False, iid="1")
    ns11c["_tick_contagem"]()
    check("contagem ativa continua rápida mesmo sem player tocando",
          ns11c["_atualizou"] and ns11c["_atrasos"] == [500],
          (ns11c["_atualizou"], ns11c["_atrasos"]))

    print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas
                  else f"FALHAS: {falhas}"))
    return falhas


if __name__ == "__main__":
    sys.exit(1 if _rodar() else 0)
