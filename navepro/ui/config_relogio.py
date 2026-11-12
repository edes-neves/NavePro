"""Janela de abrir_config_relogio_dialogo do painel do operador (mixin).

Extraída de NavePro.py sem alteração de comportamento: a AppInterface
herda deste mixin para montar a janela.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.messagebox
import tkinter.simpledialog
from tkinter import font as tkfont
from tkinter import ttk

from navepro.config import SUFIXOS_IMAGEM
from navepro.core.log import get_logger
from navepro.core.util_tk import (
    _centralizar_sobre,
    _habilitar_maximizar_janela,
    _limitar_ao_monitor,
)
from navepro.core.widgets_arredondados import TkArredondado
from navepro.ui.apoio import _escolher_arquivos_usuario

log = get_logger("abrir_config_relogio_dialogo")

# Botões e campos desenham cantos arredondados (fachada do tkinter).
tk = TkArredondado(tk)


class ConfigRelogioMixin:
    def abrir_config_relogio_dialogo(self, aba: str | None = None) -> None:
        """Abre a janela de configuração do relógio, cronômetro e contagem regressiva.

        Abas:
          - 🕐 Relógio: aparência do relógio/temperatura (manutenção da
            funcionalidade original).
          - ⏱ Cronômetro: projeta um cronômetro digital no telão (Digital-7),
            com as mesmas cores/fundo/transparência do relógio, e controles
            Iniciar/Parar/Continuar/Encerrar no monitor do operador.
          - ⏳ Contagem regressiva: projeta nome/frase + tempo contando para
            baixo, com controles Iniciar/Parar/Continuar/Encerrar.
          - 🌐 Controle Remoto: ativação, token e URL do celular.

        Com `aba='remoto'` abre já selecionada na aba 🌐 Controle Remoto.
        """
        lista_cores = [
            ("Amarelo", "#F5BE08"), ("Branco", "#FFFFFF"),
            ("Vermelho", "#FF5555"), ("Azul", "#58A6FF"),
            ("Verde", "#3FB950"), ("Roxo", "#D2A8FF"),
            ("Ciano", "#00E5FF"), ("Laranja", "#FF9800")]
        cores_fundo = [
            ("Preto", "#000000"), ("Cinza escuro", "#1a1a2e"),
            ("Azul escuro", "#0d1b2a"), ("Verde escuro", "#0a1f0a"),
            ("Vinho", "#2d0a0a")]

        # ── Configurações carregadas (relógio | cronômetro | contagem) ──
        cfg_atual = dict(getattr(self.player.telao, "_relogio_cfg", {}))
        cfg_atual.setdefault("cor_hora", "#F5BE08")
        cfg_atual.setdefault("cor_temp", "#F5BE08")
        cfg_atual.setdefault("cor_fundo", "#000000")
        cfg_atual.setdefault("fator_hora", 1.0)
        cfg_atual.setdefault("fator_temp", 1.0)
        cfg_atual.setdefault("espacamento", 1.0)
        cfg_atual.setdefault("fundo_opaco", False)
        cfg_atual.setdefault("fundo_imagem", "")

        cfg_crono = dict(self.config_data.get("cronometro", {}))
        cfg_crono.setdefault("cor_hora", "#F5BE08")
        cfg_crono.setdefault("cor_temp", "#F5BE08")
        cfg_crono.setdefault("cor_fundo", "#000000")
        cfg_crono.setdefault("fator_hora", 1.0)
        cfg_crono.setdefault("fundo_opaco", False)

        cfg_cont = dict(self.config_data.get("contagem", {}))
        cfg_cont.setdefault("cor_hora", "#F5BE08")
        cfg_cont.setdefault("cor_temp", "#F5BE08")
        cfg_cont.setdefault("cor_fundo", "#000000")
        cfg_cont.setdefault("fator_hora", 1.0)
        cfg_cont.setdefault("fundo_opaco", False)
        cfg_cont.setdefault("fonte_sub", "Arial")
        cfg_cont.setdefault("fator_sub", 0.30)
        cfg_cont.setdefault("peso_sub", "bold")
        cfg_cont.setdefault("maiusculas_sub", False)
        cfg_cont.setdefault("quebrar_sub", False)
        cfg_cont.setdefault("posicao_sub", "abaixo")
        cfg_cont.setdefault("dist_sub", 0.05)
        cfg_cont.setdefault("titulo", "")

        cfg_win = tk.Toplevel(self.root)
        cfg_win.title("⚙️ Configura Relógio / Cronômetro / Contagem")
        _limitar_ao_monitor(cfg_win, 680, 980,
                            area=self._area_monitor_operador())
        cfg_win.configure(bg='#0d1117')
        cfg_win.transient(self.root)
        _centralizar_sobre(cfg_win, self.root,
                           area=self._area_monitor_operador())
        # Não usa grab_set: o operador pode abrir outras janelas enquanto
        # ajusta o relógio/cronômetro/contagem.
        _habilitar_maximizar_janela(cfg_win, area=self._area_monitor_operador())

        c_main = tk.Frame(cfg_win, bg='#0d1117')
        c_main.pack(fill='both', expand=True, padx=15, pady=15)

        tk.Label(c_main, text="⚙️ Configura Relógio / Cronômetro / Contagem",
                 font=("Arial", 14, "bold"), fg='#f0c040', bg='#0d1117'
                 ).pack(pady=(0, 10))

        try:
            _estilo = ttk.Style(cfg_win)
            _estilo.theme_use("clam")
            _estilo.configure("Medidor.TNotebook", background='#0d1117',
                              borderwidth=0, tabmargins=[4, 4, 4, 0])
            _estilo.configure("Medidor.TNotebook.Tab", background='#21262d',
                              foreground='#c9d1d9', padding=[12, 7],
                              font=("Arial", 11, "bold"))
            _estilo.map("Medidor.TNotebook.Tab",
                        background=[('selected', '#6e40c9')],
                        foreground=[('selected', '#ffffff')])
            _estilo.configure("Medidor.TCombobox",
                              fieldbackground='#21262d', background='#21262d',
                              foreground='#c9d1d9', arrowcolor='#f0c040',
                              font=("Arial", 10))
            _estilo.map("Medidor.TCombobox",
                        fieldbackground=[('readonly', '#21262d')],
                        foreground=[('readonly', '#c9d1d9')])
        except tk.TclError:
            pass
        notebook = ttk.Notebook(c_main, style="Medidor.TNotebook")
        notebook.pack(fill='both', expand=True)

        # ── Helper para linha de cores por Radios ──
        def _linha_cores(parent, titulo, var) -> None:
            tk.Label(parent, text=titulo, font=("Arial", 11, "bold"),
                     fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x')
            frame = tk.Frame(parent, bg='#0d1117')
            frame.pack(fill='x', pady=(0, 8))
            for nome, codigo in lista_cores:
                tk.Radiobutton(
                    frame, text=nome, value=codigo, variable=var,
                    bg='#0d1117', fg='#c9d1d9', selectcolor='#0d1117',
                    activebackground='#0d1117', activeforeground='#f0c040',
                    font=("Arial", 10)).pack(side='left', padx=2)

        def _linha_fundo(parent) -> None:
            tk.Label(parent, text="Cor de fundo:", font=("Arial", 11, "bold"),
                     fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x')
            frame = tk.Frame(parent, bg='#0d1117')
            frame.pack(fill='x', pady=(0, 8))
            for nome, codigo in cores_fundo:
                tk.Radiobutton(
                    frame, text=nome, value=codigo,
                    variable=parent.var_cor_fundo,
                    bg='#0d1117', fg='#c9d1d9', selectcolor='#0d1117',
                    activebackground='#0d1117', activeforeground='#f0c040',
                    font=("Arial", 10)).pack(side='left', padx=2)

        def _escala_tamanho(parent, titulo, var) -> None:
            tk.Label(parent, text=titulo, font=("Arial", 11, "bold"),
                     fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x')
            tk.Scale(parent, from_=0.3, to=2.0, resolution=0.1,
                     orient="horizontal", variable=var, bg='#0d1117',
                     fg='#c9d1d9', troughcolor='#21262d', highlightthickness=0,
                     font=("Arial", 10)).pack(fill='x', pady=(0, 8))

        def _check_opaco(parent, var) -> None:
            tk.Checkbutton(
                parent, text="Fundo opaco (sem transparência)",
                variable=var, bg='#0d1117', fg='#c9d1d9',
                selectcolor='#0d1117', activebackground='#0d1117',
                activeforeground='#f0c040', font=("Arial", 11, "bold")
                ).pack(anchor='w', pady=(0, 8))

        # ═══════════════════════ Tab 🕐 Relógio ═══════════════════════
        tab_relogio = tk.Frame(notebook, bg='#0d1117')
        notebook.add(tab_relogio, text="🕐 Relógio")

        tab_relogio.var_cor_hora = tk.StringVar(value=str(cfg_atual["cor_hora"]))
        tab_relogio.var_cor_temp = tk.StringVar(value=str(cfg_atual["cor_temp"]))
        tab_relogio.var_cor_fundo = tk.StringVar(value=str(cfg_atual["cor_fundo"]))
        tab_relogio.var_fator_hora = tk.DoubleVar(value=float(cfg_atual["fator_hora"]))
        tab_relogio.var_fator_temp = tk.DoubleVar(value=float(cfg_atual["fator_temp"]))
        tab_relogio.var_espacamento = tk.DoubleVar(value=float(cfg_atual["espacamento"]))
        tab_relogio.var_fundo_opaco = tk.BooleanVar(value=bool(cfg_atual["fundo_opaco"]))

        _linha_cores(tab_relogio, "Cor do relógio:", tab_relogio.var_cor_hora)
        _linha_cores(tab_relogio, "Cor da temperatura:", tab_relogio.var_cor_temp)
        _linha_fundo(tab_relogio)
        _check_opaco(tab_relogio, tab_relogio.var_fundo_opaco)

        # ── Imagem de fundo (opcional) ──
        tk.Label(tab_relogio, text="Imagem de fundo (opcional):",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117',
                 anchor='w').pack(fill='x')
        linha_imagem = tk.Frame(tab_relogio, bg='#0d1117')
        linha_imagem.pack(fill='x', pady=(0, 8))
        var_fundo_imagem = tk.StringVar(value=str(cfg_atual["fundo_imagem"]))
        entry_imagem = tk.Entry(
            linha_imagem, textvariable=var_fundo_imagem, font=("Arial", 10),
            bg='#21262d', fg='#c9d1d9', insertbackground='#f0c040',
            bd=0, highlightthickness=0)
        entry_imagem.pack(side='left', fill='x', expand=True, ipady=3)

        def _escolher_imagem_fundo_relogio():
            escolhidos = _escolher_arquivos_usuario(
                cfg_win, "Escolher imagem de fundo",
                sufixos=tuple(sorted(SUFIXOS_IMAGEM)))
            if escolhidos:
                var_fundo_imagem.set(escolhidos[0])

        tk.Button(linha_imagem, text="Procurar…", font=("Arial", 10, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_escolher_imagem_fundo_relogio, cursor='hand2',
                  padx=8, pady=2).pack(side='left', padx=3)
        tk.Button(linha_imagem, text="✖ Limpar", font=("Arial", 10, "bold"),
                  bg='#da3633', fg='white', activebackground='#f85149',
                  command=lambda: var_fundo_imagem.set(""), cursor='hand2',
                  padx=8, pady=2).pack(side='left')

        _escala_tamanho(tab_relogio, "Tamanho do relógio:",
                        tab_relogio.var_fator_hora)
        _escala_tamanho(tab_relogio, "Tamanho da temperatura:",
                        tab_relogio.var_fator_temp)

        # ── Espaçamento ──
        tk.Label(tab_relogio, text="Espaçamento (hora ↔ temperatura):",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117',
                 anchor='w').pack(fill='x')
        tk.Scale(tab_relogio, from_=0.0, to=3.0, resolution=0.05,
                 orient="horizontal", variable=tab_relogio.var_espacamento,
                 bg='#0d1117', fg='#c9d1d9', troughcolor='#21262d',
                 highlightthickness=0, font=("Arial", 10)
                 ).pack(fill='x', pady=(0, 8))

        def _salvar_cfg_relogio():
            novo = {
                "cor_hora": tab_relogio.var_cor_hora.get(),
                "cor_temp": tab_relogio.var_cor_temp.get(),
                "cor_fundo": tab_relogio.var_cor_fundo.get(),
                "fator_hora": float(tab_relogio.var_fator_hora.get()),
                "fator_temp": float(tab_relogio.var_fator_temp.get()),
                "espacamento": float(tab_relogio.var_espacamento.get()),
                "fundo_opaco": bool(tab_relogio.var_fundo_opaco.get()),
                "fundo_imagem": var_fundo_imagem.get().strip(),
            }
            # Preserva o nome/frase da contagem regressiva e demais campos do
            # medidor: o dict gravado por este botão não os contém, e sem isso
            # a frase da contagem sumia do telão ao salvar as cores do relógio.
            med_cfg = dict(self.config_data.get("contagem", {}) or {})
            entry = getattr(tab_cont, "entry_titulo", None)
            if entry is not None:
                med_cfg["titulo"] = entry.get().strip()
            novo = {**med_cfg, **novo}
            self.salvar_config_relogio(novo)
            self.status_label.config(text="✅ Configuração do relógio salva")
            # A janela permanece aberta: o operador fecha quando quiser.

        tk.Button(tab_relogio, text="💾 Salvar", font=("Arial", 12, "bold"),
                  bg='#238636', fg='white', activebackground='#2ea043',
                  command=_salvar_cfg_relogio, cursor='hand2', padx=20, pady=5
                  ).pack(pady=(4, 6))

        # ── Mostrar/ocultar o relógio e a temperatura no telão (monitor 2) ──
        tk.Label(tab_relogio,
                 text="Mostrar ou esconder o relógio e a temperatura no telão:",
                 font=("Arial", 11, "bold"), fg='#58a6ff', bg='#0d1117',
                 anchor='w').pack(fill='x')
        self._btn_relogio_telao = tk.Button(
            tab_relogio, text="🚫 Ocultar relógio do telão",
            font=("Arial", 12, "bold"), bg='#6e40c9', fg='white',
            activebackground='#8957e5',
            command=self.alternar_relogio_telao, cursor='hand2',
            padx=20, pady=5)
        self._btn_relogio_telao.pack(pady=(4, 4))
        self._atualizar_botao_relogio_telao()
        tk.Label(tab_relogio,
                 text="Ao ocultar, o telão fica só com o fundo (cor ou imagem "
                      "configurada); projeções e contagem/cronômetro continuam "
                      "normais. A escolha vale só nesta sessão.",
                 font=("Arial", 9), fg='#8b949e', bg='#0d1117',
                 justify='left', wraplength=620).pack(pady=(0, 6))

        # ── Mostrar/ocultar somente a temperatura no telão (monitor 2) ──
        tk.Label(tab_relogio,
                 text="Mostrar ou esconder somente a temperatura no telão:",
                 font=("Arial", 11, "bold"), fg='#58a6ff', bg='#0d1117',
                 anchor='w').pack(fill='x')
        self._btn_temperatura_telao = tk.Button(
            tab_relogio, text="🌡️ Ocultar temperatura do telão",
            font=("Arial", 12, "bold"), bg='#1f6feb', fg='white',
            activebackground='#388bfd',
            command=self.alternar_temperatura_telao, cursor='hand2',
            padx=20, pady=5)
        self._btn_temperatura_telao.pack(pady=(4, 4))
        self._atualizar_botao_temperatura_telao()
        tk.Label(tab_relogio,
                 text="Oculta só a temperatura; o relógio continua no telão. "
                      "Projeções e contagem/cronômetro não são afetados. "
                      "A escolha vale só nesta sessão.",
                 font=("Arial", 9), fg='#8b949e', bg='#0d1117',
                 justify='left', wraplength=620).pack(pady=(0, 6))

        # ══════════════════════ Tab ⏱ Cronômetro ══════════════════════
        tab_crono = tk.Frame(notebook, bg='#0d1117')
        notebook.add(tab_crono, text="⏱ Cronômetro")

        tab_crono.var_cor_hora = tk.StringVar(value=str(cfg_crono["cor_hora"]))
        tab_crono.var_cor_temp = tk.StringVar(value=str(cfg_crono["cor_temp"]))
        tab_crono.var_cor_fundo = tk.StringVar(value=str(cfg_crono["cor_fundo"]))
        tab_crono.var_fator_hora = tk.DoubleVar(value=float(cfg_crono["fator_hora"]))
        tab_crono.var_fundo_opaco = tk.BooleanVar(value=bool(cfg_crono["fundo_opaco"]))

        _linha_cores(tab_crono, "Cor do cronômetro:",
                     tab_crono.var_cor_hora)
        _linha_fundo(tab_crono)
        _check_opaco(tab_crono, tab_crono.var_fundo_opaco)
        _escala_tamanho(tab_crono, "Tamanho do cronômetro:",
                        tab_crono.var_fator_hora)

        lbl_crono = tk.Label(tab_crono, text="00:00.00",
                             font=("Digital-7", 44, "normal"),
                             fg=tab_crono.var_cor_hora.get(), bg='#0d1117')
        lbl_crono.pack(pady=(4, 2))

        linha_crono = tk.Frame(tab_crono, bg='#0d1117')
        linha_crono.pack(fill='x', pady=6)

        def _salvar_cfg_cronometro():
            novo = {
                "cor_hora": tab_crono.var_cor_hora.get(),
                "cor_temp": tab_crono.var_cor_temp.get(),
                "cor_fundo": tab_crono.var_cor_fundo.get(),
                "fator_hora": float(tab_crono.var_fator_hora.get()),
                "fundo_opaco": bool(tab_crono.var_fundo_opaco.get()),
            }
            self._salvar_config_medidor("cronometro", novo)
            self.status_label.config(text="✅ Configuração do cronômetro salva")

        tk.Button(linha_crono, text="💾 Salvar", font=("Arial", 11, "bold"),
                  bg='#238636', fg='white', activebackground='#2ea043',
                  command=_salvar_cfg_cronometro, cursor='hand2',
                  padx=12, pady=4).pack(side='left', padx=3)

        linha_crono_ops = tk.Frame(tab_crono, bg='#0d1117')
        linha_crono_ops.pack(fill='x', pady=6)

        btn_crono_projetar = tk.Button(
            linha_crono_ops, text="🖥️ Projetar Cronômetro",
            font=("Arial", 11, "bold"), bg='#6e40c9', fg='white',
            activebackground='#8957e5', command=lambda: self.cronometro_projetar(lbl_crono),
            cursor='hand2', padx=10, pady=5)
        btn_crono_projetar.pack(side='left', padx=3)

        btn_crono_iniciar = tk.Button(
            linha_crono_ops, text="▶ Iniciar", font=("Arial", 11, "bold"),
            bg='#238636', fg='white', activebackground='#2ea043',
            command=lambda: self.cronometro_iniciar(lbl_crono),
            cursor='hand2', padx=10, pady=5)
        btn_crono_iniciar.pack(side='left', padx=3)

        btn_crono_parar = tk.Button(
            linha_crono_ops, text="⏸ Parar", font=("Arial", 11, "bold"),
            bg='#9e6a03', fg='white', activebackground='#c77b04',
            command=self.cronometro_parar, cursor='hand2', padx=10, pady=5)
        btn_crono_parar.pack(side='left', padx=3)

        btn_crono_continuar = tk.Button(
            linha_crono_ops, text="▶ Continuar", font=("Arial", 11, "bold"),
            bg='#1f6feb', fg='white', activebackground='#388bfd',
            command=self.cronometro_continuar, cursor='hand2', padx=10, pady=5)
        btn_crono_continuar.pack(side='left', padx=3)

        btn_crono_encerrar = tk.Button(
            linha_crono_ops, text="✖ Encerrar", font=("Arial", 11, "bold"),
            bg='#da3633', fg='white', activebackground='#f85149',
            command=self.cronometro_encerrar, cursor='hand2', padx=10, pady=5)
        btn_crono_encerrar.pack(side='left', padx=3)

        tk.Label(tab_crono, text="Projeta no telão (monitor 2) um cronômetro em Digital-7, "
                                 "centralizado; os controles ficam aqui no monitor do operador.",
                 font=("Arial", 9), fg='#8b949e', bg='#0d1117', justify='left',
                 wraplength=620).pack(pady=(4, 0))

        self._crono_btns = {"botoes": {
            "iniciar": btn_crono_iniciar,
            "parar": btn_crono_parar,
            "continuar": btn_crono_continuar,
        }}
        self._marcar_botoes_crono()

        # ════════════════ Tab ⏳ Contagem regressiva ══════════════════
        tab_cont = tk.Frame(notebook, bg='#0d1117')
        notebook.add(tab_cont, text="⏳ Contagem regressiva")

        # ── Aba 🌐 Controle Remoto (mesmo conteúdo da janela antiga) ──
        tab_remoto = tk.Frame(notebook, bg='#0d1117')
        notebook.add(tab_remoto, text="🌐 Controle Remoto")
        self._conteudo_controle_remoto(tab_remoto)

        tab_cont.var_cor_hora = tk.StringVar(value=str(cfg_cont["cor_hora"]))
        tab_cont.var_cor_temp = tk.StringVar(value=str(cfg_cont["cor_temp"]))
        tab_cont.var_cor_fundo = tk.StringVar(value=str(cfg_cont["cor_fundo"]))
        tab_cont.var_fator_hora = tk.DoubleVar(value=float(cfg_cont["fator_hora"]))
        tab_cont.var_fundo_opaco = tk.BooleanVar(value=bool(cfg_cont["fundo_opaco"]))
        tab_cont.var_fonte_sub = tk.StringVar(value=str(cfg_cont["fonte_sub"]))
        tab_cont.var_fator_sub = tk.DoubleVar(value=float(cfg_cont["fator_sub"]))
        tab_cont.var_peso_sub = tk.BooleanVar(
            value=str(cfg_cont["peso_sub"]).lower() != "normal")
        tab_cont.var_maiusculas_sub = tk.BooleanVar(
            value=bool(cfg_cont["maiusculas_sub"]))
        tab_cont.var_quebrar_sub = tk.BooleanVar(
            value=bool(cfg_cont["quebrar_sub"]))
        tab_cont.var_posicao_sub = tk.StringVar(
            value=str(cfg_cont.get("posicao_sub", "abaixo")))
        tab_cont.var_dist_sub = tk.DoubleVar(
            value=float(cfg_cont.get("dist_sub", 0.05)))

        # ── Nome / frase e tempo ──
        tk.Label(tab_cont, text="Nome / frase (exibido no telão):",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117',
                 anchor='w').pack(fill='x')
        entry_titulo = tk.Entry(
            tab_cont, font=("Arial", 11), bg='#21262d', fg='#c9d1d9',
            insertbackground='#f0c040', bd=0, highlightthickness=0)
        # Guardado no próprio telão para a aba Relógio poder preservar o
        # nome/frase ao salvar (o novo dict da contagem é remontado lá).
        tab_cont.entry_titulo = entry_titulo
        entry_titulo.insert(0, str(cfg_cont.get("titulo", "") or ""))
        entry_titulo.pack(fill='x', ipady=3, pady=(0, 8))

        # ── Opções do nome / frase (só afetam o texto, NÃO os números) ──
        tk.Label(tab_cont,
                 text="Opções do nome / frase (não afetam o número):",
                 font=("Arial", 11, "bold"), fg='#58a6ff', bg='#0d1117',
                 anchor='w').pack(fill='x')

        tk.Label(tab_cont, text="Fonte:",
                 font=("Arial", 10, "bold"), fg='#c9d1d9', bg='#0d1117',
                 anchor='w').pack(fill='x')
        try:
            _fontes_sistema = sorted(tkfont.families(self.root))
        except Exception:
            _fontes_sistema = ["Arial", "Helvetica", "Times", "Courier"]
        if cfg_cont["fonte_sub"] not in _fontes_sistema:
            _fontes_sistema.insert(0, str(cfg_cont["fonte_sub"]))
        ttk.Combobox(
            tab_cont, style="Medidor.TCombobox", values=_fontes_sistema,
            textvariable=tab_cont.var_fonte_sub
        ).pack(fill='x', pady=(0, 6))

        tk.Label(tab_cont,
                 text="Tamanho (proporção ao tamanho do número):",
                 font=("Arial", 10, "bold"), fg='#c9d1d9', bg='#0d1117',
                 anchor='w').pack(fill='x')
        tk.Scale(tab_cont, from_=0.10, to=1.00, resolution=0.01,
                 orient="horizontal", variable=tab_cont.var_fator_sub,
                 bg='#0d1117', fg='#c9d1d9', troughcolor='#21262d',
                 highlightthickness=0, font=("Arial", 9)
                 ).pack(fill='x', pady=(0, 6))

        linha_opts_sub = tk.Frame(tab_cont, bg='#0d1117')
        linha_opts_sub.pack(fill='x', pady=(0, 8))
        tk.Checkbutton(linha_opts_sub, text="Negrito",
                       variable=tab_cont.var_peso_sub, bg='#0d1117',
                       fg='#c9d1d9', selectcolor='#0d1117',
                       activebackground='#0d1117',
                       activeforeground='#f0c040', font=("Arial", 10)
                       ).pack(side='left', padx=(0, 14))
        tk.Checkbutton(linha_opts_sub, text="LETRAS MAIÚSCULAS",
                       variable=tab_cont.var_maiusculas_sub, bg='#0d1117',
                       fg='#c9d1d9', selectcolor='#0d1117',
                       activebackground='#0d1117',
                       activeforeground='#f0c040', font=("Arial", 10)
                       ).pack(side='left', padx=(0, 14))
        tk.Checkbutton(linha_opts_sub, text="Quebrar linha longa",
                       variable=tab_cont.var_quebrar_sub, bg='#0d1117',
                       fg='#c9d1d9', selectcolor='#0d1117',
                       activebackground='#0d1117',
                       activeforeground='#f0c040', font=("Arial", 10)
                       ).pack(side='left')

        tk.Label(tab_cont, text="Posição do nome / frase:",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117',
                 anchor='w').pack(fill='x')
        linha_pos_sub = tk.Frame(tab_cont, bg='#0d1117')
        linha_pos_sub.pack(fill='x', pady=(0, 6))
        tk.Radiobutton(linha_pos_sub, text="Abaixo do número",
                       value="abaixo", variable=tab_cont.var_posicao_sub,
                       bg='#0d1117', fg='#c9d1d9', selectcolor='#0d1117',
                       activebackground='#0d1117',
                       activeforeground='#f0c040',
                       font=("Arial", 10)).pack(side='left', padx=(0, 14))
        tk.Radiobutton(linha_pos_sub, text="Acima do número",
                       value="acima", variable=tab_cont.var_posicao_sub,
                       bg='#0d1117', fg='#c9d1d9', selectcolor='#0d1117',
                       activebackground='#0d1117',
                       activeforeground='#f0c040',
                       font=("Arial", 10)).pack(side='left')

        tk.Label(tab_cont, text="Distância do nome/frase até o número:",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117',
                 anchor='w').pack(fill='x')
        tk.Scale(tab_cont, from_=0.0, to=0.55, resolution=0.01,
                 orient="horizontal", variable=tab_cont.var_dist_sub,
                 bg='#0d1117', fg='#c9d1d9', troughcolor='#21262d',
                 highlightthickness=0, font=("Arial", 9)
                 ).pack(fill='x', pady=(0, 6))

        tk.Label(tab_cont, text="Tempo (minutos, ex.: 5  →  ou  MM:SS, ex.: 2:30):",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117',
                 anchor='w').pack(fill='x')
        entry_tempo = tk.Entry(
            tab_cont, font=("Arial", 14, "bold"), bg='#21262d', fg='#f0c040',
            insertbackground='#f0c040', bd=0, highlightthickness=0, justify='center')
        entry_tempo.pack(fill='x', ipady=3, pady=(0, 8))

        _linha_cores(tab_cont, "Cor do número:",
                     tab_cont.var_cor_hora)
        _linha_cores(tab_cont, "Cor do nome/frase:",
                     tab_cont.var_cor_temp)
        _linha_fundo(tab_cont)
        _check_opaco(tab_cont, tab_cont.var_fundo_opaco)
        _escala_tamanho(tab_cont, "Tamanho do número:",
                        tab_cont.var_fator_hora)

        lbl_cont = tk.Label(tab_cont, text="00:00",
                            font=("Digital-7", 44, "normal"),
                            fg=tab_cont.var_cor_hora.get(), bg='#0d1117')
        lbl_cont.pack(pady=(4, 2))

        linha_cont = tk.Frame(tab_cont, bg='#0d1117')
        linha_cont.pack(fill='x', pady=6)

        def _salvar_cfg_contagem():
            novo = {
                "cor_hora": tab_cont.var_cor_hora.get(),
                "cor_temp": tab_cont.var_cor_temp.get(),
                "cor_fundo": tab_cont.var_cor_fundo.get(),
                "fator_hora": float(tab_cont.var_fator_hora.get()),
                "fundo_opaco": bool(tab_cont.var_fundo_opaco.get()),
                "fonte_sub": tab_cont.var_fonte_sub.get().strip() or "Arial",
                "fator_sub": float(tab_cont.var_fator_sub.get()),
                "peso_sub": "bold" if tab_cont.var_peso_sub.get() else "normal",
                "maiusculas_sub": bool(tab_cont.var_maiusculas_sub.get()),
                "quebrar_sub": bool(tab_cont.var_quebrar_sub.get()),
                "posicao_sub": tab_cont.var_posicao_sub.get(),
                "dist_sub": float(tab_cont.var_dist_sub.get()),
                "titulo": entry_titulo.get().strip(),
            }
            self._salvar_config_medidor("contagem", novo)
            self.status_label.config(text="✅ Configuração da contagem salva")

        tk.Button(linha_cont, text="💾 Salvar", font=("Arial", 11, "bold"),
                  bg='#238636', fg='white', activebackground='#2ea043',
                  command=_salvar_cfg_contagem, cursor='hand2',
                  padx=12, pady=4).pack(side='left', padx=3)

        linha_cont_ops = tk.Frame(tab_cont, bg='#0d1117')
        linha_cont_ops.pack(fill='x', pady=6)

        def _contagem_projetar():
            self.contagem_projetar(entry_titulo.get().strip(), entry_tempo.get(), lbl_cont)

        def _contagem_iniciar():
            total = self._parsear_tempo_contagem(entry_tempo.get())
            if total is None:
                tkinter.messagebox.showerror(
                    "Tempo inválido",
                    "Informe o tempo da contagem regressiva (ex.: 5 minutos " +
                    "ou 2:30).",
                    parent=cfg_win)
                return
            self.contagem_iniciar(total, entry_titulo.get().strip(),
                                  lbl_cont)

        btn_cont_projetar = tk.Button(
            linha_cont_ops, text="🖥️ Projetar", font=("Arial", 11, "bold"),
            bg='#6e40c9', fg='white', activebackground='#8957e5',
            command=_contagem_projetar, cursor='hand2', padx=10, pady=5)
        btn_cont_projetar.pack(side='left', padx=3)

        btn_cont_iniciar = tk.Button(
            linha_cont_ops, text="▶ Iniciar", font=("Arial", 11, "bold"),
            bg='#238636', fg='white', activebackground='#2ea043',
            command=_contagem_iniciar, cursor='hand2', padx=10, pady=5)
        btn_cont_iniciar.pack(side='left', padx=3)

        btn_cont_parar = tk.Button(
            linha_cont_ops, text="⏸ Parar", font=("Arial", 11, "bold"),
            bg='#9e6a03', fg='white', activebackground='#c77b04',
            command=self.contagem_parar, cursor='hand2', padx=10, pady=5)
        btn_cont_parar.pack(side='left', padx=3)

        btn_cont_continuar = tk.Button(
            linha_cont_ops, text="▶ Continuar", font=("Arial", 11, "bold"),
            bg='#1f6feb', fg='white', activebackground='#388bfd',
            command=self.contagem_continuar, cursor='hand2', padx=10, pady=5)
        btn_cont_continuar.pack(side='left', padx=3)

        btn_cont_encerrar = tk.Button(
            linha_cont_ops, text="✖ Encerrar", font=("Arial", 11, "bold"),
            bg='#da3633', fg='white', activebackground='#f85149',
            command=self.contagem_encerrar, cursor='hand2', padx=10, pady=5)
        btn_cont_encerrar.pack(side='left', padx=3)

        tk.Label(tab_cont, text="Projeta no telão (monitor 2) o nome/frase e o tempo "
                                "da contagem regressiva, centralizados. As opções "
                                "de fonte, tamanho, negrito, maiúsculas e quebra "
                                "de linha valem apenas para o nome/frase; o número "
                                "é sempre em Digital-7.",
                 font=("Arial", 9), fg='#8b949e', bg='#0d1117', justify='left',
                 wraplength=620).pack(pady=(4, 0))

        self._contagem_btns = {"botoes": {
            "iniciar": btn_cont_iniciar,
            "parar": btn_cont_parar,
            "continuar": btn_cont_continuar,
        }}
        self._marcar_botoes_contagem()

        if aba == 'remoto':
            notebook.select(tab_remoto)
