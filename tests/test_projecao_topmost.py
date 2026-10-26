"""Regressão: projeções precisam ficar acima da apresentação em tela cheia.

Bug relatado: a primeira projeção de versículo subia por cima do
Impress/PowerPoint. Ao terminar, o foco voltava para a apresentação (correto),
mas a projeção seguinte aparecia por baixo da tela cheia. O ``lift()`` sozinho
não vence uma janela em tela cheia já focada; por isso as projeções ligam
``-topmost`` e o relógio/vídeo desligam esse estado.
"""
import ast
import os
import sys
import tkinter as tk

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
ARQ_T = os.path.join(RAIZ, "navepro", "core", "telao.py")
src = open(ARQ_T, encoding="utf-8").read()
tree = ast.parse(src)
nos = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

_metodos = ("_elevar_para_projecao", "_desativar_topmost_projecao")
_corpo = "\n".join(ast.get_source_segment(src, nos[n]) for n in _metodos)

ns = {"tk": tk}
exec(compile("class Telao:\n" + "\n".join(
    "    " + linha for linha in _corpo.split("\n")) + "\n", "<telao>", "exec"), ns)
Telao = ns["Telao"]

falhas = []


def check(nome, cond, extra=""):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


def chama(metodo, alvo):
    return any(
        isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
        and no.func.attr == alvo
        for no in ast.walk(nos[metodo])
    )


class Root:
    def __init__(self):
        self.attrs = []
        self.lifts = 0

    def attributes(self, *args):
        self.attrs.append(args)

    def lift(self):
        self.lifts += 1


class Stub(Telao):
    def __init__(self):
        self.root = Root()


# ── Núcleo: liga/desliga o topmost e sempre levanta a janela ─────────
t = Stub()
t._elevar_para_projecao()
check("1ª projeção fica topmost", t._topmost_projecao is True)
check("1ª projeção aplica -topmost=True",
      ("-topmost", True) in t.root.attrs, str(t.root.attrs))
check("1ª projeção levanta a janela", t.root.lifts == 1, str(t.root.lifts))

t._elevar_para_projecao()
check("2ª projeção continua topmost e levanta de novo",
      t._topmost_projecao is True and t.root.lifts == 2,
      f"lifts={t.root.lifts}")
check("não repete -topmost=True desnecessariamente",
      t.root.attrs.count(("-topmost", True)) == 1, str(t.root.attrs))

t._desativar_topmost_projecao()
check("voltar ao relógio desliga o topmost", t._topmost_projecao is False)
check("voltar ao relógio aplica -topmost=False",
      ("-topmost", False) in t.root.attrs, str(t.root.attrs))

t._elevar_para_projecao()
check("projeção seguinte volta a ficar topmost",
      t._topmost_projecao is True and t.root.lifts == 3,
      f"lifts={t.root.lifts}")
check("projeção seguinte reaplica -topmost=True",
      t.root.attrs.count(("-topmost", True)) == 2, str(t.root.attrs))

# ── Todos os modos de projeção usam o reforço ────────────────────────
for metodo in ("projetar_texto", "projetar_slides", "projetar_imagem",
               "projetar_imagem_com_texto", "_projetar_medidor",
               "_garantir_foco_teclado"):
    check(f"{metodo} eleva o telão para a projeção",
          chama(metodo, "_elevar_para_projecao"), metodo)

check("relógio devolve o telão à camada normal",
      chama("mostrar_relogio", "_desativar_topmost_projecao"))
check("vídeo devolve o telão à camada normal",
      chama("preparar_video", "_desativar_topmost_projecao"))

print("\n" + ("TODOS OS CASOS PASSARAM" if not falhas else f"FALHAS: {falhas}"))
sys.exit(1 if falhas else 0)
