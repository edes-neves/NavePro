"""Painel do operador: criação de widgets e menu (mixin).

Extraído de NavePro.py sem alteração de comportamento: a AppInterface
herda deste mixin para montar a interface principal.
"""

from __future__ import annotations

import os
import tkinter as tk
import tkinter.messagebox
import tkinter.simpledialog

from navepro.config import APP_VERSION
from navepro.core.icones import _carregar_emoji, _carregar_icone
from navepro.core.log import get_logger
from navepro.core.paths import _caminho_recurso
from navepro.core.widgets_arredondados import TkArredondado
from navepro.ui.apoio import _criar_faixa_secao, _marcar_area_cinza_clara

log = get_logger("painel")

# Botões e campos desenham cantos arredondados (fachada do tkinter).
tk = TkArredondado(tk)


class PainelMixin:
    def criar_widgets(self) -> None:
        """Cria todos os widgets da interface principal."""
        main_frame = tk.Frame(self.root, bg='#0d1117')
        main_frame.pack(fill='both', expand=True, padx=32, pady=24)

        # ── Logo / Identidade visual ──
        logo_frame = tk.Frame(main_frame, bg='#0d1117')
        logo_frame.pack(pady=(0, 8))
        try:
            from PIL import Image, ImageTk
            logo_img = Image.open(_caminho_recurso(os.path.join("img", 'Icon.png'))).resize((48, 48), Image.LANCZOS)
            self._logo_tk = ImageTk.PhotoImage(logo_img)
            tk.Label(logo_frame, image=self._logo_tk, bg='#0d1117').pack(side='left', padx=(0, 10))
        except Exception:
            # Fallback: texto estilizado
            tk.Label(logo_frame, text="🎬", font=("Arial", 28), bg='#0d1117', fg='#f0c040'
                    ).pack(side='left', padx=(0, 10))

        tk.Label(logo_frame, text="NAVEPRO",
                font=("Arial", 18, "bold"), bg='#0d1117', fg='#f0c040'
                ).pack(side='left')
        tk.Label(logo_frame, text=f"Versão {APP_VERSION}",
                font=("Arial", 9), bg='#0d1117', fg='#8b949e'
                ).pack(side='left', padx=(8, 0))

        # Título
        tk.Label(
            main_frame,
            text="Sistema de Projeção Profissional",
            font=("Adventist Sans", 20, "bold"),
            fg='#f0c040', bg='#0d1117'
        ).pack(pady=(10, 5))

        # Separador sutil
        sep1 = tk.Frame(main_frame, bg='#30363d', height=1)
        sep1.pack(fill='x', padx=40, pady=(0, 8))

        # Relógio
        self.hora_label = tk.Label(
            main_frame, text="",
            font=("Digital-7", 30, "bold"),
            fg="#f0c040", bg='#0d1117'
        )
        self.hora_label.pack(pady=5)

        # Temperatura
        self.temp_label = tk.Label(
            main_frame, text="",
            font=("Digital-7", 24, "bold"),
            fg="#58a6ff", bg='#0d1117'
        )
        self.temp_label.pack(pady=2)

        # Status
        self.status_label = tk.Label(
            main_frame, text="",
            font=("Arial", 14),
            fg='#f0c040', bg='#0d1117'
        )
        self.status_label.pack(pady=5)

        # ── Cidade / Clima ──
        # Card de clima com visual destacado
        clima_card = tk.Frame(main_frame, bg='#161b22', highlightbackground='#30363d',
                               highlightthickness=1)
        clima_card.pack(pady=5, ipady=8, ipadx=15)
        _criar_faixa_secao(clima_card, topo=True)

        # Linha 1: Cidade + Estado + Salvar
        clima_linha1 = tk.Frame(clima_card, bg='#161b22')
        clima_linha1.pack(pady=(2, 0))

        tk.Label(
            clima_linha1, text="📍",
            font=("Arial", 14),
            fg='#f0c040', bg='#161b22'
        ).pack(side='left', padx=(0, 8))

        self.entry_cidade = tk.Entry(
            clima_linha1, width=15, font=("Arial", 11),
            bg='#eaeef2', fg='#1f2328', insertbackground='#1f2328',
            justify='center', bd=0, highlightthickness=0
        )
        self.entry_cidade.pack(side='left', padx=2, ipady=3)
        self.entry_cidade.insert(0, "Cidade")
        self.entry_cidade.config(fg='#656d76')
        _marcar_area_cinza_clara(self.entry_cidade, '#eaeef2')
        self.entry_cidade.bind("<FocusIn>", lambda e: self._on_focus_cidade())
        self.entry_cidade.bind("<FocusOut>", lambda e: self._on_focus_out_cidade())
        self.entry_cidade.bind("<KeyRelease>", self._reset_focus_timer)

        if self.cidade_salva:
            self.entry_cidade.delete(0, tk.END)
            self.entry_cidade.insert(0, self.cidade_salva)
            self.entry_cidade.config(fg='#1f2328')

        self.entry_estado = tk.Entry(
            clima_linha1, width=5, font=("Arial", 11),
            bg='#eaeef2', fg='#1f2328', insertbackground='#1f2328',
            justify='center', bd=0, highlightthickness=0
        )
        self.entry_estado.pack(side='left', padx=2, ipady=3)
        self.entry_estado.insert(0, "UF")
        self.entry_estado.config(fg='#656d76')
        _marcar_area_cinza_clara(self.entry_estado, '#eaeef2')
        self.entry_estado.bind("<FocusIn>", lambda e: self._on_focus_estado())
        self.entry_estado.bind("<FocusOut>", lambda e: self._on_focus_out_estado())
        self.entry_estado.bind("<KeyRelease>", self._reset_focus_timer)

        if self.estado_salvo:
            self.entry_estado.delete(0, tk.END)
            self.entry_estado.insert(0, self.estado_salvo)
            self.entry_estado.config(fg='#1f2328')

        tk.Button(
            clima_linha1, text="Salvar",
            font=("Arial", 10, "bold"),
            bg="#6e40c9", fg='#f0c040', activebackground='#8b5cf6',
            command=self.salvar_cidade, cursor='hand2', bd=0,
            padx=10, pady=2
        ).pack(side='left', padx=8)
        _criar_faixa_secao(clima_card, topo=False)

        # Separador
        sep2 = tk.Frame(main_frame, bg='#30363d', height=1)
        sep2.pack(fill='x', padx=40, pady=(8, 8))

        # ── Busca ──
        busca_container = tk.Frame(main_frame, bg='#0d1117')
        busca_container.pack(pady=5)

        busca_frame = tk.Frame(busca_container, bg='#161b22')
        busca_frame.pack(ipady=8, ipadx=10)
        _criar_faixa_secao(busca_frame, topo=True)

        tk.Label(
            busca_frame, text="🔍",
            fg='#f0c040', bg='#161b22', font=("Arial", 16)
        ).pack(side='left', padx=(10, 5))

        self.entry_busca = tk.Entry(
            busca_frame, width=20, font=("Arial", 16),
            bg='#21262d', fg='#f0c040', insertbackground='#f0c040',
            justify='center'
        )
        self.entry_busca.pack(side='left', padx=5, ipady=5)
        self.entry_busca.insert(0, self.placeholder_busca)
        self.entry_busca.bind("<FocusIn>", self._on_focus_in)
        self.entry_busca.bind("<FocusOut>", self._on_focus_out)
        self.entry_busca.bind("<Return>", self.enter_busca)
        self.entry_busca.bind("<KeyRelease>", self._on_entry_keyrelease)

        self.repetir_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            busca_frame,
            text="🔁 Repetir",
            variable=self.repetir_var,
            bg='#161b22',
            fg='#f0c040',
            selectcolor='#21262d',
            activebackground='#161b22',
            activeforeground='#f0c040',
            font=("Arial", 11),
            cursor='hand2'
        ).pack(side='left', padx=(5, 10))
        _criar_faixa_secao(busca_frame, topo=False)

        # Separador
        sep3 = tk.Frame(main_frame, bg='#30363d', height=1)
        sep3.pack(fill='x', padx=40, pady=(8, 8))

        # ── Lista de resultados ──
        list_container = tk.Frame(main_frame, bg='#161b22')
        list_container.pack(fill='both', expand=True, pady=10)
        _criar_faixa_secao(list_container, topo=True)

        self.canvas_lista = tk.Canvas(
            list_container, bg='#161b22', highlightthickness=0
        )
        scrollbar = tk.Scrollbar(
            list_container, orient="vertical", command=self.canvas_lista.yview,
            bg='#21262d', troughcolor='#161b22', activebackground='#6e40c9'
        )
        self.scroll_frame = tk.Frame(self.canvas_lista, bg='#161b22')

        # O campo de resultados tem cor própria por tema (_pintar_lista_cores):
        # fica fora da recolorização genérica para o cinza claro não distorcer.
        self.list_container = list_container
        self.scrollbar_lista = scrollbar
        for _w in (list_container, self.canvas_lista, scrollbar, self.scroll_frame):
            try:
                _w._navepro_tema_ignorar = True
            except Exception:
                pass

        self.scroll_frame.bind(
            "<Configure>",
            lambda e: self.canvas_lista.configure(
                scrollregion=self.canvas_lista.bbox("all")
            )
        )
        self.canvas_inner_id = self.canvas_lista.create_window(
            (0, 0), window=self.scroll_frame, anchor="nw"
        )

        # Faz o frame interno acompanhar a largura do canvas
        def _ajustar_largura_canvas(event):
            self.canvas_lista.itemconfig(self.canvas_inner_id, width=event.width)

        self.canvas_lista.bind("<Configure>", _ajustar_largura_canvas)
        self.canvas_lista.configure(yscrollcommand=scrollbar.set)

        self.canvas_lista.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        _criar_faixa_secao(list_container, topo=False)


        # ── Controles ──
        controls_frame = tk.Frame(main_frame, bg='#161b22')
        controls_frame.pack(fill='x', pady=(10, 0), ipady=8)
        _marcar_area_cinza_clara(controls_frame, '#161b22')
        _criar_faixa_secao(controls_frame, topo=True)
        # Guardado para o campo de resultados usar a mesma cor "por baixo dos
        # botões" no tema claro (ver _pintar_lista_cores).
        self.controls_frame = controls_frame

        # Botões de controle em estilo "pill" (ícones grandes, sem texto)
        pill_frame = tk.Frame(controls_frame, bg='#21262d', highlightthickness=0)
        pill_frame.pack(side='left', padx=15)
        _marcar_area_cinza_clara(pill_frame)

        def _criar_botao_pill(parent, icone, tooltip, comando, icone_png=None,
                              lado='left', pack_padx=0, fonte_texto=("Arial", 18),
                              tamanho=40):
            """Botão-pílula com um ícone que sai igual em qualquer sistema.

            Ordem de preferência: emoji colorido renderizado pela Pillow (o
            botão recebe a imagem, não depende do Tk resolver o glifo), o PNG
            fixo de `icone_png` em icones/ e, por último, o próprio caractere
            no rótulo. O Tk 8.6 não tem fonte de emoji própria e o fallback de
            fonte muda entre Ubuntu, Debian e Windows — por isso o caractere
            cru não é confiável.

            `tamanho` é o lado do emoji em pixels (a pílula continua 40x40:
            menor que isso e o PNG de fallback, que tem 40px, sairia cortado).
            """
            args = dict(
                bg='#21262d', fg='#f0c040', activebackground='#6e40c9',
                activeforeground='#f0c040',
                command=comando, cursor='hand2',
                bd=0, highlightthickness=0,
                padx=16, pady=10
            )
            imagem = _carregar_emoji(icone, tamanho)
            if imagem is None and icone_png:
                imagem = _carregar_icone(icone_png)
            if imagem is not None:
                args.update(text="", image=imagem, width=40, height=40,
                            compound="center")
                btn = tk.Button(parent, **args)
                btn._navepro_imagem = imagem  # mantém ref para não sumir
            else:
                args.update(text=icone, font=fonte_texto)
                btn = tk.Button(parent, **args)
            btn.pack(side=lado, padx=pack_padx)
            _marcar_area_cinza_clara(btn)
            # Cria tooltip
            _criar_tooltip(btn, tooltip)
            return btn

        def _criar_tooltip(widget, texto):
            tooltip_win = None
            def mostrar(event):
                nonlocal tooltip_win
                if tooltip_win:
                    return
                x = widget.winfo_rootx() + widget.winfo_width() // 2
                y = widget.winfo_rooty() + widget.winfo_height() + 5
                tooltip_win = tk.Toplevel(widget)
                tooltip_win.wm_overrideredirect(True)
                tooltip_win.wm_geometry(f"+{x}+{y}")
                tooltip_win.configure(bg='#161b22')
                lbl = tk.Label(tooltip_win, text=texto, bg='#161b22',
                               fg='#f0c040', font=("Arial", 9),
                               padx=8, pady=3)
                lbl.pack()
            def esconder(event):
                nonlocal tooltip_win
                if tooltip_win:
                    tooltip_win.destroy()
                    tooltip_win = None
            widget.bind("<Enter>", mostrar)
            widget.bind("<Leave>", esconder)

        _criar_botao_pill(pill_frame, "⏮", "Anterior", self.tocar_anterior,
                          icone_png="anterior", pack_padx=10)
        _criar_botao_pill(pill_frame, "⏯", "Play / Pause", self.player.play_pause,
                          icone_png="playpause", pack_padx=10)
        _criar_botao_pill(pill_frame, "⏹", "Parar", self.parar,
                          icone_png="parar", pack_padx=10)
        _criar_botao_pill(pill_frame, "⏭", "Próximo", self.tocar_proximo,
                          icone_png="proximo", pack_padx=10)

        # Espaçador flexível
        _espacador = tk.Frame(controls_frame, bg='#161b22')
        _marcar_area_cinza_clara(_espacador, '#161b22')
        _espacador.pack(side='left', fill='x', expand=True)

        # Botão Sorteio (canto inferior direito, mesmo estilo pílula dos demais)
        sorteio_frame = tk.Frame(controls_frame, bg='#21262d', highlightthickness=0)
        sorteio_frame.pack(side='right', padx=0)
        _marcar_area_cinza_clara(sorteio_frame)
        _criar_botao_pill(sorteio_frame, "🎲", "Sorteio Profissional",
                          self.abrir_sorteio, icone_png="sorteio", tamanho=30,
                          pack_padx=8)

        # Botões dos novos módulos (frame separado à direita)
        modulos_frame = tk.Frame(controls_frame, bg='#21262d', highlightthickness=0)
        modulos_frame.pack(side='right', padx=0)
        _marcar_area_cinza_clara(modulos_frame)
        _criar_botao_pill(modulos_frame, "📖", "Hinos / Letras", self.janela_hinos,
                          icone_png="hinos", tamanho=30, pack_padx=8)
        _criar_botao_pill(modulos_frame, "✝️", "Bíblia", self.janela_biblia,
                          icone_png="biblia", tamanho=30, pack_padx=8)
        _criar_botao_pill(modulos_frame, "📋", "Ordem de Serviço", self.janela_ordem_servico,
                          icone_png="ordem", tamanho=30, pack_padx=8)
        _criar_botao_pill(modulos_frame, "📢", "Anúncios", self.janela_anuncios,
                          icone_png="anuncios", tamanho=30, pack_padx=8)

        # Botões Gerenciar Banco e Configurações (mesma pílula, montados por
        # último: o pack side='right' define a posição da direita p/ a esquerda)
        _criar_botao_pill(controls_frame, "📦", "Gerenciar Banco",
                          self.abrir_gerenciador, icone_png="banco",
                          lado='right', pack_padx=8, fonte_texto=("Arial", 16),
                          tamanho=30)
        _criar_botao_pill(controls_frame, "⚙️", "Configurações",
                          self.abrir_config_relogio_dialogo, icone_png="config",
                          lado='right', pack_padx=8, fonte_texto=("Arial", 16),
                          tamanho=30)
        _criar_faixa_secao(controls_frame, topo=False)
    def _criar_menu(self) -> None:
        """Cria a barra de menu no topo da janela."""
        menubar = tk.Menu(self.root, bg='#161b22', fg='#f0c040',
                          activebackground='#6e40c9', activeforeground='#f0c040',
                          font=("Arial", 10))

        # ── Arquivo (placeholder) ──
        menu_arquivo = tk.Menu(menubar, tearoff=0, bg='#21262d', fg='#c9d1d9',
                               activebackground='#6e40c9', activeforeground='#f0c040',
                               font=("Arial", 10))
        menu_arquivo.add_command(label="Sair", command=self.fechar,
                                 accelerator="Ctrl+Q")
        menubar.add_cascade(label="Arquivo", menu=menu_arquivo)

        # ── Configurações (entre Arquivo e Editar) ──
        menu_config = tk.Menu(menubar, tearoff=0, bg='#21262d', fg='#c9d1d9',
                              activebackground='#6e40c9', activeforeground='#f0c040',
                              font=("Arial", 10))
        menu_config.add_command(label="Configurar Relógio / Cronômetro / Contagem",
                                command=self.abrir_config_relogio_dialogo)
        menu_config.add_command(label="Configurar Projeção",
                                command=self.abrir_config_projecao_dialogo)
        menu_config.add_command(label="🌐 Controle Remoto",
                                command=self.abrir_controle_remoto)
        menu_config.add_separator()
        menu_config.add_command(label="Gerenciar Banco",
                                command=self.abrir_gerenciador)
        menubar.add_cascade(label="Configurações", menu=menu_config)

        # ── Editar (placeholder) ──
        menu_editar = tk.Menu(menubar, tearoff=0, bg='#21262d', fg='#c9d1d9',
                              activebackground='#6e40c9', activeforeground='#f0c040',
                              font=("Arial", 10))
        menu_editar.add_command(label="Gerenciar Banco",
                                command=self.abrir_gerenciador)
        menu_editar.add_separator()
        menu_editar.add_command(label="Hinos / Letras",
                                command=self.janela_hinos)
        menu_editar.add_command(label="Bíblia",
                                command=self.janela_biblia)
        menu_editar.add_command(label="Ordem de Serviço",
                                command=self.janela_ordem_servico)
        menubar.add_cascade(label="Editar", menu=menu_editar)

        # ── Exibir (após Editar) ──
        menu_exibir = tk.Menu(menubar, tearoff=0, bg='#21262d', fg='#c9d1d9',
                              activebackground='#6e40c9', activeforeground='#f0c040',
                              font=("Arial", 10))
        menu_exibir.add_command(label="Hinos / Letras",
                                command=self.janela_hinos)
        menu_exibir.add_command(label="Bíblia",
                                command=self.janela_biblia)
        menu_exibir.add_command(label="Ordem de Serviço",
                                command=self.janela_ordem_servico)
        menu_exibir.add_command(label="Anúncios",
                                command=self.janela_anuncios)
        menubar.add_cascade(label="Exibir", menu=menu_exibir)

        # ── Visualizar ──
        menu_visualizar = tk.Menu(menubar, tearoff=0, bg='#21262d', fg='#c9d1d9',
                                  activebackground='#6e40c9', activeforeground='#f0c040',
                                  font=("Arial", 10))
        menu_visualizar.add_command(label="Alternar modo Repetir",
                                    command=self._toggle_repetir)
        menu_visualizar.add_separator()
        menu_visualizar.add_command(label="Alternar Tela Cheia",
                                    command=self._alternar_maximizar,
                                    accelerator="F11")
        menu_visualizar.add_separator()
        self._var_tema_claro = tk.BooleanVar(value=(self.tema == 'claro'))
        menu_visualizar.add_checkbutton(label="Tema Claro",
                                        variable=self._var_tema_claro,
                                        command=self._alternar_tema,
                                        accelerator="Ctrl+T")
        menubar.add_cascade(label="Visualizar", menu=menu_visualizar)

        # ── Ajuda > Sobre ──
        menu_ajuda = tk.Menu(menubar, tearoff=0, bg='#21262d', fg='#c9d1d9',
                             activebackground='#6e40c9', activeforeground='#f0c040',
                             font=("Arial", 10))
        menu_ajuda.add_command(label="Compartilhar ideias",
                               command=lambda: self._abrir_email(
                                   "Compartilhar ideias sobre o NavePro"))
        menu_ajuda.add_command(label="Relatar um problema",
                               command=lambda: self._abrir_email(
                                   "Relatar um problema no NavePro"))
        menu_ajuda.add_separator()
        menu_ajuda.add_command(label="Verificar atualizações…",
                               command=lambda: self.verificar_atualizacao(manual=True))
        menu_ajuda.add_separator()
        menu_ajuda.add_command(label="Sobre", command=self._mostrar_sobre)
        menubar.add_cascade(label="Ajuda", menu=menu_ajuda)

        # Guarda referências para recolorir os menus ao trocar o tema
        self._menus = [menubar, menu_arquivo, menu_config, menu_editar,
                       menu_exibir, menu_visualizar, menu_ajuda]

        self.root.config(menu=menubar)
