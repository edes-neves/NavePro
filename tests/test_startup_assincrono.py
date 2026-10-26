#!/usr/bin/env python3
"""Startup não pode travar a janela principal (NavePro.py).

`_sincronizar_uploads_midia` varre a pasta uploads, faz stat dos arquivos novos
e recarrega o cache. Com muitos arquivos isso segurava a thread do Tk logo
depois que a janela aparecia. Agora a sincronização roda em uma thread daemon,
depois de o servidor HTTP já ter sido iniciado.
"""

import ast
import os
import sys
import threading
import time

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
if _AQUI not in sys.path:
    sys.path.insert(0, _AQUI)

from fixture_log import log  # noqa: E402

_SRC = open(os.path.join(RAIZ, "NavePro.py"), encoding="utf-8").read()
_TREE = ast.parse(_SRC)

falhas = []


def check(nome, cond, extra=""):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


def _metodo(nome: str):
    for no in ast.walk(_TREE):
        if isinstance(no, ast.FunctionDef) and no.name == nome:
            return no
    raise AssertionError(f"método {nome} não encontrado em NavePro.py")


_no = _metodo("_inicializar_em_segundo_plano")
_mod = ast.Module(body=[_no], type_ignores=[])
ast.fix_missing_locations(_mod)


class ServidorFake:
    def __init__(self):
        self.iniciou = False
        self.ui = None
        self.remoto = None

    def iniciar(self):
        self.iniciou = True


class RootFake:
    def __init__(self):
        self.agendados = []

    def after(self, ms, fn):
        self.agendados.append((ms, fn))
        return str(len(self.agendados))


class AppFake:
    def __init__(self):
        self._servidor_thread = None
        self.cidade_salva = ""
        self.estado_salvo = ""
        self.root = RootFake()
        self._temp_timer = None

    def _na_thread_ui(self, fn, timeout=5.0):
        return fn()

    def _remoto_despacho(self, acao, dados):
        return None

    def _aplicar_acesso_remoto(self):
        pass

    def _aplicar_temperatura(self, temp):
        pass

    def atualizar_temperatura(self):
        pass

    def verificar_atualizacao(self, manual=False):
        pass


iniciou = threading.Event()
liberar = threading.Event()
terminou = threading.Event()


def _sincronizar_fake():
    iniciou.set()
    liberar.wait(2)
    terminou.set()
    return 0


_ns = {
    "threading": threading,
    "_sincronizar_uploads_midia": _sincronizar_fake,
    "ServidorAsyncHTTP": ServidorFake,
    "BACKEND_URL": "http://127.0.0.1:5897",
    "log": log,
    "obter_temperatura": lambda cidade, estado: "25°C",
    "SEGUNDOS_PARA_VERIFICAR_ATUALIZACAO": 3600,
}
exec(compile(_mod, "<_inicializar_em_segundo_plano>", "exec"), _ns)  # noqa: S102
_inicializar = _ns["_inicializar_em_segundo_plano"]

app = AppFake()
t0 = time.monotonic()
_inicializar(app)
decorrido = time.monotonic() - t0

check("startup não espera a sincronização terminar", decorrido < 0.5,
      f"{decorrido:.3f}s")
check("servidor HTTP inicia antes/independente da sincronização",
      app._servidor_thread is not None and app._servidor_thread.iniciou)
check("sincronização rodou em background", iniciou.wait(1))
check("startup seguiu e agendou a temperatura",
      any(ms == 1_800_000 for ms, _ in app.root.agendados))
check("startup seguiu e agendou a verificação de atualização",
      any(ms == 3600 * 1000 for ms, _ in app.root.agendados))

liberar.set()
check("thread de sincronização termina normalmente", terminou.wait(2))

print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas else f"FALHAS: {falhas}"))
sys.exit(1 if falhas else 0)
