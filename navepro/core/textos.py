"""Utilitários de texto: detecção de mídia, acentos e normalização."""

import os
import re
import threading
import unicodedata
from collections import OrderedDict
from typing import Optional

from navepro.config import EXTENSOES_VIDEO, EXTENSOES_AUDIO, EXTENSOES_TEXTO


def detectar_tipo_arquivo(caminho: str) -> Optional[str]:
    """Detecta o tipo de mídia pela extensão."""
    ext = os.path.splitext(caminho)[1].lower()
    if ext in EXTENSOES_VIDEO:
        return 'video'
    if ext in EXTENSOES_AUDIO:
        return 'audio'
    if ext in EXTENSOES_TEXTO:
        return 'texto'
    return None


# Regex compilada para remoção de acentos (O(n), sem laço Python)
_PATTERN_ACENTOS: re.Pattern = re.compile(
    '[áàãâäéèêëíìîïóòõôöúùûüçñÁÀÃÂÄÉÈÊËÍÌÎÏÓÒÕÔÖÚÙÛÜÇÑ]'
)
# Cache LRU para remover_acentos (evita normalizações repetidas)
_ACENTOS_CACHE: OrderedDict[str, str] = OrderedDict()
_ACENTOS_CACHE_LOCK = threading.Lock()
_ACENTOS_CACHE_MAX: int = 1024

_MAPA_ACENTOS: dict[str, str] = {
    'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'ä': 'a',
    'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
    'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
    'ó': 'o', 'ò': 'o', 'õ': 'o', 'ô': 'o', 'ö': 'o',
    'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
    'ç': 'c', 'ñ': 'n',
    'Á': 'A', 'À': 'A', 'Ã': 'A', 'Â': 'A', 'Ä': 'A',
    'É': 'E', 'È': 'E', 'Ê': 'E', 'Ë': 'E',
    'Í': 'I', 'Ì': 'I', 'Î': 'I', 'Ï': 'I',
    'Ó': 'O', 'Ò': 'O', 'Õ': 'O', 'Ô': 'O', 'Ö': 'O',
    'Ú': 'U', 'Ù': 'U', 'Û': 'U', 'Ü': 'U',
    'Ç': 'C', 'Ñ': 'N',
}


def _replace_acentos(match: re.Match) -> str:
    """Callback para substituir acento no regex."""
    char = match.group(0)
    return _MAPA_ACENTOS.get(char, char)


def remover_acentos(texto: str) -> str:
    """Remove acentos usando regex compilada com callback e cache LRU."""
    if not texto:
        return texto
    # Cache check (thread-safe via lock)
    with _ACENTOS_CACHE_LOCK:
        cached = _ACENTOS_CACHE.get(texto)
        if cached is not None:
            return cached
    texto = unicodedata.normalize('NFC', texto)
    resultado = _PATTERN_ACENTOS.sub(_replace_acentos, texto)
    # Cache write (LRU via OrderedDict.move_to_end)
    with _ACENTOS_CACHE_LOCK:
        if len(_ACENTOS_CACHE) >= _ACENTOS_CACHE_MAX:
            _ACENTOS_CACHE.popitem(last=False)
        _ACENTOS_CACHE[texto] = resultado
        _ACENTOS_CACHE.move_to_end(texto)
    return resultado


def normalizar_texto(texto: str) -> str:
    """Normaliza: minúsculas, sem acentos, sem espaços extras."""
    return re.sub(r'\s+', ' ', remover_acentos(str(texto or '').strip())).casefold()