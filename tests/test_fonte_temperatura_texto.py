"""Regressão: mensagem de temperatura indisponível usa fonte de texto.

Sem internet (ou com o serviço de temperatura fora do ar) o telão troca o
número pela mensagem de erro. A Digital-7 é de sete segmentos e fica
ilegível em frases; os números devem continuar nela, mas o texto precisa de
uma fonte de leitura (Adventist Sans ou outra disponível no sistema).
"""
import ast
import os
import re
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
ARQ = os.path.join(RAIZ, 'navepro', 'core', 'telao.py')
src = open(ARQ, encoding='utf-8').read()
tree = ast.parse(src)

_CONSTANTES = ('_FONTES_TEXTO_RELOGIO', '_TEMPERATURA_NUMERICA')
_partes = []
for no in tree.body:
    if isinstance(no, ast.Assign):
        for alvo in no.targets:
            if isinstance(alvo, ast.Name) and alvo.id in _CONSTANTES:
                _partes.append(ast.get_source_segment(src, no))

nos = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
_METODOS = ('_familia_texto_relogio', '_tamanho_texto_para_slot',
            '_fonte_temp_para_texto')
_corpo = "\n".join(ast.get_source_segment(src, nos[n]) for n in _METODOS)


class Fonte:
    def __init__(self, family=None, size=0):
        self.family = family
        self.size = int(size or 0)

    def measure(self, texto):
        fator = 0.45 if self.family == 'Digital-7' else 1.0
        return int(len(texto) * self.size * fator)

    def metrics(self, nome):
        fator = 1.0 if self.family == 'Digital-7' else 1.35
        return max(1, int(self.size * fator))


class FakeTkFont:
    Font = Fonte

    def __init__(self, disponiveis):
        self.disponiveis = set(disponiveis)

    def families(self, root):
        return set(self.disponiveis)


ns = {'re': re, 'tkfont': FakeTkFont(())}
exec(compile("\n".join(_partes), '<constantes>', 'exec'), ns)
exec(compile("class Telao:\n"
             + "\n".join("    " + linha for linha in _corpo.split("\n"))
             + "\n", '<telao>', 'exec'), ns)
Telao = ns['Telao']


class Stub(Telao):
    def __init__(self, largura_max=1000):
        self.root = object()
        self._font_temp = ('Digital-7', 100, 'normal')
        self._largura_temp_max = largura_max
        self._font_temp_exib = None
        self._font_temp_exib_texto = None


def criar(disponiveis, largura_max=1000):
    ns['tkfont'] = FakeTkFont(disponiveis)
    return Stub(largura_max)


falhas = []


def check(nome, cond, extra=''):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


# 1) Números continuam na Digital-7, com o tamanho do slot numérico.
t = criar({'Adventist Sans', 'DejaVu Sans'})
for texto in ('25°C', '-3°C', '25,5°C', '25°', ' 18 C '):
    f = t._fonte_temp_para_texto(texto)
    check(f'número {texto!r} em Digital-7', f[0] == 'Digital-7', str(f))
    check(f'número {texto!r} mantém o tamanho', f[1] == 100, str(f))

# 2) Mensagens de indisponibilidade usam a Adventist Sans (preferida).
t = criar({'Adventist Sans', 'DejaVu Sans'})
for texto in ('NAO ENCONTRADA', 'ERRO AO OBTER TEMPERATURA',
              'NAO PERTENCE AO ESTADO DE: SAO PAULO.'):
    f = t._fonte_temp_para_texto(texto)
    check(f'mensagem {texto!r} em Adventist Sans', f[0] == 'Adventist Sans',
          str(f))

# 3) Sem Adventist Sans, cai numa fonte de texto disponível.
t = criar({'DejaVu Sans', 'Liberation Sans'})
f = t._fonte_temp_para_texto('SEM INTERNET')
check('fallback usa DejaVu Sans', f[0] == 'DejaVu Sans', str(f))

t = criar({'Liberation Sans'})
f = t._fonte_temp_para_texto('SEM INTERNET')
check('fallback usa Liberation Sans', f[0] == 'Liberation Sans', str(f))

t = criar(set())
f = t._fonte_temp_para_texto('SEM INTERNET')
check('sem fontes listadas assume Adventist Sans', f[0] == 'Adventist Sans',
      str(f))

# 4) Texto com números misturados não é temperatura: usa fonte de texto.
t = criar({'Adventist Sans'})
f = t._fonte_temp_para_texto('25°C SEM INTERNET')
check('frase com número não vira Digital-7', f[0] == 'Adventist Sans',
      str(f))

# 5) Texto longo encolhe para caber na largura disponível.
t = criar({'Adventist Sans'}, largura_max=500)
texto = 'NAO PERTENCE AO ESTADO DE: SAO PAULO.'
f = t._fonte_temp_para_texto(texto)
tamanho_slot = t._tamanho_texto_para_slot('Adventist Sans', 100)
check('texto longo encolhe', f[1] < tamanho_slot, f'{f[1]} vs {tamanho_slot}')
check('texto não passa da largura',
      Fonte('Adventist Sans', f[1]).measure(texto) <= 500, str(f))

# 6) O resultado é cacheado por texto (mesma tupla, sem recomputar).
t = criar({'Adventist Sans'})
f1 = t._fonte_temp_para_texto('SEM INTERNET')
f2 = t._fonte_temp_para_texto('SEM INTERNET')
check('cache devolve a mesma fonte', f1 is f2, f'{f1} vs {f2}')

# 7) Vazio devolve a fonte do slot (comportamento anterior preservado).
t = criar({'Adventist Sans'})
check('vazio devolve _font_temp',
      t._fonte_temp_para_texto('') == ('Digital-7', 100, 'normal'))

# 8) Trocar de mensagem/número invalida o cache corretamente.
t = criar({'Adventist Sans'})
t._fonte_temp_para_texto('SEM INTERNET')
f = t._fonte_temp_para_texto('25°C')
check('cache não vaza entre texto e número', f[0] == 'Digital-7', str(f))

print('\n' + ('TODOS OS CASOS PASSARAM' if not falhas else f'FALHAS: {falhas}'))
sys.exit(1 if falhas else 0)
