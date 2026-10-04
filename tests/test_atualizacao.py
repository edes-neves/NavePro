import os, sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

import navepro.core.atualizacao as at
from navepro.core import ambiente as am

falhas = []
def check(n, cond, extra=''):
    print(f"{'OK ' if cond else 'FALHA'} {n}{(' -> '+extra) if extra else ''}")
    if not cond: falhas.append(n)

RELEASE = {'assets': [
    {'name': 'NavePro-2.1.0.AppImage', 'browser_download_url': 'u/appimage'},
    {'name': 'NavePro-x86_64.flatpak', 'browser_download_url': 'u/fp64'},
    {'name': 'NavePro-aarch64.flatpak', 'browser_download_url': 'u/fparm'},
    {'name': 'NavePro-2.1.0.exe', 'browser_download_url': 'u/exe'},
]}

class Cenario:
    """Simula um ambiente de execução (flatpak / appimage / windows)."""
    _nomes = ('_eh_windows', '_eh_flatpak', '_eh_appimage')

    def __init__(self, flatpak=False, appimage=False, windows=False):
        self.fp, self.am, self.win = flatpak, appimage, windows
        self._env = {k: os.environ.get(k) for k in ('FLATPAK_ID', 'APPIMAGE')}

    def __enter__(self):
        for k in self._env:
            os.environ.pop(k, None)
        if self.fp:
            os.environ['FLATPAK_ID'] = 'io.github.edesneves.NavePro'
        if self.am:
            os.environ['APPIMAGE'] = '/home/x/NavePro-2.1.0.AppImage'
        # at.* importa as funções de ambiente, então as duas cópias
        # precisam ser trocadas juntas.
        self._orig = {n: getattr(am, n) for n in self._nomes}
        self._orig_at = {n: getattr(at, n) for n in self._nomes}
        mapa = {'_eh_windows': self.win, '_eh_flatpak': self.fp,
                '_eh_appimage': self.am}
        for n in self._nomes:
            setattr(am, n, lambda v=mapa[n]: v)
            setattr(at, n, lambda v=mapa[n]: v)
        return self

    def __exit__(self, *a):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for n in self._nomes:
            setattr(am, n, self._orig[n])
            setattr(at, n, self._orig_at[n])

# ── 1) detecção por variável de ambiente ──
with Cenario(flatpak=True):
    check('FLATPAK_ID define flatpak', am._eh_flatpak())
with Cenario(appimage=True):
    check('APPIMAGE define appimage', am._eh_appimage())
with Cenario():
    check('sem nada, não é flatpak nem appimage',
          not am._eh_flatpak() and not am._eh_appimage())

# /.flatpak-info como segundo sinal
_orig_exists = os.path.exists
def existe_fake(p): return p == '/.flatpak-info'
os.path.exists = existe_fake
try:
    check('/.flatpak-info também define flatpak (sem FLATPAK_ID)', am._eh_flatpak())
finally:
    os.path.exists = _orig_exists

# ── 2) formato instalado ──
with Cenario(flatpak=True):
    check('formato: flatpak', at._formato_instalado() == 'flatpak')
with Cenario(appimage=True):
    check('formato: appimage', at._formato_instalado() == 'appimage')
with Cenario(windows=True):
    check('formato: windows', at._formato_instalado() == 'windows')
with Cenario(flatpak=True, windows=True):
    check('flatpak ganha do windows (ordem de precedência)',
          at._formato_instalado() == 'flatpak')

# ── 3) o bug original: flatpak NÃO pode receber AppImage ──
with Cenario(flatpak=True):
    a = at._procurar_asset_instalador(RELEASE)
    check('flatpak: nenhum asset para baixar', a is None, str(a))
with Cenario(appimage=True):
    a = at._procurar_asset_instalador(RELEASE)
    check('appimage: pega o .AppImage', a and a['name'].endswith('.AppImage'),
          a['name'] if a else 'None')
with Cenario(windows=True):
    a = at._procurar_asset_instalador(RELEASE)
    check('windows: pega o .exe', a and a['name'].endswith('.exe'),
          a['name'] if a else 'None')
with Cenario(appimage=True):
    a = at._procurar_asset_instalador({})
    check('release sem assets: None', a is None)
    a = at._procurar_asset_instalador({'assets': [{'name': 'x.flatpak'}]})
    check('appimage ignora .flatpak', a is None, str(a))

# ── 4) rótulos para a interface ──
with Cenario(flatpak=True):
    check('rótulo flatpak', at._rotulo_instalador() == 'Flatpak')
with Cenario(windows=True):
    check('rótulo windows', at._rotulo_instalador() == '.exe')
with Cenario(appimage=True):
    check('rótulo appimage', at._rotulo_instalador() == '.AppImage')

# ── 5) comando do flatpak ──
with Cenario(flatpak=True):
    cmd = at._comando_atualizacao_flatpak()
    check('usa flatpak-spawn --host', cmd[:3] == ['flatpak-spawn', '--host', 'flatpak'], str(cmd))
    check('atualiza só o usuário (sem pedir senha)', cmd[3:5] == ['update', '--user'], str(cmd))
    check('--assumeyes presente (senão o prompt responderia "n")',
          '--assumeyes' in cmd, str(cmd))
    check('aponta para o app em execução',
          cmd[-1] == 'io.github.edesneves.NavePro', str(cmd))
with Cenario():
    cmd = at._comando_atualizacao_flatpak()
    check('sem FLATPAK_ID cai no ID canônico',
          cmd[-1] == 'io.github.edesneves.NavePro', str(cmd))

print('\n' + ('TODOS OS CASOS PASSARAM' if not falhas else f'FALHAS: {falhas}'))
sys.exit(1 if falhas else 0)
