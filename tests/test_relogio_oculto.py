"""Regressão: botão "Ocultar relógio do telão" (aba Relógio).

O operador pode esconder a hora e a temperatura no telão (monitor 2) sem
afetar projeções nem medidores. `mostrar_relogio` deve respeitar o flag e
`definir_relogio_oculto` deve esconder imediatamente no modo relógio.
"""
import ast
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
ARQ_T = os.path.join(RAIZ, 'navepro', 'core', 'telao.py')
src = open(ARQ_T, encoding='utf-8').read()
tree = ast.parse(src)
nos = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

_metodos = ('mostrar_relogio', '_esconder_textos_relogio',
            'definir_relogio_oculto', '_desativar_topmost_projecao')
_corpo = "\n".join(ast.get_source_segment(src, nos[n]) for n in _metodos)

ns = {}
exec(compile("class Telao:\n" + "\n".join(
    "    " + linha for linha in _corpo.split("\n")) + "\n", '<telao>', 'exec'), ns)
Telao = ns['Telao']


class Canvas:
    def __init__(self):
        self.chamadas = []

    def itemconfig(self, item, **kw):
        self.chamadas.append((item, kw))


class Root:
    def __init__(self):
        self.deiconified = 0
        self.lowered = 0
        self.attrs = []

    def deiconify(self):
        self.deiconified += 1

    def lower(self):
        self.lowered += 1

    def attributes(self, *a):
        self.attrs.append(a)

    def update_idletasks(self):
        pass


class Stub(Telao):
    def __init__(self, oculto=False, mostrando_relogio=True, projetando=False,
                 vivo=True, visible=True):
        self.rodando = True
        self._vivo = vivo
        self._is_visible = visible
        self._relogio_oculto = oculto
        self.mostrando_relogio = mostrando_relogio
        self._current_alpha = 0.55
        self._current_text = ""
        self._current_temp = ""
        self.overlay_text = 'HORA'
        self.temp_text = 'TEMP'
        self.canvas = Canvas()
        self.root = Root()
        self._projetando = projetando

    def _raiz_viva(self):
        return self._vivo

    def _alpha_relogio(self):
        return 0.55

    def _fonte_temp_para_texto(self, texto):
        return ('Digital-7', 40, 'normal')

    def _esconder_textos_relogio(self):
        # versão real, mas sem update_idletasks
        if not self._raiz_viva():
            return
        self.canvas.itemconfig(self.overlay_text, text="", state="hidden")
        self.canvas.itemconfig(self.temp_text, text="", state="hidden")
        self._current_text = ""
        self._current_temp = ""


falhas = []


def check(nome, cond, extra=''):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


def ultimo(item):
    """Últimos kwargs aplicados ao item."""
    kw = {}
    for it, k in t.canvas.chamadas:
        if it == item:
            kw.update(k)
    return kw


# 1) oculto: não desenha hora nem temperatura
t = Stub(oculto=True)
t.mostrar_relogio("10:00", "25°")
check('oculto: hora escondida', ultimo('HORA').get('state') == 'hidden', str(ultimo('HORA')))
check('oculto: temperatura escondida', ultimo('TEMP').get('state') == 'hidden', str(ultimo('TEMP')))
check('oculto: sem texto desenhado',
      '10:00' not in str(t.canvas.chamadas) and '25°' not in str(t.canvas.chamadas))
check('oculto: caches zerados', t._current_text == "" and t._current_temp == "")

# 2) visível: desenha hora e temperatura normalmente
t = Stub(oculto=False)
t.mostrar_relogio("10:00", "25°")
check('visível: hora desenhada', ultimo('HORA').get('text') == '10:00', str(ultimo('HORA')))
check('visível: temperatura desenhada', ultimo('TEMP').get('text') == '25°', str(ultimo('TEMP')))
check('visível: estado normal', ultimo('HORA').get('state') == 'normal')

# 3) definir_relogio_oculto(True) no modo relógio esconde na hora
t = Stub(oculto=False)
t.definir_relogio_oculto(True)
check('ocultar: flag ligado', t._relogio_oculto is True)
check('ocultar: hora escondida', ultimo('HORA').get('state') == 'hidden')
check('ocultar: temperatura escondida', ultimo('TEMP').get('state') == 'hidden')

# 4) definir_relogio_oculto(True) durante projeção: não mexe no canvas
t = Stub(oculto=False, mostrando_relogio=False)
t.definir_relogio_oculto(True)
check('projetando: flag ligado', t._relogio_oculto is True)
check('projetando: canvas intacto', not t.canvas.chamadas, str(t.canvas.chamadas))

# 5) mostrar de novo: volta a desenhar
t = Stub(oculto=True)
t.definir_relogio_oculto(False)
t.mostrar_relogio("11:00", "26°")
check('mostrar: hora desenhada', ultimo('HORA').get('text') == '11:00', str(ultimo('HORA')))
check('mostrar: flag desligado', t._relogio_oculto is False)

# 6) telão morto: não quebra
t = Stub(oculto=True, vivo=False)
t.mostrar_relogio("10:00", "25°")
t.definir_relogio_oculto(True)
check('telão morto: sem chamadas de canvas', not t.canvas.chamadas)

# 7) voltar ao relógio desliga o -topmost usado durante as projeções
t = Stub(oculto=False)
t._topmost_projecao = True
t.mostrar_relogio("10:00", "25°")
check('relógio: topmost desligado', t._topmost_projecao is False)
check('relógio: -topmost=False aplicado',
      ('-topmost', False) in t.root.attrs, str(t.root.attrs))

print('\n' + ('TODOS OS CASOS PASSARAM' if not falhas else f'FALHAS: {falhas}'))
sys.exit(1 if falhas else 0)
