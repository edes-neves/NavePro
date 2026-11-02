"""Janela de _janela_gerenciar_midias do painel do operador (mixin).

Extraída de NavePro.py sem alteração de comportamento: a AppInterface
herda deste mixin para montar a janela.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
import tkinter.messagebox
import tkinter.simpledialog
from tkinter import ttk

from navepro.core.banco import _listar_midias_ativas, db_execute
from navepro.core.log import get_logger
from navepro.core.util_tk import _centralizar_sobre, _limitar_ao_monitor
from navepro.core.widgets_arredondados import TkArredondado

log = get_logger("_janela_gerenciar_midias")

# Botões e campos desenham cantos arredondados (fachada do tkinter).
tk = TkArredondado(tk)


class GerenciadorMidiasMixin:
    def _janela_gerenciar_midias(self) -> None:
        """Janela completa para gerenciar as mídias do banco."""
        janela = tk.Toplevel(self.root)
        janela.title("📦 Gerenciar Banco de Mídia")
        _limitar_ao_monitor(janela, 800, 900,
                            area=self._area_monitor_operador())
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        _centralizar_sobre(janela, self.root,
                           area=self._area_monitor_operador())

        main = tk.Frame(janela, bg='#0d1117')
        main.pack(fill='both', expand=True, padx=15, pady=15)

        # Info (variável local)
        gerenciador_info = tk.Label(
            main, text="📊 Carregando...",
            font=("Arial", 14, "bold"), fg='#f0c040', bg='#0d1117'
        )
        gerenciador_info.pack(fill='x')

        # Botões
        btn_frame = tk.Frame(main, bg='#0d1117')
        btn_frame.pack(fill='x', pady=10)

        # Filtros (variável local)
        filtro_var = tk.StringVar(value="todos")

        # TreeView (variável local)
        list_container = tk.Frame(main, bg='#161b22')
        list_container.pack(fill='both', expand=True, pady=5)

        colunas = ("ID", "Nome", "Tipo", "Tamanho", "Arquivo")
        gerenciador_tree = ttk.Treeview(
            list_container, columns=colunas,
            show='headings', height=15
        )
        for col in colunas:
            gerenciador_tree.heading(col, text=col)
            widths = {
                "ID": 40, "Nome": 250, "Tipo": 70,
                "Tamanho": 80, "Arquivo": 300,
            }
            gerenciador_tree.column(col, width=widths.get(col, 100))

        scrollbar_y = tk.Scrollbar(
            list_container, orient="vertical",
            command=gerenciador_tree.yview
        )
        gerenciador_tree.configure(yscrollcommand=scrollbar_y.set)
        gerenciador_tree.pack(side='left', fill='both', expand=True)
        scrollbar_y.pack(side='right', fill='y')

        # Estilo
        style = ttk.Style()
        style.theme_use('clam')
        style.configure(
            "Treeview",
            background="#21262d", foreground="#c9d1d9",
            fieldbackground="#21262d", font=("Arial", 10)
        )
        style.configure(
            "Treeview.Heading",
            background="#161b22", foreground="#f0c040",
            font=("Arial", 10, "bold")
        )
        style.map('Treeview', background=[('selected', '#6e40c9')],
                  foreground=[('selected', '#ffffff')])
        style.configure("Vertical.TScrollbar", background="#21262d",
                        troughcolor="#161b22", arrowcolor="#f0c040")

        _atualizacao_id = 0

        def _preencher_lista(midias: list[dict]) -> None:
            """Preenche a TreeView (roda na thread do Tk)."""
            total = len(midias)
            videos = sum(1 for m in midias if m.get('tipo') == 'video')
            audios = sum(1 for m in midias if m.get('tipo') == 'audio')
            textos = sum(1 for m in midias if m.get('tipo') == 'texto')

            try:
                gerenciador_info.config(
                    text=f"📊 {total} mídia(s)  |  🎬 {videos}  🎵 {audios}  📄 {textos}"
                )
            except tk.TclError:
                return

            for item in gerenciador_tree.get_children():
                gerenciador_tree.delete(item)

            for m in midias:
                tamanho = m.get('tamanho_bytes', 0)
                if tamanho > 1024 * 1024:
                    tamanho_str = f"{tamanho / 1024 / 1024:.1f} MB"
                elif tamanho > 1024:
                    tamanho_str = f"{tamanho / 1024:.1f} KB"
                else:
                    tamanho_str = f"{tamanho} B"

                icone = {"video": "🎬", "audio": "🎵", "texto": "📄"}
                icon = icone.get(m.get('tipo'), "📁")
                gerenciador_tree.insert(
                    "", tk.END, iid=str(m['id']),
                    values=(
                        m['id'],
                        f"{icon} {m.get('nome_exibicao', '')}",
                        m.get('tipo', ''),
                        tamanho_str,
                        os.path.basename(m.get('caminho_arquivo', '')),
                    )
                )

        def _atualizar_lista():
            """Consulta o banco em background e atualiza a TreeView."""
            nonlocal _atualizacao_id
            _atualizacao_id += 1
            req_id = _atualizacao_id

            try:
                tipo_filtro = filtro_var.get()
                gerenciador_info.config(text="⏳ Carregando...")
            except tk.TclError:
                return
            tipo = None if tipo_filtro == "todos" else tipo_filtro

            def _consultar():
                try:
                    midias = _listar_midias_ativas(tipo)
                except Exception as e:
                    log.exception(f"Erro ao carregar lista de mídias: {e}")
                    midias = []

                def _aplicar():
                    if req_id != _atualizacao_id:
                        return
                    try:
                        if not janela.winfo_exists():
                            return
                    except tk.TclError:
                        return
                    _preencher_lista(midias)

                try:
                    self.root.after(0, _aplicar)
                except tk.TclError:
                    pass

            threading.Thread(target=_consultar, daemon=True).start()

        # Botões (usam closures em vez de self._*)
        tk.Button(
            btn_frame, text="📂 Adicionar Mídias",
            font=("Arial", 11, "bold"),
            bg='#238636', fg='white', activebackground='#2ea043',
            command=lambda: self._adicionar_midias_ao_banco(
                janela, _atualizar_lista),
            cursor='hand2', padx=15, pady=5
        ).pack(side='left', padx=5)

        def _remover():
            """Remove selecionadas (closure)."""
            selecionados = gerenciador_tree.selection()
            if not selecionados:
                tkinter.messagebox.showwarning(
                    "Seleção", "Selecione pelo menos uma mídia na lista!",
                    parent=janela,
                )
                return

            if not tkinter.messagebox.askyesno(
                "Confirmar",
                f"Remover {len(selecionados)} mídia(s)?",
                parent=janela,
            ):
                return

            for midia_id in selecionados:
                db_execute(
                    "UPDATE midia SET ativo = 0, data_modificacao = datetime('now') WHERE id = ?",
                    (int(midia_id),),
                )

            self.db.reload_cache()
            tkinter.messagebox.showinfo(
                "✅",
                f"{len(selecionados)} mídia(s) removida(s)!",
                parent=janela,
            )
            _atualizar_lista()

        tk.Button(
            btn_frame, text="🗑️ Remover Selecionadas",
            font=("Arial", 11, "bold"),
            bg='#da3633', fg='white', activebackground='#f85149',
            command=_remover,
            cursor='hand2', padx=15, pady=5
        ).pack(side='left', padx=5)

        tk.Button(
            btn_frame, text="🔄 Atualizar Lista",
            font=("Arial", 11, "bold"),
            bg='#21262d', fg='#f0c040', activebackground='#30363d',
            command=_atualizar_lista,
            cursor='hand2', padx=15, pady=5
        ).pack(side='left', padx=5)

        # Filtros (usam closure)
        filtro_frame = tk.Frame(main, bg='#161b22')
        filtro_frame.pack(fill='x', pady=5, ipady=3)

        for texto, valor in [
            ("📋 Todos", "todos"),
            ("🎬 Vídeos", "video"),
            ("🎵 Áudios", "audio"),
            ("📄 Textos", "texto"),
        ]:
            tk.Radiobutton(
                filtro_frame, text=texto,
                variable=filtro_var, value=valor,
                bg='#161b22', fg='#c9d1d9', selectcolor='#21262d',
                activebackground='#161b22',
                command=_atualizar_lista
            ).pack(side='left', padx=8)

        # Carrega dados iniciais
        _atualizar_lista()
