#!/usr/bin/env python3
"""Fade de áudio no Play/Pausar/Parar (navepro/core/mediaplayer.py).

O fade é "best-effort": só age onde já controlamos o player (IPC do mpv no
Windows, D-Bus/MPRIS no Linux fora do Flatpak); sem isso, o comportamento
antigo (pausar/parar na hora) precisa continuar idêntico. Esta suíte trava:

  - o formato do Volume no MPRIS (`Properties.Set` com `variant:double:`);
  - o volume do mpv por IPC (`set_property volume` 0-100);
  - `_canal_volume` usa o host no Flatpak (mpris-host) e MPRIS direto fora;
  - o fade desce/some até o alvo e só então roda o `depois` (pausar/parar);
  - um fade novo cancela o anterior (só o mais recente age);
  - retomar toca do 0 e sobe; pausar desce e devolve o volume (o smplayer
    grava o volume ao sair — não pode ficar salvo mudo);
  - `parar_agora` (encerramento) cancela o fade e para na hora.
"""

import ast
import os
import sys
import types

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

import navepro.core.player as player_mod  # noqa: E402
from navepro.core import mediaplayer as mp  # noqa: E402

falhas = []


def check(nome, cond, extra=''):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


# ── Extração dos métodos reais do MediaPlayer (sem instanciar Tk) ──────
_SRC = open(os.path.join(RAIZ, "navepro", "core", "mediaplayer.py"),
            encoding="utf-8").read()


def _extrair(*nomes):
    """Devolve um namespace com os métodos pedidos do MediaPlayer."""
    ns = dict(vars(mp))
    for node in ast.walk(ast.parse(_SRC)):
        if isinstance(node, ast.ClassDef) and node.name == "MediaPlayer":
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name in nomes:
                    mod = ast.Module(body=[sub], type_ignores=[])
                    ast.fix_missing_locations(mod)
                    exec(compile(mod, f"<{sub.name}>", "exec"), ns)
    return ns


def _ligar(obj, ns, *nomes):
    for nome in nomes:
        setattr(obj, nome, types.MethodType(ns[nome], obj))
    return obj


class _Resp:
    def __init__(self, code=0, out=''):
        self.returncode = code
        self.stdout = out


# ── 1) MPRIS: leitura e escrita de Volume (navepro/core/player.py) ─────
_orig_run = player_mod.subprocess.run
try:
    chamadas = []

    def _fake_run(cmd, **kw):
        chamadas.append(cmd)
        if 'Properties.Get' in ' '.join(cmd):
            return _Resp(0, '   variant       double 0.42\n')
        return _Resp(0, '')

    player_mod.subprocess.run = _fake_run
    v = player_mod.mpris_obter_volume('org.mpris.MediaPlayer2.smplayer')
    check('mpris_obter_volume lê o double (0.42)', v == 0.42, str(v))
    ok = player_mod.mpris_definir_volume(
        'org.mpris.MediaPlayer2.smplayer', 0.30)
    check('mpris_definir_volume devolve True no sucesso', ok is True)
    set_cmd = next(c for c in chamadas if 'Properties.Set' in ' '.join(c))
    check('MPRIS Set é method_call no barramento da sessão',
          '--type=method_call' in set_cmd and '--session' in set_cmd)
    check('MPRIS Set usa Properties.Set da org.freedesktop.DBus',
          'org.freedesktop.DBus.Properties.Set' in set_cmd)
    check('MPRIS Set passa o Volume como variant:double (0.300)',
          'variant:double:0.300' in set_cmd
          and 'string:org.mpris.MediaPlayer2.Player' in set_cmd
          and 'string:Volume' in set_cmd, str(set_cmd))
    player_mod.mpris_definir_volume('org.mpris.MediaPlayer2.smplayer', 2.5)
    check('MPRIS Set clampa acima de 1.0',
          'variant:double:1.000' in chamadas[-1][-1], str(chamadas[-1]))
finally:
    player_mod.subprocess.run = _orig_run

# No Flatpak o volume vai pelo HOST: flatpak-spawn --host + barramento do host.
try:
    chamadas = []
    player_mod.subprocess.run = lambda cmd, **kw: (chamadas.append(cmd), _Resp(0, ''))[1]
    player_mod.mpris_definir_volume(
        'org.mpris.MediaPlayer2.smplayer', 0.5, host=True)
    cmd_host = chamadas[-1]
    check('MPRIS no host usa flatpak-spawn --host',
          cmd_host[0] == 'flatpak-spawn' and '--host' in cmd_host, str(cmd_host[:3]))
    check('MPRIS no host aponta o barramento da sessão do host',
          any(a.startswith('--env=DBUS_SESSION_BUS_ADDRESS=') for a in cmd_host))
    check('MPRIS no host mantém o Set de Volume',
          'org.freedesktop.DBus.Properties.Set' in cmd_host
          and 'variant:double:0.500' in cmd_host)
finally:
    player_mod.subprocess.run = _orig_run

# mpris_obter_volume: resposta sem double / erro → None
try:
    player_mod.subprocess.run = lambda cmd, **kw: _Resp(
        0, '   variant       string "x"\n')
    check('mpris_obter_volume sem double devolve None',
          player_mod.mpris_obter_volume('d') is None)
    player_mod.subprocess.run = lambda cmd, **kw: _Resp(1, '')
    check('mpris_definir_volume devolve False no erro',
          player_mod.mpris_definir_volume('d', 0.5) is False)
finally:
    player_mod.subprocess.run = _orig_run

# ── 2) Volume por IPC do mpv (Windows) ─────────────────────────────────
ns = _extrair('_ler_volume', '_escrever_volume')


class _IpcFake:
    def __init__(self, lido=50):
        self.lido = lido
        self.cmds = []

    def propriedade(self, nome, timeout=2.0):
        self.cmds.append(('get', nome, timeout))
        return self.lido

    def comandar(self, cmd, timeout=3.0):
        self.cmds.append(('set', list(cmd), timeout))
        return True, None


obj = types.SimpleNamespace(_ipc=_IpcFake(lido=50))
_ligar(obj, ns, '_ler_volume', '_escrever_volume')
check('mpv: _ler_volume converte 50 -> 0.5', obj._ler_volume(("mpv", None)) == 0.5)
obj._escrever_volume(("mpv", None), 0.5)
check('mpv: _escrever_volume manda set_property volume 50',
      obj._ipc.cmds[-1] == ('set', ["set_property", "volume", 50], 0.6),
      str(obj._ipc.cmds[-1]))
obj._escrever_volume(("mpv", None), 0.0)
check('mpv: volume 0 vira 0 (não "0.0")',
      obj._ipc.cmds[-1][1] == ["set_property", "volume", 0],
      str(obj._ipc.cmds[-1]))

# ── 2b) canal "mpris-host" (Flatpak): lê/escreve pelo host ─────────────
ns_host = _extrair('_ler_volume', '_escrever_volume')
chamadas_host = []


def _obter_host(dest, timeout=1.0, host=False):
    chamadas_host.append(('get', dest, host))
    return 0.5


def _definir_host(dest, valor, timeout=1.0, host=False):
    chamadas_host.append(('set', dest, host, round(valor, 3)))
    return True


ns_host['mpris_obter_volume'] = _obter_host
ns_host['mpris_definir_volume'] = _definir_host
obj_host = types.SimpleNamespace()
_ligar(obj_host, ns_host, '_ler_volume', '_escrever_volume')
check('mpris-host: _ler_volume lê pelo host',
      obj_host._ler_volume(("mpris-host", 'd')) == 0.5
      and chamadas_host[-1] == ('get', 'd', True), str(chamadas_host[-1]))
obj_host._escrever_volume(("mpris-host", 'd'), 0.5)
check('mpris-host: _escrever_volume escreve pelo host',
      chamadas_host[-1] == ('set', 'd', True, 0.5), str(chamadas_host[-1]))

# ── 3) _canal_volume: onde já controlamos (Flatpak vai pelo host) ──────
ns_canal = _extrair('_canal_volume', '_candidatos_mpris')


def _canal(win=False, linux=False, flatpak=False, ipc=False, mpris_dest=None):
    o = types.SimpleNamespace(
        _player_em_uso='smplayer', player_cmd='smplayer',
        _ipc_mpv_disponivel=lambda: ipc)
    _ligar(o, ns_canal, '_canal_volume', '_candidatos_mpris')
    ns_canal['_eh_windows'] = lambda: win
    ns_canal['_eh_linux'] = lambda: linux
    ns_canal['_eh_flatpak'] = lambda: flatpak
    ns_canal['mpris_ativo'] = lambda candidatos, timeout=1.0: mpris_dest
    return o._canal_volume()


check('canal: Linux não-Flatpak com MPRIS vivo',
      _canal(linux=True, mpris_dest='org.mpris.MediaPlayer2.smplayer')
      == ("mpris", 'org.mpris.MediaPlayer2.smplayer'))
check('canal: Linux sem MPRIS → None', _canal(linux=True) is None)
check('canal: Flatpak com MPRIS vivo → canal do host ("mpris-host")', _canal(
    linux=True, flatpak=True, mpris_dest='org.mpris.MediaPlayer2.smplayer')
    == ("mpris-host", 'org.mpris.MediaPlayer2.smplayer'))
check('canal: Flatpak sem MPRIS → None', _canal(linux=True, flatpak=True) is None)
check('canal: Windows com IPC → ("mpv", None)',
      _canal(win=True, ipc=True) == ("mpv", None))
check('canal: Windows sem IPC → None', _canal(win=True, ipc=False) is None)


# ── 4) _fade_audio: rampa, termina no alvo e chama depois ──────────────
class _FakeRoot:
    def __init__(self):
        self.pendentes = []
        self._prox = 0

    def after(self, ms, func):
        self._prox += 1
        self.pendentes.append([ms, func, self._prox])
        return self._prox

    def after_cancel(self, tid):
        self.pendentes = [p for p in self.pendentes if p[2] != tid]


def _rodar(root, limite=5000):
    n = 0
    while root.pendentes and n < limite:
        _, func, _ = root.pendentes.pop(0)
        func()
        n += 1
    if n >= limite:
        raise AssertionError("fade não terminou (loop de agenda)")


ns_fade = _extrair('_fade_audio', '_cancelar_fade',
                   '_agendar_ui', '_cancelar_agendamento')


def _fade_obj(valor_inicial, canal=("mpris", 'd')):
    writes = []
    root = _FakeRoot()
    o = types.SimpleNamespace(
        _root_after=root, _fade_geracao=0, _fade_timer=None,
        _canal_volume=lambda: canal,
        _ler_volume=lambda c, v=valor_inicial: v,
        _escrever_volume=lambda c, x: (writes.append(x), True)[1])
    _ligar(o, ns_fade, '_fade_audio', '_cancelar_fade',
           '_agendar_ui', '_cancelar_agendamento')
    return o, writes, root


o, writes, root = _fade_obj(0.8)
fim = []
o._fade_audio(0.0, depois=lambda: fim.append(True), inicio=0.8)
check('fade: agenda sem rodar na hora (não bloqueia)', len(writes) == 0)
_rodar(root)
check('fade: número de passos == _FADE_AUDIO_PASSOS',
      len(writes) == mp._FADE_AUDIO_PASSOS, str(len(writes)))
check('fade: começa alto e desce até 0',
      writes[0] < 0.8 and abs(writes[-1]) < 1e-9, str((writes[0], writes[-1])))
check('fade: desce de forma monótona (sem subir)',
      all(writes[i] >= writes[i + 1] for i in range(len(writes) - 1)))
check('fade: chama depois uma única vez ao terminar', fim == [True])

# Sem canal de volume: chama depois na hora, sem agendar nada.
o, writes, root = _fade_obj(0.8, canal=None)
fim = []
o._fade_audio(0.0, depois=lambda: fim.append(True))
check('fade sem canal: não agenda nada', root.pendentes == [] and writes == [])
check('fade sem canal: executa o depois na hora (comportamento antigo)',
      fim == [True])

# Um fade novo cancela o anterior (só o mais recente age).
o, writes, root = _fade_obj(0.8)
o._fade_audio(0.0, inicio=0.8)     # fade A (para 0)
o._fade_audio(0.4, inicio=0.8)     # fade B (sobe para 0.4) cancela A
_rodar(root)
check('fade: o mais recente cancela o anterior',
      len(writes) == mp._FADE_AUDIO_PASSOS and abs(writes[-1] - 0.4) < 1e-9,
      str((len(writes), writes[-1] if writes else None)))

# Se o player some (3 falhas seguidas), não insiste e chama depois.
falhas_encadeadas = []


def _escrever_falho(c, x):
    return False


o, _, root = _fade_obj(0.8)
o._escrever_volume = _escrever_falho
o._fade_audio(0.0, depois=lambda: falhas_encadeadas.append(True), inicio=0.8)
_rodar(root)
check('fade: desiste após 3 falhas e roda o depois',
      falhas_encadeadas == [True] and root.pendentes == [])

# ── 5) _iniciar_fade_entrada: começa do 0 e sobe até o alvo ────────────
ns_ent = _extrair('_fade_audio', '_cancelar_fade', '_agendar_ui',
                  '_cancelar_agendamento', '_iniciar_fade_entrada')
root = _FakeRoot()
writes = []
o = types.SimpleNamespace(
    _root_after=root, _fade_geracao=0, _fade_timer=None,
    is_playing=True, is_paused=False, _volume_alvo=0.7,
    _canal_volume=lambda: ("mpris", 'd'),
    _ler_volume=lambda c: 0.0,   # volume salvo ficou em 0 → usa o alvo guardado
    _escrever_volume=lambda c, x: (writes.append(x), True)[1])
_ligar(o, ns_ent, '_fade_audio', '_cancelar_fade', '_agendar_ui',
       '_cancelar_agendamento', '_iniciar_fade_entrada')
o._iniciar_fade_entrada()
_rodar(root)
check('fade-in: zera antes de subir (o 0.0 aparece)',
      writes and abs(writes[0]) < 1e-9, str(writes[:2]))
check('fade-in: termina no alvo guardado (_volume_alvo)',
      writes and abs(writes[-1] - 0.7) < 1e-9, str(writes[-1] if writes else None))

# Se desistir (o barramento ainda não tem o player): tenta de novo algumas
# vezes e para — sem exceção e sem travar o play.
root = _FakeRoot()
tentativas_canal = []
o = types.SimpleNamespace(
    _root_after=root, _fade_geracao=0, _fade_timer=None,
    is_playing=True, is_paused=False, _volume_alvo=0.7,
    _canal_volume=lambda: (tentativas_canal.append(1), None)[1])
_ligar(o, ns_ent, '_fade_audio', '_cancelar_fade', '_agendar_ui',
       '_cancelar_agendamento', '_iniciar_fade_entrada')
o._iniciar_fade_entrada()
_rodar(root)
check('fade-in sem canal: tenta e desiste sozinho (sem travar o play)',
      len(tentativas_canal) == mp._FADE_ENTRADA_TENTATIVAS + 1
      and root.pendentes == [], str(len(tentativas_canal)))

# ── 6) play_pause: retomar zera e sobe; pausar desce e devolve ─────────
ns_pp = _extrair('play_pause')


def _pp_obj(playing, paused, volume=None, alvo=0.7):
    escritas = []
    fades = []
    obj = types.SimpleNamespace(
        is_playing=playing, is_paused=paused, playlist=[], index=0,
        tempo_inicio=None, tempo_acumulado=0.0, duracao_total=None,
        _volume_alvo=alvo, _fade_timer=None,
        _canal_volume=lambda: ("mpris", 'd'),
        obter_volume=lambda: volume,
        _escrever_volume=lambda c, v: (escritas.append(v), True)[1],
        definir_volume=lambda v: (escritas.append(v), True)[1],
        _pausar_player=lambda: True,
        _fade_audio=lambda alvo_, depois=None, inicio=None, canal=None, duracao=None: (
            fades.append({"alvo": alvo_, "depois": depois, "inicio": inicio})),
        _avisar_sem_controle_se_precisar=lambda: escritas.append('aviso'),
        _tocar_arquivo=lambda a: True,
    )
    _ligar(obj, ns_pp, 'play_pause')
    return obj, escritas, fades


# Tocando → pausar: desce a 0 (início = volume atual), depois pausa e devolve.
o, escritas, fades = _pp_obj(playing=True, paused=False, volume=0.8)
o.play_pause()
check('pausar: inicia o fade a partir do volume atual',
      fades and fades[0]['alvo'] == 0.0 and fades[0]['inicio'] == 0.8, str(fades))
fades[0]['depois']()  # simula o fim do fade
check('pausar: pausa só depois do fade', o.is_paused is True)
check('pausar: devolve o volume (não deixa salvo mudo)',
      escritas and abs(escritas[-1] - 0.8) < 1e-9, str(escritas))

# Pausado → retomar: zera o volume, toca e sobe até o alvo guardado.
o, escritas, fades = _pp_obj(playing=False, paused=True, alvo=0.7)
o.play_pause()
check('retomar: zera o volume antes de tocar', escritas and escritas[0] == 0.0,
      str(escritas))
check('retomar: toca e sobe do 0 até o alvo',
      o.is_playing is True and fades and fades[0]['alvo'] == 0.7
      and fades[0]['inicio'] == 0.0, str(fades))

# Sem controle de volume (obter_volume None): pausa na hora (comportamento antigo).
o, escritas, fades = _pp_obj(playing=True, paused=False, volume=None)
o.play_pause()
check('pausar sem volume: pausa na hora, sem fade',
      o.is_paused is True and fades == [], str(fades))

# ── 7) stop: fade-out e só então _parar_agora; parar_agora é imediato ──
ns_stop = _extrair('stop', 'parar_agora')
o = types.SimpleNamespace(
    is_playing=True, is_paused=False, tempo_inicio=1.0, tempo_acumulado=2.0,
    duracao_total=9.0, _volume_alvo=None,
    _canal_volume=lambda: ("mpris", 'd'),
    _ler_volume=lambda c: 0.6,
    _parar_agora=lambda: setattr(o, 'parou', True))
o.parou = False
fades = []
o._fade_audio = lambda alvo_, depois=None, inicio=None, canal=None, duracao=None: (
    fades.append({"alvo": alvo_, "depois": depois}))
_ligar(o, ns_stop, 'stop', 'parar_agora')
o.stop()
check('parar: marca parado já e inicia o fade até 0',
      o.is_playing is False and fades and fades[0]['alvo'] == 0.0, str(fades))
check('parar: guarda o alvo (volume de antes) para restaurar depois',
      abs((o._volume_alvo or 0) - 0.6) < 1e-9, str(o._volume_alvo))
fades[0]['depois']()
check('parar: só encerra o processo depois do fade', o.parou is True)

# parar_agora: cancela o fade e para na hora (encerramento do app).
o2 = types.SimpleNamespace()
ordem = []
o2._cancelar_fade = lambda: ordem.append('cancelar')
o2._parar_agora = lambda: ordem.append('parar')
_ligar(o2, ns_stop, 'parar_agora')
o2.parar_agora()
check('parar_agora: cancela o fade ANTES de parar',
      ordem == ['cancelar', 'parar'], str(ordem))

# ── 8) Invariantes estruturais ─────────────────────────────────────────
fonte_nv = open(os.path.join(RAIZ, 'NavePro.py'), encoding='utf-8').read()
check('_canal_volume trata o Flatpak (usa _eh_flatpak)',
      '_eh_flatpak' in _extrair('_canal_volume')['_canal_volume'].__code__.co_names)
seg_canal = _SRC.split('def _canal_volume')[1][:1200]
check('_canal_volume: Flatpak usa o canal do host (mpris-host)',
      'mpris-host' in seg_canal and '_eh_flatpak' in seg_canal
      and 'mpris_ativo' in seg_canal)
seg_stop = _SRC.split('def stop')[1][:1200]
check('stop: faz fade antes de _parar_agora',
      '_fade_audio' in seg_stop and '_parar_agora' in seg_stop)
seg_pp = _SRC.split('def play_pause')[1][:1200]
check('play_pause avisa quando o pause não surte efeito',
      '_avisar_sem_controle_se_precisar()' in seg_pp)
check('NavePro.fechar para o player sem fade (parar_agora)',
      'parar_agora' in fonte_nv.split('def fechar')[1][:900])

print('\n' + ('TODOS OS CASOS PASSARAM' if not falhas else f'FALHAS: {falhas}'))
sys.exit(1 if falhas else 0)
