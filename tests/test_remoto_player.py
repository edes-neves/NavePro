#!/usr/bin/env python3
"""Testes do controle remoto de reprodução (_remoto_controle_player).

Trava a ação POST /api/remoto/player (aba Hino do controle remoto):
`play_pause` alterna pausa/continuar e `parar` encerra a mídia, reusando
exatamente os mesmos caminhos do painel do operador (sem duplicar lógica).
"""

import ast
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

src = open(os.path.join(RAIZ, 'NavePro.py'), encoding='utf-8').read()
tree = ast.parse(src)

node = next(n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef)
            and n.name == '_remoto_controle_player')

ns: dict = {}
exec(ast.get_source_segment(src, node), ns)  # noqa: S102
controle = ns['_remoto_controle_player']


class PlayerFake:
    def __init__(self, tocando=True, pausado=False):
        self.is_playing = tocando
        self.is_paused = pausado
        self.chamadas: list[str] = []

    def play_pause(self):
        self.chamadas.append('play_pause')
        if self.is_playing and not self.is_paused:
            self.is_paused = True
        elif self.is_paused:
            self.is_paused = False
            self.is_playing = True


class AppFake:
    def __init__(self, player):
        self.player = player
        self.parou = False

    def parar(self):
        self.parou = True
        self.player.is_playing = False
        self.player.is_paused = False


def checar(nome, cond):
    if not cond:
        raise AssertionError("FALHOU: " + nome)
    print("ok -", nome)


p = PlayerFake()
app = AppFake(p)

r = controle(app, {'acao': 'play_pause'})
checar("play_pause com mídia tocando pausa", r['ok'] and p.is_paused)
checar("resposta de play_pause traz 'tocando'", 'tocando' in r)

r = controle(app, {'acao': 'play_pause'})
checar("play_pause de novo continua", r['ok'] and not p.is_paused)

r = controle(app, {'acao': 'parar'})
checar("parar chama self.parar()", r['ok'] and app.parou)
checar("parar devolve tocando/pausado = False",
       r['tocando'] is False and r['pausado'] is False)

p2 = PlayerFake(tocando=False)
app2 = AppFake(p2)
r = controle(app2, {'acao': 'play_pause'})
checar("play_pause sem mídia devolve erro", r['ok'] is False and not p2.chamadas)
checar("erro sem mídia não chama parar", not app2.parou)

r = controle(AppFake(PlayerFake()), {'acao': 'nao_existe'})
checar("ação inválida devolve erro", r['ok'] is False)

print("Todos os testes passaram.")
