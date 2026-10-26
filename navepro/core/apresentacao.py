"""NavePro - Abertura de apresentações e PDF no aplicativo do sistema.

As apresentações da Ordem de Serviço não tocam dentro do NavePro: são
entregues a um aplicativo externo (PowerPoint/Impress) em modo de
apresentação. Este módulo monta o comando de cada plataforma, isolado da
interface para poder ser testado sem Tk.

Dois detalhes de plataforma justificam o módulo:

1. **Flatpak** — o LibreOffice do host aparece em `/run/host/usr/bin`, mas
   esse caminho pode ser descoberto e NÃO pode ser executado direto no
   sandbox. O comando certo é `flatpak-spawn --host libreoffice --show ...`,
   pelo nome, no host.
2. **Windows** — abrir o `.pptx` pela associação chama o PowerPoint só para
   editar. O modo apresentação exige o switch `/s` no `POWERPNT.EXE`.
3. **Wayland** — o NavePro (Tk 8.6) roda via XWayland. Forçar o LibreOffice
   a usar X11 (`GDK_BACKEND=x11`) mantém a janela do slide show visível para
   o retorno automático de foco; em Wayland nativo não há API portátil para
   outra aplicação ativar a janela.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from navepro.core.player import localizar_executavel

# Extensões que o item de Ordem de Serviço entrega ao aplicativo externo.
EXTENSOES_APRESENTACAO = frozenset(
    {'.ppt', '.pptx', '.pps', '.ppsx', '.odp', '.pdf'})

# Extensões abertas pelo PowerPoint no Windows. `.pps`/`.ppsx` já são
# apresentações por associação; o `/s` mantém o mesmo comportamento.
EXTENSOES_POWERPOINT = frozenset({'.ppt', '.pptx', '.pps', '.ppsx'})

# O NavePro usa Tk 8.6/X11; manter o LibreOffice no XWayland permite que o
# `foco_apresentacao` encontre e ative a janela do slide show no Linux.
_GDK_X11 = 'GDK_BACKEND=x11'


def _comando_apresentacao(
    caminho: str,
    *,
    windows: bool,
    flatpak: bool,
    localizar: Callable[[str], str | None] = localizar_executavel,
) -> list[str]:
    """Monta o comando que abre `caminho` em modo de apresentação.

    `localizar` devolve o caminho de um executável ou None (injetável nos
    testes). O PDF continua no visualizador padrão do sistema, como antes.
    """
    ext = os.path.splitext(caminho or '')[1].lower()

    if windows:
        if ext in EXTENSOES_POWERPOINT:
            powerpnt = localizar('powerpnt')
            if powerpnt:
                return [powerpnt, '/s', caminho]
        return ['cmd', '/c', 'start', '', caminho]

    if ext == '.pdf':
        # O LibreOffice em modo apresentação não serve para PDF.
        return ['xdg-open', caminho]

    for nome in ('libreoffice', 'soffice'):
        executavel = localizar(nome)
        if executavel:
            if flatpak:
                # O binário do host não roda no sandbox: executa no host.
                return ['flatpak-spawn', '--host', f'--env={_GDK_X11}',
                        nome, '--show', caminho]
            return [executavel, '--show', caminho]

    if flatpak:
        # Sem LibreOffice no host: deixa a associação do host abrir o arquivo.
        return ['flatpak-spawn', '--host', f'--env={_GDK_X11}',
                'xdg-open', caminho]
    return ['xdg-open', caminho]


def _ambiente_apresentacao(
    base: dict[str, str] | None = None,
) -> dict[str, str]:
    """Ambiente para o aplicativo externo no Linux/Flatpak.

    Força o backend GTK para X11: além de casar com o Tk/XWayland do
    NavePro, é o que torna a janela do slide show localizável e focável.
    """
    ambiente = dict(base if base is not None else os.environ)
    ambiente['GDK_BACKEND'] = 'x11'
    return ambiente


def _monitorar_apresentacao(cmd: list[str]) -> bool:
    """True se o processo do comando termina junto com a apresentação.

    Só o LibreOffice/Impress é monitorável: `xdg-open`/`start` devolvem na
    hora, enquanto o aplicativo escolhido continua aberto em outro processo.
    Reconhece o caminho completo e o wrapper `flatpak-spawn --host`.
    """
    return any(os.path.basename(parte).lower() in ('libreoffice', 'soffice')
               for parte in cmd)
