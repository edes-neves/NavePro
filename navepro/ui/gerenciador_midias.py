"""Janela de _janela_gerenciar_midias do painel do operador (mixin).

Extraída de NavePro.py sem alteração de comportamento: a AppInterface
herda deste mixin para montar a janela.
"""

from __future__ import annotations

import mimetypes
import os
import re
import shutil
import threading
import tkinter as tk
import tkinter.messagebox
import tkinter.simpledialog
from collections.abc import Callable
from tkinter import ttk

from navepro.config import EXTENSOES_AUDIO, EXTENSOES_VIDEO
from navepro.core.banco import _listar_midias_ativas, db_execute
from navepro.core.log import get_logger
from navepro.core.paths import UPLOAD_FOLDER
from navepro.core.textos import detectar_tipo_arquivo
from navepro.core.util_tk import (
    _centralizar_sobre,
    _habilitar_maximizar_janela,
    _limitar_ao_monitor,
)
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
        _habilitar_maximizar_janela(janela, area=self._area_monitor_operador())

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

    def _selecionar_arquivos_personalizado(
        self, janela_pai: tk.Toplevel
    ) -> list[str]:
        """Janela personalizada para selecionar arquivos de mídia.

        Mostra apenas pastas do usuário que NÃO começam com '.'
        (ocultas). Carregamento rápido e assíncrono.
        """
        EXTENSOES_VALIDAS = {
            '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.webm',
            '.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac',
            '.txt', '.pdf',
        }

        selecionados: list[str] = []
        home = os.path.expanduser("~")
        pasta_atual: list[str] = [home]
        carregando = [False]  # Flag para evitar carregamento concorrente

        def _chave_ordenacao_natural(nome: str) -> tuple:
            """Gera chave para ordenação numérica natural."""
            match = re.match(r"(\d+)[\s\-._]+(.+)", nome)
            if match:
                return (0, int(match.group(1)), match.group(2).casefold())
            match = re.match(r"(\d+)", nome)
            if match:
                num = int(match.group(1))
                resto = nome[len(match.group(1)):].lstrip(' -._').casefold()
                return (0, num, resto)
            return (1, 0, nome.casefold())

        def escanear_pastas_rapido(caminho: str) -> list[str]:
            """Escaneia apenas subpastas não ocultas (rápido, sem stat)."""
            try:
                with os.scandir(caminho) as it:
                    return sorted(
                        (e.name for e in it
                         if e.is_dir(follow_symlinks=False)
                         and not e.name.startswith('.')),
                        key=_chave_ordenacao_natural
                    )
            except (PermissionError, OSError):
                return []

        def escanear_arquivos_rapido(caminho: str) -> list[str]:
            """Escaneia apenas arquivos de mídia não ocultos."""
            try:
                with os.scandir(caminho) as it:
                    return sorted(
                        (e.name for e in it
                         if e.is_file(follow_symlinks=False)
                         and not e.name.startswith('.')
                         and os.path.splitext(e.name)[1].lower() in EXTENSOES_VALIDAS),
                        key=_chave_ordenacao_natural
                    )
            except (PermissionError, OSError):
                return []

        def atualizar_conteudo() -> None:
            """Atualiza a lista na thread principal (rápido, sem bloquear)."""
            if carregando[0]:
                return
            carregando[0] = True

            caminho = pasta_atual[0]

            # Atualiza label do caminho
            caminho_label.config(text=f"📁 {caminho}")
            estado_label.config(text="⏳ Carregando...")
            lista.delete(0, tk.END)
            lista.insert(tk.END, "⏳ Carregando...")
            janela.update_idletasks()

            # Escaneia em background
            def _carregar():
                try:
                    pastas = escanear_pastas_rapido(caminho)
                    arquivos = escanear_arquivos_rapido(caminho)

                    janela.after(0, lambda: _preencher_lista(pastas, arquivos))
                except Exception as e:
                    janela.after(0, lambda e=e: _preencher_lista([], [], erro=str(e)))

            def _preencher_lista(pastas: list[str], arquivos: list[str], erro: str = "") -> None:
                lista.delete(0, tk.END)

                if erro:
                    lista.insert(tk.END, f"❌ Erro: {erro}")
                    estado_label.config(text="Erro ao acessar diretório")
                    carregando[0] = False
                    return

                # Pastas (com ícone e cor diferente)
                for p in pastas:
                    lista.insert(tk.END, f"📂 {p}")
                    lista.itemconfig(tk.END, {'fg': '#f0c040', 'bg': '#21262d'})

                # Separador visual se houver pastas e arquivos
                if pastas and arquivos:
                    lista.insert(tk.END, "")
                    lista.itemconfig(tk.END, {'bg': '#161b22', 'selectbackground': '#161b22'})

                # Arquivos
                for arq in arquivos:
                    ext = os.path.splitext(arq)[1].lower()
                    if ext in EXTENSOES_VIDEO:
                        icon = "🎬"
                    elif ext in EXTENSOES_AUDIO:
                        icon = "🎵"
                    else:
                        icon = "📄"
                    lista.insert(tk.END, f"{icon} {arq}")
                    lista.itemconfig(tk.END, {'fg': '#c9d1d9', 'bg': '#21262d'})

                # Se não há nada
                if not pastas and not arquivos:
                    lista.insert(tk.END, "📭 (vazio)")
                    lista.itemconfig(tk.END, {'fg': '#8b949e', 'bg': '#21262d'})

                # Atualiza estado
                selecionar_todos_btn.config(
                    state=tk.NORMAL if arquivos else tk.DISABLED
                )
                estado_label.config(
                    text=f"{len(pastas)} pasta(s), {len(arquivos)} arquivo(s) | "
                         f"{len(selecionados)} selecionado(s)"
                )
                adicionar_btn.config(text=f"📥 Adicionar ({len(selecionados)})")
                carregando[0] = False

            threading.Thread(target=_carregar, daemon=True).start()

        def ao_duplo_clicar(event: object = None) -> None:
            """Abre pasta ou seleciona arquivo ao dar duplo clique."""
            if carregando[0]:
                return
            selecao = lista.curselection()
            if not selecao:
                return
            item = lista.get(selecao[0])

            if item.startswith("📂"):
                nome_pasta = item[2:].strip()
                novo_caminho = os.path.join(pasta_atual[0], nome_pasta)
                if os.path.isdir(novo_caminho):
                    pasta_atual[0] = novo_caminho
                    atualizar_conteudo()
                    voltar_btn.config(
                        state=tk.NORMAL if pasta_atual[0] != home else tk.DISABLED
                    )
            elif item.startswith(("🎬", "🎵", "📄")):
                nome_arquivo = item[2:].strip()
                caminho_completo = os.path.join(pasta_atual[0], nome_arquivo)
                idx = selecao[0]
                if caminho_completo in selecionados:
                    selecionados.remove(caminho_completo)
                    lista.itemconfig(idx, {'bg': '#21262d'})
                else:
                    selecionados.append(caminho_completo)
                    lista.itemconfig(idx, {'bg': '#238636'})
                estado_label.config(
                    text=f"{len(selecionados)} selecionado(s)"
                )
                adicionar_btn.config(text=f"📥 Adicionar ({len(selecionados)})")

        def atualizar_contador_selecao() -> None:
            """Atualiza contador com base na seleção visual da lista (EXTENDED)."""
            if carregando[0]:
                return
            selecionados.clear()
            indices_selecionados = lista.curselection()
            for i in indices_selecionados:
                item = lista.get(i)
                if item.startswith(("🎬", "🎵", "📄")):
                    nome_arquivo = item[2:].strip()
                    caminho_completo = os.path.join(pasta_atual[0], nome_arquivo)
                    selecionados.append(caminho_completo)
            estado_label.config(text=f"{len(selecionados)} selecionado(s)")
            adicionar_btn.config(text=f"📥 Adicionar ({len(selecionados)})")

        def selecionar_todos() -> None:
            """Alterna seleção de todos os arquivos de mídia."""
            if carregando[0]:
                return
            indices_arquivos = [
                i for i in range(lista.size())
                if lista.get(i).startswith(("🎬", "🎵", "📄"))
            ]
            if not indices_arquivos:
                return

            selecao_atual = set(lista.curselection())
            todos_selecionados = all(i in selecao_atual for i in indices_arquivos)

            if todos_selecionados:
                for i in indices_arquivos:
                    lista.selection_clear(i)
            else:
                for i in indices_arquivos:
                    lista.selection_set(i)

            atualizar_contador_selecao()

        def voltar() -> None:
            """Volta para a pasta anterior."""
            if carregando[0]:
                return
            pasta_anterior = os.path.dirname(pasta_atual[0])
            if pasta_anterior != pasta_atual[0] and os.path.isdir(pasta_anterior):
                pasta_atual[0] = pasta_anterior
                atualizar_conteudo()
                voltar_btn.config(
                    state=tk.NORMAL if pasta_atual[0] != home else tk.DISABLED
                )

        def confirmar() -> None:
            """Confirma a seleção e fecha a janela."""
            atualizar_contador_selecao()  # Sincroniza antes de fechar
            janela.destroy()

        def cancelar() -> None:
            """Cancela e limpa a seleção."""
            selecionados.clear()
            janela.destroy()

        # ── Cria a janela ──
        janela = tk.Toplevel(janela_pai)
        janela.title("📂 Selecionar mídias")
        janela.geometry("700x500")
        janela.configure(bg='#0d1117')
        janela.transient(janela_pai)
        _centralizar_sobre(janela, janela_pai)
        _habilitar_maximizar_janela(janela, area=self._area_monitor_operador())
        janela.after(50, janela.grab_set)

        # Caminho atual
        caminho_label = tk.Label(
            janela, text=f"📁 {home}",
            font=("Arial", 10), fg='#f0c040', bg='#0d1117',
            anchor='w'
        )
        caminho_label.pack(fill='x', padx=10, pady=(10, 2))

        # Lista com scroll
        frame_lista = tk.Frame(janela, bg='#161b22')
        frame_lista.pack(fill='both', expand=True, padx=10, pady=5)

        lista = tk.Listbox(
            frame_lista, font=("Arial", 12),
            bg='#21262d', fg='#c9d1d9', selectbackground='#6e40c9',
            selectforeground='white', highlightthickness=0,
            borderwidth=0, activestyle='none',
            selectmode=tk.EXTENDED
        )
        scrollbar = tk.Scrollbar(
            frame_lista, orient="vertical", command=lista.yview,
            bg='#21262d', troughcolor='#161b22', activebackground='#6e40c9'
        )
        lista.configure(yscrollcommand=scrollbar.set)
        lista.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        lista.bind("<Double-Button-1>", ao_duplo_clicar)
        lista.bind("<<ListboxSelect>>", lambda e: atualizar_contador_selecao())

        # Estado
        estado_label = tk.Label(
            janela, text="",
            font=("Arial", 10), fg='#8b949e', bg='#0d1117'
        )
        estado_label.pack(fill='x', padx=10, pady=2)

        # Botões
        botoes_frame = tk.Frame(janela, bg='#0d1117')
        botoes_frame.pack(fill='x', padx=10, pady=(5, 10))

        voltar_btn = tk.Button(
            botoes_frame, text="⬆️ Voltar",
            font=("Arial", 10, "bold"),
            bg='#21262d', fg='#f0c040', activebackground='#30363d',
            command=voltar, cursor='hand2',
            state=tk.DISABLED
        )
        voltar_btn.pack(side='left', padx=2)

        selecionar_todos_btn = tk.Button(
            botoes_frame, text="✅ Selecionar Todos",
            font=("Arial", 10, "bold"),
            bg='#238636', fg='white', activebackground='#2ea043',
            command=selecionar_todos, cursor='hand2',
            state=tk.DISABLED
        )
        selecionar_todos_btn.pack(side='left', padx=2)

        # Espaço flexível
        tk.Frame(botoes_frame, bg='#0d1117').pack(side='left', fill='x', expand=True)

        adicionar_btn = tk.Button(
            botoes_frame, text="📥 Adicionar (0)",
            font=("Arial", 11, "bold"),
            bg='#6e40c9', fg='#f0c040', activebackground='#8b5cf6',
            command=confirmar, cursor='hand2', padx=15
        )
        adicionar_btn.pack(side='right', padx=2)

        cancelar_btn = tk.Button(
            botoes_frame, text="❌ Cancelar",
            font=("Arial", 11, "bold"),
            bg='#da3633', fg='white', activebackground='#f85149',
            command=cancelar, cursor='hand2', padx=15
        )
        cancelar_btn.pack(side='right', padx=2)

        # Centraliza
        _centralizar_sobre(janela, janela_pai)

        # Carrega conteúdo inicial
        atualizar_conteudo()

        # Aguarda o fechamento
        janela.wait_window()

        return selecionados
    def _adicionar_midias_ao_banco(
        self, janela_pai: tk.Toplevel,
        apos_adicionar: Callable[[], None] | None = None,
    ) -> None:
        """Abre seletor de arquivos e adiciona ao banco."""
        arquivos = self._selecionar_arquivos_personalizado(janela_pai)
        if not arquivos:
            return

        adicionados = 0
        for caminho in arquivos:
            if not os.path.exists(caminho):
                continue
            tipo = detectar_tipo_arquivo(caminho)
            if not tipo:
                continue
            nome = os.path.basename(caminho)
            nome_exib = os.path.splitext(nome)[0]
            tamanho = os.path.getsize(caminho)
            mime, _ = mimetypes.guess_type(caminho)

            destino = os.path.join(UPLOAD_FOLDER, nome)
            contador = 1
            while os.path.exists(destino):
                nome_base, ext = os.path.splitext(nome)
                destino = os.path.join(
                    UPLOAD_FOLDER, f"{nome_base}_{contador}{ext}"
                )
                contador += 1

            try:
                shutil.copy2(caminho, destino)
            except Exception as e:
                log.exception(f"Erro ao copiar {caminho}: {e}")
                continue

            db_execute(
                """INSERT INTO midia
                (nome_original, nome_exibicao, tipo, caminho_arquivo,
                 tamanho_bytes, mime_type, data_upload, data_modificacao)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
                (os.path.basename(destino), nome_exib, tipo, destino,
                 tamanho, mime or ''),
            )
            adicionados += 1

        if adicionados > 0:
            # Recarregar cache
            self.db.reload_cache()
            tkinter.messagebox.showinfo(
                "✅ Sucesso",
                f"{adicionados} mídia(s) adicionada(s) ao banco!",
                parent=janela_pai,
            )
            if apos_adicionar is not None:
                apos_adicionar()
        else:
            tkinter.messagebox.showwarning(
                "⚠️", "Nenhuma mídia válida foi adicionada.",
                parent=janela_pai,
            )

