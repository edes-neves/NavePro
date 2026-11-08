#!/usr/bin/env python3
"""Testes das configurações do relógio no controle remoto.

A aba Relógio do celular lê/salva a aparência do relógio e mostra/oculta
relógio/temperatura no telão. Estes testes extraem os handlers de
navepro/ui/remoto.py via AST e exercitam validação, clamp dos tamanhos e
o despacho das ações — sem Tk nem telão de verdade.
"""

import ast
import os
import sys
import time

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

_SRC = open(os.path.join(RAIZ, "navepro", "ui", "remoto.py"),
            encoding="utf-8").read()
_TREE = ast.parse(_SRC)

falhas = 0


def checar(desc, cond, extra=""):
    global falhas
    print(f"{'OK ' if cond else 'X  '} {desc}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas += 1


def _extrair(nome: str) -> str:
    for no in _TREE.body:
        if isinstance(no, ast.ClassDef):
            for m in no.body:
                if isinstance(m, ast.FunctionDef) and m.name == nome:
                    return ast.get_source_segment(_SRC, m)
    raise AssertionError(f"{nome} não encontrada em remoto.py")


_METODOS = (
    "_relogio_padrao",
    "_cor_hex_valida",
    "_bool_remoto",
    "_remoto_relogio_estado",
    "_remoto_relogio_configurar",
    "_remoto_relogio_projetar",
    "_remoto_relogio_alternar",
    "_remoto_relogio",
)
ns: dict = {"time": time}
for _nome in _METODOS:
    exec(compile(_extrair(_nome), f"<{_nome}>", "exec"), ns)  # noqa: S102


class FakeTelao:
    def __init__(self):
        self._relogio_cfg = {
            "cor_hora": "#F5BE08", "cor_temp": "#F5BE08",
            "cor_fundo": "#000000", "fator_hora": 1.0, "fator_temp": 1.0,
            "espacamento": 1.0, "fundo_opaco": False, "fundo_imagem": "",
        }
        self.mostrando_relogio = True
        self._em_slides = False
        self.chamadas = []

    def parar_projecao(self):
        self.chamadas.append("parar_projecao")
        self.mostrando_relogio = True

    def restaurar_tela(self):
        self.chamadas.append("restaurar_tela")
        self.mostrando_relogio = True

    def mostrar_relogio(self, hora, temp):
        self.chamadas.append(("mostrar_relogio", hora, temp))


class FakePlayer:
    def __init__(self):
        self.telao = FakeTelao()
        self.is_playing = False
        self.is_paused = False

    def _garantir_telao(self):
        return self.telao


class FakeApp:
    def __init__(self):
        self.player = FakePlayer()
        self.config_data = {}
        self.temperatura_atual = "25°C"
        self._relogio_oculto_telao = False
        self._temperatura_oculta_telao = False
        self.cidade_salva = "São Paulo"
        self.estado_salvo = "SP"
        self.salvo = None
        self.chamadas = []

    def salvar_config_relogio(self, cfg):
        self.salvo = dict(cfg)
        self.config_data["relogio"] = dict(cfg)
        self.player.telao._relogio_cfg.update(cfg)

    def _temperatura_valida(self):
        return True

    def parar(self):
        self.chamadas.append("parar")
        self.player.is_playing = False
        self.player.is_paused = False

    def alternar_relogio_telao(self):
        self.chamadas.append("alternar_relogio_telao")
        self._relogio_oculto_telao = not self._relogio_oculto_telao

    def alternar_temperatura_telao(self):
        self.chamadas.append("alternar_temperatura_telao")
        self._temperatura_oculta_telao = not self._temperatura_oculta_telao


def _ligar(fake: FakeApp) -> FakeApp:
    for nome in ("_relogio_padrao", "_cor_hex_valida", "_bool_remoto"):
        setattr(fake, nome, ns[nome])
    for nome in ("_remoto_relogio_estado", "_remoto_relogio_configurar",
                 "_remoto_relogio_projetar", "_remoto_relogio_alternar",
                 "_remoto_relogio"):
        setattr(fake, nome, ns[nome].__get__(fake))
    return fake


# ── 1. Helpers de validação ─────────────────────────────────────────
checar("cor #RRGGBB é aceita", ns["_cor_hex_valida"]("#a1B2c3"))
checar("cor sem # é recusada", not ns["_cor_hex_valida"]("a1b2c3"))
checar("cor curta é recusada", not ns["_cor_hex_valida"]("#12345"))
checar("bool('false') vira False", ns["_bool_remoto"]("false") is False)
checar("bool('true') vira True", ns["_bool_remoto"]("true") is True)
checar("bool(True) continua True", ns["_bool_remoto"](True) is True)

# ── 2. Estado ───────────────────────────────────────────────────────
fake = _ligar(FakeApp())
j = fake._remoto_relogio_estado()
checar("estado devolve ok e modo relógio",
       j["ok"] and j["modo"] == "relogio")
checar("estado devolve a temperatura válida", j["temperatura"] == "25°C")
checar("estado devolve config padrão",
       j["config"]["cor_hora"] == "#F5BE08"
       and j["config"]["fator_hora"] == 1.0)
fake.player.telao._em_slides = True
checar("estado identifica slides",
       fake._remoto_relogio_estado()["modo"] == "slides")

# ── 3. Configurar: salva, preserva extras e faz clamp ───────────────
fake = _ligar(FakeApp())
fake.config_data = {"relogio": {"titulo": "Aviso da contagem"}}
j = fake._remoto_relogio_configurar({
    "cor_hora": "#ff0000",
    "cor_temp": "#00FF00",
    "cor_fundo": "#123456",
    "fator_hora": 9,
    "fator_temp": 0.1,
    "espacamento": 1.5,
    "fundo_opaco": "false",
})
checar("configurar devolve ok", j["ok"])
checar("cores são aplicadas",
       fake.salvo["cor_hora"] == "#ff0000"
       and fake.salvo["cor_temp"] == "#00FF00"
       and fake.salvo["cor_fundo"] == "#123456")
checar("fator acima do máximo vira 2.0", fake.salvo["fator_hora"] == 2.0)
checar("fator abaixo do mínimo vira 0.3", fake.salvo["fator_temp"] == 0.3)
checar("espaçamento é preservado", fake.salvo["espacamento"] == 1.5)
checar("fundo_opaco string 'false' vira False",
       fake.salvo["fundo_opaco"] is False)
checar("campos extras do medidor sobrevivem",
       fake.salvo.get("titulo") == "Aviso da contagem")
checar("config salva chega ao telão",
       fake.player.telao._relogio_cfg["cor_hora"] == "#ff0000")

# ── 4. Configurar: entradas inválidas não salvam ────────────────────
fake = _ligar(FakeApp())
fake.salvo = "intocado"
j = fake._remoto_relogio_configurar({"cor_hora": "vermelho"})
checar("cor inválida devolve erro", not j["ok"] and "inválida" in j["erro"])
checar("cor inválida não salva", fake.salvo == "intocado")
j = fake._remoto_relogio_configurar({"fator_hora": "abc"})
checar("número inválido devolve erro", not j["ok"])
j = fake._remoto_relogio_configurar({"espacamento": "nan"})
checar("NaN devolve erro", not j["ok"])

# ── 5. Alternar relógio/temperatura ─────────────────────────────────
fake = _ligar(FakeApp())
fake._remoto_relogio_alternar({"oculto": True}, "alternar_relogio")
checar("alternar_relogio oculta", fake._relogio_oculto_telao is True)
chamadas = len(fake.chamadas)
fake._remoto_relogio_alternar({"oculto": True}, "alternar_relogio")
checar("pedir o mesmo estado não alterna de novo",
       len(fake.chamadas) == chamadas)
fake._remoto_relogio_alternar({"oculto": False}, "alternar_relogio")
checar("alternar_relogio mostra", fake._relogio_oculto_telao is False)
fake._remoto_relogio_alternar({"oculto": True}, "alternar_temperatura")
checar("alternar_temperatura oculta",
       fake._temperatura_oculta_telao is True)

# ── 6. Projetar relógio ─────────────────────────────────────────────
fake = _ligar(FakeApp())
fake.player.telao.mostrando_relogio = False
fake.player.telao._em_slides = True
j = fake._remoto_relogio_projetar()
checar("projetar encerra a projeção",
       "parar_projecao" in fake.player.telao.chamadas and j["ok"])
checar("projetar redesenha o relógio",
       any(isinstance(c, tuple) and c[0] == "mostrar_relogio"
           for c in fake.player.telao.chamadas))
fake = _ligar(FakeApp())
fake.player.is_playing = True
fake._remoto_relogio_projetar()
checar("projetar para a mídia quando há vídeo/áudio",
       fake.chamadas == ["parar"])
fake = _ligar(FakeApp())
fake._relogio_oculto_telao = True
j = fake._remoto_relogio_projetar()
checar("projetar desfaz o relógio oculto",
       j["oculto"] is False and fake._relogio_oculto_telao is False)

# ── 7. Despacho de ações ────────────────────────────────────────────
fake = _ligar(FakeApp())
j = fake._remoto_relogio({"acao": "configurar", "cor_hora": "#abcdef"})
checar("despacho 'configurar' salva", j["ok"]
       and fake.salvo["cor_hora"] == "#abcdef")
j = fake._remoto_relogio({"acao": "projetar"})
checar("despacho 'projetar' devolve estado", j["ok"])
j = fake._remoto_relogio({"acao": "nao_existe"})
checar("ação desconhecida devolve erro", not j["ok"])

# ── 8. Rotas e despacho no servidor ────────────────────────────────
_SRV = open(os.path.join(RAIZ, "navepro", "core", "servidor_http.py"),
            encoding="utf-8").read()
checar("POST /api/remoto/relogio mapeado",
       "'/api/remoto/relogio': 'relogio'" in _SRV)
checar("GET /api/remoto/relogio mapeado",
       "('relogio_estado', {})" in _SRV)
checar("despacho registra relogio_estado e relogio",
       "'relogio_estado': lambda d:" in _SRC
       and "'relogio': lambda d:" in _SRC)

print()
if falhas:
    print(f"X {falhas} teste(s) falharam.")
    sys.exit(1)
print("OK todos os testes do relógio remoto passaram.")
