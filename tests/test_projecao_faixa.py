import ast, os, sqlite3, sys, types, tkinter as tkinter

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)
ARQ = os.path.join(RAIZ, 'NavePro.py')
src = open(ARQ, encoding='utf-8').read()
tree = ast.parse(src)
nos = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

class TclError(Exception): pass
tkinter.TclError = TclError

# ---------- TelaoWindow real (só a navegação de slides) ----------
corpo_telao = '\n'.join(
    ast.get_source_segment(src, nos[n]) for n in ('_mostrar_slide','slide_proximo','slide_anterior'))
fabrica_telao = f'''
class Telao:
    _em_slides = False
    _slides = []
    _slide_index = 0
    mostrando_letra = False
    mostrar_relogio = False
{chr(10).join("    " + l for l in corpo_telao.split(chr(10)))}
'''
ns = {'os': os, 'tkinter': tkinter, 'tk': tkinter, 'TclError': TclError}
exec(compile(fabrica_telao, '<telao>', 'exec'), ns)
Telao = ns['Telao']

class TelaoTeste(Telao):
    def __init__(self):
        self._slides=[]; self._slide_index=0; self._em_slides=False
        self.mostrando_letra=False; self.desenhos=[]; self.paradas=0
    # helpers que _mostrar_slide usa
    def _desenhar_texto_no_canvas(self, texto, referencia=''): self.desenhos.append((texto, referencia))
    def _limpar_camada_imagem(self): pass
    def parar_projecao(self):
        self.paradas += 1; self._em_slides=False; self._slides=[]
        self.mostrando_letra=False
    def projetar_slides(self, slides, indice_inicial=0):
        self._slides = list(slides); self._slide_index = 0
        self._em_slides = True; self.mostrando_letra = True
        self.paradas = 0; self.desenhos = []
        self._mostrar_slide(indice_inicial)

# ---------- janela da Bíblia (só _projetar_versiculo) ----------
DB = os.path.expanduser('~/.navepro/midia.db')
_cache = {}
def db_query(sql, params=()):
    k = (sql, tuple(params))
    if k not in _cache:
        c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
        _cache[k] = c.execute(sql, params).fetchall()
    return _cache[k]

class Var:
    def __init__(s, v): s.v = v
    def get(s): return s.v
    def set(s, v): s.v = v

AVISOS = []
class _MB:
    @staticmethod
    def showwarning(titulo, msg, parent=None): AVISOS.append((titulo, msg))
class FakeMsg:
    messagebox = _MB

PRE = """def _fabrica():
    _cap_numeros = []
    _proj_faixa = None
    _destaques = []
    _indicador = [None]
    versao_var = Vars["versao"]; livro_var = Vars["livro"]
    cap_var = Vars["cap"]; vers_var = Vars["vers"]
    _destacar_versiculo_na_tela = lambda num: (_destaques.append(num), True)[1]
    _carregar_capitulo = lambda foco=None: _destaques.append(("carregar", foco))
    _atualizar_indicador_slide = lambda: _indicador.__setitem__(0, "atualizado")
    self = self_stub
"""
POST = """
    return _projetar_versiculo, _cap_numeros, _destaques, _indicador, lambda: _proj_faixa
"""
# corpo real da função, indentado em 4 (sem f-string: as chaves ficam intactas)
_corpo = "\n".join("    " + l for l in ast.get_source_segment(
    src, nos["_projetar_versiculo"]).split("\n"))
fabrica = PRE + _corpo + POST
Vars = {'versao': Var('Almeida Revista e Corrigida'), 'livro': Var('João'),
        'cap': Var('3'), 'vers': Var('')}
telao = TelaoTeste()
ns2 = {'Vars': Vars, 'self_stub': types.SimpleNamespace(player=types.SimpleNamespace(telao=telao)),
       'db_query': db_query, 'tkinter': FakeMsg(), 'janela': object()}
# _analisar_faixa_versiculos real, extraído do arquivo
exec(compile(ast.get_source_segment(src, nos['_analisar_faixa_versiculos']),
             '<faixa>', 'exec'), ns2)
exec(compile(fabrica, '<fabrica>', 'exec'), ns2)
projetar, cap_numeros, destaques, indicador, faixa_atual = ns2['_fabrica']()

falhas = []
def check(nome, cond, extra=''):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> '+extra) if extra else ''}")
    if not cond: falhas.append(nome)

def projetar_com(entrada):
    AVISOS.clear(); destaques.clear(); indicador[0] = None
    telao.__init__()
    Vars['vers'].set(entrada)
    projetar()
    return (list(telao.desenhos), list(cap_numeros), faixa_atual(),
            getattr(telao, '_em_slides', False), list(AVISOS))

def simulating(entrada, n):
    """Projeta e avança n slides; devolve os versículos vistos."""
    projetar_com(entrada)
    vistos = []
    if getattr(telao, '_em_slides', False):
        vistos.append(telao.desenhos[-1][1])
        for _ in range(n):
            if not telao.slide_proximo(): break
            if not getattr(telao, '_em_slides', False): break
            vistos.append(telao.desenhos[-1][1])
    return vistos

# --- 1) BUG REPORTADO: "9-16" deve começar no 9 ---
desenhos, numeros, faixa, em_slides, avisos = projetar_com('9-16')
check('V:="9-16" projeta 8 slides (nada além da faixa)', len(cap_numeros) == 8, f'{len(cap_numeros)}')
check('V:="9-16" slides = 9..16', numeros == list(range(9,17)), str(numeros))
check('V:="9-16" começa no versículo 9',
      desenhos and desenhos[0][1] == 'João 3:9', desenhos[0][1] if desenhos else '-')
check('V:="9-16" faixa rotulada (9,16)', faixa == (9,16), str(faixa))
check('V:="9-16" sem aviso', avisos == [], str(avisos))

# --- 2) um a um até o 16 e encerrar ---
vistos = simulating('9-16', 12)
check('navega 9,10,...,16 um a um',
      vistos == [f'João 3:{n}' for n in range(9,17)], str(vistos))
check('ao passar do 16 a projeção encerra', telao.paradas == 1 and not telao._em_slides,
      f'paradas={telao.paradas} em_slides={telao._em_slides}')
check('não projeta o 17 nem volta ao 1', all('3:17' not in v and '3:1 ' not in v for v in vistos))

# --- 3) ◀ Anterior não sai da faixa ---
projetar_com('9-16')
for _ in range(12): telao.slide_anterior()
check('◀ Anterior para no versículo 9', telao.desenhos[-1][1] == 'João 3:9',
      telao.desenhos[-1][1])
check('◀ Anterior não encerra a projeção', telao.paradas == 0 and telao._em_slides)

# --- 4) casos que NÃO podem mudar ---
desenhos, numeros, faixa, em_slides, avisos = projetar_com('')
check('V: vazio = capítulo inteiro (36)', numeros == list(range(1,37)), str(len(numeros)))
check('V: vazio começa no 1', desenhos[0][1] == 'João 3:1')
check('V: vazio sem faixa no rótulo', faixa is None, str(faixa))

desenhos, numeros, faixa, em_slides, avisos = projetar_com('16')
check('V:="16" = capítulo inteiro (36)', numeros == list(range(1,37)), str(len(numeros)))
check('V:="16" começa no 16', desenhos[-1][1] == 'João 3:16' and
      telao._slide_index == numeros.index(16), f"idx={telao._slide_index}")
check('V:="16" sem faixa no rótulo', faixa is None, str(faixa))

# --- 5) entradas inválidas não projetam nada ---
for entrada,motivo in (('abc','texto'), ('9-3','invertida'), ('1-','incompleta'), ('0','zero')):
    desenhos, numeros, faixa, em_slides, avisos = projetar_com(entrada)
    ok = not desenhos and not em_slides and len(avisos) == 1
    check(f'V:={entrada!r} ({motivo}) não projeta e avisa', ok,
          avisos[0][1][:40] if avisos else 'sem aviso')

# --- 6) faixa inexistente ---
desenhos, numeros, faixa, em_slides, avisos = projetar_com('100-200')
check('faixa inexistente avisa e não projeta',
      not desenhos and len(avisos) == 1, avisos[0][1][:46] if avisos else '')

# --- 7) capítulo sem versículos no banco ---
Vars['cap'].set('999'); Vars['vers'].set('')
projetar_com('')
check('capítulo inexistente avisa', len(AVISOS) == 1 and 'Nenhum versículo' in AVISOS[0][1])
Vars['cap'].set('3')

print('\n' + ('TODOS OS CASOS PASSARAM' if not falhas else f'FALHAS: {falhas}'))
sys.exit(1 if falhas else 0)
