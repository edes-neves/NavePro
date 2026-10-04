import os, ast, sys, types

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)
ARQ = os.path.join(RAIZ, 'NavePro.py')
src = open(ARQ).read()
nos = {n.name: n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)}

class TclError(Exception): pass

class Label:
    def __init__(s): s.texto=None; s.vivo=True
    def winfo_exists(s): return 1 if s.vivo else 0
    def config(s, **k): s.texto = k.get('text', s.texto)

class Text:
    def __init__(s): s.tags_removidos=0; s.linhas={}
    def tag_remove(s, tag, a, b): s.tags_removidos += 1
    def tag_configure(s, *a, **k): pass
    def get(s, a, b): return '\n'.join(s.linhas.get(i,'') for i in sorted(s.linhas))
    def tag_add(s, *a): pass
    def see(s, x): pass

NOMES = ('_atualizar_indicador_slide','_sincronizar_biblia_com_telao','_refletir_telao_na_janela')
PRE = """def _fabrica():
    _cap_numeros = CAP_NUMEROS
    _proj_faixa = PROJ_FAIXA
    _travado_recarga = False
    label_slide = LABEL
    biblia_text = TEXT
    _destacar_versiculo_na_tela = DESTACAR
    _carregar_capitulo = CARREGAR
    _atualizar_indicador_slide = lambda: None
"""
POST = """
    return """ + ', '.join(NOMES) + """
"""
corpo = "\n".join("    " + ast.get_source_segment(src, nos[n]).replace("\n", "\n    ") for n in NOMES)

estado = {}
def novo_telao(em_slides, idx, n_slides):
    return types.SimpleNamespace(_em_slides=em_slides, _slides=[None]*n_slides,
                                _slide_index=idx, mostrando_letra=em_slides)

def rodar(cap_numeros, proj_faixa, telao, destacar_ret=True, carregar_calls=None):
    global estado
    LABEL.texto = None
    cap = list(cap_numeros)
    CALLS = []
    def destacar(num):
        CALLS.append(('destacar', num)); return destacar_ret
    def carregar(foco=None):
        CALLS.append(('carregar', foco))
        if carregar_calls is not None: carregar_calls.append(foco)
    ns = {
        'CAP_NUMEROS': cap, 'PROJ_FAIXA': proj_faixa, 'LABEL': LABEL, 'TEXT': TEXT,
        'DESTACAR': destacar, 'CARREGAR': carregar,
        'self': types.SimpleNamespace(player=types.SimpleNamespace(telao=telao)),
        'tk': types.SimpleNamespace(TclError=TclError, END='end'), 'Optional': __import__('typing').Optional,
        'vers_var': types.SimpleNamespace(
            get=lambda: 'x', set=lambda v: CALLS.append(('V:set', v))),
    }
    exec(compile(PRE + corpo + POST, '<fab>', 'exec'), ns)
    f1, f2, f3 = ns['_fabrica']()
    f3()
    return LABEL.texto, CALLS

LABEL, TEXT = Label(), Text()
falhas = []
def check(n, cond, extra=''):
    print(f"{'OK ' if cond else 'FALHA'} {n}{(' -> '+extra) if extra else ''}")
    if not cond: falhas.append(n)

# 1) projeção de faixa: rótulo mostra a faixa, não "de 8"
txt, _ = rodar(list(range(9,17)), (9,16), novo_telao(True, 3, 8))
check('rótulo da faixa mostra "faixa 9-16"', txt == 'Versículo 12 · faixa 9-16', str(txt))

# 2) projeção do capítulo inteiro: rótulo antigo "de 36"
txt, _ = rodar(list(range(1,37)), None, novo_telao(True, 15, 36))
check('capítulo inteiro mantém "de 36"', txt == 'Versículo 16 de 36', str(txt))

# 3) durante a navegação: destaca e NÃO recarrega
TEXT.tags_removidos = 0
txt, calls = rodar(list(range(9,17)), (9,16), novo_telao(True, 3, 8), destacar_ret=True)
check('navegando: destaca o versículo 12', ('destacar', 12) in calls, str(calls))
check('navegando: não recarrega o capítulo', not any(c[0]=='carregar' for c in calls), str(calls))

# 4) versículo fora da vista: cai no foco de sincronismo (recarga)
txt, calls = rodar(list(range(9,17)), (9,16), novo_telao(True, 3, 8), destacar_ret=False)
check('versículo ausente: recarrega com foco 12', ('carregar', 12) in calls, str(calls))

# 5) ao encerrar (não há mais slides): limpa o destaque e atualiza o rótulo
TEXT.tags_removidos = 0
txt, calls = rodar(list(range(9,17)), (9,16), novo_telao(False, 0, 0))
check('após encerrar: limpa o destaque', TEXT.tags_removidos == 1, f"tags={TEXT.tags_removidos}")
check('após encerrar: não toca em V: nem recarrega',
      not any(c[0] in ('V:set','carregar','destacar') for c in calls), str(calls))
check('após encerrar: rótulo volta a "Sem projeção"', txt == 'Sem projeção', str(txt))

print('\n' + ('TODOS OS CASOS PASSARAM' if not falhas else f'FALHAS: {falhas}'))
sys.exit(1 if falhas else 0)
