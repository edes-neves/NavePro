"""Verificação de atualização automática e download do instalador."""

import json
import os
import re
import urllib.request

from navepro.config import APP_ID_FLATPAK, APP_VERSION, RELEASES_API_URL
from navepro.core.ambiente import _eh_appimage, _eh_flatpak, _eh_windows
from navepro.core.log import get_logger
from navepro.core.ssl_context import _baixar

log = get_logger("atualizacao")

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


def _buscar_release_latest(timeout: int = 10) -> dict | None:
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
        log.warning(f"⚠️  Verificação de atualização falhou: {e}")
        return None


def _procurar_asset_instalador(release: dict) -> dict | None:
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


def _nome_arquivo_seguro(nome: str | None) -> str:
    """Basename do nome de asset do release (recusa .. e caminho absoluto).

    O nome vem do JSON da API: sem isto, um nome como "../../evil" ou
    "..\\..\\evil" escaparia de ~/Downloads na hora de salvar o instalador.
    """
    nome = (nome or '').replace('\\', '/')
    nome = os.path.basename(nome)
    return '' if nome in ('.', '..') else nome


def _url_asset_valida(url: str | None) -> bool:
    """True se a URL do asset é HTTPS (recusa downgrade de esquema)."""
    return bool(url) and str(url).lower().startswith('https://')


def _procurar_checksum_sha256(
        release: dict | None, nome_asset: str) -> str | None:
    """URL do .sha256 publicado ao lado do asset (None se o release não tiver).

    Opcional e retroativo: releases antigos sem .sha256 continuam baixando
    como antes; releases que publicarem o arquivo passam a ser verificados.
    """
    for asset in (release or {}).get('assets', []) or []:
        if str(asset.get('name', '')) == f"{nome_asset}.sha256":
            url = str(asset.get('browser_download_url', ''))
            return url if _url_asset_valida(url) else None
    return None


def _ler_checksum_sha256(url: str) -> str | None:
    """Baixa o .sha256 do release e devolve o hex (None se inválido/falhar)."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": f"NavePro/{APP_VERSION}"})
        with _baixar(req, timeout=15) as resp:
            texto = resp.read(2048).decode('utf-8', errors='replace')
        encontrado = re.search(r'([0-9a-fA-F]{64})', texto)
        return encontrado.group(1).lower() if encontrado else None
    except Exception as e:
        log.warning(f"⚠️ Não foi possível obter o checksum do release: {e}")
        return None


def _sha256_do_arquivo(caminho: str) -> str:
    """SHA-256 de um arquivo, em hex minúsculo (lido em blocos)."""
    import hashlib
    digesto = hashlib.sha256()
    with open(caminho, 'rb') as f:
        while True:
            bloco = f.read(1024 * 1024)
            if not bloco:
                break
            digesto.update(bloco)
    return digesto.hexdigest()


def _pasta_downloads() -> str:
    """Retorna ~/Downloads (ou ~ como fallback) para salvar o instalador."""
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    if not os.path.isdir(downloads):
        downloads = os.path.expanduser("~")
    return downloads