#!/usr/bin/env python3
"""Testes da edição inline e da exclusão de serviços na Ordem de Serviço.

Cobre o comportamento pedido: clicar na caixa "Programação" deixa o nome
editável; o texto é salvo sozinho ao sair da caixa; o botão "+ Nova Projeção"
vira "Del Projeção" (vermelho) durante a edição; e a exclusão só acontece
depois da confirmação do operador.

As funções internas de `janela_ordem_servico` são extraídas via AST (como nos
demais testes headless) e executadas com dublês, sem abrir janela.
"""

import ast
import datetime as dt
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


def _carregar_ns(*nomes, **ns):
    """Compila as funções aninhadas pedidas dentro de um namespace de dublês."""
    for nome in nomes:
        codigo = ast.get_source_segment(_SRC, _FUNCS[nome])
        exec(compile(ast.parse(codigo), f"<{nome}>", "exec"), ns)  # noqa: S102
    return ns


class _Var:
    def __init__(self, valor=""):
        self.valor = valor

    def get(self):
        return self.valor

    def set(self, valor):
        self.valor = valor


class _Messagebox:
    def __init__(self, resposta=True):
        self.resposta = resposta
        self.ask = []
        self.avisos = []

    def askyesno(self, *args, **kwargs):
        self.ask.append((args, kwargs))
        return self.resposta

    def showwarning(self, *args, **kwargs):
        self.avisos.append((args, kwargs))


def _ns_renomear(dados, renomear, var, selecionado, salvar_ok=True):
    chamadas = []
    msg = _Messagebox()

    def _salvar(_dados, _ok=salvar_ok):
        chamadas.append("salvar")
        return _ok

    ns = {
        "dados": dados,
        "_renomear": renomear,
        "servico_var": var,
        "servico_selecionado_id": selecionado,
        "_definir_botao_exclusao": lambda ativo: chamadas.append(
            ("botao", ativo)),
        "_restaurar_rotulo_servico": lambda: chamadas.append("rotulo"),
        "_salvar_servicos_json": _salvar,
        "_carregar_servicos": lambda: chamadas.append("carregar"),
        "_on_servico_select": lambda: chamadas.append("select"),
        "tkinter": types.SimpleNamespace(messagebox=msg),
        "janela": object(),
    }
    ns = _carregar_ns("_finalizar_renomear_servico", **ns)
    ns["_chamadas"] = chamadas
    ns["_msg"] = msg
    return ns


def _ns_dia(dados, dia):
    ns = {
        "dados": dados,
        "dia_selecionado": [dia],
        "_CHAVES_DIA": ("domingo", "segunda", "terca", "quarta",
                        "quinta", "sexta", "sabado"),
        "datetime": dt.datetime,
    }
    return _carregar_ns("_normalizar_dia", "_dia_do_servico",
                        "_ordenar_servicos", **ns)


def _ns_excluir(dados, servico, selecionado, salvar_ok=True, resposta=True):
    chamadas = []
    msg = _Messagebox(resposta=resposta)
    proximo = {servico["id"]: 2}
    escolhido = {"id": 7}
    combo = {"values": ()}

    def _carregar_servicos():
        ordenados = sorted(dados["servicos"],
                           key=lambda s: s.get("id") or 0, reverse=True)
        combo["values"] = tuple(s.get("nome", "") for s in ordenados)
        chamadas.append("carregar")

    def _on_servico_select():
        selecionado[0] = dados.get("_servico_selecionado")
        chamadas.append("select")

    ns = {
        "dados": dados,
        "_servico_atual": lambda: servico,
        "tkinter": types.SimpleNamespace(messagebox=msg),
        "janela": object(),
        "_salvar_servicos_json": lambda _dados: (chamadas.append("salvar")
                                                 or salvar_ok),
        "_ordenar_servicos": lambda: sorted(
            dados["servicos"], key=lambda s: s.get("id") or 0, reverse=True),
        "_SERVICO_PROXIMO_ITEM": proximo,
        "_SERVICO_ITEM_REPRODUZINDO": {},
        "esquecer_manter_videos_servico":
            lambda sid: chamadas.append(("esquecer", sid)),
        "_item_escolhido": escolhido,
        "servico_selecionado_id": selecionado,
        "_carregar_servicos": _carregar_servicos,
        "combo_servico": combo,
        "_on_servico_select": _on_servico_select,
        "_restaurar_rotulo_servico": lambda: chamadas.append("rotulo"),
        "_carregar_itens": lambda: chamadas.append("itens"),
    }
    ns = _carregar_ns("_excluir_servico", **ns)
    ns["_chamadas"] = chamadas
    ns["_msg"] = msg
    ns["_proximo"] = proximo
    ns["_escolhido"] = escolhido
    return ns


def _rodar():
    falhas = []

    def check(nome, cond, extra=""):
        print(f"{'OK ' if cond else 'FALHA'} {nome}"
              f"{(' -> ' + str(extra)) if extra else ''}")
        if not cond:
            falhas.append(nome)

    # ── 1) Estrutura/UI: clique edita, saída salva, botão vira vermelho ──
    ns = _carregar_ns("_iniciar_renomear_servico")
    src_iniciar = ast.get_source_segment(_SRC, _FUNCS[
        "_iniciar_renomear_servico"])
    check("clique na caixa inicia a edição inline",
          "combo_servico.bind(\"<Button-1>\", _iniciar_renomear_servico"
          in _SRC)
    check("sair da caixa (FocusOut) salva o nome",
          "combo_servico.bind(\"<FocusOut>\", _finalizar_renomear_servico"
          in _SRC)
    check("clique em qualquer ponto da janela também salva",
          "_confirmar_renomear_ao_clicar" in _SRC
          and 'janela.bind("<ButtonPress-1>", _confirmar_renomear_ao_clicar'
          in _SRC)
    check("edição deixa o combobox editável",
          "combo_servico.configure(state='normal')" in src_iniciar)
    check("restauração volta ao modo somente leitura",
          "combo_servico.configure(state='readonly')" in _SRC)
    check("botão fica vermelho com o texto Del Projeção durante a edição",
          'text="🗑️ Del Projeção"' in _SRC
          and "bg='#da3633'" in _SRC)
    check("botão volta a verde e a Nova Projeção ao sair da edição",
          'text="➕ Nova Projeção"' in _SRC
          and "bg='#238636'" in _SRC)
    check("exclusão pede confirmação (padrão \"não\")",
          "askyesno(" in _SRC
          and "default='no'" in _SRC)
    check("botão da barra usa o despacho novo/exclusão",
          "command=_acao_botao_novo" in _SRC)

    # ── 2) Renomear: salva o novo texto ──
    dados = {"servicos": [{"id": 1, "nome": "Culto", "itens": []}]}
    renomear = {"id": 1, "nome_original": "Culto"}
    var = _Var("Culto de Domingo")
    sel = [1]
    ns = _ns_renomear(dados, renomear, var, sel)
    ns["_finalizar_renomear_servico"]()
    check("nome editado é salvo automaticamente",
          dados["servicos"][0]["nome"] == "Culto de Domingo"
          and "salvar" in ns["_chamadas"])
    check("edição é encerrada após salvar",
          renomear["id"] is None
          and ("botao", False) in ns["_chamadas"])
    check("seletor recarrega com o novo rótulo",
          "carregar" in ns["_chamadas"] and "select" in ns["_chamadas"])

    # ── 3) Nome vazio não sobrescreve ──
    dados = {"servicos": [{"id": 1, "nome": "Culto", "itens": []}]}
    renomear = {"id": 1, "nome_original": "Culto"}
    ns = _ns_renomear(dados, renomear, _Var("   "), [1])
    ns["_finalizar_renomear_servico"]()
    check("nome vazio mantém o nome antigo",
          dados["servicos"][0]["nome"] == "Culto"
          and "salvar" not in ns["_chamadas"])

    # ── 4) Serviço trocado no meio da edição não renomeia o errado ──
    dados = {"servicos": [{"id": 1, "nome": "Culto", "itens": []},
                          {"id": 2, "nome": "Ensaio", "itens": []}]}
    renomear = {"id": 1, "nome_original": "Culto"}
    ns = _ns_renomear(dados, renomear, _Var("Ensaio"), [2])
    ns["_finalizar_renomear_servico"]()
    check("troca de serviço cancela a edição (não renomeia o anterior)",
          dados["servicos"][0]["nome"] == "Culto"
          and "salvar" not in ns["_chamadas"])

    # ── 5) Falha ao salvar restaura o nome antigo ──
    dados = {"servicos": [{"id": 1, "nome": "Culto", "itens": []}]}
    renomear = {"id": 1, "nome_original": "Culto"}
    ns = _ns_renomear(dados, renomear, _Var("Novo"), [1], salvar_ok=False)
    ns["_finalizar_renomear_servico"]()
    check("falha no save devolve o nome antigo e avisa",
          dados["servicos"][0]["nome"] == "Culto"
          and bool(ns["_msg"].avisos))

    # ── 6) Excluir sem confirmar não apaga nada ──
    dados = {"servicos": [{"id": 3, "nome": "Noite", "itens": [{"id": 1}]},
                          {"id": 1, "nome": "Manhã", "itens": []}],
             "_servico_selecionado": 3}
    selecionado = [3]
    serv = dados["servicos"][0]
    ns = _ns_excluir(dados, serv, selecionado, resposta=False)
    ns["_excluir_servico"]()
    check("confirmar 'não' mantém o serviço",
          len(dados["servicos"]) == 2 and "salvar" not in ns["_chamadas"])
    check("confirmação é pedida uma vez",
          len(ns["_msg"].ask) == 1)

    # ── 7) Excluir confirmado remove o serviço e seleciona o próximo ──
    dados = {"servicos": [{"id": 3, "nome": "Noite", "itens": [{"id": 1}]},
                          {"id": 1, "nome": "Manhã", "itens": []}],
             "_servico_selecionado": 3}
    selecionado = [3]
    serv = dados["servicos"][0]
    ns = _ns_excluir(dados, serv, selecionado, resposta=True)
    ns["_excluir_servico"]()
    _args, _kwargs = ns["_msg"].ask[0]
    check("diálogo mostra o nome do serviço",
          "Noite" in _args[1] and "item dele" in _args[1], _args[1])
    check("serviço excluído sai do servicos.json",
          [s["id"] for s in dados["servicos"]] == [1])
    check("outro serviço é selecionado após excluir",
          dados["_servico_selecionado"] == 1 and selecionado[0] == 1)
    check("ponteiro de execução do serviço removido é limpo",
          ns["_proximo"] == {} and ns["_escolhido"]["id"] is None)
    check("exclusão é persistida",
          "salvar" in ns["_chamadas"])

    # ── 8) Excluir o último serviço deixa a janela vazia ──
    dados = {"servicos": [{"id": 5, "nome": "Único", "itens": []}],
             "_servico_selecionado": 5}
    selecionado = [5]
    serv = dados["servicos"][0]
    ns = _ns_excluir(dados, serv, selecionado, resposta=True)
    ns["_excluir_servico"]()
    check("último serviço excluído limpa a seleção",
          not dados["servicos"] and "_servico_selecionado" not in dados
          and "itens" in ns["_chamadas"])

    # ── 9) Falha ao gravar a exclusão não perde o serviço ──
    dados = {"servicos": [{"id": 3, "nome": "Noite", "itens": []}],
             "_servico_selecionado": 3}
    selecionado = [3]
    serv = dados["servicos"][0]
    ns = _ns_excluir(dados, serv, selecionado, salvar_ok=False,
                     resposta=True)
    ns["_excluir_servico"]()
    check("falha no save restaura a lista e avisa",
          len(dados["servicos"]) == 1
          and dados["_servico_selecionado"] == 3
          and bool(ns["_msg"].avisos))

    # ── 10) Dias da semana e filtragem das programações ─────────────
    check("dias da semana vão de Domingo a Sábado",
          '"domingo", "segunda", "terca", "quarta"' in _SRC
          and '"Quinta", "Sexta", "Sábado")' in _SRC)
    check("campo Programação e botão Nova Projeção estão presentes",
          'text="Programação:"' in _SRC
          and 'text="➕ Nova Projeção"' in _SRC)
    check("antigo rótulo Projeção foi removido",
          'text="Projeção:"' not in _SRC)
    ns_rotulo = _carregar_ns("_rotulo_servico")
    check("programação aparece só com o nome, sem número automático",
          ns_rotulo["_rotulo_servico"](
              {"id": 7, "nome": "Culto da Manhã"}) == "Culto da Manhã")

    # ── 11) Itens reproduzidos: caixinha, tachado e opção no topo ────
    check("cada item tem a caixa de reproduzido na primeira coluna",
          "command=lambda i=iid: _alternar_reproduzido(i)" in _SRC)
    check("caixa marcada usa indicador de alto contraste",
          "selectcolor='#238636'" in _SRC)
    check("item marcado fica tachado (overstrike)",
          "_fonte_com_risco" in _SRC and '"overstrike"' in _SRC)
    check("topo tem a opção Marcar reproduzidos",
          'text="Marcar reproduzidos"' in _SRC)
    check("execução marca o item só quando ele termina",
          "marcar_reproduzido=marcar" in _SRC
          and "ao_terminar=_ao_terminar_item" in _SRC
          and "anterior_reproduzido_id" in _SRC)
    check("programação pode manter os vídeos do YouTube",
          'text="Manter vídeos do YouTube desta programação"' in _SRC
          and "definir_manter_videos_servico(" in _SRC)

    dados_dia = {"servicos": [
        {"id": 1, "nome": "Culto", "dia": "domingo", "itens": []},
        {"id": 2, "nome": "Terça", "criado_em": "2026-11-17T19:00:00",
         "itens": []},
        {"id": 3, "nome": "Antigo", "itens": []},
        {"id": 4, "nome": "Terça 2", "dia": "Terça", "itens": []},
    ]}
    ns_dia = _ns_dia(dados_dia, "terca")
    check("dia explícito vale",
          ns_dia["_dia_do_servico"](dados_dia["servicos"][0]) == "domingo")
    check("dia legado é inferido pela data de criação",
          ns_dia["_dia_do_servico"](dados_dia["servicos"][1]) == "terca")
    check("programação antiga sem data fica no Domingo",
          ns_dia["_dia_do_servico"](dados_dia["servicos"][2]) == "domingo")
    check("dia com acento/maiúscula é normalizado",
          ns_dia["_dia_do_servico"](dados_dia["servicos"][3]) == "terca")
    check("só as programações do dia selecionado aparecem",
          [s["id"] for s in ns_dia["_ordenar_servicos"]()] == [4, 2])

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
