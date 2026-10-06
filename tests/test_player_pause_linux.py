"""Pause do player no Linux: MPRIS/D-Bus e o fallback do Flatpak.

Cobre o que quebrou no Flatpak 2.1.2: o pause do painel precisa (a) falar
com o nome MPRIS REAL do player — o mpv do smplayer registra
org.mpris.MediaPlayer2.mpv, que faltava no mapa — e (b) no Flatpak o sinal
tem que ir pelo pidfile do smplayer-host via flatpak-spawn, ANTES do MPRIS
porque os métodos MPRIS do sandbox não pausam o smplayer de forma
confiável (só a leitura de propriedade funciona). O MPRIS só afirma
sucesso se o PlaybackStatus realmente mudar — o dbus-send devolve exit 0
mesmo quando o nome não existe ou o método não surte efeito.
"""

import ast
import os
import sys
import tempfile
import threading
import types

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

import navepro.core.player as player_mod
from navepro.core.player import MPRIS_DESTS, destino_mpris, mpris_ativo, mpris_status

falhas = []
def check(n, cond, extra=''):
    print(f"{'OK ' if cond else 'FALHA'} {n}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(n)

# ── 1) destino_mpris: nome base, qualquer separador, sem .exe ──
check('mpv mapeia para org.mpris.MediaPlayer2.mpv',
      destino_mpris('mpv') == 'org.mpris.MediaPlayer2.mpv')
check('caminho do Flatpak vira o nome do mpv',
      destino_mpris('/run/host/usr/bin/mpv') == 'org.mpris.MediaPlayer2.mpv')
check('caminho do Windows vira o nome do mpv',
      destino_mpris(r'C:\Program Files\mpv\mpv.exe')
      == 'org.mpris.MediaPlayer2.mpv')
check('smplayer mapeia para o nome dele',
      destino_mpris('smplayer') == 'org.mpris.MediaPlayer2.smplayer')
check('vlc mapeia para o nome dele',
      destino_mpris('vlc') == 'org.mpris.MediaPlayer2.vlc')
check('player desconhecido devolve None', destino_mpris('foobar') is None)
check('comando vazio devolve None', destino_mpris('') is None)

# ── 2) mpris_ativo: NameHasOwner manda (dbus-send mente no exit code) ──
class _Resp:
    def __init__(self, code=0, out=''):
        self.returncode = code
        self.stdout = out

def _fake_run(cmd, **kw):
    if any('ListNames' in parte for parte in cmd):
        return _Resp(0, '   string "org.freedesktop.DBus"\n'
                        '   string "org.mpris.MediaPlayer2.smplayer_1"\n'
                        '   string "org.mpris.MediaPlayer2.mpv"\n')
    alvo = cmd[-1].replace('string:', '')
    if alvo == 'org.mpris.MediaPlayer2.mpv':
        return _Resp(0, '   boolean true\n')
    return _Resp(0, '   boolean false\n')

_orig_run = player_mod.subprocess.run
player_mod.subprocess.run = _fake_run
try:
    r = mpris_ativo(['org.mpris.MediaPlayer2.smplayer',
                     'org.mpris.MediaPlayer2.mpv'])
    check('acha o nome que responde (mpv)', r == 'org.mpris.MediaPlayer2.mpv',
          str(r))
    r = mpris_ativo([None, '', 'org.mpris.MediaPlayer2.mpv'])
    check('ignora entradas vazias', r == 'org.mpris.MediaPlayer2.mpv', str(r))
finally:
    player_mod.subprocess.run = _orig_run

# 2b) Nome exato morto e nenhum nome pedido no ListNames → None
def _fake_run_vazio(cmd, **kw):
    if any('ListNames' in parte for parte in cmd):
        return _Resp(0, '   string "org.freedesktop.DBus"\n'
                        '   string "org.mpris.MediaPlayer2.firefox"\n')
    return _Resp(0, '   boolean false\n')

player_mod.subprocess.run = _fake_run_vazio
try:
    r = mpris_ativo(['org.mpris.MediaPlayer2.smplayer'])
    check('devolve None quando ninguém dos pedidos responde', r is None, str(r))
finally:
    player_mod.subprocess.run = _orig_run

# 2c) Sufixo de instância via ListNames (exato morto, player como _1)
def _fake_run_sufixo(cmd, **kw):
    if any('ListNames' in parte for parte in cmd):
        return _Resp(0, '   string "org.freedesktop.DBus"\n'
                        '   string "org.mpris.MediaPlayer2.smplayer_1"\n'
                        '   string "org.mpris.MediaPlayer2.vlc"\n')
    return _Resp(0, '   boolean false\n')

player_mod.subprocess.run = _fake_run_sufixo
try:
    r = mpris_ativo(['org.mpris.MediaPlayer2.smplayer',
                     'org.mpris.MediaPlayer2.mpv'])
    check('acha o nome com sufixo (smplayer_1)', r == 'org.mpris.MediaPlayer2.smplayer_1',
          str(r))
    r = mpris_ativo(['org.mpris.MediaPlayer2.mpv'])
    check('não sequestra player que não foi pedido',
          r is None, str(r))
finally:
    player_mod.subprocess.run = _orig_run

# 2d) mpris_status: lê PlaybackStatus via Properties.Get
def _fake_run_status(cmd, **kw):
    if any('Properties.Get' in parte for parte in cmd):
        return _Resp(0, '   variant string "Paused"\n')
    return _Resp(0, '')

player_mod.subprocess.run = _fake_run_status
try:
    st = mpris_status('org.mpris.MediaPlayer2.smplayer')
    check('mpris_status devolve "Paused"', st == 'Paused', str(st))
finally:
    player_mod.subprocess.run = _orig_run

# 2e) mpris_status: player morto → None (não mente com Playing/Paused)
def _fake_run_status_morto(cmd, **kw):
    return _Resp(1, '')

player_mod.subprocess.run = _fake_run_status_morto
try:
    st = mpris_status('org.mpris.MediaPlayer2.smplayer')
    check('mpris_status devolve None quando morto', st is None, str(st))
finally:
    player_mod.subprocess.run = _orig_run

# ── 3) _pausar_player extraído do NavePro.py, com stubs ──
src = open(os.path.join(RAIZ, 'NavePro.py'), encoding='utf-8').read()
tree = ast.parse(src)
nos = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
assert '_pausar_player' in nos and '_pausar_player_flatpak' in nos
assert '_mpris_alternar' in nos

# 3-pre) REGRESSÃO: o import real do módulo precisa fornecer os nomes que os
# métodos de pause usam. Sem isso o app morre com NameError no clique do
# pause (ex.: _eh_flatpak faltando no import — os testes de extração não
# pegavam porque injetavam o stub à mão).
_ns_import = {}
for _node in tree.body:
    if isinstance(_node, ast.ImportFrom) and _node.module == 'navepro.core.ambiente':
        exec(ast.get_source_segment(src, _node), _ns_import)
check('NavePro.py importa _eh_flatpak de ambiente',
      '_eh_flatpak' in _ns_import, str(sorted(_ns_import)))
_ns_import2 = {}
for _node in tree.body:
    if isinstance(_node, ast.ImportFrom) and _node.module == 'navepro.core.player':
        exec(ast.get_source_segment(src, _node), _ns_import2)
check('NavePro.py importa mpris_status de player',
      'mpris_status' in _ns_import2, str(sorted(_ns_import2)))
check('NavePro.py importa mpris_ativo/destino_mpris/MPRIS_DESTS',
      {'mpris_ativo', 'destino_mpris', 'MPRIS_DESTS'} <= set(_ns_import2),
      str(sorted(_ns_import2)))

def _montar(flatpak=False, mpris_vivos=(), pid_host=None, proc_pid=None,
            pause=False, list_names_sufixo=None,
            status_seq=('Playing', 'Paused')):
    """Monta um self falso + o namespace com as funções reais extraídas.

    status_seq: tupla (antes, depois) devolvida por mpris_status — controla
    se o PlayPause "funcionou" (mudou) ou não (mesmo status).
    """
    raiz_tmp = tempfile.mkdtemp(prefix='navepro-pausa-')
    pid_path = os.path.join(raiz_tmp, 'smplayer-host.pid')
    if pid_host is not None:
        with open(pid_path, 'w', encoding='utf-8') as f:
            f.write(str(pid_host))
    sinais = []
    chamadas = []
    status_iter = iter(status_seq)

    def fake_subprocess(cmd, **kw):
        chamadas.append(cmd)
        if any('NameHasOwner' in parte for parte in cmd):
            alvo = cmd[-1].replace('string:', '')
            vivo = alvo in mpris_vivos
            return _Resp(0, f'   boolean {"true" if vivo else "false"}\n')
        if any('ListNames' in parte for parte in cmd):
            linhas = ['   string "org.freedesktop.DBus"']
            for nome in mpris_vivos:
                linhas.append(f'   string "{nome}"')
            if list_names_sufixo:
                linhas.append(f'   string "{list_names_sufixo}"')
            return _Resp(0, '\n'.join(linhas) + '\n')
        if any('Properties.Get' in parte for parte in cmd):
            try:
                st = next(status_iter)
            except StopIteration:
                st = status_seq[-1]
            if st is None:
                return _Resp(1, '')
            return _Resp(0, f'   variant string "{st}"\n')
        return _Resp(0, '')

    class _OS:
        SIGSTOP = 19
        SIGCONT = 18
        @staticmethod
        def kill(pid, sig):
            sinais.append((pid, sig))
        path = types.SimpleNamespace(
            join=lambda *a: pid_path if a[-1] == 'smplayer-host.pid'
                            else os.path.join(*a),
            expanduser=os.path.expanduser,
        )

    ns = {
        'Optional': __import__('typing').Optional,
        'subprocess': types.SimpleNamespace(run=fake_subprocess),
        'os': _OS,
        'signal': types.SimpleNamespace(SIGSTOP=19, SIGCONT=18),
        'time': __import__('time'),
        're': __import__('re'),
        '_ambiente_sem_appimage': lambda: {},
    }
    # Imports REAIS do NavePro.py no ns: se o módulo esqueceu de importar
    # algum nome que os métodos usam (ex.: _eh_flatpak), o NameError aparece
    # aqui nos testes de comportamento — igual ao clique no painel.
    for _node in tree.body:
        if isinstance(_node, ast.ImportFrom) and _node.module in (
                'navepro.core.ambiente', 'navepro.core.player'):
            exec(ast.get_source_segment(src, _node), ns)
    if flatpak:
        ns['_eh_flatpak'] = lambda: True
    # mpris_ativo/mpris_status (reais) chamam player_mod.subprocess.run:
    # aponta para o mesmo fake para o NameHasOwner enxergar mpris_vivos.
    player_mod.subprocess.run = fake_subprocess
    for nome in ('_pausar_player', '_pausar_player_flatpak', '_mpris_alternar'):
        exec(ast.get_source_segment(src, nos[nome]), ns)
    self = types.SimpleNamespace(
        player_cmd='smplayer',
        _player_em_uso='smplayer',
        is_paused=pause,
        _process=types.SimpleNamespace(pid=proc_pid) if proc_pid else None,
        _process_lock=threading.Lock(),
        _MPRIS_DESTS=dict(MPRIS_DESTS),
    )
    self._pausar_player = types.MethodType(ns['_pausar_player'], self)
    self._pausar_player_flatpak = types.MethodType(
        ns['_pausar_player_flatpak'], self)
    self._mpris_alternar = types.MethodType(ns['_mpris_alternar'], self)
    return self, ns, chamadas, sinais

# 3a) MPRIS vivo + status muda (Playing→Paused) → PlayPause, True
self, ns, chamadas, sinais = _montar(
    mpris_vivos=('org.mpris.MediaPlayer2.smplayer',),
    status_seq=('Playing', 'Paused'))
ok = self._pausar_player()
check('MPRIS vivo + status muda: pausa de verdade', ok is True)
check('MPRIS vivo: mandou PlayPause no nome certo',
      any('PlayPause' in ' '.join(c) and
          'org.mpris.MediaPlayer2.smplayer' in ' '.join(c)
          for c in chamadas), str(chamadas[:1]))

# 3b) MPRIS vivo mas status NÃO muda (método inócuo) → AppImage: SIGSTOP filho
self, ns, chamadas, sinais = _montar(
    mpris_vivos=('org.mpris.MediaPlayer2.smplayer',),
    status_seq=('Paused', 'Paused'), proc_pid=4321)
ok = self._pausar_player()
check('MPRIS vivo mas status igual: não mente, cai no SIGSTOP do filho',
      ok is True and sinais == [(4321, 19)], str(sinais))

# 3c) Bug do 2.1.2: ninguém no barramento, sem filho → False (não mente)
self, ns, chamadas, sinais = _montar(mpris_vivos=(), proc_pid=None,
                                     status_seq=(None, None))
ok = self._pausar_player()
check('MPRIS morto e sem filho: devolve False (painel avisa)', ok is False)

# 3d) MPV morto + filho direto (AppImage): SIGSTOP continua como fallback
self, ns, chamadas, sinais = _montar(mpris_vivos=(), proc_pid=4321,
                                     status_seq=(None, None))
ok = self._pausar_player()
check('AppImage, MPRIS morto: SIGSTOP no filho direto', ok is True and
      sinais == [(4321, 19)], str(sinais))

# 3e) Flatpak: pidfile PRIMEIRO (antes do MPRIS), STOP no grupo, sem SIGSTOP
#     no proxy — mesmo com MPRIS vivo, o caminho confiável vem primeiro.
#     O kill vai DIRETO (util-linux) via flatpak-spawn: o /bin/sh do host é
#     dash e o builtin dele rejeita pid negativo.
self, ns, chamadas, sinais = _montar(
    flatpak=True,
    mpris_vivos=('org.mpris.MediaPlayer2.smplayer',),
    pid_host=98765, proc_pid=1234,
    status_seq=('Playing', 'Paused'))
ok = self._pausar_player()
flatpak_calls = [c for c in chamadas if c and c[0] == 'flatpak-spawn']
check('Flatpak: mandou sinal no host via pidfile (caminho principal)',
      ok is True and flatpak_calls, str(flatpak_calls[:1]))
check('Flatpak: STOP no grupo do player (pid do pidfile, kill direto)',
      flatpak_calls and 'kill' in flatpak_calls[-1] and
      '-STOP' in flatpak_calls[-1] and '-98765' in flatpak_calls[-1],
      str(flatpak_calls[-1] if flatpak_calls else '-'))
check('Flatpak: sem wrapper de sh (dash rejeita pid negativo)',
      flatpak_calls and '/bin/sh' not in flatpak_calls[-1],
      str(flatpak_calls[-1] if flatpak_calls else '-'))
check('Flatpak: zero SIGSTOP no processo da mão', sinais == [], str(sinais))
mpris_calls = [c for c in chamadas if any('PlayPause' in p for p in c)]
check('Flatpak com pidfile: NÃO precisou do MPRIS', mpris_calls == [],
      str(mpris_calls[:1]))

# 3f) Flatpak pausado: manda CONT (despausa)
self, ns, chamadas, sinais = _montar(flatpak=True, mpris_vivos=(),
                                     pid_host=98765, pause=True,
                                     status_seq=(None, None))
ok = self._pausar_player()
flatpak_calls = [c for c in chamadas if c and c[0] == 'flatpak-spawn']
check('Flatpak pausado: manda CONT (despausa)',
      ok is True and flatpak_calls and '-CONT' in flatpak_calls[-1] and
      '-98765' in flatpak_calls[-1],
      str(flatpak_calls[-1] if flatpak_calls else '-'))

# 3g) Flatpak sem pidfile, sem MPRIS → False (sem mentir pausado)
self, ns, chamadas, sinais = _montar(flatpak=True, mpris_vivos=(),
                                     pid_host=None, status_seq=(None, None))
ok = self._pausar_player()
check('Flatpak sem pidfile e sem MPRIS: devolve False', ok is False)

# 3h) Flatpak sem pidfile, mas MPRIS vivo E status muda → MPRIS com verificação
self, ns, chamadas, sinais = _montar(
    flatpak=True,
    mpris_vivos=('org.mpris.MediaPlayer2.smplayer',),
    pid_host=None, status_seq=('Playing', 'Paused'))
ok = self._pausar_player()
mpris_calls = [c for c in chamadas if any('PlayPause' in p for p in c)]
check('Flatpak sem pidfile: MPRIS verificado como fallback', ok is True and
      mpris_calls, str(mpris_calls[:1]))

# 3i) Flatpak sem pidfile, MPRIS vivo mas status NÃO muda → False (sem mentir)
self, ns, chamadas, sinais = _montar(
    flatpak=True,
    mpris_vivos=('org.mpris.MediaPlayer2.smplayer',),
    pid_host=None, status_seq=('Playing', 'Playing'))
ok = self._pausar_player()
check('Flatpak sem pidfile, MPRIS inócuo: devolve False (não mente)',
      ok is False)

# 3j) Nome exato morto, mas o player está com sufixo de instância
self, ns, chamadas, sinais = _montar(
    mpris_vivos=(),
    list_names_sufixo='org.mpris.MediaPlayer2.smplayer_1',
    status_seq=('Playing', 'Paused'))
ok = self._pausar_player()
check('MPRIS com sufixo: acha o nome e pausa', ok is True and
      any('PlayPause' in ' '.join(c) and
          'org.mpris.MediaPlayer2.smplayer_1' in ' '.join(c)
          for c in chamadas), str(chamadas[:2]))

# 3k) Shim do Flatpak: kill de saída direto (util-linux), CONT antes do TERM.
#     Wrapper de sh falharia: o dash do host rejeita pid negativo, e processo
#     parado (pause por SIGSTOP) ignora SIGTERM para sempre.
for _caminho_shim in ('flatpak/smplayer-host', 'flatpak/flathub/smplayer-host'):
    _shim = open(os.path.join(RAIZ, _caminho_shim), encoding='utf-8').read()
    _cont = _shim.find('flatpak-spawn --host kill -CONT')
    _term = _shim.find('flatpak-spawn --host kill -TERM')
    check(f'{_caminho_shim}: kill direto CONT antes do TERM',
          _cont != -1 and _term != -1 and _cont < _term,
          f'cont={_cont} term={_term}')
    check(f'{_caminho_shim}: sem wrapper de sh no kill',
          "/bin/sh -c" not in _shim.split('_kill_host_player')[1].split('trap')[0],
          _shim.split('_kill_host_player')[1][:200])

# 3l) sincronizar_tempo_dbus não pode perguntar ao player congelado (SIGSTOP
#     pausa o MPRIS e cada sync seguraria a interface ~2 s no timeout).
check('sincronizar_tempo_dbus pula quando pausado no Linux',
      'if self.is_paused and _eh_linux():' in src)

# 3m) _matar_processo acorda o grupo (CONT) antes do TERM — senão stop após
#     pause deixa o player do AppImage congelado para sempre.
_matar_no = [n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == '_matar_processo'][0]
_matar = ast.get_source_segment(src, _matar_no) or ''
check('_matar_processo manda CONT antes do TERM',
      'signal.SIGCONT' in _matar and
      _matar.find('signal.SIGCONT') < _matar.find('signal.SIGTERM'))

player_mod.subprocess.run = _orig_run

print('\n' + ('TODOS OS CASOS PASSARAM' if not falhas else f'FALHAS: {falhas}'))
sys.exit(1 if falhas else 0)
