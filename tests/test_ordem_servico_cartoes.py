#!/usr/bin/env python3
"""Regressões de desempenho dos cartões da Ordem de Projeção.

Cobre as duas correções feitas para o "piscar" ao abrir programações com
muitos itens:

1. durante a montagem dos cartões o estilo "reproduzido" não dispara a
   passada de seleção em todos os cartões (era O(n²) de ``configure``);
2. o ``<Configure>`` do canvas é debounced e só reaplica ``wraplength``
   quando a largura realmente muda.

As funções internas são extraídas via AST e executadas com dublês, como nos
demais testes headless.
"""

import ast
import os
import sys
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
    ns = {
        "_cards": {"1": {"check_var": _Var(True),
                         "fontes": [(widget, ("Arial", 11, "bold"))]}},
        "_atualizar_selecao_visual": lambda: chamadas.append("selecao"),
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
        "_atualizar_selecao_visual": lambda: acoes.append("selecao"),
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
        "_duracao_timers": {"inicio": None, "poll": None},
        "_eh_url_youtube": lambda c: c.startswith("https://"),
        "os": os,
        "self": types.SimpleNamespace(root=root, player=object()),
        "threading": types.SimpleNamespace(Thread=_Thread),
        "_trabalho_duracao": lambda *a: None,
        "_agendar_poll_duracoes": lambda: chamadas.append("poll"),
    }
    ns = _carregar_ns("_agendar_inicio_duracoes", "_iniciar_duracoes",
                      "_pedir_duracao", **ns)
    ns["_root"] = root
    ns["_thread"] = _Thread
    ns["_chamadas"] = chamadas
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
          "selecao" in chamadas, chamadas)

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

    # ── 5) Atualização só do cartão afetado ──
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

    print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas
                  else f"FALHAS: {falhas}"))
    return falhas


if __name__ == "__main__":
    sys.exit(1 if _rodar() else 0)
