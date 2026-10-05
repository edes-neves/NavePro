#!/usr/bin/env python3
"""Testes da escolha de monitor do telão e do DPI-awareness.

Regressão do Windows: sem DPI-awareness, o Tk media a tela em pixels lógicos
e o screeninfo em pixels físicos, e o Windows devolvia o telão para o monitor
primário. Estes testes travam a REGRIA de escolha (telão nunca divide o
monitor com o painel), inclusive quando a detecção do primário falha.
"""

import ast
import os
import sys
from typing import List, Optional

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)


def _carregar_monitorinfo() -> type:
    """Extrai a classe MonitorInfo do NavePro.py sem importar o app inteiro."""
    src = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
    no = ast.parse(src)
    for node in ast.walk(no):
        if isinstance(node, ast.ClassDef) and node.name == "MonitorInfo":
            mod = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(mod)
            ns: dict = {}
            exec(compile(mod, "<MonitorInfo>", "exec"), ns)
            return ns["MonitorInfo"]
    raise AssertionError("MonitorInfo não encontrada em NavePro.py")


def _carregar_escolher() -> callable:
    """Extrai _escolher_monitor_telao do NavePro.py sem importar o app."""
    return _extrair("_escolher_monitor_telao")


def _carregar_painel() -> callable:
    """Extrai _escolher_monitor_painel do NavePro.py sem importar o app."""
    return _extrair("_escolher_monitor_painel")


def _extrair(nome_funcao: str) -> callable:
    """Extrai uma função de nível superior do NavePro.py via AST."""
    src = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
    no = ast.parse(src)
    # _escolher_monitor_telao chama _escolher_monitor_painel: precisa dos dois.
    corpos = []
    for node in no.body:
        if isinstance(node, ast.FunctionDef) and node.name in (
            "_escolher_monitor_telao", "_escolher_monitor_painel"
        ):
            corpos.append(node)
    mod = ast.Module(body=corpos, type_ignores=[])
    ast.fix_missing_locations(mod)
    ns: dict = {
        "MonitorInfo": _carregar_monitorinfo(),
        "List": List,
        "Optional": Optional,
    }
    exec(compile(mod, "<escolher>", "exec"), ns)
    assert nome_funcao in ns, f"{nome_funcao} não encontrada em NavePro.py"
    return ns[nome_funcao]


def _mk(cls, x, y, w, h, primary=False, name="M"):
    return cls(x, y, w, h, name, primary=primary)


def _rodar() -> int:
    falhas = 0
    MonitorInfo = _carregar_monitorinfo()
    escolher = _carregar_escolher()
    painel_escolher = _carregar_painel()

    def checar(desc, cond):
        nonlocal falhas
        if cond:
            print(f"✅ {desc}")
        else:
            print(f"❌ {desc}")
            falhas += 1

    # ── Caso 1: primário detectado (o caminho normal do Linux via xrandr) ──
    A = _mk(MonitorInfo, 0, 0, 1920, 1080, primary=True, name="primario")
    B = _mk(MonitorInfo, 1920, 0, 1280, 720, primary=False, name="telao")
    m = escolher([A, B])
    checar("primário detectado: telão vai para o não primário", m is B)

    # ── Caso 2: primário é o segundo da lista ──
    m = escolher([B, A])
    checar("primário em outra posição: telão vai para o não primário", m is B)

    # ── Caso 3: dois primários marcados ──
    # Não há monitor "não primário" disponível, então o telão usa o segundo
    # primário. O que não pode é colidir com o painel, que fica no primeiro.
    C = _mk(MonitorInfo, 1920, 0, 1920, 1080, primary=True, name="p2")
    painel_2p = painel_escolher([A, C])
    m = escolher([A, C])
    checar("dois primários: painel fica no primeiro", painel_2p is A)
    checar("dois primários: telão não colide com o painel", m is not painel_2p)

    # ── Caso 4: NENHUM primário — a regressão do Windows ──
    # Antes, o telão pegava monitors[0], o mesmo do painel.
    X = _mk(MonitorInfo, 0, 0, 1920, 1080)
    Y = _mk(MonitorInfo, 1920, 0, 1280, 720)
    m = escolher([X, Y])
    checar("sem primário: telão NÃO fica no monitor do painel", m is not X)
    checar("sem primário: telão fica no segundo monitor", m is Y)

    # ── Caso 5: sem primário com três monitores ──
    Z = _mk(MonitorInfo, 3200, 0, 1920, 1080)
    m = escolher([X, Y, Z])
    checar("sem primário, 3 monitores: telão sai do primeiro", m is not X)

    # ── Caso 6: um único monitor ──
    m = escolher([A])
    checar("monitor único: telão usa o único monitor", m is A)

    # ── Caso 7: nenhum monitor (detecção totalmente falha) ──
    checar("lista vazia: retorna None", escolher([]) is None)

    # ── Caso 8: mais de dois, sem primário, devem ficar separados ──
    M3 = [X, Y, Z]
    painel = M3[0]
    telao = escolher(M3)
    checar("painel e telão em monitores distintos", painel is not telao)

    # ── DPI-awareness: no-op correto fora do Windows ──
    from navepro.core.ambiente import _tornar_dpi_aware, _eh_windows
    if _eh_windows():
        print(f"ℹ️  Windows: _tornar_dpi_aware() -> {_tornar_dpi_aware()}")
    else:
        checar("fora do Windows, _tornar_dpi_aware() é no-op inofensivo",
               _tornar_dpi_aware() is False)

    # ── Invariante geral: painel e telão NUNCA no mesmo monitor ──
    # Varre combinações de primário para travar a regra estrutural,
    # incluindo os casos degenerados que quebram no Windows.
    MonitorInfo2 = MonitorInfo
    prim_flags = [False, True]
    colisoes = 0
    total = 0
    for n in (2, 3):
        import itertools
        for combo in itertools.product(prim_flags, repeat=n):
            lista = [_mk(MonitorInfo2, 1920 * i, 0, 1920, 1080,
                         primary=bool(p), name=f"m{i}")
                     for i, p in enumerate(combo)]
            p_mon = painel_escolher(lista)
            t_mon = escolher(lista)
            total += 1
            if p_mon is None or t_mon is None or p_mon is t_mon:
                colisoes += 1
    checar(f"painel e telão nunca colidem ({total} combinações de monitores)",
           colisoes == 0)

    return falhas


if __name__ == "__main__":
    f = _rodar()
    print()
    if f:
        print(f"❌ {f} teste(s) falharam.")
        sys.exit(1)
    print("✅ todos os testes de monitor passaram.")