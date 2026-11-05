"""Janela da Bíblia em grade — livros, capítulos e versículos na mesma tela.

Layout no estilo do Holyrics, responsivo de 1024×768 até telas atuais:

* coluna esquerda (altura toda): versículos do capítulo em botões com o
  texto, numa coluna estreita mas confortável para leitura;
* à direita, no topo: todos os livros em botões compactos (abreviação
  grande + nome completo em letra menor);
* à direita, embaixo dos livros: duas colunas — capítulos do livro
  selecionado (à esquerda) e versículos em botões numéricos (à direita),
  ambos com o mesmo formato de botão quadrado.

Há, de propósito, uma redundância de versículos: o texto à esquerda e os
números à direita. Clicar em qualquer um projeta só aquele versículo no
telão; as setas/controle remoto continuam navegando o capítulo. A janela
clássica de combos + área de texto continua disponível como
``janela_biblia_busca``.
"""

from __future__ import annotations

import os
import tkinter as tk
import tkinter as tkinter
import tkinter.messagebox
from tkinter import ttk

from navepro.core.banco import db_query
from navepro.core.biblia_import import importar_biblias
from navepro.core.monitores import _escolher_monitor_painel, get_monitors_config
from navepro.core.slides import _buscar_versiculos_por_texto
from navepro.core.util_tk import _centralizar_sobre
from navepro.core.widgets_arredondados import TkArredondado
from navepro.ui.apoio import _escolher_arquivos_usuario

# Botões e campos desenham cantos arredondados (fachada do tkinter).
tk = TkArredondado(tk)

COR_FUNDO = '#0d1117'
COR_BARRA = '#161b22'
COR_CARTAO = '#21262d'
COR_HOVER = '#30363d'
COR_TEXTO = '#c9d1d9'
COR_APAGADO = '#8b949e'
COR_DESTAQUE = '#f0c040'
COR_AZUL = '#1f6feb'
COR_AZUL_ATIVO = '#388bfd'
COR_ROXO = '#6e40c9'
COR_ROXO_ATIVO = '#8b5cf6'
COR_VERDE = '#3fb950'
COR_VERMELHO = '#da3633'
COR_VERMELHO_ATIVO = '#f85149'

PLACEHOLDER_BUSCA = "Buscar versículo por texto..."

# Cache do índice da Bíblia entre aberturas da janela. As consultas DISTINCT
# são baratas com o índice, mas a janela é aberta e fechada várias vezes
# durante o culto; cachear evita repetir as mesmas leituras. É invalidado
# após importar uma Bíblia (ver `_invalidar_cache_biblia`).
_CACHE_BIBLIA: dict = {
    'versoes': None,
    'livros': {},
    'capitulos': {},
}


def _invalidar_cache_biblia() -> None:
    """Descarta o índice em cache (chamar após importar/alterar Bíblias)."""
    _CACHE_BIBLIA['versoes'] = None
    _CACHE_BIBLIA['livros'].clear()
    _CACHE_BIBLIA['capitulos'].clear()

# Abreviações usadas no botão compacto do livro (ordem canônica).
ABREVIACOES_BIBLIA = {
    "Gênesis": "Gn", "Êxodo": "Êx", "Levítico": "Lv", "Números": "Nm",
    "Deuteronômio": "Dt", "Josué": "Js", "Juízes": "Jz", "Rute": "Rt",
    "1 Samuel": "1Sm", "2 Samuel": "2Sm", "1 Reis": "1Rs", "2 Reis": "2Rs",
    "1 Crônicas": "1Cr", "2 Crônicas": "2Cr", "Esdras": "Ed",
    "Neemias": "Ne", "Ester": "Et", "Jó": "Jó", "Salmos": "Sl",
    "Provérbios": "Pv", "Eclesiastes": "Ec", "Cânticos": "Ct",
    "Isaías": "Is", "Jeremias": "Jr", "Lamentações": "Lm",
    "Ezequiel": "Ez", "Daniel": "Dn", "Oséias": "Os", "Joel": "Jl",
    "Amós": "Am", "Obadias": "Ob", "Jonas": "Jn", "Miquéias": "Mq",
    "Naum": "Na", "Habacuque": "Hc", "Sofonias": "Sf", "Ageu": "Ag",
    "Zacarias": "Zc", "Malaquias": "Ml", "Mateus": "Mt", "Marcos": "Mc",
    "Lucas": "Lc", "João": "Jo", "Atos": "At", "Romanos": "Rm",
    "1 Coríntios": "1Co", "2 Coríntios": "2Co", "Gálatas": "Gl",
    "Efésios": "Ef", "Filipenses": "Fp", "Colossenses": "Cl",
    "1 Tessalonicenses": "1Ts", "2 Tessalonicenses": "2Ts",
    "1 Timóteo": "1Tm", "2 Timóteo": "2Tm", "Tito": "Tt", "Filemom": "Fm",
    "Hebreus": "Hb", "Tiago": "Tg", "1 Pedro": "1Pe", "2 Pedro": "2Pe",
    "1 João": "1Jo", "2 João": "2Jo", "3 João": "3Jo", "Judas": "Jd",
    "Apocalipse": "Ap",
}


class JanelaBibliaGradeMixin:
    def janela_biblia(self) -> None:
        """Abre a Bíblia em grade, em tela cheia no monitor do operador."""
        aberta = getattr(self, "_biblia_grade", None)
        if aberta is not None:
            try:
                if aberta.winfo_exists():
                    aberta.lift()
                    aberta.focus_force()
                    return
            except tk.TclError:
                pass
        self._biblia_grade = None

        janela = tk.Toplevel(self.root)
        janela.title("✝️ Bíblia")
        janela.configure(bg=COR_FUNDO)
        self._biblia_grade = janela

        # Tela cheia no monitor do painel (primário). Posicionar antes de
        # ligar o fullscreen garante que o Tk use o monitor certo no Linux;
        # no Windows o fullscreen já vai para o primário, que é o painel.
        painel = None
        try:
            painel = _escolher_monitor_painel(get_monitors_config())
        except Exception:
            painel = None
        largura_inicial = (painel.width if painel is not None
                           else janela.winfo_screenwidth())
        altura_inicial = (painel.height if painel is not None
                          else janela.winfo_screenheight())
        if painel is not None:
            janela.geometry(
                f"{largura_inicial}x{altura_inicial}"
                f"+{painel.x}+{painel.y}")
        janela.update_idletasks()
        try:
            janela.attributes('-fullscreen', True)
        except tk.TclError:
            pass
        janela.lift()
        janela.focus_force()

        # ── Estado da seleção ──
        estado = {'livro': None, 'cap': None, 'modo': 'capitulo'}
        _projecao_ref: list = [None]
        _cap_numeros: list[int] = []
        _versos_atuais: list = []
        _itens_livros: dict[str, dict] = {}
        _itens_capitulos: dict[int, dict] = {}
        _itens_numeros: dict[int, dict] = {}
        _itens_versos: dict[int, dict] = {}
        _livro_hover: list[str | None] = [None]
        _resultado_atual: list = [None, None]
        _id_resize: list = [None]
        _id_carga: list = [None]
        # Tamanho usado no último desenho: evita redesenhar tudo quando um
        # Configure chega sem mudança real de tamanho (o fullscreen dispara
        # vários durante a abertura).
        _tamanho_renderizado: list = [None]

        # ── Barra superior ──
        topo = tk.Frame(janela, bg=COR_BARRA)
        topo.pack(fill='x')

        linha1 = tk.Frame(topo, bg=COR_BARRA)
        linha1.pack(fill='x', padx=14, pady=(8, 2))

        tk.Label(linha1, text="✝️ Bíblia", font=("Arial", 16, "bold"),
                 fg=COR_DESTAQUE, bg=COR_BARRA).pack(side='left')

        label_trilha = tk.Label(linha1, text="Antigo e Novo Testamento",
                                font=("Arial", 12, "bold"),
                                fg=COR_TEXTO, bg=COR_BARRA)
        label_trilha.pack(side='left', padx=(16, 0))

        tk.Button(
            linha1, text="✕ Fechar", font=("Arial", 11, "bold"),
            bg=COR_VERMELHO, fg='#ffffff',
            activebackground=COR_VERMELHO_ATIVO, activeforeground='#ffffff',
            command=lambda: _fechar(), cursor='hand2', padx=12, pady=4
            ).pack(side='right')

        linha2 = tk.Frame(topo, bg=COR_BARRA)
        linha2.pack(fill='x', padx=14, pady=2)

        tk.Label(linha2, text="Versão:", font=("Arial", 11, "bold"),
                 fg=COR_DESTAQUE, bg=COR_BARRA).pack(side='left')
        versao_var = tk.StringVar()
        combo_versao = ttk.Combobox(
            linha2, textvariable=versao_var, state='readonly', width=30,
            font=("Arial", 11))
        combo_versao.pack(side='left', padx=(4, 12))
        # StringVar de Combobox precisa de referência viva (ver AGENTS.md).
        combo_versao._navepro_var = versao_var

        entry_busca = tk.Entry(
            linha2, font=("Arial", 11), bg=COR_CARTAO, fg=COR_APAGADO,
            insertbackground=COR_DESTAQUE, bd=0, highlightthickness=0)
        entry_busca.pack(side='left', fill='x', expand=True,
                         padx=(0, 6), ipady=4)
        entry_busca.insert(0, PLACEHOLDER_BUSCA)

        tk.Button(
            linha2, text="🔍 Buscar", font=("Arial", 10, "bold"),
            bg=COR_AZUL, fg='#ffffff', activebackground=COR_AZUL_ATIVO,
            activeforeground='#ffffff', command=lambda: _executar_busca(),
            cursor='hand2', padx=10, pady=4).pack(side='left', padx=2)
        tk.Button(
            linha2, text="📥 Importar", font=("Arial", 10, "bold"),
            bg=COR_ROXO_ATIVO, fg='#ffffff', activebackground='#a78bfa',
            activeforeground='#ffffff', command=lambda: _importar_dialog(),
            cursor='hand2', padx=10, pady=4).pack(side='left', padx=2)
        tk.Button(
            linha2, text="🎨 Projeção", font=("Arial", 10, "bold"),
            bg=COR_AZUL, fg='#ffffff', activebackground=COR_AZUL_ATIVO,
            activeforeground='#ffffff',
            command=lambda: self.abrir_config_projecao_dialogo(
                janela, mostrar_cor_ref=True),
            cursor='hand2', padx=10, pady=4).pack(side='left', padx=2)

        linha3 = tk.Frame(topo, bg=COR_BARRA)
        linha3.pack(fill='x', padx=14, pady=(2, 8))

        tk.Button(
            linha3, text="◀ Anterior", font=("Arial", 10, "bold"),
            bg=COR_AZUL, fg='#ffffff', activebackground=COR_AZUL_ATIVO,
            activeforeground='#ffffff', command=lambda: _slide_anterior(),
            cursor='hand2', padx=10, pady=2).pack(side='left', padx=(0, 3))
        tk.Button(
            linha3, text="Próximo ▶", font=("Arial", 10, "bold"),
            bg=COR_AZUL, fg='#ffffff', activebackground=COR_AZUL_ATIVO,
            activeforeground='#ffffff', command=lambda: _slide_proximo(),
            cursor='hand2', padx=10, pady=2).pack(side='left', padx=3)
        tk.Button(
            linha3, text="⏹ Parar", font=("Arial", 10, "bold"),
            bg=COR_VERMELHO, fg='#ffffff',
            activebackground=COR_VERMELHO_ATIVO, activeforeground='#ffffff',
            command=lambda: _parar_projecao(), cursor='hand2',
            padx=10, pady=2).pack(side='left', padx=3)

        tk.Label(linha3, text="🔠", font=("Arial", 10, "bold"),
                 fg=COR_DESTAQUE, bg=COR_BARRA).pack(side='left',
                                                     padx=(12, 2))
        tk.Button(
            linha3, text="A−", font=("Arial", 10, "bold"),
            bg=COR_ROXO_ATIVO, fg='#ffffff', activebackground='#a78bfa',
            activeforeground='#ffffff', command=lambda: _ajustar_fonte(-0.8),
            cursor='hand2', padx=8, pady=2).pack(side='left', padx=2)
        tk.Button(
            linha3, text="A+", font=("Arial", 10, "bold"),
            bg=COR_ROXO_ATIVO, fg='#ffffff', activebackground='#a78bfa',
            activeforeground='#ffffff', command=lambda: _ajustar_fonte(0.8),
            cursor='hand2', padx=8, pady=2).pack(side='left', padx=2)
        tk.Button(
            linha3, text="🔃", font=("Arial", 10, "bold"),
            bg=COR_ROXO_ATIVO, fg='#ffffff', activebackground='#a78bfa',
            activeforeground='#ffffff', command=lambda: _restaurar_fonte(),
            cursor='hand2', padx=8, pady=2).pack(side='left', padx=2)

        label_slide = tk.Label(linha3, text="Sem projeção",
                               font=("Arial", 10, "bold"),
                               fg=COR_APAGADO, bg=COR_BARRA)
        label_slide.pack(side='right')

        # ── Áreas roláveis (livros / capítulos / versículos) ──
        def _criar_area_rolavel(parent, titulo: str):
            area = tk.Frame(parent, bg=COR_FUNDO)
            cabecalho = tk.Label(
                area, text=titulo, font=("Arial", 10, "bold"),
                fg=COR_DESTAQUE, bg=COR_FUNDO, anchor='w')
            cabecalho.pack(fill='x', padx=4)
            container = tk.Frame(area, bg=COR_FUNDO)
            container.pack(fill='both', expand=True)
            canvas = tk.Canvas(container, bg=COR_FUNDO, width=1, height=1,
                               highlightthickness=0, bd=0)
            barra = ttk.Scrollbar(container, orient='vertical',
                                  command=canvas.yview)
            canvas.configure(yscrollcommand=barra.set)
            canvas.pack(side='left', fill='both', expand=True)
            barra.pack(side='right', fill='y')
            return area, canvas, cabecalho

        corpo = tk.Frame(janela, bg=COR_FUNDO)
        corpo.pack(fill='both', expand=True)
        corpo.grid_rowconfigure(0, weight=1)
        corpo.grid_columnconfigure(0, weight=3, uniform='corpo')
        corpo.grid_columnconfigure(1, weight=7)

        # Coluna esquerda, altura toda: versículos por extenso.
        area_versiculos, canvas_versiculos, titulo_versiculos = \
            _criar_area_rolavel(corpo, "Versículos")
        area_versiculos.grid(row=0, column=0, sticky='nsew',
                             padx=(10, 5), pady=(2, 8))

        lateral = tk.Frame(corpo, bg=COR_FUNDO)
        lateral.grid(row=0, column=1, sticky='nsew',
                     padx=(5, 10), pady=(2, 8))
        lateral.grid_columnconfigure(0, weight=1)
        lateral.grid_rowconfigure(0, weight=1)
        lateral.grid_rowconfigure(1, weight=1)

        # Topo da direita: livros.
        area_livros, canvas_livros, titulo_livros = \
            _criar_area_rolavel(lateral, "Livros")
        area_livros.grid(row=0, column=0, sticky='nsew', pady=(0, 4))

        # Abaixo dos livros: capítulos (esquerda) e números dos
        # versículos (direita), com o mesmo formato de botão.
        rodape = tk.Frame(lateral, bg=COR_FUNDO)
        rodape.grid(row=1, column=0, sticky='nsew', pady=(4, 0))
        rodape.grid_rowconfigure(0, weight=1)
        rodape.grid_columnconfigure(0, weight=2, uniform='rodape')
        rodape.grid_columnconfigure(1, weight=3)

        area_capitulos, canvas_capitulos, titulo_capitulos = \
            _criar_area_rolavel(rodape, "Capítulos")
        area_capitulos.grid(row=0, column=0, sticky='nsew', padx=(0, 5))

        area_numeros, canvas_numeros, titulo_numeros = \
            _criar_area_rolavel(rodape, "Versículos")
        area_numeros.grid(row=0, column=1, sticky='nsew', padx=(5, 0))

        # ── Versões ──
        def _versoes_disponiveis() -> list[str]:
            if _CACHE_BIBLIA['versoes'] is not None:
                return list(_CACHE_BIBLIA['versoes'])
            rows = db_query(
                "SELECT DISTINCT versao FROM versiculos ORDER BY versao")
            _CACHE_BIBLIA['versoes'] = [r['versao'] for r in rows]
            return list(_CACHE_BIBLIA['versoes'])

        versoes = _versoes_disponiveis()
        if not versoes:
            versoes = ["Almeida Revista e Corrigida"]
        versao_padrao = ("Almeida Revista e Corrigida"
                         if "Almeida Revista e Corrigida" in versoes
                         else versoes[0])
        versao_var.set(versao_padrao)
        combo_versao.config(values=versoes)

        # ── Rolagem com a roda do mouse na área sob o ponteiro ──
        def _rolar_mouse(event):
            try:
                widget = janela.winfo_containing(event.x_root, event.y_root)
            except tk.TclError:
                widget = None
            alvo = None
            areas = (canvas_livros, canvas_capitulos, canvas_numeros,
                     canvas_versiculos)
            while widget is not None:
                if widget in areas:
                    alvo = widget
                    break
                widget = widget.master
            if alvo is None:
                return 'break'
            if getattr(event, 'num', None) == 4:
                alvo.yview_scroll(-3, 'units')
            elif getattr(event, 'num', None) == 5:
                alvo.yview_scroll(3, 'units')
            else:
                delta = int(getattr(event, 'delta', 0) or 0)
                if delta:
                    alvo.yview_scroll(int(-delta / 120) * 3, 'units')
            return 'break'

        janela.bind('<MouseWheel>', _rolar_mouse)
        janela.bind('<Button-4>', _rolar_mouse)
        janela.bind('<Button-5>', _rolar_mouse)

        # ── Ajudantes de desenho (tudo em canvas) ──
        def _largura_canvas(canvas, fracao: float, minimo: int) -> int:
            largura = canvas.winfo_width()
            if largura <= 1:
                largura = max(minimo, int(largura_inicial * fracao))
            return largura

        def _desenhar_mensagem(canvas, titulo: str, dica: str = '') -> None:
            canvas.delete('all')
            largura = _largura_canvas(canvas, 0.3, 220)
            canvas.create_text(largura / 2, 24, text=titulo,
                               font=("Arial", 12, "bold"), fill=COR_TEXTO,
                               anchor='n', width=largura - 24,
                               justify='center')
            if dica:
                canvas.create_text(largura / 2, 48, text=dica,
                                   font=("Arial", 9), fill=COR_APAGADO,
                                   anchor='n', width=largura - 24,
                                   justify='center')
            canvas.configure(scrollregion=(0, 0, largura, 80))

        def _largura_versiculos() -> int:
            largura = canvas_versiculos.winfo_width()
            if largura <= 1:
                largura = max(220, (largura_inicial * 3) // 10)
            return largura

        def _rolar_ate(canvas, item_id) -> None:
            try:
                janela.update_idletasks()
                caixa = canvas.bbox(item_id)
                total = canvas.bbox('all')
                if not caixa or not total:
                    return
                altura_total = max(1, total[3] - total[1])
                altura_item = caixa[3] - caixa[1]
                altura_visivel = canvas.winfo_height()
                alvo = max(0, caixa[1] - total[1] - max(
                    0, (altura_visivel - altura_item) // 2))
                canvas.yview_moveto(min(1.0, alvo / altura_total))
            except tk.TclError:
                pass

        def _desenhar_grade(canvas, valores, colunas: int, cel_w: float,
                            cel_h: int, prefixo: str, comando) -> dict:
            itens: dict = {}
            for i, valor in enumerate(valores):
                coluna = i % colunas
                linha = i // colunas
                x = coluna * cel_w
                y = linha * cel_h
                tag = f"{prefixo}_{i}"
                rect = canvas.create_rectangle(
                    x + 2, y + 2, x + cel_w - 2, y + cel_h - 2,
                    fill=COR_CARTAO, outline='', tags=(tag,))
                texto = canvas.create_text(
                    x + cel_w / 2, y + cel_h / 2, text=str(valor),
                    font=("Arial", 11, "bold"), fill=COR_TEXTO,
                    anchor='center', tags=(tag,))
                itens[valor] = {'rect': rect, 'texto': texto}
                canvas.tag_bind(
                    tag, '<Button-1>',
                    lambda e, v=valor: comando(v))
            return itens

        # ── Destaques ──
        def _pintar_item(canvas, item, ativo: bool) -> None:
            try:
                canvas.itemconfigure(
                    item['rect'], fill=COR_ROXO if ativo else COR_CARTAO)
                canvas.itemconfigure(
                    item['texto'], fill='#ffffff' if ativo else COR_TEXTO)
            except tk.TclError:
                pass

        def _pintar_livro(nome: str) -> None:
            item = _itens_livros.get(nome)
            if item is None:
                return
            ativo = nome == estado['livro']
            hover = nome == _livro_hover[0]
            fundo = COR_ROXO if ativo else (COR_HOVER if hover else COR_CARTAO)
            texto = '#ffffff' if (ativo or hover) else COR_TEXTO
            try:
                canvas_livros.itemconfigure(item['rect'], fill=fundo)
                canvas_livros.itemconfigure(item['abrev'], fill=texto)
                canvas_livros.itemconfigure(item['nome'], fill=texto)
            except tk.TclError:
                pass

        def _destacar_livro(_livro: str | None = None) -> None:
            for nome in _itens_livros:
                _pintar_livro(nome)

        def _definir_hover_livro(nome: str | None) -> None:
            if _livro_hover[0] == nome:
                return
            anterior = _livro_hover[0]
            _livro_hover[0] = nome
            for alvo in (anterior, nome):
                if alvo:
                    _pintar_livro(alvo)

        def _destacar_capitulo(cap: int | None) -> None:
            for numero, item in _itens_capitulos.items():
                _pintar_item(canvas_capitulos, item, numero == cap)

        def _destacar_versiculo(num: int | None,
                                rolar: bool = True) -> None:
            for numero, item in _itens_versos.items():
                _pintar_item(canvas_versiculos, item, numero == num)
            for numero, item in _itens_numeros.items():
                _pintar_item(canvas_numeros, item, numero == num)
            if num is not None and rolar:
                if num in _itens_versos:
                    _rolar_ate(canvas_versiculos,
                               _itens_versos[num]['rect'])
                if num in _itens_numeros:
                    _rolar_ate(canvas_numeros,
                               _itens_numeros[num]['rect'])

        def _versiculo_projetado() -> int | None:
            telao = self.player.telao
            if _projecao_ref[0] != (estado['livro'], estado['cap']):
                return None
            if (getattr(telao, '_em_slides', False) and _cap_numeros
                    and 0 <= telao._slide_index < len(_cap_numeros)):
                return _cap_numeros[telao._slide_index]
            return None

        # ── Indicador / sincronia com o telão ──
        def _atualizar_indicador() -> None:
            try:
                if not label_slide.winfo_exists():
                    return
            except tk.TclError:
                return
            telao = self.player.telao
            projetando_capitulo = (
                _projecao_ref[0] == (estado['livro'], estado['cap']))
            if (getattr(telao, '_em_slides', False) and telao._slides
                    and projetando_capitulo):
                idx = telao._slide_index
                num = (_cap_numeros[idx]
                       if 0 <= idx < len(_cap_numeros) else idx + 1)
                label_slide.config(
                    text=f"Versículo {num} de {len(telao._slides)}",
                    fg=COR_VERDE, bg=COR_BARRA)
            elif getattr(telao, 'mostrando_letra', False):
                label_slide.config(text="Projeção ativa", fg=COR_DESTAQUE,
                                   bg=COR_BARRA)
            else:
                label_slide.config(text="Sem projeção", fg=COR_APAGADO,
                                   bg=COR_BARRA)

        def _refletir_telao() -> None:
            _destacar_versiculo(_versiculo_projetado())
            _atualizar_indicador()

        def _ao_parar() -> None:
            _projecao_ref[0] = None
            _destacar_versiculo(None)
            _atualizar_indicador()

        # ── Projeção ──
        def _projetar_versiculo(num: int) -> None:
            if not _versos_atuais:
                return
            livro = estado['livro']
            cap = estado['cap']
            numeros = [r['versiculo'] for r in _versos_atuais]
            slides = [(r['texto'], f"{livro} {cap}:{r['versiculo']}")
                      for r in _versos_atuais]
            try:
                inicio = numeros.index(num)
            except ValueError:
                inicio = 0
            self.player.telao.projetar_slides(slides, indice_inicial=inicio)
            _projecao_ref[0] = (livro, cap)
            _destacar_versiculo(num)
            _atualizar_indicador()

        def _ajustar_fonte(delta: float) -> None:
            self._ajustar_fonte_projecao(delta, _atualizar_indicador)

        def _restaurar_fonte() -> None:
            self._restaurar_fonte_projecao(_atualizar_indicador)

        _slide_anterior, _slide_proximo, _parar_projecao = \
            self._criar_navegacao_slides(ao_navegar=_refletir_telao,
                                         ao_parar=_ao_parar)

        # ── Consultas ──
        def _livros_da_versao() -> list[str]:
            versao = versao_var.get()
            if versao in _CACHE_BIBLIA['livros']:
                return list(_CACHE_BIBLIA['livros'][versao])
            rows = db_query(
                "SELECT DISTINCT livro FROM versiculos WHERE versao = ?",
                (versao,))
            presentes = {r['livro'] for r in rows}
            ordenados = [livro for livro in self.LIVROS_BIBLIA
                         if livro in presentes]
            extras = sorted(presentes - set(self.LIVROS_BIBLIA))
            livros = ordenados + extras
            _CACHE_BIBLIA['livros'][versao] = livros
            return list(livros)

        def _capitulos(livro: str | None) -> list[int]:
            if not livro:
                return []
            chave = (versao_var.get(), livro)
            if chave in _CACHE_BIBLIA['capitulos']:
                return list(_CACHE_BIBLIA['capitulos'][chave])
            rows = db_query(
                "SELECT DISTINCT capitulo FROM versiculos WHERE versao = ? "
                "AND livro = ? ORDER BY capitulo", chave)
            capitulos = [r['capitulo'] for r in rows]
            _CACHE_BIBLIA['capitulos'][chave] = capitulos
            return list(capitulos)

        # ── Renderização ──
        def _renderizar_livros() -> list[str]:
            canvas_livros.delete('all')
            _itens_livros.clear()
            _livro_hover[0] = None
            livros = _livros_da_versao()
            titulo_livros.config(text=f"Livros ({len(livros)})")
            if not livros:
                _desenhar_mensagem(
                    canvas_livros,
                    "Nenhuma Bíblia importada nesta versão.",
                    "Use o botão '📥 Importar' para adicionar uma Bíblia.")
                return livros
            largura = _largura_canvas(canvas_livros, 0.7, 300)
            colunas = max(9, min(16, largura // 60))
            cel_w = largura / colunas
            cel_h = 50
            for i, livro in enumerate(livros):
                coluna = i % colunas
                linha = i // colunas
                x = coluna * cel_w
                y = linha * cel_h
                tag = f"livro_{i}"
                rect = canvas_livros.create_rectangle(
                    x + 2, y + 2, x + cel_w - 2, y + cel_h - 2,
                    fill=COR_CARTAO, outline='', tags=(tag,))
                abreviatura = ABREVIACOES_BIBLIA.get(livro, livro[:2])
                abrev = canvas_livros.create_text(
                    x + cel_w / 2, y + 5, text=abreviatura,
                    font=("Arial", 12, "bold"), fill=COR_TEXTO,
                    anchor='n', tags=(tag,))
                nome_id = canvas_livros.create_text(
                    x + cel_w / 2, y + 23, text=livro, font=("Arial", 7),
                    fill=COR_TEXTO, anchor='n',
                    width=max(30, int(cel_w) - 8), justify='center',
                    tags=(tag,))
                _itens_livros[livro] = {'rect': rect, 'abrev': abrev,
                                        'nome': nome_id}
                canvas_livros.tag_bind(
                    tag, '<Button-1>',
                    lambda e, nome=livro: _selecionar_livro(nome))
                canvas_livros.tag_bind(
                    tag, '<Enter>',
                    lambda e, nome=livro: _definir_hover_livro(nome))
                canvas_livros.tag_bind(
                    tag, '<Leave>',
                    lambda e: _definir_hover_livro(None))
            altura = ((len(livros) + colunas - 1) // colunas) * cel_h
            canvas_livros.configure(scrollregion=(0, 0, largura, altura))
            _destacar_livro(estado['livro'])
            return livros

        def _renderizar_capitulos(livro: str | None,
                                  caps: list[int] | None = None) -> None:
            canvas_capitulos.delete('all')
            _itens_capitulos.clear()
            titulo_capitulos.config(
                text=f"Capítulos — {livro}" if livro else "Capítulos")
            if not livro:
                _desenhar_mensagem(canvas_capitulos,
                                   "Escolha um livro acima.")
                return
            if caps is None:
                caps = _capitulos(livro)
            if not caps:
                _desenhar_mensagem(canvas_capitulos,
                                   "Nenhum capítulo encontrado.")
                return
            largura = _largura_canvas(canvas_capitulos, 0.28, 180)
            colunas = max(4, min(14, largura // 46))
            cel_w = largura / colunas
            cel_h = 38
            _itens_capitulos.update(_desenhar_grade(
                canvas_capitulos, caps, colunas, cel_w, cel_h,
                "cap", _selecionar_capitulo))
            altura = ((len(caps) + colunas - 1) // colunas) * cel_h
            canvas_capitulos.configure(scrollregion=(0, 0, largura, altura))
            _destacar_capitulo(estado['cap'])

        def _renderizar_numeros(livro: str | None, cap: int | None) -> None:
            canvas_numeros.delete('all')
            _itens_numeros.clear()
            if not livro or cap is None:
                titulo_numeros.config(text="Versículos")
                _desenhar_mensagem(canvas_numeros, "Escolha um capítulo.")
                return
            titulo_numeros.config(text=f"Versículos — {livro} {cap}")
            nums = [r['versiculo'] for r in _versos_atuais]
            if not nums:
                _desenhar_mensagem(canvas_numeros, "Nenhum versículo.")
                return
            largura = _largura_canvas(canvas_numeros, 0.42, 220)
            colunas = max(4, min(18, largura // 46))
            cel_w = largura / colunas
            cel_h = 38
            _itens_numeros.update(_desenhar_grade(
                canvas_numeros, nums, colunas, cel_w, cel_h,
                "num", _projetar_versiculo))
            altura = ((len(nums) + colunas - 1) // colunas) * cel_h
            canvas_numeros.configure(scrollregion=(0, 0, largura, altura))
            _destacar_versiculo(_versiculo_projetado(), rolar=False)

        def _renderizar_versiculos(livro: str, cap: int) -> None:
            nonlocal _versos_atuais
            canvas_versiculos.delete('all')
            _itens_versos.clear()
            _resultado_atual[:] = [None, None]
            titulo_versiculos.config(text=f"Versículos — {livro} {cap}")
            rows = db_query(
                "SELECT versiculo, texto FROM versiculos WHERE versao = ? "
                "AND livro = ? AND capitulo = ? ORDER BY versiculo",
                (versao_var.get(), livro, cap))
            _versos_atuais = list(rows)
            _cap_numeros[:] = [r['versiculo'] for r in _versos_atuais]
            if not _versos_atuais:
                _desenhar_mensagem(
                    canvas_versiculos,
                    "Nenhum versículo encontrado neste capítulo.")
                _renderizar_numeros(None, None)
                _atualizar_indicador()
                return
            largura = _largura_versiculos()
            y = 4
            for r in _versos_atuais:
                num = r['versiculo']
                tag = f"verso_{num}"
                texto_id = canvas_versiculos.create_text(
                    12, y + 6, text=f"{num}. {r['texto']}",
                    font=("Arial", 11), fill=COR_TEXTO, anchor='nw',
                    width=max(120, largura - 24), justify='left',
                    tags=(tag,))
                caixa = canvas_versiculos.bbox(texto_id)
                altura = (caixa[3] - caixa[1]) if caixa else 18
                rect = canvas_versiculos.create_rectangle(
                    4, y, largura - 4, y + altura + 12,
                    fill=COR_CARTAO, outline='', tags=(tag,))
                canvas_versiculos.tag_lower(rect, texto_id)
                _itens_versos[num] = {'rect': rect, 'texto': texto_id}
                canvas_versiculos.tag_bind(
                    tag, '<Button-1>',
                    lambda e, n=num: _projetar_versiculo(n))
                y += altura + 16
            canvas_versiculos.configure(
                scrollregion=(0, 0, largura, max(y, 1)))
            _renderizar_numeros(livro, cap)
            _atualizar_indicador()

        def _renderizar_resultados(termo: str, rows: list) -> None:
            canvas_versiculos.delete('all')
            _itens_versos.clear()
            _resultado_atual[:] = [termo, list(rows)]
            canvas_numeros.delete('all')
            _itens_numeros.clear()
            titulo_numeros.config(text="Versículos")
            _desenhar_mensagem(canvas_numeros, "Resultados da busca.")
            titulo_versiculos.config(
                text=f"Resultados — “{termo}” ({len(rows)})")
            if not rows:
                _desenhar_mensagem(
                    canvas_versiculos,
                    "Nenhum versículo encontrado para esta busca.",
                    "Tente outro termo ou importe uma Bíblia.")
                _atualizar_indicador()
                return
            largura = _largura_versiculos()
            y = 4
            for i, r in enumerate(rows):
                texto = (f"{r['livro']} {r['capitulo']}:{r['versiculo']} — "
                         f"{r['texto']}")
                tag = f"busca_{i}"
                texto_id = canvas_versiculos.create_text(
                    12, y + 6, text=texto, font=("Arial", 11),
                    fill=COR_TEXTO, anchor='nw',
                    width=max(120, largura - 24), justify='left',
                    tags=(tag,))
                caixa = canvas_versiculos.bbox(texto_id)
                altura = (caixa[3] - caixa[1]) if caixa else 18
                rect = canvas_versiculos.create_rectangle(
                    4, y, largura - 4, y + altura + 12,
                    fill=COR_CARTAO, outline='', tags=(tag,))
                canvas_versiculos.tag_lower(rect, texto_id)
                canvas_versiculos.tag_bind(
                    tag, '<Button-1>',
                    lambda e, li=r['livro'], ca=r['capitulo'],
                    ve=r['versiculo']: _ir_para(li, ca, ve))
                y += altura + 16
            canvas_versiculos.configure(
                scrollregion=(0, 0, largura, max(y, 1)))
            _atualizar_indicador()

        # ── Seleção ──
        def _atualizar_trilha() -> None:
            livro = estado['livro']
            cap = estado['cap']
            if livro and cap is not None:
                label_trilha.config(text=f"📚 {livro} · Capítulo {cap}")
            elif livro:
                label_trilha.config(text=f"📚 {livro}")
            else:
                label_trilha.config(text="Antigo e Novo Testamento")

        def _limpar_versiculos(mensagem: str = "Selecione um livro.") -> None:
            nonlocal _versos_atuais
            canvas_versiculos.delete('all')
            _itens_versos.clear()
            canvas_numeros.delete('all')
            _itens_numeros.clear()
            _versos_atuais = []
            _cap_numeros[:] = []
            _resultado_atual[:] = [None, None]
            titulo_versiculos.config(text="Versículos")
            titulo_numeros.config(text="Versículos")
            _desenhar_mensagem(canvas_versiculos, mensagem)
            _desenhar_mensagem(canvas_numeros, "Escolha um capítulo.")
            _atualizar_indicador()

        def _ir_para(livro: str, cap: int, versiculo: int | None = None) -> None:
            estado.update(livro=livro, cap=cap, modo='capitulo')
            _destacar_livro(livro)
            _renderizar_capitulos(livro)
            _renderizar_versiculos(livro, cap)
            _atualizar_trilha()
            if versiculo is not None:
                _projetar_versiculo(versiculo)

        def _selecionar_livro(livro: str) -> None:
            estado.update(livro=livro, modo='capitulo')
            caps = _capitulos(livro)
            estado['cap'] = caps[0] if caps else None
            _destacar_livro(livro)
            _renderizar_capitulos(livro, caps)
            if estado['cap'] is not None:
                _renderizar_versiculos(livro, estado['cap'])
            else:
                _limpar_versiculos("Nenhum versículo neste livro.")
            _atualizar_trilha()

        def _selecionar_capitulo(cap: int) -> None:
            if not estado['livro']:
                return
            estado.update(cap=cap, modo='capitulo')
            _destacar_capitulo(cap)
            _renderizar_versiculos(estado['livro'], cap)
            _atualizar_trilha()

        def _recarregar_versao() -> None:
            livro = estado['livro']
            cap = estado['cap']
            livros = _livros_da_versao()
            if livro not in livros:
                livro = livros[0] if livros else None
                cap = None
            caps = _capitulos(livro) if livro else []
            if cap not in caps:
                cap = caps[0] if caps else None
            estado.update(livro=livro, cap=cap, modo='capitulo')
            _renderizar_livros()
            _renderizar_capitulos(livro, caps)
            if livro and cap is not None:
                _renderizar_versiculos(livro, cap)
            else:
                _limpar_versiculos()
            _atualizar_trilha()

        # ── Busca por texto ──
        def _ao_focus_in(_event=None) -> None:
            if entry_busca.get().strip() == PLACEHOLDER_BUSCA:
                entry_busca.delete(0, tk.END)
                entry_busca.config(fg=COR_DESTAQUE)

        def _ao_focus_out(_event=None) -> None:
            if not entry_busca.get().strip():
                entry_busca.delete(0, tk.END)
                entry_busca.insert(0, PLACEHOLDER_BUSCA)
                entry_busca.config(fg=COR_APAGADO)

        entry_busca.bind('<FocusIn>', _ao_focus_in)
        entry_busca.bind('<FocusOut>', _ao_focus_out)

        def _executar_busca(event=None):
            termo = entry_busca.get().strip()
            if not termo or termo == PLACEHOLDER_BUSCA:
                estado['modo'] = 'capitulo'
                if estado['livro'] and estado['cap'] is not None:
                    _renderizar_versiculos(estado['livro'], estado['cap'])
                    _atualizar_trilha()
                return 'break'
            rows = _buscar_versiculos_por_texto(versao_var.get(), termo)
            estado['modo'] = 'resultados'
            _renderizar_resultados(termo, rows)
            return 'break'

        entry_busca.bind('<Return>', _executar_busca)

        # ── Versão / importação ──
        def _ao_trocar_versao(_event=None) -> None:
            if estado['modo'] == 'resultados':
                _executar_busca()
            else:
                _recarregar_versao()

        combo_versao.bind('<<ComboboxSelected>>', _ao_trocar_versao)

        def _importar_dialog() -> None:
            selecionados = _escolher_arquivos_usuario(
                parent=janela,
                titulo="Importar Bíblia (XML / TXT / JSON)",
                pasta_inicial=os.path.expanduser("~"))
            if not selecionados:
                return
            resumo = importar_biblias(selecionados, self.LIVROS_BIBLIA)
            _invalidar_cache_biblia()
            msg = (f"✅ {resumo['inseridos']} versículos importados, "
                   f"{resumo['pulados']} já existentes (pulados).")
            if resumo['versoes']:
                msg += f"\n📚 Versões: {', '.join(resumo['versoes'])}"
            if resumo['desconhecidos']:
                msg += (f"\n⚠️ {len(resumo['desconhecidos'])} livro(s) não "
                        f"reconhecidos: "
                        f"{', '.join(str(x) for x in sorted(resumo['desconhecidos']))}")
            if resumo['erros']:
                msg += f"\n⚠️ {resumo['erros']} arquivo(s) com erro."
            tkinter.messagebox.showinfo("Importação de Bíblia", msg,
                                        parent=janela)
            versoes = _versoes_disponiveis()
            if versoes:
                combo_versao.config(values=versoes)
            if resumo['versoes']:
                versao_var.set(resumo['versoes'][0])
            _recarregar_versao()

        # ── Responsividade ──
        def _redimensionar() -> None:
            _id_resize[0] = None
            try:
                if not janela.winfo_exists():
                    return
                if (janela.winfo_width(), janela.winfo_height()) == \
                        _tamanho_renderizado[0]:
                    return
            except tk.TclError:
                return
            janela.update_idletasks()
            _renderizar_livros()
            if estado['livro']:
                _renderizar_capitulos(estado['livro'])
                if estado['modo'] == 'resultados':
                    termo, rows = _resultado_atual
                    if termo is not None:
                        _renderizar_resultados(termo, rows)
                elif estado['cap'] is not None and _versos_atuais:
                    _renderizar_versiculos(estado['livro'], estado['cap'])
            try:
                _tamanho_renderizado[0] = (janela.winfo_width(),
                                           janela.winfo_height())
            except tk.TclError:
                pass

        def _ao_redimensionar_janela(event) -> None:
            if event.widget is not janela:
                return
            # A carga inicial ainda não desenhou a janela: os Configure do
            # fullscreen não devem disparar um segundo desenho completo.
            if _tamanho_renderizado[0] is None:
                return
            if (event.width, event.height) == _tamanho_renderizado[0]:
                return
            if _id_resize[0] is not None:
                try:
                    janela.after_cancel(_id_resize[0])
                except tk.TclError:
                    pass
            _id_resize[0] = janela.after(180, _redimensionar)

        # ── Janela / teclado ──
        def _fechar() -> None:
            try:
                janela.destroy()
            except tk.TclError:
                pass

        def _toggle_fullscreen() -> str:
            try:
                atual = bool(janela.attributes('-fullscreen'))
                janela.attributes('-fullscreen', not atual)
                if atual:
                    janela.geometry('1200x800')
                    _centralizar_sobre(janela, self.root)
            except tk.TclError:
                pass
            return 'break'

        def _ao_escape(_event=None) -> str:
            if getattr(self.player.telao, 'mostrando_letra', False):
                _parar_projecao()
            else:
                _fechar()
            return 'break'

        def _nav_tecla(acao):
            def _handler(_event=None):
                try:
                    foco = janela.focus_get()
                    if foco is not None and foco.winfo_class() in (
                            'Entry', 'TEntry', 'Text', 'Spinbox',
                            'TCombobox'):
                        return None
                except tk.TclError:
                    pass
                return acao()
            return _handler

        def _ao_destruir(event) -> None:
            if event.widget is not janela:
                return
            for chave in (_id_carga, _id_resize):
                if chave[0] is not None:
                    try:
                        janela.after_cancel(chave[0])
                    except tk.TclError:
                        pass
                    chave[0] = None
            if getattr(self, '_biblia_grade', None) is janela:
                self._biblia_grade = None

        janela.bind('<Left>', _nav_tecla(_slide_anterior))
        janela.bind('<Up>', _nav_tecla(_slide_anterior))
        janela.bind('<Right>', _nav_tecla(_slide_proximo))
        janela.bind('<Down>', _nav_tecla(_slide_proximo))
        janela.bind('<Escape>', _ao_escape)
        janela.bind('<F11>', lambda e: _toggle_fullscreen())
        janela.bind('<Control-f>', lambda e: (entry_busca.focus_set(),
                                              'break')[1])
        janela.bind('<Control-F>', lambda e: (entry_busca.focus_set(),
                                              'break')[1])
        janela.bind('<Destroy>', _ao_destruir)

        # ── Carga inicial ──
        # A janela já aparece com a barra superior; o índice e a grade são
        # consultados/desenhados numa tarefa ociosa, depois que o Tk pinta a
        # janela. Assim a abertura não fica bloqueada pelas consultas e pelo
        # desenho dos livros.
        def _carga_inicial() -> None:
            _id_carga[0] = None
            try:
                if not janela.winfo_exists():
                    return
            except tk.TclError:
                return
            janela.update_idletasks()
            livros = _renderizar_livros()
            if livros:
                _selecionar_livro(livros[0])
            else:
                _renderizar_capitulos(None)
                _limpar_versiculos()
            _atualizar_trilha()
            try:
                _tamanho_renderizado[0] = (janela.winfo_width(),
                                           janela.winfo_height())
                janela.bind('<Configure>', _ao_redimensionar_janela)
            except tk.TclError:
                pass

        _id_carga[0] = janela.after_idle(_carga_inicial)
