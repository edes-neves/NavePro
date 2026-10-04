"""Verificação de atualização automática e download do instalador."""

import json
import os
import re
import urllib.request
from typing import Optional

from navepro.config import APP_ID_FLATPAK, APP_VERSION, RELEASES_API_URL
from navepro.core.ambiente import _eh_appimage, _eh_flatpak, _eh_windows
from navepro.core.ssl_context import _baixar

# Formatos em que o NavePro pode estar instalado. O formato decide tanto o
# asset do release a baixar quanto o texto das instruções: um Flatpak NÃO
# se atualiza trocando um arquivo em ~/Downloads.
FORMATO_FLATPAK = "flatpak"
FORMATO_APPIMAGE = "appimage"
FORMATO_WINDOWS = "windows"


def _formato_instalado() -> str:
    """Detecta como ESTA cópia do NavePro foi instalada.

    Flatpak > Windows > AppImage. Um Flatpak é detectado primeiro porque
    também é Linux: sem essa ordem, quem roda dentro do Flatpak cairia no
    caso "AppImage" e receberia um arquivo que não pode usar.
    """
    if _eh_flatpak():
        return FORMATO_FLATPAK
    if _eh_windows():
        return FORMATO_WINDOWS
    if _eh_appimage():
        return FORMATO_APPIMAGE
    # Linux avulso (ex.: python NavePro.py): o AppImage é o pacote
    # distribuível mais próximo do que o usuário tem.
    return FORMATO_APPIMAGE


def _rotulo_instalador(formato: str = "") -> str:
    """Nome do pacote a baixar/mostrar, para as mensagens da interface."""
    formato = formato or _formato_instalado()
    if formato == FORMATO_WINDOWS:
        return ".exe"
    if formato == FORMATO_FLATPAK:
        return "Flatpak"
    return ".AppImage"


def _app_id_flatpak() -> str:
    """ID do Flatpak em execução (FLATPAK_ID) ou o canônico do projeto."""
    import os
    return os.environ.get('FLATPAK_ID') or APP_ID_FLATPAK


def _comando_atualizacao_flatpak() -> list:
    """Comando que atualiza o app instalado como Flatpak.

    O binário `flatpak` não existe dentro do sandbox, então usa-se
    `flatpak-spawn --host`, que executa no host. O manifesto do Flatpak já
    concede `--talk-name=org.freedesktop.Flatpak`, então isso é permitido
    sem privilégio; `--user` evita pedir senha de administrador.

    `--assumeyes` é obrigatório: sem ele o flatpak pergunta "Prosseguir
    com essas alterações? [Y/n]" e, como o app roda sem terminal, a
    resposta seria "n" — a atualização não aconteceria. Passa-se o ID do
    app para atualizar só o NavePro, não a sessão inteira.
    """
    return ['flatpak-spawn', '--host', 'flatpak', 'update', '--user',
            '--assumeyes', _app_id_flatpak()]


def _versao_tuple(versao: str) -> tuple:
    """Converte '1.8.0'/'v1.9.1' em tupla numérica para comparação."""
    partes: list[int] = []
    for p in re.split(r'\D+', versao):
        if p:
            try:
                partes.append(int(p))
            except ValueError:
                partes.append(0)
    return tuple(partes) or (0,)


def _versao_nova(remota: str, local: str = APP_VERSION) -> bool:
    """True se a versão remota (GitHub) for maior que a instalada."""
    return _versao_tuple(remota) > _versao_tuple(local)


def _buscar_release_latest(timeout: int = 10) -> Optional[dict]:
    """Consulta o release mais recente na API do GitHub (thread-safe).

    Retorna dict com 'tag_name', 'name', 'body' e 'assets' (lista de
    assets do release, cada um com 'name' e 'browser_download_url').
    """
    try:
        req = urllib.request.Request(
            RELEASES_API_URL, headers={
                "User-Agent": f"NavePro/{APP_VERSION}",
                "Accept": "application/vnd.github+json",
            }
        )
        with _baixar(req, timeout=timeout) as resp:
            dados = json.loads(resp.read().decode('utf-8'))
        if not isinstance(dados, dict) or not dados.get('tag_name'):
            return None
        return dados
    except Exception as e:
        print(f"⚠️  Verificação de atualização falhou: {e}")
        return None


def _procurar_asset_instalador(release: dict) -> Optional[dict]:
    """Encontra o instalador correspondente à plataforma atual.

    Windows procura o primeiro asset '.exe'; Linux, o primeiro '.AppImage'.
    Em Flatpak devolve None: a atualização é feita com `flatpak update`, sem
    baixar arquivo (ver _comando_atualizacao_flatpak).
    """
    formato = _formato_instalado()
    if formato == FORMATO_FLATPAK:
        return None
    sufixo = ".exe" if formato == FORMATO_WINDOWS else ".appimage"
    for asset in release.get('assets', []) or []:
        nome = str(asset.get('name', '')).lower()
        if nome.endswith(sufixo):
            return asset
    return None


def _pasta_downloads() -> str:
    """Retorna ~/Downloads (ou ~ como fallback) para salvar o instalador."""
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    if not os.path.isdir(downloads):
        downloads = os.path.expanduser("~")
    return downloads