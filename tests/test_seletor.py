import ast, atexit, os, sys, types

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, _AQUI)
sys.path.insert(0, RAIZ)
ARQ = os.path.join(RAIZ, 'NavePro.py')
src = open(ARQ, encoding='utf-8').read()
nos = {n.name: n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)}
from fixture_arvore import criar_arvore, limpar_arvore

class TclError(Exception): pass
REG, AVISOS, CONFIRMA, RESPOSTAS = {}, [], [], []

class Base:
    def __init__(self, *a, **k):
        self._cfg = {}; self._bindings = {}
        REG.setdefault('widgets', []).append(self)
    def __getattr__(self, nome): return lambda *a, **k: None
    def pack(self, *a, **k): pass
    def bind(self, *a, **k): self._bindings[a[0]] = a[1]
    def config(self, **k): self._cfg.update(k)
    def configure(self, **k): self._cfg.update(k)
    def destroy(self): REG.setdefault('destruidos', []).append(self)
    def wait_window(self):
        """Fica 'aberto' enquanto o roteiro simula o operador."""
        if REG.get('durante'): REG['durante']()

class Entry(Base):
    def __init__(self, *a, **k): super().__init__(); self.buf = ''
    def insert(self, i, t): self.buf += t
    def delete(self, *a): self.buf = ''
    def get(self): return self.buf

class Listbox(Base):
    def __init__(self, *a, **k): super().__init__(); self.itens = []
    def insert(self, i, t): self.itens.append(t)
    def delete(self, *a, **k):
        if a and a[0] == 0: self.itens = []
    def nearest(self, y): return int(y)
    def curselection(self): return []

class Button(Base):
    def __init__(self, pai, **k):
        super().__init__(); self._cfg.update(k); self.cmd = k.get('command')
        REG.setdefault('botoes', {})[k.get('text')] = self
    def invoke(self): self.cmd()

class _MB:
    @staticmethod
    def showwarning(titulo, msg, parent=None): AVISOS.append((titulo, msg))
    @staticmethod
    def askyesno(titulo, msg, parent=None):
        CONFIRMA.append((titulo, msg))
        return RESPOSTAS.pop(0) if RESPOSTAS else True

class _TclInterp:
    TclError = TclError
tkinter = types.SimpleNamespace(TclError=TclError, END='end', messagebox=_MB)
tk = types.SimpleNamespace(Toplevel=Base, Frame=Base, Button=Button, Label=Base,
                           Entry=Entry, Listbox=Listbox, Scrollbar=Base,
                           END='end', TclError=TclError)
ns = {'tk': tk, 'tkinter': tkinter, 'Optional': __import__('typing').Optional,
      'List': list, 'Tuple': tuple}
exec(compile(ast.get_source_segment(src, nos['_listar_pastas_arquivos_usuario']), '<l>', 'exec'), ns)
exec(compile(ast.get_source_segment(src, nos['_escolher_arquivos_usuario']), '<s>', 'exec'), ns)
escolher, listar = ns['_escolher_arquivos_usuario'], ns['_listar_pastas_arquivos_usuario']
RAIZ = criar_arvore()
atexit.register(limpar_arvore, RAIZ)

falhas = []
def check(n, cond, extra=''):
    print(f"{'OK ' if cond else 'FALHA'} {n}{(' -> '+extra) if extra else ''}")
    if not cond: falhas.append(n)

def abrir(roteiro=None, **kw):
    REG.clear(); AVISOS.clear(); CONFIRMA.clear(); RESPOSTAS.clear()
    REG['botoes'] = {}; REG['durante'] = roteiro
    return escolher(None, "Teste", **kw)

def campo(): return [w for w in REG['widgets'] if isinstance(w, Entry)][0]
def lista(): return [w for w in REG['widgets'] if isinstance(w, Listbox)][0]
def clicar(txt): REG['botoes'][txt].invoke()
def duplo(idx): lista()._bindings['<Double-Button-1>'](types.SimpleNamespace(y=idx))

# ───── 1) a reclamação: nada de "." na lista ─────
nomes = [t[1] for t in listar(RAIZ, ('.navepro',))]
check('nenhum item começa com "."', not any(n.startswith('.') for n in nomes), str(nomes))
check('pastas do usuário visíveis', {'Documentos','Imagens','Sub'} <= set(nomes), str(nomes))
check('arquivo do sufixo pedido visível', 'a.navepro' in nomes, str(nomes))
check('arquivo de outro sufixo escondido', 'b.txt' not in nomes, str(nomes))

# ───── 2) modo importar: igual ao de antes ─────
r = abrir(pasta_inicial=RAIZ, sufixos=('.navepro',))
check('importar: lista sem ocultos',
      not any('.oculta' in i or '.config' in i for i in lista().itens), str(lista().itens))
check('importar: cancelar devolve vazio', r == (), str(r))
check('importar: botão "Importar" continua verde',
      REG['botoes']['Importar']._cfg['bg'] == '#238636', REG['botoes']['Importar']._cfg['bg'])
check('importar: sem campo de nome', not any(isinstance(w, Entry) for w in REG['widgets']))
check('importar: duplo clique na pasta entra nela (Documentos é vazia)',
      (duplo(0), lista().itens)[1] == [], str(lista().itens))

# ───── 3) modo salvar ─────
r = abrir(lambda: clicar('💾 Salvar'), pasta_inicial=RAIZ,
          sufixos=('.navepro',), nome_para_salvar='NavePro-2026.navepro')
check('salvar: nome sugerido no campo', campo().get() == 'NavePro-2026.navepro')
check('salvar: devolve o caminho completo',
      r == (os.path.join(RAIZ, 'NavePro-2026.navepro'),), str(r))
check('salvar: sem avisos', AVISOS == [] and CONFIRMA == [], str(AVISOS))

def roteiro_nome_vazio():
    campo().buf = '   '
    clicar('💾 Salvar')
r = abrir(roteiro_nome_vazio, pasta_inicial=RAIZ, nome_para_salvar='x.navepro')
check('salvar sem nome: avisa', len(AVISOS) == 1, str(AVISOS))
check('salvar sem nome: não salva', r == (), str(r))

r = abrir(lambda: clicar('💾 Salvar'), pasta_inicial=RAIZ, nome_para_salvar='Sub')
check('nome que é pasta: entra na pasta', any('Pasta' in i for i in lista().itens), str(lista().itens))
check('nome que é pasta: não salva', r == (), str(r))

RESPOSTAS.clear()
r = abrir(lambda: (RESPOSTAS.append(False), clicar('💾 Salvar')), pasta_inicial=RAIZ,
          nome_para_salvar='a.navepro')
check('existente: pergunta antes de sobrescrever', len(CONFIRMA) == 1, str(CONFIRMA))
check('existente: "não" não salva', r == (), str(r))
RESPOSTAS.clear()
r = abrir(lambda: (RESPOSTAS.append(True), clicar('💾 Salvar')), pasta_inicial=RAIZ,
          nome_para_salvar='a.navepro')
check('existente: "sim" salva', r == (os.path.join(RAIZ,'a.navepro'),), str(r))

def roteiro_duplo():
    idx = next(i for i, t in enumerate(lista().itens) if 'a.navepro' in t)
    duplo(idx)
r = abrir(roteiro_duplo, pasta_inicial=RAIZ, sufixos=('.navepro',), nome_para_salvar='x.navepro')
check('duplo clique no arquivo: põe o nome no campo', campo().get() == 'a.navepro', campo().get())
check('duplo clique no arquivo: não fecha o diálogo', r == (), str(r))

def roteiro_duplo_pasta():
    duplo(0)
r = abrir(roteiro_duplo_pasta, pasta_inicial=RAIZ, sufixos=('.navepro',), nome_para_salvar='Sub')
check('duplo clique na pasta: entra e mantém o nome', campo().get() == 'Sub', campo().get())

r = abrir(lambda: clicar('💾 Salvar'), pasta_inicial=RAIZ, nome_para_salvar='backup')
check('seletor não inventa extensão (exportar_transferencia põe)',
      r == (os.path.join(RAIZ,'backup'),), str(r))
r = abrir(lambda: clicar('Cancelar'), pasta_inicial=RAIZ, nome_para_salvar='y.navepro')
check('cancelar devolve vazio', r == (), str(r))

print('\n' + ('TODOS OS CASOS PASSARAM' if not falhas else f'FALHAS: {falhas}'))
sys.exit(1 if falhas else 0)
