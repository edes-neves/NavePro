#!/usr/bin/env python3
"""Atalhos globais e janelinha de dicas.

Cobre os seis atalhos pedidos (Ctrl+B/L/A/S/G/F), a preferência de exibir as
dicas no arranque e a presença do item "Ver Atalhos do Sistema" no menu.
"""

import json
import os
import shutil
import sys
import tempfile

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

import navepro.ui.atalhos as at  # noqa: E402

falhas = []


def check(nome, cond, extra=""):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


# ── 1. Conteúdo da janelinha e mapa de ações ────────────────────────
_ESPERADOS = {
    "b": ("Ctrl+B", "Bíblia", "janela_biblia"),
    "l": ("Ctrl+L", "Ordem de Projeção", "janela_ordem_servico"),
    "a": ("Ctrl+A", "Anúncios", "janela_anuncios"),
    "s": ("Ctrl+S", "Sorteio Profissional", "abrir_sorteio"),
    "g": ("Ctrl+G", "Gerenciar Banco", "abrir_gerenciador"),
    "f": ("Ctrl+F", "Configurações", "abrir_config_relogio_dialogo"),
}
_itens = [item for _titulo, itens in at.SECOES_ATALHOS for item in itens]
for tecla, (combinacao, descricao, metodo) in _ESPERADOS.items():
    check(f"{combinacao} abre {descricao}",
          (combinacao, descricao) in _itens and at._ACOES.get(tecla) == metodo,
          str(at._ACOES.get(tecla)))
check("dicas também listam o atalho do tema",
      ("Ctrl+T", "Alternar tema claro/escuro") in _itens)

# ── 2. Preferência de exibição no arranque ──────────────────────────
check("config sem a chave mostra as dicas", at.deve_mostrar_dicas({}) is True)
check("config inválido mostra as dicas", at.deve_mostrar_dicas(None) is True)
check("chave False não mostra as dicas",
      at.deve_mostrar_dicas({at.CHAVE_DICAS: False}) is False)
check("chave True mostra as dicas",
      at.deve_mostrar_dicas({at.CHAVE_DICAS: True}) is True)


class _RootFalso:
    def __init__(self):
        self.binds = {}

    def bind(self, sequencia, funcao):
        self.binds[sequencia] = funcao


class _Host(at.AtalhosMixin):
    def __init__(self, config):
        self.root = _RootFalso()
        self.config_data = config
        self.chamadas = []
        self._shutting_down = False
        self._janela_atalhos = None

    def janela_biblia(self):
        self.chamadas.append("Bíblia")

    def janela_ordem_servico(self):
        self.chamadas.append("Ordem de Projeção")

    def janela_anuncios(self):
        self.chamadas.append("Anúncios")

    def abrir_sorteio(self):
        self.chamadas.append("Sorteio Profissional")

    def abrir_gerenciador(self):
        self.chamadas.append("Gerenciar Banco")

    def abrir_config_relogio_dialogo(self):
        self.chamadas.append("Configurações")

    def abrir_dicas_atalhos(self):
        self.chamadas.append("dicas")


# ── 3. Bind dos atalhos (minúsculo e maiúsculo) ─────────────────────
_h = _Host({})
_h._registrar_atalhos()
for tecla, (_combinacao, descricao, _metodo) in _ESPERADOS.items():
    for sequencia in (f"<Control-{tecla}>", f"<Control-{tecla.upper()}>"):
        check(f"bind {sequencia}", sequencia in _h.root.binds)
    resultado = _h.root.binds[f"<Control-{tecla}>"](None)
    check(f"{sequencia} abre {descricao}", _h.chamadas[-1] == descricao,
          str(_h.chamadas[-1:]))
    check(f"{sequencia} consome o evento", resultado == "break")

# ── 4. Exibição inicial respeita config e shutdown ──────────────────
_h = _Host({})
_h._mostrar_dicas_atalhos_iniciais()
check("arranque abre as dicas por padrão", _h.chamadas == ["dicas"],
      str(_h.chamadas))

_h = _Host({at.CHAVE_DICAS: False})
_h._mostrar_dicas_atalhos_iniciais()
check("arranque não abre se o usuário desativou", _h.chamadas == [],
      str(_h.chamadas))

_h = _Host({})
_h._shutting_down = True
_h._mostrar_dicas_atalhos_iniciais()
check("arranque não abre durante o encerramento", _h.chamadas == [],
      str(_h.chamadas))

# ── 5. Persistência da caixinha ─────────────────────────────────────
_orig_config = at.CONFIG_FILE
_pasta = tempfile.mkdtemp(prefix="navepro_atalhos_")
try:
    at.CONFIG_FILE = os.path.join(_pasta, "config.json")
    _h = _Host({"cidade": "Umuarama"})
    _h._salvar_preferencia_dicas(False)
    with open(at.CONFIG_FILE, encoding="utf-8") as arquivo:
        _salvo = json.load(arquivo)
    check("marcar 'não exibir' persiste no config",
          _salvo.get(at.CHAVE_DICAS) is False)
    check("demais chaves do config são preservadas",
          _salvo.get("cidade") == "Umuarama")

    _h._salvar_preferencia_dicas(True)
    with open(at.CONFIG_FILE, encoding="utf-8") as arquivo:
        _salvo = json.load(arquivo)
    check("desmarcar volta a exibir no próximo arranque",
          _salvo.get(at.CHAVE_DICAS) is True)
finally:
    at.CONFIG_FILE = _orig_config
    shutil.rmtree(_pasta, ignore_errors=True)

# ── 6. Integração: menu, atalhos e mixin na AppInterface ────────────
_src_navepro = open(os.path.join(RAIZ, "NavePro.py"),
                    encoding="utf-8").read()
_src_painel = open(os.path.join(RAIZ, "navepro", "ui", "painel.py"),
                   encoding="utf-8").read()
check("menu Visualizar tem Ver Atalhos do Sistema",
      'label="Ver Atalhos do Sistema"' in _src_painel)
check("AppInterface herda AtalhosMixin",
      "AtalhosMixin" in _src_navepro)
check("app registra os atalhos ao iniciar",
      "self._registrar_atalhos()" in _src_navepro)
check("app agenda as dicas ao iniciar",
      "self._mostrar_dicas_atalhos_iniciais" in _src_navepro)

print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas else f"FALHAS: {falhas}"))
sys.exit(1 if falhas else 0)
