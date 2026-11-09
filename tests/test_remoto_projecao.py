#!/usr/bin/env python3
"""Testes da Aparência da Projeção no controle remoto.

A janela "Aparência da Projeção" do computador (fonte, tamanho, cores,
versículo, fundo e duração) passa a ser configurável pelo celular. Estes
testes extraem os handlers de navepro/ui/remoto.py via AST e exercitam
validação, clamp, preservação de campos e o upload de imagem do fundo —
sem Tk nem telão de verdade.
"""

import ast
import os
import sys
import tempfile

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

_SRC = open(os.path.join(RAIZ, "navepro", "ui", "remoto.py"),
            encoding="utf-8").read()
_TREE = ast.parse(_SRC)
_SRV = open(os.path.join(RAIZ, "navepro", "core", "servidor_http.py"),
            encoding="utf-8").read()
_SRV_TREE = ast.parse(_SRV)
_WEB = open(os.path.join(RAIZ, "navepro", "remoto_web.py"),
            encoding="utf-8").read()

falhas = 0


def checar(desc, cond, extra=""):
    global falhas
    print(f"{'OK ' if cond else 'X  '} {desc}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas += 1


def _extrair(nome: str, tree=_TREE, src=_SRC) -> str:
    for no in tree.body:
        if isinstance(no, ast.ClassDef):
            for m in no.body:
                if isinstance(m, ast.FunctionDef) and m.name == nome:
                    return ast.get_source_segment(src, m)
    raise AssertionError(f"{nome} não encontrada")


_METODOS = (
    "_projecao_padrao",
    "_cor_hex_valida",
    "_bool_remoto",
    "_remoto_projecao_estado",
    "_remoto_projecao_configurar",
    "_remoto_projecao_imagens",
)
ns: dict = {"os": os, "UPLOAD_FOLDER": "/tmp"}
for _nome in _METODOS:
    exec(compile(_extrair(_nome), f"<{_nome}>", "exec"), ns)  # noqa: S102


class FakeTelao:
    def __init__(self):
        self._proj_cfg = {
            "fonte": "Montserrat", "tamanho_pct": 5.0, "cor": "#FFFFFF",
            "duracao_seg": 30, "cor_ref": "#A0A0A0",
            "cor_fundo": "#000000", "fundo_opaco": True,
            "fundo_imagem": "", "biblia_caixa": "normal",
            "biblia_alinhamento": "centro",
        }


class FakePlayer:
    def __init__(self):
        self.telao = FakeTelao()


class FakeApp:
    def __init__(self):
        self.player = FakePlayer()
        self.config_data = {}
        self.salvo = None

    def salvar_config_projecao(self, cfg):
        self.salvo = dict(cfg)
        self.config_data["projecao"] = dict(cfg)
        self.player.telao._proj_cfg.update(cfg)


def _ligar(fake: FakeApp) -> FakeApp:
    for nome in ("_projecao_padrao", "_cor_hex_valida", "_bool_remoto"):
        setattr(fake, nome, ns[nome])
    for nome in ("_remoto_projecao_estado", "_remoto_projecao_configurar",
                 "_remoto_projecao_imagens"):
        setattr(fake, nome, ns[nome].__get__(fake))
    return fake


# ── 1. Padrões e estado ─────────────────────────────────────────────
checar("padrão tem os campos da janela do computador",
       set(ns["_projecao_padrao"]()) == {
           "fonte", "tamanho_pct", "cor", "duracao_seg", "cor_ref",
           "cor_fundo", "fundo_opaco", "fundo_imagem", "biblia_caixa",
           "biblia_alinhamento"})
fake = _ligar(FakeApp())
j = fake._remoto_projecao_estado()
checar("estado devolve ok e config padrão",
       j["ok"] and j["config"]["fonte"] == "Montserrat"
       and j["config"]["tamanho_pct"] == 5.0
       and j["config"]["biblia_caixa"] == "normal")
checar("estado sem imagem devolve tem_imagem False",
       j["tem_imagem"] is False and j["imagem"] == "")
fake.config_data = {"projecao": {"cor": "#FF0000", "duracao_seg": 12}}
fake.player.telao._proj_cfg = {}
j = fake._remoto_projecao_estado()
checar("estado usa a config salva quando o telão ainda não tem valores",
       j["config"]["cor"] == "#FF0000" and j["config"]["duracao_seg"] == 12)
fake.player.telao._proj_cfg = {"tamanho_pct": 7.5}
j = fake._remoto_projecao_estado()
checar("estado dá prioridade ao que está vivo no telão",
       j["config"]["tamanho_pct"] == 7.5)

# ── 2. Configurar: salva, valida e faz clamp ────────────────────────
fake = _ligar(FakeApp())
fake.config_data = {"projecao": {"campo_futuro": "mantém"}}
j = fake._remoto_projecao_configurar({
    "fonte": "Roboto",
    "tamanho_pct": 99,
    "cor": "#ff0000",
    "cor_ref": "#00FF00",
    "cor_fundo": "#123456",
    "duracao_seg": 0,
    "fundo_opaco": "false",
    "fundo_imagem": "  /tmp/fundo.jpg  ",
    "biblia_caixa": "maiusculas",
    "biblia_alinhamento": "direita",
})
checar("configurar devolve ok", j["ok"])
checar("fonte é aplicada", fake.salvo["fonte"] == "Roboto")
checar("tamanho acima do máximo vira 15", fake.salvo["tamanho_pct"] == 15.0)
checar("duração abaixo do mínimo vira 1", fake.salvo["duracao_seg"] == 1)
checar("cores são aplicadas",
       fake.salvo["cor"] == "#ff0000"
       and fake.salvo["cor_ref"] == "#00FF00"
       and fake.salvo["cor_fundo"] == "#123456")
checar("fundo_opaco string 'false' vira False",
       fake.salvo["fundo_opaco"] is False)
checar("imagem é normalizada sem espaços",
       fake.salvo["fundo_imagem"] == "/tmp/fundo.jpg")
checar("caixa e alinhamento do versículo são salvos",
       fake.salvo["biblia_caixa"] == "maiusculas"
       and fake.salvo["biblia_alinhamento"] == "direita")
checar("campo desconhecido da config sobrevive",
       fake.salvo.get("campo_futuro") == "mantém")
checar("config salva chega ao telão",
       fake.player.telao._proj_cfg["cor"] == "#ff0000")

# Campos ausentes não são apagados
fake = _ligar(FakeApp())
fake.player.telao._proj_cfg["cor_ref"] = "#ABCDEF"
fake._remoto_projecao_configurar({"cor": "#111111"})
checar("configurar só a cor preserva os outros campos",
       fake.salvo["cor"] == "#111111"
       and fake.salvo["cor_ref"] == "#ABCDEF")

# ── 3. Entradas inválidas não salvam ────────────────────────────────
for dados, desc in (
    ({"fonte": "Comic Sans"}, "fonte inválida"),
    ({"cor": "vermelho"}, "cor inválida"),
    ({"cor_fundo": "#12345"}, "cor curta inválida"),
    ({"tamanho_pct": "abc"}, "tamanho não numérico"),
    ({"duracao_seg": "abc"}, "duração não numérica"),
    ({"biblia_caixa": "gritando"}, "caixa inválida"),
    ({"biblia_alinhamento": "justificado"}, "alinhamento inválido"),
):
    fake = _ligar(FakeApp())
    fake.salvo = "intocado"
    j = fake._remoto_projecao_configurar(dados)
    checar(f"{desc} devolve erro e não salva",
           not j["ok"] and fake.salvo == "intocado")

# ── 4. Imagens disponíveis no computador ────────────────────────────
with tempfile.TemporaryDirectory() as pasta:
    for nome in ("fundo.jpg", "foto.PNG", "musica.mp3", "texto.txt"):
        with open(os.path.join(pasta, nome), "wb") as f:
            f.write(b"x")
    ns["UPLOAD_FOLDER"] = pasta
    fake = _ligar(FakeApp())
    j = fake._remoto_projecao_imagens()
    nomes = sorted(i["nome"] for i in j["imagens"])
    checar("lista só imagens da pasta uploads", nomes == ["foto.PNG", "fundo.jpg"])
    checar("lista traz o caminho completo",
           all(os.path.isabs(i["caminho"]) for i in j["imagens"]))
ns["UPLOAD_FOLDER"] = "/tmp"

# ── 5. Upload da imagem do celular (multipart) ──────────────────────
_UP = _extrair("_handle_upload_projecao_bytes", _SRV_TREE, _SRV)


class ServidorFake:
    def __init__(self, uploads):
        self.uploads = uploads
        self.resposta = None

    def _responder_erro_bytes(self, msg, codigo=400):
        self.resposta = (codigo, msg)
        return b""

    def _responder_json_bytes(self, obj, codigo=200):
        self.resposta = (codigo, obj)
        return b""


def _multipart(filename, conteudo=b"img"):
    boundary = "----NaveProProj"
    corpo = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="arquivo"; '
        f'filename="{filename}"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode() + conteudo + f"\r\n--{boundary}--\r\n".encode()
    return {"content-type": f"multipart/form-data; boundary={boundary}"}, corpo


with tempfile.TemporaryDirectory() as pasta:
    ns_up: dict = {"os": os, "re": __import__("re"), "UPLOAD_FOLDER": pasta}
    exec(compile(_UP, "<_handle_upload_projecao_bytes>", "exec"), ns_up)
    handler = ns_up["_handle_upload_projecao_bytes"]

    for nome_mal, desc in (
        ("../../escape.jpg", "filename com ../ não escapa"),
        ("/etc/escape.jpg", "filename absoluto vira basename"),
    ):
        for nome in os.listdir(pasta):
            os.unlink(os.path.join(pasta, nome))
        srv = ServidorFake(pasta)
        headers, corpo = _multipart(nome_mal)
        handler(srv, headers, corpo)
        checar(f"{desc} (arquivo só em uploads)",
               os.listdir(pasta) == ["projecao_escape.jpg"]
               and srv.resposta and srv.resposta[0] == 200
               and os.path.exists("/etc/escape.jpg") is False)

    for nome in os.listdir(pasta):
        os.unlink(os.path.join(pasta, nome))
    srv = ServidorFake(pasta)
    headers, corpo = _multipart("nota.txt")
    handler(srv, headers, corpo)
    checar("upload recusa arquivo que não é imagem",
           srv.resposta and srv.resposta[0] == 400
           and os.listdir(pasta) == [])

    srv = ServidorFake(pasta)
    headers, corpo = _multipart("foto.jpg")
    handler(srv, headers, corpo)
    checar("upload de imagem grava com prefixo projecao_",
           os.listdir(pasta) == ["projecao_foto.jpg"]
           and srv.resposta[1]["caminho"].endswith("projecao_foto.jpg"))

# ── 6. Rotas e despacho ─────────────────────────────────────────────
checar("GET /api/remoto/projecao mapeado para projecao_estado",
       "('projecao_estado', {})" in _SRV)
checar("GET /api/remoto/projecao/imagens mapeado",
       "('projecao_imagens', {})" in _SRV)
checar("POST /api/remoto/projecao/configurar mapeado",
       "'/api/remoto/projecao/configurar': 'projecao_configurar'" in _SRV)
checar("POST /api/remoto/projecao/imagem tem handler próprio",
       "def _handle_upload_projecao_bytes" in _SRV
       and "if path == '/api/remoto/projecao/imagem'" in _SRV)
checar("upload de imagem tem limite de corpo próprio",
       "if alvo == '/api/remoto/projecao/imagem'" in _SRV)
checar("despacho registra os handlers da projeção",
       "'projecao_estado': lambda d:" in _SRC
       and "'projecao_configurar': lambda d:" in _SRC
       and "'projecao_imagens': lambda d:" in _SRC)
checar("rota antiga de abrir no computador continua",
       "'abrir_config_projecao': lambda d:" in _SRC
       and "'/api/remoto/projecao': 'abrir_config_projecao'" in _SRV)

# ── 7. Página do celular ────────────────────────────────────────────
for _id in ("projecao_card", "proj_fonte", "proj_tamanho", "proj_cores_texto",
            "proj_cores_ref", "proj_cores_fundo", "proj_caixa",
            "proj_alinhamento", "proj_opaco", "proj_imagem",
            "proj_imagens_lista", "proj_upload", "proj_duracao"):
    checar(f"página tem o controle {_id}", f'id="{_id}"' in _WEB)
checar("botão Projeção continua existindo e abre o card",
       "function abrirProjecaoBiblia()" in _WEB
       and "onclick=\"abrirProjecaoBiblia()\"" in _WEB)
checar("página chama as novas rotas",
       "/api/remoto/projecao/configurar" in _WEB
       and "/api/remoto/projecao/imagens" in _WEB
       and "/api/remoto/projecao/imagem" in _WEB)
checar("abrir no computador continua disponível",
       "function abrirProjecaoNoComputador()" in _WEB
       and "apiPost('/api/remoto/projecao', {})" in _WEB)
checar("upload do celular usa FormData",
       "new FormData()" in _WEB and "input.files[0]" in _WEB)

print()
if falhas:
    print(f"X {falhas} teste(s) falharam.")
    sys.exit(1)
print("OK todos os testes da projeção remota passaram.")
