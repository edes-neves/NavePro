#!/usr/bin/env python3
"""Abertura de apresentações/PDF (navepro/core/apresentacao.py).

Regressões cobertas:

1. **Flatpak** — o LibreOffice do host é descoberto em `/run/host/usr/bin`,
   mas NÃO pode ser executado direto no sandbox. Precisa ir por
   `flatpak-spawn --host libreoffice --show ...`; antes o NavePro chamava
   `libreoffice` pelo nome e o Popen falhava em silêncio.
2. **Windows** — abrir o .pptx pela associação inicia o PowerPoint no modo
   de edição. O comando agora usa `POWERPNT.EXE /s` para entrar direto no
   modo de apresentação (com o caminho achado no registro/pastas padrão).
3. **PDF e demais sistemas** — continuam exatamente como antes.
"""

import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

from navepro.core.apresentacao import (  # noqa: E402
    EXTENSOES_APRESENTACAO,
    EXTENSOES_POWERPOINT,
    _ambiente_apresentacao,
    _comando_apresentacao,
    _monitorar_apresentacao,
)
from navepro.core.player import _CANDIDATOS_WINDOWS  # noqa: E402

falhas = []


def check(nome, cond, extra=''):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


def localizador(mapa):
    return lambda nome: mapa.get(nome)


PPTX = '/home/igreja/apresentacao.pptx'
ODP = '/home/igreja/apresentacao.odp'
PDF = '/home/igreja/letra.pdf'
LO = '/usr/bin/libreoffice'
LO_HOST = '/run/host/usr/bin/libreoffice'
POWERPNT = r'C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE'

check('.pptx está entre as extensões de apresentação',
      '.pptx' in EXTENSOES_APRESENTACAO)
check('.pdf está entre as extensões de apresentação',
      '.pdf' in EXTENSOES_APRESENTACAO)
check('.odp é tratado como apresentação do PowerPoint? Não',
      '.odp' not in EXTENSOES_POWERPOINT)

_ambiente = _ambiente_apresentacao(
    {'PATH': '/usr/bin', 'GDK_BACKEND': 'wayland'})
check('Linux força o slide show no XWayland (GDK_BACKEND=x11)',
      _ambiente['GDK_BACKEND'] == 'x11', str(_ambiente))
check('ambiente de apresentação preserva as demais variáveis',
      _ambiente['PATH'] == '/usr/bin', str(_ambiente))

# ── Linux/AppImage: comportamento antigo preservado ───────────────────
cmd = _comando_apresentacao(
    ODP, windows=False, flatpak=False,
    localizar=localizador({'libreoffice': LO}))
check('Linux usa o caminho completo do LibreOffice',
      cmd == [LO, '--show', ODP], str(cmd))

cmd = _comando_apresentacao(
    PPTX, windows=False, flatpak=False,
    localizar=localizador({'soffice': '/usr/bin/soffice'}))
check('Linux cai no soffice quando não há libreoffice',
      cmd == ['/usr/bin/soffice', '--show', PPTX], str(cmd))

cmd = _comando_apresentacao(
    PPTX, windows=False, flatpak=False, localizar=localizador({}))
check('Linux sem LibreOffice usa xdg-open',
      cmd == ['xdg-open', PPTX], str(cmd))

cmd = _comando_apresentacao(
    PDF, windows=False, flatpak=False,
    localizar=localizador({'libreoffice': LO}))
check('PDF NÃO usa LibreOffice --show',
      cmd == ['xdg-open', PDF], str(cmd))

# ── Flatpak: executa no host, nunca o binário de /run/host no sandbox ──
cmd = _comando_apresentacao(
    PPTX, windows=False, flatpak=True,
    localizar=localizador({'libreoffice': LO_HOST}))
check('Flatpak abre o LibreOffice pelo host (flatpak-spawn --host)',
      cmd == ['flatpak-spawn', '--host', '--env=GDK_BACKEND=x11',
              'libreoffice', '--show', PPTX],
      str(cmd))
check('Flatpak NÃO executa o caminho /run/host dentro do sandbox',
      LO_HOST not in cmd, str(cmd))

cmd = _comando_apresentacao(
    ODP, windows=False, flatpak=True,
    localizar=localizador({'soffice': '/run/host/usr/bin/soffice'}))
check('Flatpak usa soffice no host quando é o encontrado',
      cmd == ['flatpak-spawn', '--host', '--env=GDK_BACKEND=x11',
              'soffice', '--show', ODP],
      str(cmd))

cmd = _comando_apresentacao(
    PPTX, windows=False, flatpak=True, localizar=localizador({}))
check('Flatpak sem LibreOffice usa a associação do host',
      cmd == ['flatpak-spawn', '--host', '--env=GDK_BACKEND=x11',
              'xdg-open', PPTX], str(cmd))

cmd = _comando_apresentacao(
    PDF, windows=False, flatpak=True,
    localizar=localizador({'libreoffice': LO_HOST}))
check('PDF no Flatpak continua no xdg-open do sandbox (como antes)',
      cmd == ['xdg-open', PDF], str(cmd))

# ── Windows: PowerPoint em modo de apresentação ───────────────────────
for ext in ('.ppt', '.pptx', '.pps', '.ppsx'):
    caminho = 'C:\\apresentacoes\\culto' + ext
    cmd = _comando_apresentacao(
        caminho, windows=True, flatpak=False,
        localizar=localizador({'powerpnt': POWERPNT}))
    check(f'{ext} no Windows abre com POWERPNT.EXE /s',
          cmd == [POWERPNT, '/s', caminho], str(cmd))

cmd = _comando_apresentacao(
    PPTX, windows=True, flatpak=False, localizar=localizador({}))
check('Windows sem PowerPoint mantém a associação (cmd /c start)',
      cmd == ['cmd', '/c', 'start', '', PPTX], str(cmd))

cmd = _comando_apresentacao(
    'C:\\apresentacoes\\letra.pdf', windows=True, flatpak=False,
    localizar=localizador({'powerpnt': POWERPNT}))
check('PDF no Windows NÃO recebe o switch /s',
      cmd == ['cmd', '/c', 'start', '', 'C:\\apresentacoes\\letra.pdf'],
      str(cmd))

# ── Monitoramento do fim da apresentação ──────────────────────────────
check('monitora LibreOffice chamado direto',
      _monitorar_apresentacao([LO, '--show', ODP]) is True)
check('monitora LibreOffice via flatpak-spawn',
      _monitorar_apresentacao(
          ['flatpak-spawn', '--host', 'soffice', '--show', ODP]) is True)
check('não monitora xdg-open (o processo devolve na hora)',
      _monitorar_apresentacao(['xdg-open', PPTX]) is False)
check('não monitora o PowerPoint no Windows',
      _monitorar_apresentacao([POWERPNT, '/s', PPTX]) is False)

# ── Integração e descoberta no Windows ────────────────────────────────
_src = open(os.path.join(RAIZ, 'NavePro.py'), encoding='utf-8').read()
check('NavePro.py usa o construtor de comando',
      '_comando_apresentacao(' in _src)
check('NavePro.py usa o monitoramento novo',
      '_monitorar_apresentacao(' in _src)
check('NavePro.py não chama mais o LibreOffice só pelo nome',
      "_cmd_apres = [_so, '--show'" not in _src)
check('POWERPNT.EXE está nos candidatos do Windows',
      any('POWERPNT.EXE' in c for c in _CANDIDATOS_WINDOWS.get('powerpnt', ())))

print('\n' + ('TODOS OS CASOS PASSARAM' if not falhas else f'FALHAS: {falhas}'))
sys.exit(1 if falhas else 0)
