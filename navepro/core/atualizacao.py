"""Verificação de atualização automática e download do instalador."""

import json
import os
import re
import urllib.request
from typing import Optional

from navepro.config import APP_VERSION, RELEASES_API_URL
from navepro.core.ambiente import _eh_windows
from navepro.core.ssl_context import _baixar


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
    """Encontra o instalador da plataforma atual.

    Windows procura o primeiro asset '.exe'; Linux o primeiro '.AppImage'.
    """
    sufixo = ".exe" if _eh_windows() else ".appimage"
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