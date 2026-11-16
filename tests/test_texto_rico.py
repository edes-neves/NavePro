#!/usr/bin/env python3
"""Testes headless do texto rico dos anúncios (negrito/cor + auto-ajuste).

Cobre o parser/layout de navepro/core/fontes_pil.py e os helpers de
formatação da caixa de texto do editor (extraídos via AST, sem abrir Tk).
"""

import ast
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
if _AQUI not in sys.path:
    sys.path.insert(0, _AQUI)

from navepro.core.fontes_pil import (  # noqa: E402
    _layout_texto_rico,
    _limite_altura_texto,
    _parse_texto_rico,
    _texto_simples,
    _texto_tem_formatacao,
)

falhas = []


def check(nome, cond, extra=""):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


# ── parser das marcas ───────────────────────────────────────────────
check("rico: texto comum não tem formatação",
      _texto_tem_formatacao("texto comum") is False)
check("rico: texto comum permanece igual",
      _texto_simples("texto comum") == "texto comum")
check("rico: **negrito** vira trecho negrito",
      _parse_texto_rico("**forte** fraco") ==
      [("forte", True, None), (" fraco", False, None)],
      str(_parse_texto_rico("**forte** fraco")))
check("rico: remove as marcas de negrito",
      _texto_simples("**forte** fraco") == "forte fraco")
check("rico: {c:#RRGGBB} colore o trecho",
      _parse_texto_rico("{c:#ff0000}alerta{/c} ok") ==
      [("alerta", False, "#ff0000"), (" ok", False, None)],
      str(_parse_texto_rico("{c:#ff0000}alerta{/c} ok")))
check("rico: remove as marcas de cor",
      _texto_simples("{c:#ff0000}alerta{/c} ok") == "alerta ok")
check("rico: negrito dentro de cor",
      _parse_texto_rico("{c:#00ff00}**sim**{/c}") ==
      [("sim", True, "#00ff00")],
      str(_parse_texto_rico("{c:#00ff00}**sim**{/c}")))
check("rico: marca de negrito sem fechamento é texto comum",
      _texto_simples("sem fechar **aqui") == "sem fechar **aqui")
check("rico: cor inválida é texto comum",
      _texto_simples("{c:#zzzzzz}nada{/c}") == "{c:#zzzzzz}nada{/c}")
check("rico: cor sem fechamento é texto comum",
      _texto_simples("{c:#00ff00}nada") == "{c:#00ff00}nada")

# ── limite de altura (auto-ajuste) ──────────────────────────────────
check("ajuste: escala 1.0 limita à própria caixa",
      _limite_altura_texto(300, 1.0, 1080) == 300,
      str(_limite_altura_texto(300, 1.0, 1080)))
check("ajuste: A+ (escala > 1) pode crescer até 92% da tela",
      _limite_altura_texto(300, 1.5, 1080) == 993,
      str(_limite_altura_texto(300, 1.5, 1080)))

# ── layout com trechos e quebra de linha ────────────────────────────
layout = _layout_texto_rico(
    "**Titulo**\nTexto {c:#ff0000}vermelho{/c} comum", 500, 300)
check("layout: marca presença de formatação",
      layout["tem_formatacao"] is True)
check("layout: mantém a quebra de linha explícita",
      len(layout["linhas"]) >= 2, str(len(layout["linhas"])))
check("layout: trecho negrito preservado",
      any(n for linha in layout["linhas"] for _, n, _c, _w in linha))
check("layout: cor do trecho preservada",
      any(c == "#ff0000" for linha in layout["linhas"]
          for _t, _n, c, _w in linha))
check("layout: bloco cabe na área útil da caixa",
      layout["altura_bloco"] <= layout["altura_util"] + 1,
      f'{layout["altura_bloco"]} > {layout["altura_util"]}')
check("layout: largura do bloco cabe na área útil",
      layout["largura_max"] <= layout["largura_util"] + 1,
      f'{layout["largura_max"]} > {layout["largura_util"]}')

texto_longo = " ".join(["palavra"] * 120)
layout_longo = _layout_texto_rico(texto_longo, 420, 180)
check("ajuste: texto longo encolhe para caber na caixa",
      layout_longo["altura_bloco"] <= layout_longo["altura_util"] + 1,
      f'{layout_longo["altura_bloco"]} > {layout_longo["altura_util"]}')
check("ajuste: texto longo não passa da largura útil",
      layout_longo["largura_max"] <= layout_longo["largura_util"] + 1,
      f'{layout_longo["largura_max"]} > {layout_longo["largura_util"]}')

layout_simples = _layout_texto_rico("texto sem marca", 400, 200,
                                    negrito_base=True)
check("layout: texto comum mantém o peso base (negrito histórico)",
      layout_simples["tem_formatacao"] is False)
check("layout: texto comum sai todo no peso base",
      all(n is True for linha in layout_simples["linhas"]
          for _t, n, _c, _w in linha))

# ── helpers de formatação do editor (AST, sem abrir Tk) ─────────────
_SRC = open(os.path.join(RAIZ, "navepro", "ui", "janela_anuncios.py"),
            encoding="utf-8").read()
_NOS = {n.name: n for n in ast.walk(ast.parse(_SRC))
        if isinstance(n, ast.FunctionDef)}


class _TclError(Exception):
    pass


class _FakeText:
    def __init__(self, texto="", selecionado=True):
        self.texto = texto
        self.sel = ("1.0", "1.4") if selecionado else ()
        self.inseridos = []
        self.deletados = []
        self.separadores = 0
        self.autosep = 1
        self.selecao_final = None
        self.marcado = None

    def tag_ranges(self, tag):
        return self.sel

    def index(self, indice):
        return indice

    def get(self, inicio, fim=None):
        if fim is None:
            return ""
        return self.texto

    def cget(self, opcao):
        if opcao == "autoseparators":
            return self.autosep
        raise _TclError(opcao)

    def configure(self, **kwargs):
        if "autoseparators" in kwargs:
            self.autosep = 1 if kwargs["autoseparators"] else 0

    def edit_separator(self):
        self.separadores += 1

    def insert(self, indice, texto):
        self.inseridos.append((indice, texto))

    def delete(self, inicio, fim=None):
        self.deletados.append((inicio, fim))

    def tag_remove(self, tag, inicio, fim):
        self.selecao_final = None

    def tag_add(self, tag, inicio, fim):
        self.selecao_final = (tag, inicio, fim)

    def mark_set(self, marca, indice):
        self.marcado = (marca, indice)


_ns_fmt = {"_texto_simples": _texto_simples}
_corpo = "\n\n".join(
    ast.get_source_segment(_SRC, _NOS[n])
    for n in ("_selecao_do_texto", "_aplicar_marcacao_texto",
              "_limpar_formatacao_texto"))
exec(compile(_corpo, "<fmt>", "exec"), _ns_fmt)

aplicar = _ns_fmt["_aplicar_marcacao_texto"]
limpar = _ns_fmt["_limpar_formatacao_texto"]

widget = _FakeText("forte")
check("editor: negrito envolve a seleção",
      aplicar(widget, "**", "**") is True)
check("editor: insere a marca antes", widget.inseridos[0][1] == "**",
      str(widget.inseridos))
check("editor: insere a marca depois", widget.inseridos[1][1] == "**",
      str(widget.inseridos))
check("editor: agrupa a formatação num passo de undo",
      widget.separadores == 2, str(widget.separadores))
check("editor: restaura os autoseparators", widget.autosep == 1)
check("editor: mantém o trecho selecionado",
      widget.selecao_final is not None, str(widget.selecao_final))

widget = _FakeText("**forte**")
check("editor: negrito em seleção já marcada desmarca",
      aplicar(widget, "**", "**", alternar=True) is True)
check("editor: remove as duas marcas", widget.deletados != [],
      str(widget.deletados))
check("editor: reinsere só o conteúdo", widget.inseridos == [("1.0", "forte")],
      str(widget.inseridos))

widget = _FakeText("**forte**")
check("editor: limpar formatação remove as marcas",
      limpar(widget) is True)
check("editor: limpar reinsere o texto simples",
      widget.inseridos == [("1.0", "forte")], str(widget.inseridos))

widget = _FakeText("sem marca")
check("editor: limpar sem marcação não altera", limpar(widget) is False)
check("editor: sem seleção não formata",
      aplicar(_FakeText("texto", selecionado=False), "**", "**") is False)

# Os botões estão na prévia da imagem+texto (a caixa citada pelo operador).
check("editor: prévia tem botão de negrito", "_formatar_negrito" in _SRC)
check("editor: prévia tem botão de cor", "colorchooser.askcolor" in _SRC)
check("editor: prévia tem botão de limpar", "_formatar_limpar" in _SRC)
check("editor: prévia usa o layout de texto rico", "_layout_texto_rico" in _SRC)
check("editor: trechos ricos são desenhados em pixels (não em pontos)",
      '-max(8, int(round(layout["tamanho"] * ESCALA)))' in _SRC)
_TELAO_SRC = open(os.path.join(RAIZ, "navepro", "core", "telao.py"),
                  encoding="utf-8").read()
check("telão: trechos ricos são desenhados em pixels (não em pontos)",
      '-max(8, min(300, int(layout["tamanho"])))' in _TELAO_SRC)

# ── projeção simples usa o texto sem as marcas ──────────────────────
from navepro.core.anuncios import _montar_slides_anuncio_servico  # noqa: E402
from navepro.core.slides import _montar_slides_anuncio  # noqa: E402

anuncio = {"titulo": "Aviso", "texto": "**Importante**\n\n"
                                       "{c:#ff0000}Hoje{/c} tem culto"}
check("projeção simples: negrito não vira marca no slide",
      all("**" not in s and "{c:" not in s
          for s in _montar_slides_anuncio(anuncio)),
      str(_montar_slides_anuncio(anuncio)))
check("projeção simples: serviço também usa texto simples",
      all("**" not in s and "{c:" not in s
          for s in _montar_slides_anuncio_servico(anuncio)),
      str(_montar_slides_anuncio_servico(anuncio)))

print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas
              else f"FALHAS: {len(falhas)}"))
sys.exit(1 if falhas else 0)
