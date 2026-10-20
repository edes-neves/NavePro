"""Regressão: o medidor ativo volta após uma projeção comum (slide/letra).

Bug relatado: com a contagem regressiva no telão (nome/frase + número), ao
projetar um slide e ele terminar, o telão voltava ao relógio e a temperatura
substituía o nome/frase. O mesmo valia para o fim de uma música/vídeo com um
slide na tela. O medidor que o operador deixou projetado deve ser retomado.

Extrai, via AST, o método real `_retomar_medidor_ativo`/`_retornar_ao_relogio`
do telão e `_projetar_medidor_seguro`/`_reprojetar_medidor_ativo` do NavePro.py
para validar a lógica sem abrir janelas.
"""
import ast
import datetime
import os
import sys
import time

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
sys.path.insert(0, _AQUI)
sys.path.insert(0, RAIZ)
from fixture_log import log  # noqa: E402  (stub de log usado pelo NavePro.py)

# ── Trecho do telão ───────────────────────────────────────────────────
ARQ_T = os.path.join(RAIZ, "navepro", "core", "telao.py")
src_t = open(ARQ_T, encoding="utf-8").read()
nos_t = {n.name: n for n in ast.walk(ast.parse(src_t))
         if isinstance(n, ast.FunctionDef)}
_corpo_t = "\n".join(ast.get_source_segment(src_t, nos_t[n])
                     for n in ("_retomar_medidor_ativo", "_retornar_ao_relogio"))

# ── Trecho do NavePro.py ──────────────────────────────────────────────
src = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
nos = {n.name: n for n in ast.walk(ast.parse(src))
       if isinstance(n, ast.FunctionDef)}
_corpo_n = "\n".join(ast.get_source_segment(src, nos[n])
                     for n in ("_projetar_medidor_seguro",
                               "_reprojetar_medidor_ativo"))

ns = {"log": log, "datetime": datetime, "time": time}
_classe = ("class Telao:\n"
           + "\n".join("    " + ln for ln in _corpo_t.split("\n")) + "\n")
_classe += ("\nclass Operador:\n"
            + "\n".join("    " + ln for ln in _corpo_n.split("\n")) + "\n")
exec(compile(_classe, "<trecho>", "exec"), ns)
Telao, Operador = ns["Telao"], ns["Operador"]

falhas = []


def check(nome, cond, extra=""):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


# ── Stubs ─────────────────────────────────────────────────────────────

def _fmt_tempo(seg):
    total = int(seg or 0)
    h, r = divmod(total, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _fmt_crono(seg):
    cs = max(0, int(round(seg * 100)))
    h, r = divmod(cs, 360000)
    m, s = divmod(r, 6000)
    s, c = divmod(s, 100)
    return f"{h:02d}:{m:02d}:{s:02d}.{c:02d}" if h else f"{m:02d}:{s:02d}.{c:02d}"


FORMATAR_TEMPO = _fmt_tempo
FORMATAR_CRONO = _fmt_crono


class TelaoStub(Telao):
    """Telão mínimo: registra a reprojeção do medidor."""

    def __init__(self, ao_voltar=None, visivel=False, relogio=False,
                 mostrando_letra=True):
        self._ao_voltar_relogio = ao_voltar
        self._is_visible = visivel
        self.mostrando_relogio = relogio
        self.mostrando_letra = mostrando_letra
        self._modo_extra = None
        self._proj_timer = None
        self._em_slides = True
        self._slides = [1, 2, 3]
        self._slide_index = 1
        self._imagem_item = None
        self._imagem_pil = None
        self._imagem_orig_pil = None
        self._imagem_escala = 1.0
        self._imagem_rect_base = None
        self._texto_largura_base = None
        self._texto_box = (0, 0, 100, 100)
        self._texto_escala = 1.0
        self._mostrando_imagem = False
        self._mostrando_imagem_com_texto = False
        self._fundo_imagem_item = None
        self._fundo_imagem_to_tk = None
        self._fundo_imagem_caminho = ""
        self._font_temp_exib = None
        self._font_temp_exib_texto = None
        self._current_text = "12:34"
        self._current_temp = "Vamos começar em:"
        self._temp_salvo = "25°C"
        self.overlay_text = "HORA"
        self.temp_text = "TEMP"
        self.ref_text = "REF"
        self._font_hora = ("Digital-7", 40, "normal")
        self._font_temp = ("Digital-7", 30, "normal")
        self._cx, self._cy_hora, self._cy_temp = 100, 100, 140
        self.deiconified = 0
        self.lowered = 0
        self.canvas = self
        self.root = self
        self.relogio_desenhado = None

    def _aplicar_cores_relogio(self):
        pass

    def _alpha_relogio(self):
        return 0.55

    def deiconify(self):
        self.deiconified += 1

    def lower(self):
        self.lowered += 1

    def attributes(self, *a):
        pass

    def coords(self, *a):
        pass

    def itemconfig(self, *a, **k):
        pass

    def delete(self, *a):
        pass

    def update_idletasks(self):
        pass

    def mostrar_relogio(self, hora, temp=""):
        self.relogio_desenhado = (hora, temp)
        self.mostrando_relogio = True


class OperadorStub(Operador):
    """Operador mínimo com os estados de contagem/cronômetro e config."""

    def __init__(self, medidor_projetado=None, contagem=None, crono=None,
                 cfg=None):
        self._medidor_projetado = medidor_projetado
        self._contagem = contagem or {
            "rodando": False, "pausado": False, "fim": 0.0,
            "restante": 0.0, "total": 0.0, "titulo": "", "timer_id": None,
        }
        self._crono = crono or {
            "rodando": False, "pausado": False, "inicio": 0.0,
            "acumulado": 0.0, "timer_id": None,
        }
        self.config_data = cfg or {}
        self.projetados = []
        self.retorno_registrado = False

    @staticmethod
    def _formatar_tempo(seg):
        return FORMATAR_TEMPO(seg)

    @staticmethod
    def _formatar_cronometro(seg):
        return FORMATAR_CRONO(seg)

    def _garantir_telao(self):
        return self._telao

    def _projetar_medidor_seguro(self, chave, modo, subtitulo="",
                                 tempo="00:00", guardar_temp=True):
        self.projetados.append((chave, modo, subtitulo, tempo, guardar_temp))

    def definir_retorno_medidor(self, cb):
        self.retorno_registrado = cb is not None
        self._telao._ao_voltar_relogio = cb


# ── 1) Fim de slide com contagem rodando: retoma a contagem ──
op = OperadorStub(
    medidor_projetado="contagem",
    contagem={"rodando": True, "pausado": False, "fim": time.time() + 300,
              "restante": 300.0, "total": 300.0,
              "titulo": "Vamos começar em:", "timer_id": None},
    cfg={"contagem": {"cor_hora": "#F5BE08"}, "relogio": {}})
op._telao = TelaoStub(ao_voltar=op._reprojetar_medidor_ativo)
op._telao._retornar_ao_relogio()
check("slide/contagem: não volta ao relógio", op._telao.relogio_desenhado is None,
      str(op._telao.relogio_desenhado))
check("slide/contagem: reprojeta a contagem", len(op.projetados) == 1,
      str(op.projetados))
if op.projetados:
    chave, modo, sub, tempo, guardar = op.projetados[0]
    check("slide/contagem: chave contagem", chave == "contagem", chave)
    check("slide/contagem: frase preservada",
          sub == "Vamos começar em:", sub)
    check("slide/contagem: tempo real do medidor",
          tempo in ("05:00", "04:59"), tempo)
    check("slide/contagem: não sobrescreve a temperatura",
          guardar is False, str(guardar))

# ── 2) Contagem pausada: retoma o tempo restante ──
op = OperadorStub(
    medidor_projetado="contagem",
    contagem={"rodando": True, "pausado": True, "fim": 0.0,
              "restante": 42.0, "total": 300.0,
              "titulo": "Término:", "timer_id": None})
op._telao = TelaoStub(ao_voltar=op._reprojetar_medidor_ativo)
op._telao._retornar_ao_relogio()
check("slide/pausada: reprojeta", len(op.projetados) == 1, str(op.projetados))
if op.projetados:
    check("slide/pausada: tempo restante", op.projetados[0][3] == "00:42",
          op.projetados[0][3])
    check("slide/pausada: frase preservada",
          op.projetados[0][2] == "Término:", op.projetados[0][2])

# ── 3) Cronômetro ativo: retoma o cronômetro (sem frase) ──
op = OperadorStub(
    medidor_projetado="cronometro",
    crono={"rodando": True, "pausado": False, "inicio": time.time() - 90,
           "acumulado": 0.0, "timer_id": None})
op._telao = TelaoStub(ao_voltar=op._reprojetar_medidor_ativo)
op._telao._retornar_ao_relogio()
check("slide/cronômetro: reprojeta", len(op.projetados) == 1, str(op.projetados))
if op.projetados:
    chave, modo, sub, tempo, guardar = op.projetados[0]
    check("slide/cronômetro: chave cronometro", chave == "cronometro", chave)
    check("slide/cronômetro: sem frase", sub == "", sub)
    check("slide/cronômetro: tempo acumulado",
          tempo in ("01:30.00", "01:29.99", "01:29.98"), tempo)

# ── 4) Nenhum medidor: volta ao relógio ──
op = OperadorStub(medidor_projetado=None)
op._telao = TelaoStub(ao_voltar=op._reprojetar_medidor_ativo)
op._telao._retornar_ao_relogio()
check("sem medidor: volta ao relógio",
      op._telao.relogio_desenhado is not None)
check("sem medidor: relógio com temperatura salva",
      op._telao.relogio_desenhado[1] == "25°C",
      str(op._telao.relogio_desenhado))
check("sem medidor: não reprojeta", not op.projetados, str(op.projetados))

# ── 5) Medidor encerrado (modo None): volta ao relógio ──
op = OperadorStub(medidor_projetado=None)
op._telao = TelaoStub(ao_voltar=op._reprojetar_medidor_ativo)
op._telao._ao_voltar_relogio = None  # como encerrar_medidor faz
op._telao._retornar_ao_relogio()
check("encerrado: volta ao relógio",
      op._telao.relogio_desenhado is not None)

# ── 6) Projeção sobre um medidor: Esc fecha o medidor (volta relógio) ──
# Nesse caso o próprio medidor era o modo antes da projeção? Não: o slide
# apaga o modo. O que importa é que o operador decidiu encerrar (cb None).
op = OperadorStub(medidor_projetado="contagem",
                  contagem={"rodando": False, "pausado": False, "fim": 0.0,
                            "restante": 0.0, "total": 0.0,
                            "titulo": "", "timer_id": None})
op._telao = TelaoStub(ao_voltar=op._reprojetar_medidor_ativo)
op._telao._retornar_ao_relogio()
check("contagem zerada: não reprojeta vazia", not op.projetados,
      str(op.projetados))
check("contagem zerada: volta ao relógio",
      op._telao.relogio_desenhado is not None)

# ── 7) _projetar_medidor_seguro (REAL) registra o retorno no telão ──
class TelaoRegistra(TelaoStub):
    def __init__(self):
        super().__init__()
        self._modo_extra = None
        self.recebeu = None

    def _projetar_medidor(self, cfg, modo, subtitulo="", tempo="00:00",
                          guardar_temp=True):
        self.recebeu = (cfg, modo, subtitulo, tempo, guardar_temp)

    def definir_retorno_medidor(self, cb):
        self._ao_voltar_relogio = cb


class OperadorReal(Operador):
    def __init__(self):
        self.config_data = {"contagem": {"cor_hora": "#fff"}}
        self._medidor_projetado = None
        self.player = self

    def _garantir_telao(self):
        return self._telao


op = OperadorReal()
op._telao = TelaoRegistra()
Operador._projetar_medidor_seguro(
    op, "contagem", "contagem", subtitulo="Oi", tempo="01:00",
    guardar_temp=False)
check("seguro: registra o retorno no telão",
      callable(op._telao._ao_voltar_relogio))
check("seguro: marca o medidor projetado",
      op._medidor_projetado == "contagem", str(op._medidor_projetado))
check("seguro: repassa o cfg da chave",
      op._telao.recebeu[0] == {"cor_hora": "#fff"}, str(op._telao.recebeu))
check("seguro: respeita guardar_temp False",
      op._telao.recebeu[4] is False, str(op._telao.recebeu))

print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas else f"FALHAS: {falhas}"))
sys.exit(1 if falhas else 0)
