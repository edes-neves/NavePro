#!/usr/bin/env python3
"""Testes do botão "Executar" de cada item da aba Serviço (controle remoto).

O botão geral não envia id de item; o botão do item envia. Este teste trava o
ponto que já causou execução do item errado: o id do item pode chegar como
texto (dados antigos/importados/editados) e o servidor não pode convertê-lo
para int nem cair silenciosamente no ponteiro do serviço quando não achar o
item clicado.
"""

import ast
import os
import sys
import types

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

_SRC_EXEC = open(os.path.join(RAIZ, "navepro", "ui", "execucao_servico.py"),
                 encoding="utf-8").read()
_TREE_EXEC = ast.parse(_SRC_EXEC)

_SRC_REMOTO = open(os.path.join(RAIZ, "navepro", "ui", "remoto.py"),
                   encoding="utf-8").read()
_TREE_REMOTO = ast.parse(_SRC_REMOTO)

falhas = 0


def checar(desc, cond, extra=""):
    global falhas
    print(f"{'OK ' if cond else 'X  '} {desc}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas += 1


def _extrair(arvore, fonte, classe, nome):
    for no in arvore.body:
        if isinstance(no, ast.ClassDef) and no.name == classe:
            for m in no.body:
                if isinstance(m, ast.FunctionDef) and m.name == nome:
                    return ast.get_source_segment(fonte, m)
    raise AssertionError(f"{classe}.{nome} não encontrada")


class _Telao:
    def __init__(self):
        self.chamadas = []

    def projetar_slides(self, slides, indice_inicial=0):
        self.chamadas.append(("slides", slides))

    def projetar_texto(self, texto):
        self.chamadas.append(("texto", texto))

    def preparar_video(self):
        pass

    def restaurar_tela(self):
        pass


class _Player:
    def __init__(self):
        self.telao = _Telao()
        self.playlist = []
        self.index = 0
        self.on_state_change = None

    def _garantir_telao(self):
        return self.telao

    def _matar_processo(self):
        pass

    def carregar_playlist(self, playlist):
        self.playlist = list(playlist)

    def tocar_indice(self, indice):
        self.index = indice
        return True

    def _get_monitor_geometry(self):
        return (0, 0, 1920, 1080)


class _App:
    def __init__(self):
        self.player = _Player()
        self.root = None
        self._snapshot_servico = {"guardada": False}
        self._apresentacao_alvo = None
        self._monitor_geo = None
        self.arquivos_encontrados = []
        self.arquivo_atual = None

    def quando_midia_terminar(self, *_args):
        pass


_EXEC_NS = {
    "os": os,
    "subprocess": __import__("subprocess"),
    "tk": types.SimpleNamespace(TclError=Exception),
    "Callable": __import__("collections.abc").abc.Callable,
    "log": types.SimpleNamespace(exception=lambda *a, **k: None),
    "_SERVICO_PROXIMO_ITEM": {},
    "_slides_versiculo_item": lambda item: [item.get("letra_snapshot") or ""],
    "_montar_slides_letra": lambda titulo, letra: [(titulo, letra)],
    "_buscar_anuncio_por_ref": lambda ref: None,
    "_projetar_anuncio_ordserv": lambda telao, anun: True,
    "_eh_url": lambda caminho: str(caminho).startswith(("http://", "https://")),
    "db_query": lambda *a, **k: [],
    "_eh_windows": lambda: False,
    "_eh_flatpak": lambda: False,
    "_ambiente_sem_appimage": lambda: {},
    "_comando_apresentacao": lambda *a, **k: [],
    "_monitorar_apresentacao": lambda *a, **k: False,
    "_ambiente_apresentacao": lambda env: env,
    "_criar_alvo_apresentacao": lambda *a, **k: {},
    "_agendar_captura_janela_apresentacao": lambda *a, **k: None,
}
exec(compile(_extrair(_TREE_EXEC, _SRC_EXEC, "ExecucaoServicoMixin",
                      "executar_proximo_item_servico"),
             "<executar_proximo_item_servico>", "exec"), _EXEC_NS)  # noqa: S102
_executar = _EXEC_NS["executar_proximo_item_servico"]
_PONTEIRO = _EXEC_NS["_SERVICO_PROXIMO_ITEM"]


def _servico(ids):
    return {"id": "servico-teste", "nome": "Teste", "itens": [
        {"id": i, "tipo": "hino", "titulo_custom": f"Item {i}",
         "letra_snapshot": f"letra {i}"}
        for i in ids
    ]}


# ── 1. IDs inteiros: o botão do item executa o item clicado ─────────
_PONTEIRO.clear()
app = _App()
serv = _servico([1, 5, 2, 4])
for alvo in (5, 2, 4, 1):
    r = _executar(app, serv, escolhido=alvo)
    checar(f"id int {alvo}: executa o item clicado",
           r.get("ok") and r.get("id") == alvo)

# ── 2. IDs texto: não podem cair no primeiro item/ponteiro ──────────
_PONTEIRO.clear()
app = _App()
serv = _servico(["a", "b", "c"])
r = _executar(app, serv, escolhido="b")
checar("id texto: executa 'b', não o primeiro item",
       r.get("ok") and r.get("id") == "b" and r.get("indice") == 1,
       repr(r))

# ── 2b. IDs texto numérico + escolha int (ex.: API antiga) ───────────
_PONTEIRO.clear()
app = _App()
serv = _servico(["1", "2", "3"])
r = _executar(app, serv, escolhido=2)
checar("id '2' no JSON e escolha int 2 executam o item certo",
       r.get("ok") and r.get("id") == "2", repr(r))

# ── 3. Item inexistente: falha explícita, sem executar outro item ────
_PONTEIRO.clear()
app = _App()
serv = _servico([1, 2, 3])
r = _executar(app, serv, escolhido=99)
checar("item inexistente devolve erro",
       not r.get("ok") and r.get("codigo") == "item_inexistente", repr(r))
checar("item inexistente não projeta nada",
       app.player.telao.chamadas == [] and _PONTEIRO == {},
       repr(app.player.telao.chamadas))

# ── 4. Botão do item avança o ponteiro do botão geral ────────────────
_PONTEIRO.clear()
app = _App()
serv = _servico([1, 2, 3])
_executar(app, serv, escolhido=2)
r = _executar(app, serv)  # botão geral: próximo depois do 2
checar("botão geral continua no item seguinte ao clicado",
       r.get("ok") and r.get("id") == 3, repr(r))
_executar(app, serv, escolhido=1)
r = _executar(app, serv)
checar("voltar a um item anterior reposiciona o geral",
       r.get("ok") and r.get("id") == 2, repr(r))

# ── 5. API remota não converte o id do item para int ─────────────────
_REMOTO_NS = {"_carregar_servicos_json": lambda: {"servicos": [{
    "id": 1, "nome": "Teste", "itens": [{"id": "a"}, {"id": "b"}]}]}}
exec(compile(_extrair(_TREE_REMOTO, _SRC_REMOTO, "ControleRemotoMixin",
                      "_remoto_executar_servico"),
             "<_remoto_executar_servico>", "exec"), _REMOTO_NS)  # noqa: S102
_handler = _REMOTO_NS["_remoto_executar_servico"]


class _SelfRemoto:
    def __init__(self):
        self.capturado = []
        self.player = types.SimpleNamespace(_garantir_telao=lambda: None)

    def executar_proximo_item_servico(self, servico, *, escolhido=None):
        self.capturado.append(escolhido)
        return {"ok": True, "id": escolhido}


self_remoto = _SelfRemoto()
r = _handler(self_remoto, {"id": 1, "item": "b"})
checar("API aceita id texto sem int()",
       r.get("ok") and self_remoto.capturado[-1] == "b", repr(r))
r = _handler(self_remoto, {"id": 1, "item": "2"})
checar("API preserva id texto numérico (não vira int)",
       r.get("ok") and self_remoto.capturado[-1] == "2", repr(r))
checar("API com botão geral passa escolhido=None",
       _handler(self_remoto, {"id": 1}).get("ok")
       and self_remoto.capturado[-1] is None)
checar("API com id 0 não perde o item",
       _handler(self_remoto, {"id": 1, "item": 0}).get("ok")
       and self_remoto.capturado[-1] == 0)

print()
if falhas:
    print(f"X {falhas} teste(s) falharam.")
    sys.exit(1)
print("OK todos os testes do botão de item do serviço passaram.")
