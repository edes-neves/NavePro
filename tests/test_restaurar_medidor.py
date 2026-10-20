"""Regressão: ao terminar a música/vídeo, o medidor ativo é retomado.

Bug relatado: com a contagem regressiva rodando, ao terminar uma música o
telão voltava ao relógio e a temperatura substituía o nome/frase da
contagem. `restaurar_tela` deve retomar o medidor (contagem/cronômetro)
quando houver um ativo, e só cair no relógio quando não houver.
"""
import ast
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(_AQUI)
ARQ_T = os.path.join(RAIZ, 'navepro', 'core', 'telao.py')
src = open(ARQ_T, encoding='utf-8').read()
tree = ast.parse(src)
nos = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

corpo = ast.get_source_segment(src, nos['restaurar_tela'])

ns = {}
exec(compile("class Telao:\n" + "\n".join(
    "    " + linha for linha in corpo.split("\n")) + "\n", '<telao>', 'exec'), ns)
Telao = ns['Telao']


class Stub(Telao):
    def __init__(self, modo=None, mostrando_letra=False, vivo=True,
                 visible=True, mostrando_relogio=False,
                 current_text="12:34", current_temp="Vamos começar em:",
                 medidor_cfg=None):
        self._vivo = vivo
        self._modo_extra = modo
        self.mostrando_letra = mostrando_letra
        self._is_visible = visible
        self.mostrando_relogio = mostrando_relogio
        self._current_text = current_text
        self._current_temp = current_temp
        self._medidor_cfg = medidor_cfg or {}
        self._current_alpha = None
        self.deiconified = 0
        self.lowered = 0
        self.projetados = []
        self.root = self

    def _raiz_viva(self):
        return self._vivo

    def _alpha_relogio(self):
        return 0.55

    def deiconify(self):
        self.deiconified += 1

    def lower(self):
        self.lowered += 1

    def attributes(self, *a):
        pass

    def _projetar_medidor(self, cfg, modo, subtitulo="", tempo="00:00",
                          guardar_temp=True):
        self.projetados.append((cfg, modo, subtitulo, tempo, guardar_temp))

    def _retomar_medidor_ativo(self):
        # Sem operador registrado (fora do fluxo do telão real): não assume.
        return False

    def seguir(self, guardar_temp=True):
        self.projetados.append(('SEGUIR', guardar_temp))


falhas = []


def check(nome, cond, extra=''):
    print(f"{'OK ' if cond else 'FALHA'} {nome}{(' -> ' + extra) if extra else ''}")
    if not cond:
        falhas.append(nome)


# 1) contagem ativa: retoma o medidor, não volta ao relógio
t = Stub(modo="contagem", mostrando_letra=True,
         medidor_cfg={"fundo_opaco": True})
t.restaurar_tela()
check('contagem ativa: reprojeta o medidor', len(t.projetados) == 1, str(t.projetados))
if t.projetados:
    cfg, modo, sub, tempo, guardar = t.projetados[0]
    check('contagem ativa: modo contagem', modo == 'contagem', modo)
    check('contagem ativa: frase preservada', sub == 'Vamos começar em:', sub)
    check('contagem ativa: tempo preservado', tempo == '12:34', tempo)
    check('contagem ativa: não sobrescreve temperatura do relógio',
          guardar is False, str(guardar))
    check('contagem ativa: usa o cfg do medidor',
          cfg == {"fundo_opaco": True}, str(cfg))
check('contagem ativa: não mexe no relógio', t.deiconified == 0 and not t.mostrando_relogio)

# 2) cronômetro ativo: retoma o medidor (sem subtítulo)
t = Stub(modo="cronometro", mostrando_letra=True, current_temp="")
t.restaurar_tela()
check('cronômetro ativo: reprojeta o medidor', len(t.projetados) == 1, str(t.projetados))
if t.projetados:
    cfg, modo, sub, tempo, guardar = t.projetados[0]
    check('cronômetro ativo: modo cronometro', modo == 'cronometro', modo)
    check('cronômetro ativo: sem subtítulo', sub == '', sub)
    check('cronômetro ativo: tempo preservado', tempo == '12:34', tempo)

# 3) sem medidor: restaura o relógio normalmente
t = Stub(modo=None, mostrando_letra=False, mostrando_relogio=False)
t.restaurar_tela()
check('sem medidor: volta ao relógio', t.mostrando_relogio is True)
check('sem medidor: reexibe a janela', t.deiconified == 1, str(t.deiconified))
check('sem medidor: zera os caches', t._current_text == "" and t._current_temp == "")
check('sem medidor: não reprojeta medidor', not t.projetados, str(t.projetados))

# 4) projeção comum (letra) ativa: também volta ao relógio
t = Stub(modo=None, mostrando_letra=True, mostrando_relogio=False)
t.restaurar_tela()
check('letra projetada: volta ao relógio', t.mostrando_relogio is True)
check('letra projetada: não reprojeta medidor', not t.projetados, str(t.projetados))

# 5) telão já visível no relógio: nada a fazer
t = Stub(modo=None, mostrando_letra=False, mostrando_relogio=True, visible=True)
t.restaurar_tela()
check('já no relógio: não reexibe', t.deiconified == 0, str(t.deiconified))

# 6) telão morto: não faz nada
t = Stub(modo="contagem", mostrando_letra=True, vivo=False)
t.restaurar_tela()
check('telão morto: não reprojeta', not t.projetados, str(t.projetados))

print('\n' + ('TODOS OS CASOS PASSARAM' if not falhas else f'FALHAS: {falhas}'))
sys.exit(1 if falhas else 0)
