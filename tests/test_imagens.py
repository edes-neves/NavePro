import ast, atexit, os, sys, textwrap, types

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)
ARQ = os.path.join(RAIZ, 'NavePro.py')
src = open(ARQ, encoding='utf-8').read()
raiz_ast = ast.parse(src)
nos = {n.name: n for n in ast.walk(raiz_ast) if isinstance(n, ast.FunctionDef)}

sys.path.insert(0, _AQUI)
sys.path.insert(0, RAIZ)
from navepro.config import SUFIXOS_IMAGEM
from fixture_arvore import criar_arvore, limpar_arvore

falhas = []
def check(n, cond, extra=''):
    print(f"{'OK ' if cond else 'FALHA'} {n}{(' -> '+extra) if extra else ''}")
    if not cond: falhas.append(n)

# ── 1) o seletor real filtra pelos sufixos de imagem ──
ns = {'List': list, 'Tuple': tuple}
exec(compile(textwrap.dedent(ast.get_source_segment(src, nos['_listar_pastas_arquivos_usuario'])),
             '<l>', 'exec'), ns)
RAIZ = criar_arvore()
atexit.register(limpar_arvore, RAIZ)
nomes = [n for _, n, _ in ns['_listar_pastas_arquivos_usuario'](RAIZ, tuple(sorted(SUFIXOS_IMAGEM)))]
check('arquivos listados são só imagens',
      {n for n in nomes if not os.path.isdir(os.path.join(RAIZ, n))}
      == {'foto.png', 'FOTO.JPG', 'imagem.webp'}, str(nomes))
check('ignora .txt na busca de imagem', 'nota.txt' not in nomes, str(nomes))
check('ignora imagem oculta', '.fundo.png' not in nomes, str(nomes))
check('aceita maiúsculas (.JPG)', 'FOTO.JPG' in nomes, str(nomes))
check('pasta continua navegável', 'Imagens' in nomes, str(nomes))

# ── 2) a lógica das duas funções aninhadas ──
class Var:
    def __init__(self, v=''): self.v = v; self.chamadas = 0
    def set(self, v): self.v = v; self.chamadas += 1

class Seletor:
    """Registra como o seletor do app foi chamado."""
    retorno = ()
    def __init__(self): self.chamadas = []
    def __call__(self, parent, titulo, sufixos=(), **kw):
        self.chamadas.append((parent, titulo, sufixos, kw))
        return type(self).retorno

for nome in ('_escolher_imagem_fundo', '_escolher_imagem_fundo_relogio'):
    sel = Seletor()
    cfg_win, var = object(), Var('/antigo.png')
    ns2 = {'_escolher_arquivos_usuario': sel, 'cfg_win': cfg_win,
           'var_fundo_imagem': var, 'SUFIXOS_IMAGEM': SUFIXOS_IMAGEM,
           'tuple': tuple, 'sorted': sorted}
    exec(compile(textwrap.dedent(ast.get_source_segment(src, nos[nome])), '<f>', 'exec'), ns2)
    func = ns2[nome]

    # cancelou: a variável não é mexida
    Seletor.retorno = ()
    func()
    check(f'{nome}: cancelar não altera o campo', var.v == '/antigo.png' and var.chamadas == 0, var.v)

    # escolheu: grava o primeiro caminho
    Seletor.retorno = ('/tmp/foto.png',)
    func()
    check(f'{nome}: grava o caminho escolhido', var.v == '/tmp/foto.png', var.v)

    parent, titulo, sufixos, extra = sel.chamadas[0]
    check(f'{nome}: pai é a janela de config', parent is cfg_win)
    check(f'{nome}: título preservado', titulo == 'Escolher imagem de fundo', titulo)
    check(f'{nome}: usa os sufixos de imagem do config',
          set(sufixos) == set(SUFIXOS_IMAGEM) and sufixos == tuple(sorted(SUFIXOS_IMAGEM)), str(sufixos))
    check(f'{nome}: sem chamada de diálogo do sistema', extra == {}, str(extra))

check('nenhuma chamada a askopenfilename sobrou',
      not any('askopenfilename' in ast.get_source_segment(src, n)
              for n in ast.walk(raiz_ast) if isinstance(n, ast.FunctionDef)),
      '')

print('\n' + ('TODOS OS CASOS PASSARAM' if not falhas else f'FALHAS: {falhas}'))
sys.exit(1 if falhas else 0)
