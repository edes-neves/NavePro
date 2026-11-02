"""Janela de janela_hinos do painel do operador (mixin).

Extraída de NavePro.py sem alteração de comportamento: a AppInterface
herda deste mixin para montar a janela.
"""

from __future__ import annotations

import os
import re
import tkinter as tk
import tkinter.messagebox
import tkinter.simpledialog
import xml.etree.ElementTree as ET
from tkinter import ttk

from navepro.core.banco import _inserir_com_id_reuso, db_execute, db_query
from navepro.core.log import get_logger
from navepro.core.slides import _montar_slides_letra
from navepro.core.textos import _numero_do_titulo, _termo_like
from navepro.core.util_tk import _centralizar_sobre
from navepro.core.widgets_arredondados import TkArredondado
from navepro.ui.apoio import _escolher_arquivos_usuario
from navepro.ui.navegacao import (
    _configurar_estilo_treeview_escuro,
    _ligar_busca_com_debounce,
    _termo_da_busca,
)

log = get_logger("janela_hinos")

# Botões e campos desenham cantos arredondados (fachada do tkinter).
tk = TkArredondado(tk)


class JanelaHinosMixin:
    def janela_hinos(self) -> None:
        """Abre a janela de gerenciamento de hinos e letras."""
        janela = tk.Toplevel(self.root)
        janela.title("📖 Hinos / Letras")
        janela.geometry("950x750")
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        _centralizar_sobre(janela, self.root)

        main = tk.Frame(janela, bg='#0d1117')
        main.pack(fill='both', expand=True, padx=15, pady=15)

        tk.Label(main, text="📖 Biblioteca de Hinos e Letras",
                 font=("Arial", 16, "bold"), fg='#f0c040', bg='#0d1117'
                 ).pack(pady=(0, 10))

        # ── Barra de busca ──
        busca_frame = tk.Frame(main, bg='#161b22')
        busca_frame.pack(fill='x', pady=5, ipady=5)

        tk.Label(busca_frame, text="🔍", fg='#f0c040', bg='#161b22',
                 font=("Arial", 14)).pack(side='left', padx=(8, 5))

        placeholder = "Buscar por número, título, artista ou letra..."
        entry_busca = tk.Entry(busca_frame, font=("Arial", 13),
                               bg='#21262d', fg='#8b949e', insertbackground='#f0c040',
                               bd=0, highlightthickness=0)
        entry_busca.pack(side='left', fill='x', expand=True, padx=5, ipady=4)
        entry_busca.insert(0, placeholder)

        # O placeholder/foco/debounce da busca ficam no helper compartilhado
        # (_ligar_busca_com_debounce, mais abaixo).

        # ── TreeView ──
        tree_frame = tk.Frame(main, bg='#161b22')
        tree_frame.pack(fill='both', expand=True, pady=5)

        colunas = ("ID", "Título", "Artista", "Categoria", "CCLI")
        tree = ttk.Treeview(tree_frame, columns=colunas, show='headings', height=18)
        for col in colunas:
            tree.heading(col, text=col)
        tree.column("ID", width=40)
        tree.column("Título", width=250)
        tree.column("Artista", width=200)
        tree.column("Categoria", width=120)
        tree.column("CCLI", width=100)

        scroll_y = tk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll_y.set)
        tree.pack(side='left', fill='both', expand=True)
        scroll_y.pack(side='right', fill='y')

        _configurar_estilo_treeview_escuro()
        def _carregar_hinos(busca: str = ""):
            for item in tree.get_children():
                tree.delete(item)
            # A TreeView só usa estas colunas; não vale trazer a letra inteira
            # de todos os hinos (o banco pode ter milhares de registros).
            campos = "id, titulo, artista, categoria, ccli_numero"
            if busca and busca != placeholder:
                if busca.isdigit():
                    # Número do hino está no começo do título (ex.: "11 - ...").
                    num = int(busca)
                    rows = [r for r in db_query(
                                f"SELECT {campos} FROM letras WHERE ativo = 1 "
                                "ORDER BY titulo")
                            if _numero_do_titulo(r["titulo"]) == num]
                else:
                    busca_like = f"%{_termo_like(busca)}%"
                    rows = db_query(
                        f"SELECT {campos} FROM letras WHERE ativo = 1 AND "
                        "(titulo LIKE ? ESCAPE '\\' OR artista LIKE ? ESCAPE '\\' "
                        "OR letra_completa LIKE ? ESCAPE '\\') "
                        "ORDER BY titulo", (busca_like, busca_like, busca_like))
            else:
                rows = db_query(
                    f"SELECT {campos} FROM letras WHERE ativo = 1 ORDER BY titulo")
            for r in rows:
                tree.insert("", tk.END, iid=str(r['id']),
                            values=(r['id'], r['titulo'], r['artista'],
                                    r['categoria'], r['ccli_numero']))

        def _buscar(event=None):
            _carregar_hinos(_termo_da_busca(entry_busca, placeholder))

        def _buscar_e_projetar(event=None):
            """Enter na busca: filtra e já projeta o primeiro resultado.

            Mesmo efeito de buscar, selecionar a 1ª linha com o mouse e
            clicar em "📺 Projetar". Com o campo vazio não projeta nada.
            """
            termo = _termo_da_busca(entry_busca, placeholder)
            _carregar_hinos(termo)
            if not termo:
                return "break"
            primeiro = tree.get_children()
            if not primeiro:
                tkinter.messagebox.showwarning(
                    "Busca", "Nenhum hino encontrado para projetar.", parent=janela)
                return "break"
            tree.selection_set(primeiro[0])
            tree.focus(primeiro[0])
            _projetar_hino_selecionado()
            return "break"

        entry_busca.bind("<Return>", _buscar_e_projetar)
        # Busca em tempo real com debounce
        _ligar_busca_com_debounce(janela, entry_busca, placeholder, _buscar)

        # ── Importação de letras (XML / TXT) ──
        _NS_OPENLYRICS = "http://openlyrics.info/namespace/2009/song"

        def _texto_no(tag: str, el: ET.Element | None) -> str:
            """Retorna o texto concatenado do primeiro elemento filho com a tag dada."""
            if el is None:
                return ""
            for filho in el.iter():
                if filho.tag == f"{{{_NS_OPENLYRICS}}}{tag}":
                    return "".join(filho.itertext()).strip()
            return ""

        def _parsear_xml_letra(caminho: str) -> dict | None:
            """Extrai {titulo, artista, letra} de um arquivo XML no formato OpenLyrics/OpenLP."""
            try:
                with open(caminho, encoding="utf-8", errors="replace") as f:
                    conteudo = f.read()
                raiz = ET.fromstring(conteudo)

                propriedades = raiz.find(f"{{{_NS_OPENLYRICS}}}properties")
                titulo = _texto_no("title", propriedades)
                artista = _texto_no("author", propriedades)
                if not titulo:
                    titulo = os.path.splitext(os.path.basename(caminho))[0]

                letra = []
                lyrics = raiz.find(f"{{{_NS_OPENLYRICS}}}lyrics")
                if lyrics is not None:
                    versos = []
                    for verse in lyrics.findall(f"{{{_NS_OPENLYRICS}}}verse"):
                        linhas = verse.find(f"{{{_NS_OPENLYRICS}}}lines")
                        if linhas is None:
                            continue
                        texto_verso = "".join(linhas.itertext())
                        texto_verso = re.sub(r"[ \t]+", " ", texto_verso)
                        texto_verso = re.sub(r"\n{3,}", "\n\n", texto_verso)
                        texto_verso = texto_verso.strip("\n")
                        if texto_verso:
                            versos.append(texto_verso)
                    letra = versos

                return {
                    "titulo": titulo,
                    "artista": artista,
                    "letra_completa": "\n\n".join(letra),
                }
            except Exception as e:
                log.exception(f"⚠️ Erro ao ler XML {caminho}: {e}")
                return None

        def _parsear_txt_letra(caminho: str) -> dict | None:
            """Extrai {titulo, artista, letra} de um arquivo TXT (1ª linha = título)."""
            try:
                conteudo = None
                for enc in ("utf-8", "latin-1"):
                    try:
                        with open(caminho, encoding=enc) as f:
                            conteudo = f.read()
                        break
                    except (UnicodeDecodeError, UnicodeError):
                        continue
                if conteudo is None:
                    with open(caminho, encoding="utf-8", errors="replace") as f:
                        conteudo = f.read()

                linhas = [linha.strip() for linha in conteudo.splitlines()]
                linhas = [linha for linha in linhas if linha]
                if not linhas:
                    return None

                titulo = linhas[0]
                letra = "\n".join(linhas[1:])
                return {
                    "titulo": titulo,
                    "artista": "",
                    "letra_completa": letra,
                }
            except Exception as e:
                log.exception(f"⚠️ Erro ao ler TXT {caminho}: {e}")
                return None

        def _importar_letras(caminhos: tuple) -> None:
            """Importa letras de arquivos XML/TXT para a tabela letras."""
            if not caminhos:
                return
            importados, ja_existem, erros = 0, 0, 0
            for caminho in caminhos:
                ext = os.path.splitext(caminho)[1].lower()
                if ext == ".xml":
                    dados = _parsear_xml_letra(caminho)
                elif ext == ".txt":
                    dados = _parsear_txt_letra(caminho)
                else:
                    erros += 1
                    continue

                if not dados or not dados.get("titulo"):
                    erros += 1
                    continue

                titulo = dados["titulo"]
                existente = db_query(
                    "SELECT id FROM letras WHERE titulo = ? AND ativo = 1", (titulo,))
                if existente:
                    ja_existem += 1
                    continue

                _inserir_com_id_reuso(
                    "letras",
                    ("titulo", "artista", "compositor", "ccli_numero",
                     "categoria", "letra_completa"),
                    (titulo, dados["artista"], "", "", "",
                     dados["letra_completa"]))
                importados += 1

            _carregar_hinos()
            msg = f"✅ {importados} importados, {ja_existem} já existentes (pulados)."
            if erros:
                msg += f"\n⚠️ {erros} arquivo(s) com erro."
            tkinter.messagebox.showinfo("Importação", msg, parent=janela)

        def _importar_arquivos() -> None:
            selecionados = _escolher_arquivos_usuario(
                parent=janela,
                titulo="Importar letras (XML / TXT)",
                sufixos=(".xml", ".txt"))
            if selecionados:
                _importar_letras(tuple(selecionados))

        # ── Ajustes da projeção no telão ──
        def _configurar_projecao():
            """Abre janela para ajustar a aparência da projeção no telão."""
            self.abrir_config_projecao_dialogo(janela)

        # ── Botões ──
        btn_frame = tk.Frame(main, bg='#0d1117')
        btn_frame.pack(fill='x', pady=8)

        def _novo_hino():
            _abrir_editor_hino(None)

        def _editar_hino():
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showwarning("Seleção", "Selecione um hino.", parent=janela)
                return
            _abrir_editor_hino(int(sel[0]))

        def _excluir_hino():
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showwarning("Seleção", "Selecione um hino.", parent=janela)
                return
            if not tkinter.messagebox.askyesno("Confirmar",
                    f"Excluir {len(sel)} hino(s)?", parent=janela):
                return
            for hino_id in sel:
                db_execute("DELETE FROM letras WHERE id = ?", (int(hino_id),))
            _carregar_hinos(entry_busca.get().strip())

        tk.Button(btn_frame, text="➕ Novo Hino", font=("Arial", 11, "bold"),
                  bg='#238636', fg='white', activebackground='#2ea043',
                  command=_novo_hino, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="✏️ Editar", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_editar_hino, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="🗑️ Excluir", font=("Arial", 11, "bold"),
                  bg='#da3633', fg='white', activebackground='#f85149',
                  command=_excluir_hino, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="📥 Importar (XML/TXT)", font=("Arial", 11, "bold"),
                  bg='#8b5cf6', fg='white', activebackground='#a78bfa',
                  command=_importar_arquivos, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="🎨 Projeção", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_configurar_projecao, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="📺 Projetar", font=("Arial", 11, "bold"),
                  bg='#6e40c9', fg='#f0c040', activebackground='#8b5cf6',
                  command=lambda: _projetar_hino_selecionado(), cursor='hand2', padx=12, pady=4
                  ).pack(side='right', padx=3)

        # ── Painel de controle da projeção (slides) ──
        nav_frame = tk.Frame(main, bg='#161b22')
        nav_frame.pack(fill='x', pady=(4, 2), ipady=4)

        tk.Label(nav_frame, text="🎬 Controle da Projeção:",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#161b22'
                 ).pack(side='left', padx=(10, 8))

        tk.Button(nav_frame, text="◀ Anterior", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=lambda: _slide_anterior(), cursor='hand2', padx=12, pady=2
                  ).pack(side='left', padx=3)
        tk.Button(nav_frame, text="Próximo ▶", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=lambda: _slide_proximo(), cursor='hand2', padx=12, pady=2
                  ).pack(side='left', padx=3)
        tk.Button(nav_frame, text="⏹ Parar (Esc)", font=("Arial", 11, "bold"),
                  bg='#da3633', fg='white', activebackground='#f85149',
                  command=lambda: _parar_projecao(), cursor='hand2', padx=12, pady=2
                  ).pack(side='left', padx=3)

        tk.Label(nav_frame, text="🔠 Tamanho:",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#161b22'
                 ).pack(side='left', padx=(14, 2))
        tk.Button(nav_frame, text="A−", font=("Arial", 11, "bold"),
                  bg='#8957e5', fg='white', activebackground='#a371f7',
                  command=lambda: _ajustar_fonte(-0.8), cursor='hand2', padx=10, pady=2
                  ).pack(side='left', padx=2)
        tk.Button(nav_frame, text="A+", font=("Arial", 11, "bold"),
                  bg='#8957e5', fg='white', activebackground='#a371f7',
                  command=lambda: _ajustar_fonte(0.8), cursor='hand2', padx=10, pady=2
                  ).pack(side='left', padx=2)
        tk.Button(nav_frame, text="🔃", font=("Arial", 11, "bold"),
                  bg='#8957e5', fg='white', activebackground='#a371f7',
                  command=lambda: _restaurar_fonte(), cursor='hand2', padx=10, pady=2
                  ).pack(side='left', padx=2)

        label_slide = tk.Label(nav_frame, text="Sem projeção",
                               font=("Arial", 11, "bold"), fg='#8b949e', bg='#161b22')
        label_slide.pack(side='right', padx=10)

        _atualizar_indicador_slide = self._criar_atualizador_indicador_slide(
            label_slide)
        _slide_anterior, _slide_proximo, _parar_projecao = \
            self._criar_navegacao_slides(
                ao_navegar=_atualizar_indicador_slide,
                ao_parar=_atualizar_indicador_slide)

        def _ajustar_fonte(delta: float):
            """Aumenta/diminui a fonte da projeção e redesenha o que está ativo."""
            self._ajustar_fonte_projecao(delta, _atualizar_indicador_slide)

        def _restaurar_fonte():
            """Volta a fonte da projeção ao padrão, desfazendo o A−/A+ manual."""
            self._restaurar_fonte_projecao(_atualizar_indicador_slide)

        # Setas do teclado e Esc (janela de hinos e painel).
        self._vincular_teclas_slides(janela, _slide_anterior, _slide_proximo,
                                     _parar_projecao)

        def _projetar_hino_selecionado():
            """Inicia a projeção em slides (título + versos) no telão.

            O administrador navega com as setas do teclado ou nos botões
            do painel; Esc encerra e volta o relógio + temperatura ao telão.
            """
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showwarning("Seleção", "Selecione um hino.", parent=janela)
                return
            hino_id = int(sel[0])
            rows = db_query("SELECT * FROM letras WHERE id = ? AND ativo = 1", (hino_id,))
            if not rows:
                return
            hino = rows[0]
            slides = _montar_slides_letra(hino.get('titulo', ''),
                                          hino.get('letra_completa', ''))
            self.player.telao.projetar_slides(slides)
            _atualizar_indicador_slide()

        # ── Editor de hino ──
        def _abrir_editor_hino(hino_id: int | None = None):
            editar_win = tk.Toplevel(janela)
            editar_win.title("Editar Hino" if hino_id else "Novo Hino")
            editar_win.geometry("600x600")
            editar_win.configure(bg='#0d1117')
            editar_win.transient(janela)
            _centralizar_sobre(editar_win, janela)
            editar_win.after(50, editar_win.grab_set)

            e_main = tk.Frame(editar_win, bg='#0d1117')
            e_main.pack(fill='both', expand=True, padx=15, pady=15)

            # Campos
            campos = {}
            for label_text, campo, _default in [
                ("Título:", "titulo", ""),
                ("Artista:", "artista", ""),
                ("Compositor:", "compositor", ""),
                ("Nº CCLI:", "ccli_numero", ""),
                ("Categoria:", "categoria", ""),
            ]:
                row = tk.Frame(e_main, bg='#0d1117')
                row.pack(fill='x', pady=2)
                tk.Label(row, text=label_text, font=("Arial", 11, "bold"),
                         fg='#f0c040', bg='#0d1117', width=12, anchor='e').pack(side='left')
                entry = tk.Entry(row, font=("Arial", 11), bg='#21262d', fg='#c9d1d9',
                                 insertbackground='#f0c040', bd=0, highlightthickness=0)
                entry.pack(side='left', fill='x', expand=True, padx=5, ipady=3)
                campos[campo] = entry

            tk.Label(e_main, text="Letra completa:", font=("Arial", 11, "bold"),
                     fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x', pady=(8, 2))
            letra_text = tk.Text(e_main, font=("Arial", 11), bg='#21262d', fg='#c9d1d9',
                                 insertbackground='#f0c040', wrap='word', height=18)
            letra_text.pack(fill='both', expand=True, pady=2)

            # Carrega dados se editando
            dados_hino = {}
            if hino_id:
                rows = db_query("SELECT * FROM letras WHERE id = ?", (hino_id,))
                if rows:
                    dados_hino = rows[0]
                    campos['titulo'].insert(0, dados_hino.get('titulo', ''))
                    campos['artista'].insert(0, dados_hino.get('artista', ''))
                    campos['compositor'].insert(0, dados_hino.get('compositor', ''))
                    campos['ccli_numero'].insert(0, dados_hino.get('ccli_numero', ''))
                    campos['categoria'].insert(0, dados_hino.get('categoria', ''))
                    letra_text.insert('1.0', dados_hino.get('letra_completa', ''))

            def _salvar():
                titulo = campos['titulo'].get().strip()
                if not titulo:
                    tkinter.messagebox.showwarning("Erro", "Título é obrigatório.", parent=editar_win)
                    return
                artista = campos['artista'].get().strip()
                compositor = campos['compositor'].get().strip()
                ccli = campos['ccli_numero'].get().strip()
                categoria = campos['categoria'].get().strip()
                letra = letra_text.get('1.0', tk.END).strip()

                if hino_id:
                    db_execute(
                        "UPDATE letras SET titulo=?, artista=?, compositor=?, "
                        "ccli_numero=?, categoria=?, letra_completa=?, "
                        "atualizado_em=datetime('now') WHERE id=?",
                        (titulo, artista, compositor, ccli, categoria, letra, hino_id))
                else:
                    _inserir_com_id_reuso(
                        "letras",
                        ("titulo", "artista", "compositor", "ccli_numero",
                         "categoria", "letra_completa"),
                        (titulo, artista, compositor, ccli, categoria, letra))
                _carregar_hinos()
                editar_win.destroy()

            tk.Button(e_main, text="💾 Salvar", font=("Arial", 12, "bold"),
                      bg='#238636', fg='white', activebackground='#2ea043',
                      command=_salvar, cursor='hand2', padx=20, pady=5
                      ).pack(pady=10)

        _carregar_hinos()
