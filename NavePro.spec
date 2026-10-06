# -*- mode: python ; coding: utf-8 -*-
# NavePro.spec — configuração do PyInstaller, usada pelo Windows (NavePro.exe)
# e pelo Linux (AppImage) — a mesma configuração nos dois alvos.
#
# POR QUE ESTE SPEC EXISTE
# O --add-data da linha de comando usa o os.pathsep como separador, que é ":"
# no Linux e ";" no Windows. Com ":" no Windows o PyInstaller interpreta
# "img/Icon.ico:img" como um nome de arquivo inteiro e o recurso não chega ao
# pacote. As tuplas em `datas` não têm esse problema — por isso o
# empacotamento (Windows e Linux) é por aqui.
#
# Uso:
#   Windows:  build-windows.bat          (gera dist\NavePro.exe)
#   Linux:    ./build.sh <versão>         (gera NavePro-<versão>.AppImage)
#
# Ícone do executável: defina NAVEPRO_ICON=img/Icon.ico antes de rodar (o
# build-windows.bat já faz isso). Sem essa variável o .exe sai sem ícone
# próprio — o ícone das janelas continua funcionando, porque vem de
# _aplicar_icone_janela lendo img/Icon.ico.
#
# Janela de console: defina NAVEPRO_CONSOLE=1 para manter o terminal visível.
# O padrão é sem console. O terminal é útil para ver o log de detecção de
# monitores ("✅ screeninfo: 2 monitor(es)..."), então vale um build de
# diagnóstico com a variável ligada.

# config.json e midia.db NÃO são embutidos, de propósito.
#
# Os dois estão no .gitignore: são arquivos de trabalho de quem compila. O
# inicial_banco()/inicializar_config() do NavePro.py tratam os dois como
# OPCIONAIS — sem eles no pacote, o app cria o banco (init_db monta o schema) e
# fica com os padrões de navepro/config.py.
#
# Embutir o config.json da máquina de build era pior do que não embutir nada:
# ele gravava "player": "smplayer", que sobrescreve o PLAYER_PADRAO ("mpv" no
# Windows). Toda instalação nova nascia no player que não aceita pausar, e o
# operador ganhava o aviso "pausar/continuar não funciona" no primeiro uso.
import os

# `console` e `icon` são resolvidos aqui para permitir vars por ambiente
# sem duplicar o spec.
_CONSOLE = os.environ.get("NAVEPRO_CONSOLE", "0") == "1"
_icone = os.environ.get("NAVEPRO_ICON", "")

# `icon` só pode ser passado se a variável estiver definida: passar icon=""
# faz o PyInstaller procurar um arquivo de nome vazio e falhar.
_EXE_EXTRA = {"icon": _icone} if _icone else {}

# Só os ícones entram: são a única coisa que o app abre por nome dentro do
# pacote (_caminho_recurso em navepro/core/paths.py). icones/, NHA/ e HASD/
# NÃO são necessários — o app nunca os abre por nome, o usuário é quem escolhe
# o que importar (o seletor sempre começa em ~, não na pasta do app).
_DATAS = [
    ("img/Icon.ico", "img"),
    ("img/Icon.png", "img"),
    ("img/Icon.xbm", "img"),
]

# screeninfo é o método primário de detecção de monitores (e no Windows é o
# que ativa o DPI-awareness); sem ele o app cai na heurística do Tk. pypdf é a
# extração de anúncios em PDF. Sem _tkinter_finder o Pillow não acha o Tk.
_HIDDEN = [
    "PIL._tkinter_finder",
    "PIL.ImageTk",
    "PIL.ImageFont",
    "screeninfo",
    "pypdf",
]

a = Analysis(
    ['NavePro.py'],
    pathex=[],
    binaries=[],
    datas=_DATAS,
    hiddenimports=_HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NavePro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX em .exe gera falso positivo de antivírus com frequência e a
    # compressão não ajuda um app de ~50 MB. Desligado.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=_CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    **_EXE_EXTRA
)
