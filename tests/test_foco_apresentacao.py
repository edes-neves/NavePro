#!/usr/bin/env python3
"""Foco na apresentação após uma projeção (foco_apresentacao.py).

Cobre a seleção da janela certa (slide show, nunca o editor nem o NavePro),
a recusa em focar uma janela já fechada (para não trazer o editor do Office
para a frente) e a integração com o telão/NavePro.py.
"""

import ast
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, RAIZ)

from navepro.core import foco_apresentacao as foco  # noqa: E402

falhas = []


def check(nome, cond, extra=""):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


def janela(id_, titulo, classe, processo, pid=999, x=1920, y=0,
           largura=1920, altura=1080):
    return {
        "id": id_, "titulo": titulo, "classe": classe,
        "processo": processo, "pid": pid, "x": x, "y": y,
        "largura": largura, "altura": altura,
    }


ALVO = foco._criar_alvo_apresentacao(
    r"C:\apresentacoes\Culto Domingo.pptx", pid=123,
    monitor=(1920, 0, 1920, 1080),
    monitor_painel=(0, 0, 1920, 1080))

# ── Seleção da janela ─────────────────────────────────────────────────
slideshow = janela(
    10, "PowerPoint Slide Show - [Culto Domingo] - PowerPoint",
    "screenClass", "POWERPNT.EXE", pid=999)
editor = janela(
    11, "Culto Domingo - PowerPoint", "PPTFrameClass", "POWERPNT.EXE",
    pid=999, x=0, y=0, largura=1200, altura=800)
navepro = janela(
    12, "NAVE PRO - PRO", "Tk", "NavePro.AppImage", pid=555,
    x=1920, y=0, largura=1920, altura=1080)
tela = janela(
    13, "TELÃO", "Tk", "python3", pid=555,
    x=1920, y=0, largura=1920, altura=1080)
impress = janela(
    14, "Culto Domingo — LibreOffice Impress", "libreoffice",
    "soffice.bin", pid=321)
console = janela(
    15, "Presenter Console - Culto Domingo", "libreoffice",
    "soffice.bin", pid=321)

check("screenClass do PowerPoint é reconhecida",
      foco._pontuar_janela(slideshow, ALVO) >= 120,
      str(foco._pontuar_janela(slideshow, ALVO)))
check("janela do NavePro é descartada",
      foco._pontuar_janela(navepro, ALVO) < 0,
      str(foco._pontuar_janela(navepro, ALVO)))
check("janela do telão é descartada",
      foco._pontuar_janela(tela, ALVO) < 0,
      str(foco._pontuar_janela(tela, ALVO)))
check("Impress com o nome do arquivo é reconhecido",
      foco._pontuar_janela(impress, ALVO) >= 100,
      str(foco._pontuar_janela(impress, ALVO)))
check("editor do PowerPoint pontua menos que o slide show",
      foco._pontuar_janela(editor, ALVO) <
      foco._pontuar_janela(slideshow, ALVO),
      f"{foco._pontuar_janela(editor, ALVO)} < "
      f"{foco._pontuar_janela(slideshow, ALVO)}")
check("console do apresentador não é confundido com o slide show",
      foco._pontuar_janela(console, ALVO) < 120,
      str(foco._pontuar_janela(console, ALVO)))
check("escolhe o slide show e não o console, ambos em tela cheia",
      foco._escolher_janela([console, impress, slideshow], ALVO) is slideshow)

escolhida = foco._escolher_janela([editor, navepro, impress, slideshow], ALVO)
check("escolhe a janela do slide show entre as candidatas",
      escolhida is slideshow, str(escolhida and escolhida.get("id")))
check("nunca escolhe uma janela sem relação",
      foco._escolher_janela([navepro, tela], ALVO) is None)

# ── Captura e devolução de foco ───────────────────────────────────────
_orig_localizar = foco._localizar_janela_apresentacao
_orig_viva = foco._janela_viva
_orig_foco = foco._trazer_foco
try:
    # Janela capturada já fechada: NÃO procura outra janela do Office
    # (senão o editor do PowerPoint viria para a frente).
    alvo = foco._criar_alvo_apresentacao("Culto.pptx")
    alvo["janela"] = 42
    focadas = []
    foco._janela_viva = lambda _id: False
    foco._trazer_foco = lambda _id: focadas.append(_id) or True
    foco._localizar_janela_apresentacao = lambda _alvo: (_ for _ in ()).throw(
        AssertionError("não deve procurar outra janela"))
    check("não foca janela fechada", foco._focar_apresentacao(alvo) is False)
    check("não procura o editor quando a janela capturada morreu", not focadas)

    # Janela capturada ainda viva e ainda em modo apresentação: foca.
    alvo = foco._criar_alvo_apresentacao("Culto.pptx")
    alvo["janela"] = 55
    atual = janela(55, "PowerPoint Slide Show", "screenClass",
                   "POWERPNT.EXE")
    foco._localizar_janela_apresentacao = lambda _alvo: atual
    foco._janela_viva = lambda _id: True
    foco._trazer_foco = lambda _id: focadas.append(_id) or True
    check("foca a janela capturada que continua em apresentação",
          foco._focar_apresentacao(alvo) is True)
    check("focou a janela capturada", focadas[-1:] == [55], str(focadas))

    # Mesma janela do Impress, mas já saiu do modo apresentação (virou o
    # editor): não deve trazer o editor para a frente.
    alvo = foco._criar_alvo_apresentacao("Culto.pptx")
    alvo["janela"] = 56
    foco._localizar_janela_apresentacao = lambda _alvo: editor
    check("não foca a janela que virou editor",
          foco._focar_apresentacao(alvo) is False)
    check("editor não foi trazido para a frente", 56 not in focadas, str(focadas))

    # Sem captura ainda: localiza na hora e guarda o identificador.
    alvo = foco._criar_alvo_apresentacao("Culto.pptx")
    candidato = janela(77, "PowerPoint Slide Show", "screenClass",
                       "POWERPNT.EXE")
    foco._localizar_janela_apresentacao = lambda _alvo: candidato
    foco._janela_viva = lambda _id: True
    foco._trazer_foco = lambda _id: focadas.append(_id) or True
    check("localiza e devolve o foco quando a captura assíncrona atrasou",
          foco._focar_apresentacao(alvo) is True)
    check("guarda a janela localizada", alvo["janela"] == 77, str(alvo))
    check("focou a janela localizada", focadas[-1:] == [77], str(focadas))

    # Só o editor do Office aberto (pontuação baixa) não é capturado.
    alvo = foco._criar_alvo_apresentacao("Culto.pptx")
    foco._localizar_janela_apresentacao = lambda _alvo: editor
    check("não confunde o editor com o slide show",
          foco._parece_apresentacao(editor, alvo) is False)
    check("não devolve foco ao editor",
          foco._focar_apresentacao(alvo) is False)

    # Captura assíncrona: espera a janela aparecer e guarda o id.
    respostas = iter([None, janela(88, "PowerPoint Slide Show",
                                   "screenClass", "POWERPNT.EXE")])
    foco._localizar_janela_apresentacao = lambda _alvo: next(respostas)
    alvo = foco._criar_alvo_apresentacao("Culto.pptx")
    foco._registrar_janela_apresentacao(alvo, timeout=1.0)
    check("captura a janela quando ela aparece",
          alvo["janela"] == 88 and alvo["capturado"] is True, str(alvo))

    # Captura agendada no Tk (sem thread): só chama Xlib no callback.
    class RaizFalsa:
        def __init__(self):
            self.agendados = []

        def after(self, _ms, callback):
            self.agendados.append(callback)
            return str(len(self.agendados))

    respostas = iter([None, janela(89, "PowerPoint Slide Show",
                                   "screenClass", "POWERPNT.EXE")])
    foco._localizar_janela_apresentacao = lambda _alvo: next(respostas)
    raiz = RaizFalsa()
    alvo = foco._criar_alvo_apresentacao("Culto.pptx")
    foco._agendar_captura_janela_apresentacao(raiz, alvo, timeout=1.0)
    check("agenda a primeira captura no Tk", len(raiz.agendados) == 1)
    raiz.agendados.pop(0)()
    check("reagenda enquanto a janela não aparece",
          len(raiz.agendados) == 1)
    raiz.agendados.pop(0)()
    check("captura a janela pelo callback do Tk",
          alvo["janela"] == 89 and alvo["capturado"] is True, str(alvo))
    check("agenda o reposicionamento do controle após capturar",
          len(raiz.agendados) == 3, str(len(raiz.agendados)))

    # Alvo cancelado (apresentação terminou) não captura nada.
    alvo = foco._criar_alvo_apresentacao("Culto.pptx")
    alvo["cancelado"] = True
    foco._registrar_janela_apresentacao(alvo, timeout=0.5)
    check("não captura apresentação já encerrada", alvo["janela"] is None)
finally:
    foco._localizar_janela_apresentacao = _orig_localizar
    foco._janela_viva = _orig_viva
    foco._trazer_foco = _orig_foco

# ── Erros do X11 e posicionamento da janela de controle ──────────────
class _LibX11Falsa:
    def __init__(self):
        self.handlers = []

    def XSetErrorHandler(self, handler):
        self.handlers.append(handler)
        return 0x1234 if len(self.handlers) == 1 else 0

    def XSync(self, display, discard):
        self.sync = (display, discard)


lib_falsa = _LibX11Falsa()
with foco._silenciar_erros_x11(lib_falsa, "display"):
    pass
check("instala um handler de erros X11 durante as chamadas",
      len(lib_falsa.handlers) == 2 and lib_falsa.handlers[0] is not None,
      str(lib_falsa.handlers))
check("restaura o handler anterior do X11",
      lib_falsa.handlers[1] == 0x1234, str(lib_falsa.handlers))
check("sincroniza o X11 antes de restaurar o handler",
      lib_falsa.sync == ("display", False), str(lib_falsa.sync))

alvo_pos = foco._criar_alvo_apresentacao(
    "/apresentacoes/Culto.odp", monitor=(1920, 0, 1920, 1080),
    monitor_painel=(0, 0, 1920, 1080))
alvo_pos["janela"] = 10
apresentacao = janela(10, "Culto - LibreOffice Impress", "libreoffice",
                      "soffice.bin")
editor_telao = janela(11, "Culto — LibreOffice Impress", "libreoffice",
                      "soffice.bin")
console_telao = janela(15, "Presenter Console - Culto", "libreoffice",
                       "soffice.bin")
controle_primario = janela(16, "Culto — LibreOffice Impress",
                           "libreoffice", "soffice.bin", x=0, y=0)
outro_app = janela(17, "Firefox", "firefox", "firefox",
                   x=1920, y=0)
janelas = [apresentacao, editor_telao, console_telao,
           controle_primario, outro_app]
movidas = []
focadas_pos = []
_orig_varrer = foco._varrer_janelas_x11
_orig_mover = foco._mover_janela_para_monitor
_orig_trazer = foco._trazer_foco
try:
    foco._varrer_janelas_x11 = lambda: janelas
    foco._mover_janela_para_monitor = (
        lambda janela, destino: movidas.append((janela["id"], destino)) or True)
    foco._trazer_foco = lambda janela_id: focadas_pos.append(janela_id) or True
    total = foco._reposicionar_janelas_controle_linux(alvo_pos)
    check("move só as janelas de controle do Impress que estão no telão",
          total == 2 and [m[0] for m in movidas] == [11, 15],
          f"{total} {movidas}")
    check("move as janelas de controle para o monitor do operador",
          all(m[1] == (0, 0, 1920, 1080) for m in movidas), str(movidas))
    check("não move a apresentação capturada",
          10 not in [m[0] for m in movidas], str(movidas))
    check("não move janelas de outros aplicativos",
          17 not in [m[0] for m in movidas], str(movidas))
    check("não mexe na janela de controle que já está no primário",
          16 not in [m[0] for m in movidas], str(movidas))
    check("devolve o foco à apresentação depois de mover o controle",
          focadas_pos == [10], str(focadas_pos))
finally:
    foco._varrer_janelas_x11 = _orig_varrer
    foco._mover_janela_para_monitor = _orig_mover
    foco._trazer_foco = _orig_trazer

# ── Integração com telão e NavePro.py ─────────────────────────────────
src_telao = open(os.path.join(RAIZ, "navepro", "core", "telao.py"),
                 encoding="utf-8").read()
nos_telao = {n.name: n for n in ast.walk(ast.parse(src_telao))
             if isinstance(n, ast.FunctionDef)}
check("telão expõe o registro do retorno de apresentação",
      "definir_retorno_apresentacao" in nos_telao)
check("telão avisa o fim da projeção",
      "_avisar_fim_projecao" in nos_telao)

chamadas = [
    no.func.attr
    for no in ast.walk(nos_telao["_retornar_ao_relogio"])
    if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
]
check("avisa no retorno ao relógio e no retorno ao medidor",
      chamadas.count("_avisar_fim_projecao") == 2, str(chamadas))
check("avisa só depois de restaurar a tela",
      isinstance(nos_telao["_retornar_ao_relogio"].body[-1], ast.Expr)
      and isinstance(nos_telao["_retornar_ao_relogio"].body[-1].value, ast.Call)
      and getattr(nos_telao["_retornar_ao_relogio"].body[-1].value.func,
                  "attr", "") == "_avisar_fim_projecao")

src_nave = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
check("NavePro importa o foco da apresentação",
      "from navepro.core.foco_apresentacao import" in src_nave)
check("NavePro cria o alvo ao abrir a apresentação",
      "_criar_alvo_apresentacao(" in src_nave)
check("NavePro agenda a captura na thread principal do Tk",
      "_agendar_captura_janela_apresentacao" in src_nave
      and "threading.Thread(target=_registrar_janela_apresentacao"
      not in src_nave)
check("NavePro devolve o foco quando a projeção termina",
      "def _ao_encerrar_projecao" in src_nave
      and "_focar_apresentacao(alvo)" in src_nave)
check("NavePro re-registra o foco no telão recriado",
      "_registrar_foco_apresentacao_telao(novo_telao)" in src_nave)

print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas else f"FALHAS: {falhas}"))
sys.exit(1 if falhas else 0)
