#!/usr/bin/env python3
"""Espaço no campo de busca nunca dispara a reprodução (NavePro.py).

Bug relatado: com um termo digitado na busca, o operador apertava espaço
(no meio do nome) e o app tocava o PRIMEIRO hino da lista. Causa: o timer
de foco rouba o foco do campo após 5 s de pausa e o atalho global de espaço
caía no play_pause(). A reprodução agora só acontece no Enter ou no clique
no resultado — o espaço só toca com o campo vazio/placeholder.
"""

import ast
import os
import sys
import types

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)
sys.path.insert(0, _AQUI)

_SRC = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
_TREE = ast.parse(_SRC)

falhas = 0


def checar(desc, cond):
    global falhas
    print(f"{'OK ' if cond else 'X  '} {desc}")
    if not cond:
        falhas += 1


def _extrair(nome: str):
    for no in _TREE.body:
        if isinstance(no, ast.ClassDef) and no.name == "AppInterface":
            for m in no.body:
                if isinstance(m, ast.FunctionDef) and m.name == nome:
                    return ast.get_source_segment(_SRC, m)
    raise AssertionError(f"{nome} não encontrada em NavePro.py")


ns = {}
exec(compile(_extrair("_on_space"), "<_on_space>", "exec"), ns)  # noqa: S102
_on_space = ns["_on_space"]
ns2 = {}
exec(compile(_extrair("_clear_focus_timeout"), "<_clear_focus_timeout>", "exec"),
     ns2)  # noqa: S102
_clear_focus_timeout = ns2["_clear_focus_timeout"]

PLACEHOLDER = "Buscar hino..."


class EntryFake:
    def __init__(self, texto):
        self.texto = texto

    def get(self):
        return self.texto


class TelaoFake:
    def __init__(self, em_slides=False):
        self._em_slides = em_slides
        self.avancos = []

    def slide_proximo(self):
        self.avancos.append(1)


class AppFake:
    def __init__(self, conteudo, em_slides=False, foco_em_campo=None):
        self.entry_busca = EntryFake(conteudo)
        self.placeholder_busca = PLACEHOLDER
        self.player = types.SimpleNamespace(
            telao=TelaoFake(em_slides=em_slides),
            pausas=[],
            play_pause=lambda: self.player.pausas.append(1),
        )
        self._foco = foco_em_campo
        self.root = types.SimpleNamespace(focos=[], agendados=[],
                                          focus_get=self._focus_get,
                                          focus_set=lambda: self.root.focos.append(1),
                                          after=lambda ms, fn: self.root.agendados.append((ms, fn)) or "id")
        self._focus_timer = None

    def _focus_get(self):
        return self.entry_busca if self._foco else object()


# ── 1. Termo digitado: espaço NUNCA toca (mesmo sem foco no campo) ──
app = AppFake("Jesus Cristo", foco_em_campo=False)
r = _on_space.__get__(app)(None)
checar("com termo digitado, espaço não dispara play_pause",
       r == "break" and app.player.pausas == [])
app2 = AppFake("Jesus", foco_em_campo=True)
r = _on_space.__get__(app2)(None)
checar("com termo digitado e foco no campo, também não toca",
       r == "break" and app2.player.pausas == [])

# ── 2. Projeção em slides mantém o comportamento antigo (avança) ──
app3 = AppFake("termo", em_slides=True, foco_em_campo=False)
r = _on_space.__get__(app3)(None)
checar("com slides projetados, espaço avança o slide (como antes)",
       r == "break" and len(app3.player.telao.avancos) == 1
       and app3.player.pausas == [])

# ── 3. Campo vazio: espaço continua Play/Pause ─────────────────────
app4 = AppFake("", foco_em_campo=False)
r = _on_space.__get__(app4)(None)
checar("campo vazio sem foco: espaço toca (atalho preservado)",
       r == "break" and len(app4.player.pausas) == 1)
app5 = AppFake("", foco_em_campo=True)
r = _on_space.__get__(app5)(None)
checar("campo vazio COM foco: espaço também toca (comportamento antigo)",
       r == "break" and len(app5.player.pausas) == 1)

# ── 4. Timer de foco não rouba o foco durante a digitação ──────────
AppFake._clear_focus_timeout = _clear_focus_timeout  # para o reagendamento
app6 = AppFake("cantando", foco_em_campo=True)
_clear_focus_timeout.__get__(app6)()
checar("com termo digitado, o timer NÃO rouba o foco",
       app6.root.focos == [])
checar("com termo digitado, o timer é reagendado",
       len(app6.root.agendados) == 1
       and app6.root.agendados[0][0] == 5000)
app7 = AppFake("", foco_em_campo=True)
_clear_focus_timeout.__get__(app7)()
checar("campo vazio: o timer libera o foco (atalhos globais)",
       app7.root.focos == [1] and app7._focus_timer is None)

print()
if falhas:
    print(f"X {falhas} teste(s) falharam.")
    sys.exit(1)
print("OK todos os testes do espaço na busca passaram.")
