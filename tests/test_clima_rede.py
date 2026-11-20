"""Regressão: clima distingue falha de rede de cidade em outro estado.

Sem internet (ou com o servidor de temperatura fora do ar) a mensagem deve
ser "Verifique a rede!". A mensagem de cidade fora do estado só pode
aparecer quando a rede funcionou, o servidor respondeu e a cidade realmente
não pertence ao estado informado.
"""
import json
import os
import sys
import urllib.error

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)
from navepro.core import clima  # noqa: E402


class Resposta:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


def instalar(geo=None, nominatim=None, weather=None):
    """Substitui _baixar() por respostas fixas (ou exceções) por serviço."""
    def fake_baixar(url, timeout=8, **kwargs):
        alvo = getattr(url, 'full_url', url)
        if 'geocoding-api.open-meteo.com' in alvo:
            valor = geo
        elif 'nominatim.openstreetmap.org' in alvo:
            valor = nominatim
        elif 'api.open-meteo.com/v1/forecast' in alvo:
            valor = weather
        else:
            raise AssertionError(f'URL inesperada: {alvo}')
        if isinstance(valor, Exception):
            raise valor
        return Resposta(valor)

    clima._baixar = fake_baixar


falhas = []


def check(nome, cond, extra=''):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


SEM_REDE = urllib.error.URLError('sem rede')
CIDADE_MS = {'results': [{
    'name': 'Dourados', 'admin1': 'Mato Grosso do Sul',
    'latitude': -22.2, 'longitude': -54.8,
}]}
CIDADE_BA = {'results': [{
    'name': 'Mundo Novo', 'admin1': 'Bahia',
    'latitude': -11.7, 'longitude': -40.4,
}]}
CLIMA_OK = {'current_weather': {'temperature': 25}}

# 1) Sem internet: mensagem de rede, nunca a de estado.
instalar(geo=SEM_REDE, nominatim=SEM_REDE, weather=SEM_REDE)
r = clima.obter_temperatura('Mundo Novo', 'MS')
check('sem internet -> Verifique a rede!', r == 'Verifique a rede!', r)

# 2) Sem internet e sem estado configurado: também é problema de rede.
instalar(geo=SEM_REDE, nominatim=SEM_REDE, weather=SEM_REDE)
r = clima.obter_temperatura('Dourados', '')
check('sem internet (sem UF) -> Verifique a rede!',
      r == 'Verifique a rede!', r)

# 3) Servidor de temperatura fora do ar (geocoding respondeu, clima falhou).
instalar(geo=CIDADE_MS, nominatim=[], weather=SEM_REDE)
r = clima.obter_temperatura('Dourados', 'MS')
check('servidor de clima fora -> Verifique a rede!',
      r == 'Verifique a rede!', r)

# 4) Rede ok, cidade realmente em outro estado: aí sim a mensagem de estado.
instalar(geo=CIDADE_BA, nominatim=[], weather=CLIMA_OK)
r = clima.obter_temperatura('Mundo Novo', 'MS')
check('cidade em outro estado -> mensagem de estado',
      r == 'NAO PERTENCE AO ESTADO DE: MATO GROSSO DO SUL.', r)

# 5) Rede ok, mas cidade inexistente: não é "outro estado".
instalar(geo={'results': []}, nominatim=[], weather=CLIMA_OK)
r = clima.obter_temperatura('Cidade Inexistente', 'MS')
check('cidade não encontrada -> NAO ENCONTRADA', r == 'NAO ENCONTRADA', r)

# 6) Caminho feliz preservado: cidade no estado certo devolve a temperatura.
instalar(geo=CIDADE_MS, nominatim=[], weather=CLIMA_OK)
r = clima.obter_temperatura('Dourados', 'MS')
check('cidade no estado certo -> temperatura', r == '25°C', r)

# 7) Resposta de clima sem "current_weather" continua com o erro original.
instalar(geo=CIDADE_MS, nominatim=[], weather={})
r = clima.obter_temperatura('Dourados', 'MS')
check('resposta sem current_weather -> erro original',
      r == 'ERRO AO OBTER TEMPERATURA', r)

print('\n' + ('TODOS OS CASOS PASSARAM' if not falhas else f'FALHAS: {falhas}'))
sys.exit(1 if falhas else 0)
