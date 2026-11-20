"""Clima: geolocalização e temperatura (Open-Meteo + Nominatim).

Extraído de NavePro.py sem alterar o comportamento (ver AGENTS.md).
"""

import json
import re
import urllib.parse
import urllib.request

from navepro.config import MAPA_ESTADOS
from navepro.core.log import get_logger
from navepro.core.ssl_context import _baixar
from navepro.core.textos import normalizar_texto

log = get_logger("clima")

# Preposição correta ao citar o estado na mensagem de cidade fora do estado:
# "ao estado de Alagoas", "ao estado da Bahia", "ao estado do Acre".
# Estados sem artigo definido (AL, GO, MT, MS, MG, PE, RO, RR, SC, SP, SE)
# ficam de fora do mapa e usam "de".
_ARTIGO_ESTADO: dict[str, str] = {
    'BA': 'da', 'PB': 'da',
    'AC': 'do', 'AP': 'do', 'AM': 'do', 'CE': 'do', 'DF': 'do',
    'ES': 'do', 'MA': 'do', 'PA': 'do', 'PR': 'do', 'PI': 'do',
    'RJ': 'do', 'RN': 'do', 'RS': 'do', 'TO': 'do',
}

# Tipos do Nominatim que representam cidade/município. Ruas, lojas, fazendas
# e bairros homônimos (ex.: "Belém" em Curitiba) não entram.
_TIPOS_CIDADE: frozenset = frozenset(
    {'city', 'town', 'village', 'municipality'})


def _preposicao_estado(estado: str) -> str:
    """Retorna 'de', 'da' ou 'do' conforme o artigo definido do estado."""
    return _ARTIGO_ESTADO.get((estado or '').strip().upper(), 'de')


def _estado_para_nome(estado: str) -> str:
    """Converte sigla UF para nome completo."""
    return MAPA_ESTADOS.get(estado.upper(), estado)


def _estado_bate(texto: str, estado_sigla: str, estado_nome: str) -> bool:
    """Verifica se o texto menciona o estado como palavra/frase inteira."""
    if not estado_sigla:
        return True
    texto_norm = normalizar_texto(texto)
    if not texto_norm:
        return False
    # Limite de palavra: "PA" não pode casar dentro de "Paraná" e "Pará"
    # não pode casar dentro de "Paraná" (ou vice-versa).
    for valor in (estado_sigla, estado_nome):
        valor_norm = normalizar_texto(valor)
        if not valor_norm:
            continue
        padrao = rf'(?<!\w){re.escape(valor_norm)}(?!\w)'
        if re.search(padrao, texto_norm):
            return True
    return False


def _item_e_municipio(item: dict, cidade: str) -> bool:
    """Diz se o resultado do Open-Meteo é a cidade, não um distrito/vilarejo.

    O Open-Meteo usa ``PPL`` tanto para municípios quanto para vilarejos com o
    mesmo nome (ex.: "Mundo Novo" em Japira/PR). O município traz ``admin2``
    igual ao nome ou uma população; o vilarejo costuma vir sem população e com
    ``admin2`` do município ao qual pertence.
    """
    if normalizar_texto(item.get('name', '')) != normalizar_texto(cidade):
        return False
    admin2 = normalizar_texto(item.get('admin2', ''))
    if admin2 and admin2 == normalizar_texto(cidade):
        return True
    try:
        return int(item.get('population') or 0) > 0
    except (TypeError, ValueError):
        return False


def _resultado_aceitavel_nominatim(
    item: dict, cidade: str, estado: str, estado_nome: str
) -> bool:
    """Filtra resultados do Nominatim para evitar locais inadequados."""
    if not item:
        return False

    nome = normalizar_texto(item.get('name', ''))
    cidade_norm = normalizar_texto(cidade)
    display_name = normalizar_texto(item.get('display_name', ''))

    # Nome exato: "Rua Umuarama"/"Rancho Umuarama" não são a cidade Umuarama.
    if nome != cidade_norm:
        return False

    if estado and not _estado_bate(display_name, estado, estado_nome):
        return False

    classe = normalizar_texto(item.get('class', ''))
    tipo = normalizar_texto(item.get('type', ''))
    addresstype = normalizar_texto(item.get('addresstype', ''))

    if classe == 'place':
        return tipo in _TIPOS_CIDADE
    if classe == 'boundary' and tipo == 'administrative':
        # Municípios pequenos costumam vir como limite administrativo
        # (addresstype village/town/city/municipality).
        return addresstype in _TIPOS_CIDADE
    return False


def obter_temperatura(cidade: str, estado: str) -> str:
    """
    Obtém a temperatura atual usando Open-Meteo.
    Retorna string formatada como '25°C' ou mensagem de erro.
    """
    try:
        cidade = cidade.strip()
        estado = estado.strip().upper()
        estado_nome = _estado_para_nome(estado)

        # Tenta consultas com e sem estado
        consultas: list[str] = []
        if estado:
            consultas.append(f"{cidade}, {estado_nome}, Brasil")
            consultas.append(f"{cidade}, {estado}, Brasil")
            consultas.append(f"{cidade}, {estado_nome}")
        consultas.append(cidade)

        # Distingue "sem rede/servidor fora do ar" de "cidade em outro
        # estado". Só a segunda condição pode gerar a mensagem de estado.
        servidor_respondeu = False
        rede_falhou = False
        cidade_em_outro_estado = False

        for consulta in consultas:
            geo_url = (
                f"https://geocoding-api.open-meteo.com/v1/search?"
                f"name={urllib.parse.quote(consulta)}&count=8&language=pt&format=json"
                f"&country=BR"
            )
            if estado:
                geo_url += f"&admin1={urllib.parse.quote(estado_nome)}"

            try:
                with _baixar(geo_url, timeout=8) as response:
                    geo_data = json.loads(response.read().decode())
                servidor_respondeu = True
            except Exception as e:
                log.warning(f"⚠️ Geocoding falhou ({consulta!r}): {e}")
                rede_falhou = True
                continue

            if 'results' not in geo_data or not geo_data['results']:
                continue

            resultado = None
            for item in geo_data['results']:
                # Ignora distritos/vilarejos homônimos (ex.: "Mundo Novo" em
                # Japira/PR): só aceita resultado de nível municipal.
                if not _item_e_municipio(item, cidade):
                    continue
                if not estado:
                    resultado = item
                    break
                if _estado_bate(item.get('admin1', ''), estado, estado_nome):
                    resultado = item
                    break
                # A cidade existe e o servidor respondeu, mas em outro estado.
                cidade_em_outro_estado = True

            if resultado is None:
                log.warning(f"⚠️ Geocoding sem resultado válido para {consulta!r}")
                continue

            lat = resultado.get('latitude')
            lon = resultado.get('longitude')
            if lat is None or lon is None:
                continue

            weather_url = (
                f"https://api.open-meteo.com/v1/forecast?"
                f"latitude={lat}&longitude={lon}&current_weather=true"
            )
            try:
                with _baixar(weather_url, timeout=8) as response:
                    weather_data = json.loads(response.read().decode())
                servidor_respondeu = True
            except Exception as e:
                log.warning(f"⚠️ Weather falhou ({cidade!r} {lat},{lon}): {e}")
                rede_falhou = True
                continue

            if 'current_weather' in weather_data:
                temp = weather_data['current_weather']['temperature']
                return f"{temp}°C"

            return "ERRO AO OBTER TEMPERATURA"

        # Fallback para Nominatim
        try:
            geo_url = (
                f"https://nominatim.openstreetmap.org/search?"
                f"q={urllib.parse.quote(f'{cidade}, {estado_nome}, Brasil')}"
                f"&format=json&limit=3&addressdetails=1"
            )
            req = urllib.request.Request(geo_url, headers={'User-Agent': 'HinarioApp/1.0'})
            with _baixar(req, timeout=8) as response:
                geo_data = json.loads(response.read().decode())
            servidor_respondeu = True

            for item in geo_data:
                if not _resultado_aceitavel_nominatim(item, cidade, estado, estado_nome):
                    continue
                lat = float(item['lat'])
                lon = float(item['lon'])
                weather_url = (
                    f"https://api.open-meteo.com/v1/forecast?"
                    f"latitude={lat}&longitude={lon}&current_weather=true"
                )
                with _baixar(weather_url, timeout=8) as response:
                    weather_data = json.loads(response.read().decode())
                servidor_respondeu = True
                if 'current_weather' in weather_data:
                    return f"{weather_data['current_weather']['temperature']}°C"
        except Exception as e:
            log.warning(f"⚠️ Nominatim falhou ({cidade!r}): {e}")
            rede_falhou = True

        # Sem nenhuma resposta do servidor (ou com falha de rede sem indício
        # de cidade em outro estado), o problema é a conexão — não o estado
        # informado pelo usuário.
        if not servidor_respondeu or (rede_falhou and not cidade_em_outro_estado):
            return "Verifique a rede!"

        if estado and cidade_em_outro_estado:
            preposicao = _preposicao_estado(estado)
            return (f"A cidade não pertence ao estado {preposicao} "
                    f"{estado_nome}.")
        return "NAO ENCONTRADA"

    except Exception as e:
        log.exception(f"Erro ao obter temperatura: {e}")
        return "ERRO"
