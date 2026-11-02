#!/usr/bin/env python3
"""Testes de robustez do servicos.json (navepro/core/servicos.py).

Trava a proteção contra PERDA DE DADOS: um servicos.json corrompido não
pode ser sobrescrito silenciosamente pelo próximo salvamento — o arquivo
original é preservado renomeado e, se o .tmp do último save existir, ele
é usado como recuperação. Também cobre o round-trip normal e a
normalização de itens antigos (apresentacao → sermao).
"""

import ast
import json
import os
import sys
import tempfile

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
if _AQUI not in sys.path:
    sys.path.insert(0, _AQUI)

from fixture_log import log  # noqa: E402

_MOD = os.path.join(RAIZ, "navepro", "core", "servicos.py")
_SRC = open(_MOD, encoding="utf-8").read()
_TREE = ast.parse(_SRC)


def _carregar_ns(arquivo: str) -> dict:
    """Executa as funções de JSON do servicos.py num ns com arquivo temporário."""
    ns: dict = {"os": os, "json": json, "log": log, "SERVICOS_FILE": arquivo}
    for nome in ("_normalizar_servicos", "_recuperar_servicos_json",
                 "_carregar_servicos_json", "_salvar_servicos_json"):
        for no in ast.walk(_TREE):
            if isinstance(no, ast.FunctionDef) and no.name == nome:
                exec(compile(ast.get_source_segment(_SRC, no), f"<{nome}>",
                             "exec"), ns)  # noqa: S102
                break
    return ns


def _rodar() -> int:
    falhas = 0

    def checar(desc, cond):
        nonlocal falhas
        print(f"{'OK ' if cond else 'X  '} {desc}")
        if not cond:
            falhas += 1

    vazio = {"servicos": [], "_proximo_id_servico": 1, "_proximo_id_item": 1}
    dados = {"servicos": [{"id": 1, "nome": "Culto", "itens": []}],
             "_proximo_id_servico": 2, "_proximo_id_item": 1}

    with tempfile.TemporaryDirectory() as raiz:
        arquivo = os.path.join(raiz, "servicos.json")
        ns = _carregar_ns(arquivo)

        # ── 1. Ausência do arquivo: vazio, sem criar nada no disco ──
        checar("arquivo ausente → estrutura vazia",
               ns["_carregar_servicos_json"]() == vazio)
        checar("arquivo ausente não cria nada no disco",
               os.listdir(raiz) == [])

        # ── 2. Round-trip normal (comportamento atual preservado) ───
        checar("salva normalmente", ns["_salvar_servicos_json"](dados))
        checar("round-trip preserva os dados",
               ns["_carregar_servicos_json"]() == dados)

        # ── 3. Corrompido sem .tmp → preservado renomeado ───────────
        with open(arquivo, "w", encoding="utf-8") as f:
            f.write("{isto nao e json")
        checar("corrompido → estrutura vazia (não explode)",
               ns["_carregar_servicos_json"]() == vazio)
        checar("corrompido foi preservado em .corrompido",
               os.path.exists(arquivo + ".corrompido")
               and not os.path.exists(arquivo))
        with open(arquivo + ".corrompido", encoding="utf-8") as f:
            conteudo = f.read()
        checar("conteúdo original continua no arquivo preservado",
               conteudo == "{isto nao e json")

        # ── 4. Corrompido com .tmp válido → recupera do .tmp ────────
        with open(arquivo, "w", encoding="utf-8") as f:
            f.write("{quebrado")
        with open(arquivo + ".tmp", "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False)
        checar("recupera do .tmp do último salvamento",
               ns["_carregar_servicos_json"]() == dados)

        # ── 5. Normalização de item antigo (apresentacao → sermao) ──
        dados2 = {"servicos": [{"id": 1, "nome": "Culto",
                                "itens": [{"id": 1, "tipo": "apresentacao"}]}],
                  "_proximo_id_servico": 2, "_proximo_id_item": 2}
        with open(arquivo, "w", encoding="utf-8") as f:
            json.dump(dados2, f, ensure_ascii=False)
        carregado = ns["_carregar_servicos_json"]()
        checar("normaliza tipo antigo 'apresentacao' → 'sermao'",
               carregado["servicos"][0]["itens"][0]["tipo"] == "sermao")

        # ── 6. JSON válido com formato inesperado também é preservado ─
        tmp_antigo = arquivo + ".tmp"
        if os.path.exists(tmp_antigo):
            os.remove(tmp_antigo)
        with open(arquivo, "w", encoding="utf-8") as f:
            f.write('{"outra": "estrutura"}')
        checar("formato inesperado → estrutura vazia",
               ns["_carregar_servicos_json"]() == vazio)
        checar("formato inesperado também é preservado em .corrompido",
               os.path.exists(arquivo + ".corrompido"))

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print("\n" + ("TODOS OS CASOS PASSARAM" if not f else f"FALHAS: {f}"))
    sys.exit(1 if f else 0)
