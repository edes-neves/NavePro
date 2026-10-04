import os, ast, sys, types, tkinter as tkinter

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)
src = open(os.path.join(RAIZ, 'NavePro.py')).read()
nos = {n.name: n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)}
NOMES = ('_janela_viva','_cancelar_recarga','_recarga_agendada','_agendar_recarga',
         '_ao_alterar_referencia','_ao_destruir_janela','_sincronizar_biblia_com_telao')

agora = [0.0]
class TclError(Exception): pass
tkinter.TclError = TclError

class Janela:
    def __init__(self):
        self.timers = {}; self._id = 0; self.viva = True; self._bindings = {}
    def after(self, ms, fn):
        self._id += 1
        self.timers[str(self._id)] = (agora[0] + ms/1000, fn)   # Tk devolve o id como str
        return str(self._id)
    def after_cancel(self, tid): self.timers.pop(str(tid), None)
    def winfo_exists(self):
        if not self.viva: raise TclError('destroyed')
        return 1
    def bind(self, seq, fn): self._bindings[seq] = fn
    def tick(self, ms):
        agora[0] += ms/1000
        for tid in [t for t, (d, _) in self.timers.items() if d <= agora[0]]:
            _, fn = self.timers.pop(tid); fn()  # id permanece str

janela = Janela()
class Var:
    def __init__(self, v): self.v=v; self.traces=[]
    def get(self): return self.v
    def set(self, v):
        self.v=v
        for cb in self.traces: cb()
    def trace_add(self, mode, cb): self.traces.append(cb)

versao_var, livro_var, cap_var, vers_var = Var('ARC'), Var('João'), Var('3'), Var('16')
CARREGAMENTOS = []
_marcou = []
_cap_numeros = [10, 11, 12]

# --- escopo sintético com as funções REAIS extraídas do arquivo ---
corpo = '\n'.join('    ' + ast.get_source_segment(src, nos[n]).replace('\n', '\n    ')
                  for n in NOMES)
fabrica = f"""
def _fabrica():
    _travado_recarga = False
    _id_recarga = None
{corpo}
    return ({', '.join(NOMES)})
"""
ns = {'Optional': __import__('typing').Optional, 'tk': tkinter, 'janela': janela,
      'versao_var': versao_var, 'livro_var': livro_var, 'cap_var': cap_var,
      'vers_var': vers_var, '_cap_numeros': _cap_numeros,
      '_carregar_capitulo': lambda foco=None: CARREGAMENTOS.append(vers_var.get()),
      '_destacar_versiculo_na_tela': lambda num: (_marcou.append(num), True)[1],
      '_atualizar_indicador_slide': lambda: None,
      'self': types.SimpleNamespace(player=types.SimpleNamespace(telao=types.SimpleNamespace(
          _em_slides=True, _slides=['a','b','c'], _slide_index=2)))}
exec(compile(fabrica, '<fabrica>', 'exec'), ns)
(_janela_viva,_cancelar_recarga,_recarga_agendada,_agendar_recarga,
 _ao_alterar_referencia,_ao_destruir_janela,_sincronizar) = ns['_fabrica']()

falhas = []
def check(nome, cond, extra=''):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> '+extra) if extra else ''}")
    if not cond: falhas.append(nome)

for v in (versao_var, livro_var, cap_var, vers_var):
    v.trace_add('write', _ao_alterar_referencia)

vers_var.set('1-7')
check('digitou "1-7": não carrega na hora', CARREGAMENTOS == [])
janela.tick(499); check('antes de 500ms não carregou', CARREGAMENTOS == [])
janela.tick(1);   check('carregou aos 500ms', CARREGAMENTOS == ['1-7'], str(CARREGAMENTOS))

CARREGAMENTOS.clear()
for t in ('1', '1-', '1-7'):
    vers_var.set(t); janela.tick(100)
check('debounce: 3 teclas viram 1 carga', CARREGAMENTOS == [])
janela.tick(500); check('carga única com o valor final', CARREGAMENTOS == ['1-7'], str(CARREGAMENTOS))

for v, nome in ((versao_var,'versão'), (livro_var,'livro'), (cap_var,'cap')):
    CARREGAMENTOS.clear(); v.set('X'); janela.tick(500)
    check(f'mudar {nome} recarrega', len(CARREGAMENTOS) == 1, str(CARREGAMENTOS))

CARREGAMENTOS.clear(); _marcou.clear(); janela.timers.clear()
_sincronizar()
check('sync: grava V: sem agendar recarga', janela.timers == {} and CARREGAMENTOS == [],
      f"timers={len(janela.timers)} cargas={CARREGAMENTOS}")
janela.tick(3000)
check('sync: nada recarrega depois (setas não recarregam)', CARREGAMENTOS == [])
check('sync: Featured versículo 12', _marcou == [12], str(_marcou))
vers_var.set('13'); janela.tick(0)
check('sync: bloqueio liberado (V: editável de novo)', len(janela.timers) == 1)
janela.tick(500)

vers_var.set('9')
check('timer pendente existe', len(janela.timers) == 1)
_ao_destruir_janela(types.SimpleNamespace(widget=object()))
check('Destroy de outro widget não cancela', len(janela.timers) == 1)
_ao_destruir_janela(types.SimpleNamespace(widget=janela))
check('Destroy da janela cancela o timer', janela.timers == {})

CARREGAMENTOS.clear(); vers_var.set('9'); janela.viva = False
try:
    janela.tick(500); ok, det = CARREGAMENTOS == [], ''
except TclError as e:
    ok, det = False, str(e)
check('janela destruída: recarga ignorada, sem exceção', ok, det)

print('\n' + ('TODOS OS CASOS PASSARAM' if not falhas else f'FALHAS: {falhas}'))
sys.exit(1 if falhas else 0)
