import ast, os, sqlite3, tkinter, sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)
src = open(os.path.join(RAIZ, 'NavePro.py'), encoding='utf-8').read()
tree = ast.parse(src)

def achar(nome, classe=None):
    alvos = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef,)) and n.name == nome]
    return alvos[0] if alvos else None

# --- extrai o texto-fonte das funções reais do arquivo ---
def fonte(no, ctx_lines):
    ini = ctx_lines[no.lineno-1]
    return ast.get_source_segment(src, no)

# _analisar_faixa_versiculos é de módulo; _carregar_capitulo/_escrever_na_biblia são aninhadas
mod_fn = achar('_analisar_faixa_versiculos')
nos = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
assert mod_fn and '_carregar_capitulo' in nos and '_escrever_na_biblia' in nos

# --- stubs ---
DB = os.path.expanduser('~/.navepro/midia.db')
_cache = {}
def db_query(sql, params=()):
    chave = (sql, tuple(params))
    if chave not in _cache:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        _cache[chave] = conn.execute(sql, params).fetchall()
    return _cache[chave]

class Var:
    def __init__(self, v): self.v = v
    def get(self): return self.v
    def set(self, v): self.v = v

class TextStub:
    def __init__(self): self.buf = ''; self.state='normal'; self.hi=[]
    def config(self, **k): self.state = k.get('state', self.state)
    def delete(self, *a): self.buf = ''
    def insert(self, *a): self.buf += str(a[-1] if len(a)>2 else a[-1])
    def tag_remove(self, *a): pass
    def tag_configure(self, *a, **k): pass
    def tag_add(self, *a): self.hi.append(a)
    def index(self, x): return '1.0'
    def see(self, x): pass

versao_var, livro_var = Var('Almeida Revista e Corrigida'), Var('João')
cap_var, vers_var = Var('3'), Var('')
biblia_text = TextStub()

ns = {'Optional': __import__('typing').Optional, 'tk': tkinter,
      'db_query': db_query, 'biblia_text': biblia_text,
      'versao_var': versao_var, 'livro_var': livro_var,
      'cap_var': cap_var, 'vers_var': vers_var}
exec(ast.get_source_segment(src, mod_fn), ns)
exec(ast.get_source_segment(src, nos['_escrever_na_biblia']), ns)
exec(ast.get_source_segment(src, nos['_carregar_capitulo']), ns)
carregar = ns['_carregar_capitulo']

def versiculos_exibidos():
    nums = [int(l.split('.')[0]) for l in biblia_text.buf.split('\n')
            if l and l.split('.')[0].isdigit()]
    return nums

def titulo_erro():
    return biblia_text.buf.split('\n')[0] if not versiculos_exibidos() else None

print(f"João 3 tem {len(db_query('SELECT * FROM versiculos WHERE versao=? AND livro=? AND capitulo=3', ('Almeida Revista e Corrigida','João')))} versículos\n")

casos = [
    ("vazio",        "",        list(range(1, 37))),
    ("1",           "1",       list(range(1, 37))),
    ("7",           "7",       list(range(7, 37))),
    ("16",          "16",      list(range(16, 37))),
    ("1-7",         "1-7",     list(range(1, 8))),
    ("1 - 7",       "1 - 7",   list(range(1, 8))),
    ("5-5",         "5-5",     [5]),
    ("34-36",       "34-36",   [34, 35, 36]),
    ("36",          "36",      [36]),
    ("abc",         "abc",     None),
    ("1-",          "1-",      None),
    ("7-3",         "7-3",     None),
    ("0",           "0",       None),
    ("200",         "200",     None),
]
falhas = 0
for nome, entrada, esperado in casos:
    vers_var.set(entrada)
    carregar()
    obt = versiculos_exibidos()
    if esperado is None:
        ok = obt == [] and titulo_erro() is not None
        det = f"mensagem: {titulo_erro()[:52]!r}"
    else:
        ok = obt == esperado
        det = f"{obt[0] if obt else '-'}..{obt[-1] if obt else '-'} ({len(obt)} vs {len(esperado)})"
    falhas += not ok
    print(f"{'OK ' if ok else 'FALHA'} V:={entrada!r:8} {nome:9} -> {det}")

# foco= (projeção) continua mostrando o capítulo inteiro com destaque
vers_var.set('1-7')
biblia_text.buf=''; biblia_text.hi=[]
carregar(foco=12)
ok = versiculos_exibidos() == list(range(1,37)) and len(biblia_text.hi) == 1
falhas += not ok
print(f"{'OK ' if ok else 'FALHA'} foco=12 (sincronia do telão) -> capítulo inteiro + 1 destaque")

# cap inválido: não toca em nada (comportamento antigo)
biblia_text.buf = 'MANTIDO'
cap_var.set('abc')
carregar()
ok = biblia_text.buf == 'MANTIDO'
falhas += not ok
print(f"{'OK ' if ok else 'FALHA'} cap='abc' -> área de texto preservada")

# capítulo inexistente
cap_var.set('999')
vers_var.set('')
carregar()
ok = 'Nenhum versículo encontrado' in biblia_text.buf
falhas += not ok
print(f"{'OK ' if ok else 'FALHA'} cap=999 -> mensagem de capítulo inexistente")

print(f"\n{'TODOS OS CASOS PASSARAM' if not falhas else str(falhas)+' FALHA(S)'}")
sys.exit(1 if falhas else 0)
