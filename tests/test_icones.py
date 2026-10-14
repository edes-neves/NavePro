"""Ícones dos botões do painel: emoji colorido + PNG de fallback.

O bug que motivou esta suíte: os rótulos dos botões traziam emoji direto e o
Tk 8.6 só os desenhava quando o sistema tinha a fonte certa (no Ubuntu uns
saíam e outros não, no Debian e no Windows não saía nada). Agora o emoji vira
IMAGEM (navepro/core/icones.py) e todo botão ainda tem um PNG fixo em icones/
como segundo fallback — a garantia aqui é que nenhum botão pode ficar sem
ícone, independentemente da fonte da máquina.
"""

import ast
import os
import re
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

falhas = []
def check(nome, cond, extra=''):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)

# ── 1) toda chamada a _criar_botao_pill declara um PNG de fallback ──────────
src = open(os.path.join(RAIZ, 'NavePro.py'), encoding='utf-8').read()
chamadas = [n for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == '_criar_botao_pill']
check('há botões-pílula para analisar', len(chamadas) >= 11, str(len(chamadas)))

pares = []
for c in chamadas:
    icone = (c.args[1].value if len(c.args) > 1
             and isinstance(c.args[1], ast.Constant) else None)
    png = next((kw.value.value for kw in c.keywords
                if kw.arg == 'icone_png' and isinstance(kw.value, ast.Constant)),
               None)
    pares.append((icone, png))

sem_fallback = [i for i, p in pares if not i or not p]
check('todo botão declara emoji e icone_png', not sem_fallback, str(sem_fallback))

# ── 2) e esses PNGs existem em icones/ (senão o fallback é o texto/quadro) ──
faltando = [p for _i, p in pares
            if not os.path.exists(os.path.join(RAIZ, 'icones', f'{p}.png'))]
check('todo icone_png tem arquivo em icones/', not faltando, str(sorted(set(faltando))))

# ── 3) o gerador cobre exatamente os nomes usados (sem PNG órfão) ───────────
gerador = open(os.path.join(RAIZ, 'gerar_icones.py'), encoding='utf-8').read()
bloco = re.search(r'itens = \{(.*?)\n    \}', gerador, re.S)
gerados = set(re.findall(r'"([a-z_]+)":', bloco.group(1))) if bloco else set()
usados = {p for _i, p in pares}
check('gerador cobre todos os nomes usados', not (usados - gerados),
      str(sorted(usados - gerados)))
check('gerador não deixa PNG órfão', not (gerados - usados),
      str(sorted(gerados - usados)))

# ── 4) os PNGs são imagens 40x40 legíveis ──────────────────────────────────
# A suíte de CI roda sem Pillow instalado (só stdlib): o que precisa de PIL é
# pulado, não falhado — ver docstring de tests/test_telao_pil.py.
try:
    from PIL import Image
except Exception:
    Image = None

if Image is None:
    print('PULA  PNGs abertos no Pillow (Pillow ausente nesta máquina)')
else:
    for nome in sorted(usados):
        caminho = os.path.join(RAIZ, 'icones', f'{nome}.png')
        try:
            with Image.open(caminho) as aberto:
                tamanho = aberto.size
                px = list(aberto.convert('RGBA').getdata())
            tinta = sum(1 for *_c, a in px if a > 0)
            check(f'PNG {nome} 40x40 e com desenho',
                  tamanho == (40, 40) and tinta > 0,
                  f'{tamanho} tinta={tinta}')
        except Exception as e:
            check(f'PNG {nome} abre', False, str(e))

# ── 5) o renderizador de emoji: não quebra e nunca devolve lixo ────────────
from navepro.core import icones  # noqa: E402

emojis = sorted({i for i, _p in pares})
if Image is None:
    print('PULA  renderização do emoji (Pillow ausente nesta máquina)')
else:
    fonte = icones._localizar_fonte_emoji()
    print(f'      (fonte de emoji colorida desta máquina: {fonte})')
    for e in emojis:
        try:
            im = icones._emoji_para_imagem(e, 40)
            ok = im is None or (im.size[0] <= 40 and im.size[1] <= 40
                                and im.getbbox() is not None)
            check(f'emoji {e!r} renderiza no máximo 40x40', ok,
                  str(im.size if im else None))
        except Exception as ex:
            check(f'emoji {e!r} não lança exceção', False, str(ex))

    # Se existe fonte de emoji, ela tem que desenhar o emoji dela: caso
    # contrário o localizador escolheu uma fonte que não serve.
    if fonte:
        probe = icones._emoji_para_imagem(icones._PROBE_EMOJI, 40)
        check('fonte escolhida desenha emoji de teste', probe is not None)

# ── 6) PNG inexistente devolve None (o chamador cai para o texto) ──────────
check('PNG desconhecido vira None sem exceção',
      icones._carregar_icone('nao_existe_mesmo') is None)

print('\n' + ('TODOS OS CASOS PASSARAM' if not falhas else f'FALHAS: {falhas}'))
sys.exit(1 if falhas else 0)
