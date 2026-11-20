"""Clima: geolocalização e temperatura (Open-Meteo + Nominatim).

Extraído de NavePro.py sem alterar o comportamento (ver AGENTS.md).
"""

import json
import urllib.parse
import urllib.request

from navepro.config import MAPA_ESTADOS
from navepro.core.log import get_logger
from navepro.core.ssl_context import _baixar
from navepro.core.textos import normalizar_texto, remover_acentos

log = get_logger("clima")


def _estado_para_nome(estado: str) -> str:
    """Converte sigla UF para nome completo."""
    return MAPA_ESTADOS.get(estado.upper(), estado)


def _estado_bate(texto: str, estado_sigla: str, estado_nome: str) -> bool:
    """Verifica se o texto menciona o estado."""
    if not estado_sigla:
        return True
    texto_norm = normalizar_texto(texto)
    if not texto_norm:
        return False
    valores = {
        normalizar_texto(estado_sigla),
        normalizar_texto(estado_nome),
    }
    return any(v and v in texto_norm for v in valores)


def _cidade_estado_especial(cidade: str, estado: str) -> bool:
    """Verifica se é 'Mundo Novo' que existe em múltiplos estados."""
    return (
        normalizar_texto(cidade) == 'mundo novo'
        and normalizar_texto(estado) in {'ms', 'ba', 'go'}
    )


def _resultado_aceitavel_nominatim(
    item: dict, cidade: str, estado: str, estado_nome: str
) -> bool:
    """Filtra resultados do Nominatim para evitar locais inadequados."""
    if not item:
        return False

    nome = normalizar_texto(item.get('name', ''))
    cidade_norm = normalizar_texto(cidade)
    display_name = normalizar_texto(item.get('display_name', ''))

    nome_bate = nome == cidade_norm
    tokens_cidade = set(cidade_norm.split())
    tokens_nome = set(nome.split())
    tokens_batem = bool(tokens_cidade and tokens_cidade.issubset(tokens_nome))

    if not (nome_bate or tokens_batem):
        return False

    if _cidade_estado_especial(cidade, estado):
        return bool(estado and _estado_bate(display_name, estado, estado_nome))

    classe = normalizar_texto(item.get('class', ''))
    tipo = normalizar_texto(item.get('type', ''))

    if classe in {'landuse', 'water', 'amenity', 'natural'}:
        return False
    if tipo in {'building', 'peak', 'river', 'city_district',
                 'hamlet', 'suburb', 'neighbourhood', 'isolated_dwelling',
                 'farm', 'residential', 'locality'}:
        return False

    if estado and not _estado_bate(display_name, estado, estado_nome):
        return False

    return True


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
                if normalizar_texto(item.get('name', '')) != normalizar_texto(cidade):
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
                f"&format=json&limit=3"
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
            estado_upper = remover_acentos(estado_nome).upper()
            return f"NAO PERTENCE AO ESTADO DE: {estado_upper}."
        return "NAO ENCONTRADA"

    except Exception as e:
        log.exception(f"Erro ao obter temperatura: {e}")
        return "ERRO"
