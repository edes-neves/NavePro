"""Janela de janela_anuncios do painel do operador (mixin).

Extraída de NavePro.py sem alteração de comportamento: a AppInterface
herda deste mixin para montar a janela.
"""

from __future__ import annotations

import json
import os
import re
import tkinter as tk
import tkinter.messagebox
import tkinter.simpledialog
from tkinter import ttk

from navepro.config import EXTENSOES_AUDIO, EXTENSOES_VIDEO, SUFIXOS_IMAGEM
from navepro.core.anuncios import (
    _atualizar_anuncio_db,
    _copiar_arquivo_uploads,
    _excluir_anuncios_db,
    _inserir_anuncio_db,
    _listar_anuncios_db,
    _migrar_anuncios_do_json,
    _tipo_midia_para_arquivo,
)
from navepro.core.fontes_pil import (
    _PCT_FONTE_CAIXA,
    _caixa_texto_padrao,
    _calcular_texto_em_caixa,
    _fonte_familia_do_pil,
)
from navepro.core.log import get_logger
from navepro.core.paths import UPLOAD_FOLDER
from navepro.core.servicos import _extrair_texto_pdf
from navepro.core.util_tk import (
    _centralizar_sobre,
    _habilitar_maximizar_janela,
    _limitar_ao_monitor,
)
from navepro.core.widgets_arredondados import TkArredondado
from navepro.ui.apoio import _escolher_arquivos_usuario
from navepro.ui.navegacao import (
    _configurar_estilo_treeview_escuro,
    _ligar_busca_com_debounce,
    _termo_da_busca,
)

log = get_logger("janela_anuncios")

# Botões e campos desenham cantos arredondados (fachada do tkinter).
tk = TkArredondado(tk)


class JanelaAnunciosMixin:
    def janela_anuncios(self) -> None:
        """Abre a janela de gerenciamento de anúncios.

        Mesma cara da janela "Hinos / Letras", mas:
          - o botão "Novo Anúncio" cria anúncio;
          - o botão "Importar" aceita TXT e PDF (vira slide de texto);
          - "Importar Mídia" aceita vídeo, áudio e imagem (slide de imagem);
          - TUDO é salvo no banco de dados SQLite (tabela "anuncios"),
            inclusive o caminho do arquivo de mídia importado.
        """
        janela = tk.Toplevel(self.root)
        janela.title("📢 Anúncios")
        janela.geometry("1000x700")
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        _centralizar_sobre(janela, self.root)
        _habilitar_maximizar_janela(janela)

        main = tk.Frame(janela, bg='#0d1117')
        main.pack(fill='both', expand=True, padx=15, pady=15)

        titulo_label = tk.Label(main, text="📢 Anúncios",
                font=("Arial", 16, "bold"), fg='#f0c040', bg='#0d1117')
        titulo_label.pack(pady=(0, 2))
        tk.Label(main, text="Salvos no banco de dados SQLite — aceitam texto, vídeo, áudio e slide (imagem)",
                font=("Arial", 9), fg='#8b949e', bg='#0d1117').pack(pady=(0, 8))

        # ── Barra de busca ──
        busca_frame = tk.Frame(main, bg='#161b22')
        busca_frame.pack(fill='x', pady=5, ipady=5)

        tk.Label(busca_frame, text="🔍", fg='#f0c040', bg='#161b22',
                 font=("Arial", 14)).pack(side='left', padx=(8, 5))

        placeholder = "Buscar por título ou texto..."
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

        colunas = ("ID", "Título", "Categoria", "Tipo")
        tree = ttk.Treeview(tree_frame, columns=colunas, show='headings', height=18)
        for col in colunas:
            tree.heading(col, text=col)
        tree.column("ID", width=50)
        tree.column("Título", width=360)
        tree.column("Categoria", width=170)
        tree.column("Tipo", width=150)

        scroll_y = tk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll_y.set)
        tree.pack(side='left', fill='both', expand=True)
        scroll_y.pack(side='right', fill='y')

        _configurar_estilo_treeview_escuro()

        def _carregar_anuncios(busca: str = ""):
            for item in tree.get_children():
                tree.delete(item)
            termo = (busca or "").strip()
            # Ignora o placeholder (ex.: "Buscar por título ou texto...")
            if placeholder and (termo == placeholder or termo.startswith(placeholder)):
                termo = termo[len(placeholder):].strip()
            termo = termo.lower()
            for a in _listar_anuncios_db():
                if termo and termo != "":
                    alvo = " ".join([
                        a.get('titulo', ''),
                        a.get('categoria', ''),
                        a.get('texto', ''),
                    ]).lower()
                    if termo not in alvo:
                        continue
                tipo = a.get('tipo_midia') or 'slide'
                rotulo_tipo = {"slide": "📄 Texto", "video": "🎬 Vídeo",
                               "audio": "🎵 Áudio",
                               "imagem": "🖼️ Imagem"}.get(tipo, tipo)
                tree.insert("", tk.END, iid=str(a.get('id')),
                            values=(a.get('id'), a.get('titulo', ''),
                                    a.get('categoria', ''), rotulo_tipo))

        def _buscar(event=None):
            _carregar_anuncios(_termo_da_busca(entry_busca, placeholder))

        def _buscar_e_projetar(event=None):
            """Enter na busca: filtra e já projeta o primeiro anúncio.

            Mesmo efeito de buscar, selecionar a 1ª linha com o mouse e
            clicar em "📺 Projetar". Com o campo vazio não projeta nada.
            """
            termo = _termo_da_busca(entry_busca, placeholder)
            _carregar_anuncios(termo)
            if not termo:
                return "break"
            primeiro = tree.get_children()
            if not primeiro:
                tkinter.messagebox.showwarning(
                    "Busca", "Nenhum anúncio encontrado para projetar.", parent=janela)
                return "break"
            tree.selection_set(primeiro[0])
            tree.focus(primeiro[0])
            _projetar_anuncio_selecionado()
            return "break"

        entry_busca.bind("<Return>", _buscar_e_projetar)
        # Busca em tempo real com debounce
        _ligar_busca_com_debounce(janela, entry_busca, placeholder, _buscar)

        # ── Importação TXT / PDF ──
        def _parsear_txt_anuncio(caminho: str) -> dict | None:
            """Extrai {titulo, categoria, texto} de um TXT (1ª linha = título)."""
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

                linhas = [linha.strip() for linha in conteudo.splitlines() if linha.strip()]
                if not linhas:
                    return None
                return {
                    "titulo": linhas[0],
                    "categoria": "",
                    "texto": "\n".join(linhas[1:]),
                }
            except Exception as e:
                log.exception(f"⚠️ Erro ao ler TXT de anúncio {caminho}: {e}")
                return None

        def _parsear_pdf_anuncio(caminho: str) -> dict | None:
            """Extrai {titulo, categoria, texto} de um PDF (título = nome do arquivo)."""
            try:
                texto = _extrair_texto_pdf(caminho)
                if not texto:
                    return None
                texto_limpo = re.sub(r"[ \t]+", " ", texto)
                texto_limpo = re.sub(r"\n{3,}", "\n\n", texto_limpo).strip("\n")
                return {
                    "titulo": os.path.splitext(os.path.basename(caminho))[0],
                    "categoria": "",
                    "texto": texto_limpo,
                }
            except Exception as e:
                log.exception(f"⚠️ Erro ao ler PDF de anúncio {caminho}: {e}")
                return None

        def _importar_anuncios(caminhos: tuple) -> tuple:
            """Importa TXT/PDF como anúncios tipo 'slide'.

            Retorna (importados, ja_existem, erros).
            """
            importados, ja_existem, erros = 0, 0, 0
            if not caminhos:
                return importados, ja_existem, erros
            titulos_existentes = {str(a.get('titulo', '')).lower()
                                  for a in _listar_anuncios_db()}
            for caminho in caminhos:
                ext = os.path.splitext(caminho)[1].lower()
                if ext == ".txt":
                    dados = _parsear_txt_anuncio(caminho)
                elif ext == ".pdf":
                    dados = _parsear_pdf_anuncio(caminho)
                else:
                    erros += 1
                    continue

                if not dados or not dados.get("titulo"):
                    erros += 1
                    continue

                titulo = dados["titulo"].strip()
                if titulo.lower() in titulos_existentes:
                    ja_existem += 1
                    continue

                if _inserir_anuncio_db({
                        "titulo": titulo,
                        "categoria": (dados.get('categoria') or '').strip(),
                        "texto": (dados.get('texto') or '').strip(),
                        "tipo_midia": "slide"}):
                    titulos_existentes.add(titulo.lower())
                    importados += 1
                else:
                    erros += 1
            return importados, ja_existem, erros

        def _importar_midias() -> None:
            """Importa TXT/PDF/vídeo/áudio/imagem: cada arquivo vira um anúncio.

            TXT/PDF viram anúncios tipo 'slide' (texto), as mídias mantêm o
            tipo detectado pela extensão.
            """
            sufixos = tuple(sorted(
                EXTENSOES_VIDEO | EXTENSOES_AUDIO | SUFIXOS_IMAGEM | {".txt", ".pdf"}))
            selecionados = _escolher_arquivos_usuario(
                parent=janela,
                titulo="Importar arquivos (TXT / PDF / vídeo / áudio / imagem)",
                sufixos=sufixos)
            if not selecionados:
                return
            importados, ja_existem, erros = 0, 0, 0

            # TXT/PDF primeiro (geram anúncios de texto)
            docs = [c for c in selecionados
                    if os.path.splitext(c)[1].lower() in (".txt", ".pdf")]
            if docs:
                di, dj, de = _importar_anuncios(tuple(docs))
                importados += di
                ja_existem += dj
                erros += de

            for caminho in selecionados:
                ext = os.path.splitext(caminho)[1].lower()
                if not caminho or not os.path.isfile(caminho) or ext in (".txt", ".pdf"):
                    continue
                tipo = _tipo_midia_para_arquivo(caminho)
                if not tipo:
                    erros += 1
                    continue
                destino = _copiar_arquivo_uploads(caminho)
                if destino is None:
                    erros += 1
                    continue
                titulo = os.path.splitext(os.path.basename(caminho))[0]
                if _inserir_anuncio_db({
                        "titulo": titulo,
                        "categoria": "",
                        "texto": "",
                        "tipo_midia": tipo,
                        "arquivo_midia": destino,
                        "nome_arquivo_midia": os.path.basename(destino)}):
                    importados += 1
                else:
                    erros += 1

            _carregar_anuncios()
            msg = f"✅ {importados} anúncio(s) importado(s)."
            if ja_existem:
                msg += f"  ({ja_existem} já existente(s) pulado(s).)"
            if erros:
                msg += f"\n⚠️ {erros} arquivo(s) com erro."
            tkinter.messagebox.showinfo("Importação", msg, parent=janela)

        # ── Ajustes da projeção no telão ──
        def _configurar_projecao():
            self.abrir_config_projecao_dialogo(janela)

        # ── Botões ──
        btn_frame = tk.Frame(main, bg='#0d1117')
        btn_frame.pack(fill='x', pady=8)

        def _novo_anuncio():
            _abrir_editor_anuncio(None)

        def _editar_anuncio():
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showwarning("Seleção", "Selecione um anúncio.", parent=janela)
                return
            _abrir_editor_anuncio(int(sel[0]))

        def _anuncio_duplo_clique(event):
            if tree.identify_region(event.x, event.y) == "heading":
                return
            if not tree.identify_row(event.y):
                return
            if tree.selection():
                _abrir_editor_anuncio(int(tree.selection()[0]))

        tree.bind("<Double-1>", _anuncio_duplo_clique)

        def _excluir_anuncio():
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showwarning("Seleção", "Selecione um anúncio.", parent=janela)
                return
            if not tkinter.messagebox.askyesno("Confirmar",
                    f"Excluir {len(sel)} anúncio(s)?", parent=janela):
                return
            ids_excluir = {int(i) for i in sel}
            if not _excluir_anuncios_db(ids_excluir):
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível gravar a exclusão no banco.",
                    parent=janela)
                return
            _carregar_anuncios(entry_busca.get().strip())

        tk.Button(btn_frame, text="➕ Novo Anúncio", font=("Arial", 11, "bold"),
                  bg='#238636', fg='white', activebackground='#2ea043',
                  command=_novo_anuncio, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="✏️ Editar", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_editar_anuncio, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="🗑️ Excluir", font=("Arial", 11, "bold"),
                  bg='#da3633', fg='white', activebackground='#f85149',
                  command=_excluir_anuncio, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="📥 Importar Mídia", font=("Arial", 11, "bold"),
                  bg='#8b5cf6', fg='white', activebackground='#a78bfa',
                  command=_importar_midias, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="🔄 Transferir (PC↔PC)", font=("Arial", 11, "bold"),
                  bg='#2f6f47', fg='white', activebackground='#3f8f57',
                  command=lambda: self.janela_transferencia(janela),
                  cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="🎨 Projeção", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_configurar_projecao, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="📺 Projetar", font=("Arial", 11, "bold"),
                  bg='#6e40c9', fg='#f0c040', activebackground='#8b5cf6',
                  command=lambda: _projetar_anuncio_selecionado(), cursor='hand2',
                  padx=12, pady=4).pack(side='right', padx=3)

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

        tk.Label(nav_frame, text="🖼️ Imagem:",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#161b22'
                 ).pack(side='left', padx=(14, 2))
        tk.Button(nav_frame, text="−", font=("Arial", 11, "bold"),
                  bg='#8957e5', fg='white', activebackground='#a371f7',
                  command=lambda: _ajustar_imagem(False), cursor='hand2', padx=10, pady=2
                  ).pack(side='left', padx=2)
        tk.Button(nav_frame, text="+", font=("Arial", 11, "bold"),
                  bg='#8957e5', fg='white', activebackground='#a371f7',
                  command=lambda: _ajustar_imagem(True), cursor='hand2', padx=10, pady=2
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

        # Anúncio atualmente projetado (para gravar ao vivo o tamanho da fonte
        # em anúncios de imagem + texto, do mesmo jeito que o modo só-texto já
        # grava a configuração de projeção em config.json). O estado vive em
        # self._anuncio_proj (criado no __init__), compartilhado com o
        # controle remoto — não reatribuir aqui para não apagá-lo.

        def _ajustar_fonte(delta: float):
            telao = self.player.telao
            if getattr(telao, "_mostrando_imagem_com_texto", False):
                # Anúncio de imagem + texto: ajusta o tamanho da fonte (escala
                # 'ts' da caixa de texto) em tempo real, sem tocar na imagem.
                texto = getattr(telao, "_current_text", "")
                if texto:
                    escala = float(getattr(telao, "_texto_escala", 1.0) or 1.0)
                    telao._texto_escala = min(2.5, max(0.25, escala + delta * 0.1))
                    telao._desenhar_texto_anuncio(texto)
                    self._persistir_escala_texto(float(telao._texto_escala))
                _atualizar_indicador_slide()
                return
            self._ajustar_fonte_projecao(delta, _atualizar_indicador_slide)

        def _restaurar_fonte():
            """Volta a fonte ao padrão, desfazendo o A−/A+ manual (ao vivo e salvo)."""
            telao = self.player.telao
            if getattr(telao, "_mostrando_imagem_com_texto", False):
                texto = getattr(telao, "_current_text", "")
                if texto:
                    telao._texto_escala = 1.0
                    telao._desenhar_texto_anuncio(texto)
                    self._persistir_escala_texto(1.0)
                _atualizar_indicador_slide()
                return
            self._restaurar_fonte_projecao(_atualizar_indicador_slide)

        def _ajustar_imagem(aumentar: bool):
            """Redimensiona SOMENTE a imagem já projetada no telão (ao vivo).

            Em anúncios de imagem + texto, é a camada da imagem que muda —
            o texto fica intacto. Em imagem pura, o comportamento é o mesmo
            de antes (escala centralizada). A nova escala é persistida no
            anúncio (config_midia) para valer em todas as projeções seguintes.
            """
            telao = self.player.telao
            if not getattr(telao, "_mostrando_imagem", False):
                return
            if aumentar:
                telao.imagem_aumentar()
            else:
                telao.imagem_diminuir()
            self._persistir_escala_imagem(
                float(getattr(telao, "_imagem_escala", 1.0) or 1.0))

        # Setas do teclado e Esc (janela de anúncios e painel).
        self._vincular_teclas_slides(janela, _slide_anterior, _slide_proximo,
                                     _parar_projecao)

        # Passador de slides (controle remoto): AvPag/RetPag, espaço, F5 e
        # BackSpace também navegam os slides projetados (além das setas).
        self._criar_passador_slides(janela, ao_navegar=_atualizar_indicador_slide)

        def _projetar_anuncio_selecionado():
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showwarning("Seleção", "Selecione um anúncio.", parent=janela)
                return
            res = self.projetar_anuncio(
                int(sel[0]), ao_atualizar=_atualizar_indicador_slide)
            if not res.get('ok'):
                tkinter.messagebox.showwarning(
                    "Anúncio", res.get('erro', ''), parent=janela)

        # ── Editor de anúncio ──
        def _abrir_editor_anuncio(anuncio_id: int | None = None):
            editar_win = tk.Toplevel(janela)
            editar_win.title("Editar Anúncio" if anuncio_id else "Novo Anúncio")
            _limitar_ao_monitor(editar_win, 680, 860)
            editar_win.configure(bg='#0d1117')
            editar_win.transient(janela)
            _centralizar_sobre(editar_win, janela)
            _habilitar_maximizar_janela(editar_win)
            editar_win.after(50, editar_win.grab_set)

            e_main = tk.Frame(editar_win, bg='#0d1117')
            e_main.pack(fill='both', expand=True, padx=15, pady=15)

            # Campos
            campos = {}
            for label_text, campo, _default in [
                ("Título:", "titulo", ""),
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

            # Carrega dados se editando
            dados_anuncio = {}
            if anuncio_id:
                para_editar = next(
                    (a for a in _listar_anuncios_db()
                     if int(a.get('id', 0)) == anuncio_id), None)
                if para_editar:
                    dados_anuncio = dict(para_editar)

            tk.Label(e_main, text="Tipo de conteúdo:", font=("Arial", 11, "bold"),
                     fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x', pady=(8, 2))
            rotulos_tipo = {
                "slide": "📄 Slide (texto)",
                "video": "🎬 Vídeo",
                "audio": "🎵 Áudio",
                "imagem": "🖼️ Imagem (slide)",
            }
            tipo_inicial = (dados_anuncio.get('tipo_midia') or 'slide') or 'slide'
            tipo_var = tk.StringVar(
                value=rotulos_tipo.get(tipo_inicial, rotulos_tipo["slide"]))
            tipo_combo = ttk.Combobox(
                e_main, textvariable=tipo_var, state='readonly',
                values=[rotulos_tipo[k] for k in ("slide", "video", "audio", "imagem")],
                font=("Arial", 11))
            tipo_combo.pack(fill='x', pady=2)

            def _tipo_interno() -> str:
                atual = tipo_var.get()
                if atual in rotulos_tipo:
                    return atual
                for k, v in rotulos_tipo.items():
                    if atual == v:
                        return k
                return "slide"

            arquivo_var = tk.StringVar(value=dados_anuncio.get('arquivo_midia') or '')

            arquivo_row = tk.Frame(e_main, bg='#0d1117')
            arquivo_row.pack(fill='x', pady=(6, 0))
            arquivo_label = tk.Label(arquivo_row, text="Nenhum arquivo selecionado",
                                     font=("Arial", 10), fg='#8b949e', bg='#0d1117',
                                     anchor='w')
            arquivo_label.pack(side='left', fill='x', expand=True, padx=5)

            def _atualizar_arquivo_label():
                caminho = arquivo_var.get().strip()
                if caminho:
                    arquivo_label.config(text=f"📎 {os.path.basename(caminho)}",
                                         fg='#3fb950')
                else:
                    arquivo_label.config(text="Nenhum arquivo selecionado", fg='#8b949e')

            def _escolher_arquivo():
                sufixos = {
                    "video": tuple(sorted(EXTENSOES_VIDEO)),
                    "audio": tuple(sorted(EXTENSOES_AUDIO)),
                    "imagem": tuple(sorted(SUFIXOS_IMAGEM)),
                    "slide": (),
                }[_tipo_interno()]
                if not sufixos:
                    tkinter.messagebox.showinfo(
                        "Dica", "Para tipo 'Slide (texto)' escreva o texto abaixo — "
                                "não precisa de arquivo. Para vídeo/áudio/imagem, "
                                "altere o tipo e selecione o arquivo.", parent=editar_win)
                    return
                titulo_dialogo = f"Escolher arquivo ({_tipo_interno()})"
                selecionados = _escolher_arquivos_usuario(
                    parent=editar_win, titulo=titulo_dialogo, sufixos=sufixos)
                if selecionados:
                    arquivo_var.set(selecionados[0])
                    _atualizar_arquivo_label()
                    _montar_area_conteudo()

            tk.Button(arquivo_row, text="📂 Selecionar arquivo",
                      font=("Arial", 10, "bold"),
                      bg='#1f6feb', fg='white', activebackground='#388bfd',
                      command=_escolher_arquivo, cursor='hand2', padx=10, pady=2
                      ).pack(side='right', padx=5)

            rotulo_texto = tk.Frame(e_main, bg='#0d1117')
            rotulo_texto.pack(fill='x', pady=(8, 2))
            tk.Label(rotulo_texto, text="Texto do anúncio:", font=("Arial", 11, "bold"),
                     fg='#f0c040', bg='#0d1117', anchor='w').pack(side='left')
            btn_copiar_texto = tk.Button(
                rotulo_texto, text="📋 Copiar", font=("Arial", 9, "bold"),
                bg='#21262d', fg='#f0c040', activebackground='#30363d',
                cursor='hand2', padx=10, pady=1,
                command=lambda: _copiar_texto_editor())
            btn_copiar_texto.pack(side='right')

            area_conteudo = tk.Frame(e_main, bg='#0d1117')
            area_conteudo.pack(fill='both', expand=True, pady=2)

            # Estado compartilhado do modo imagem (posição/tamanho no espaço 1440x1080)
            _widget_texto = {"w": None}
            _texto_salvo = {"t": dados_anuncio.get('texto', '') if dados_anuncio else ''}
            # Estado do MODO SLIDE (múltiplas telas): lista de slides + índice atual.
            # Cada slide é {"texto", "imagem", "nome"} (imagem opcional).
            # São persistidos: textos separados por linha em branco na coluna
            # texto (mesmo formato da projeção) e, havendo imagens, o JSON
            # {"mslides": [...]} em config_midia.
            texto_original = dados_anuncio.get('texto', '') if dados_anuncio else ''
            mslides_ini: list = []
            if dados_anuncio:
                try:
                    _cfg_e = json.loads(dados_anuncio.get('config_midia') or '{}')
                    if isinstance(_cfg_e, dict) and isinstance(_cfg_e.get("mslides"), list):
                        mslides_ini = _cfg_e["mslides"]
                except (ValueError, TypeError, AttributeError):
                    mslides_ini = []
            if mslides_ini:
                lista_inicial = [
                    {"texto": (s.get("texto") or '') if isinstance(s, dict) else str(s),
                     "imagem": (s.get("imagem") or '') if isinstance(s, dict) else '',
                     "nome": (s.get("nome") or '') if isinstance(s, dict) else '',
                     "config": (s.get("config") or '') if isinstance(s, dict) else ''}
                    for s in mslides_ini]
            else:
                lista_inicial = [
                    {"texto": seg.strip(), "imagem": '', "nome": ''}
                    for seg in re.split(r'\n\s*\n', texto_original) if seg.strip()]
                if not lista_inicial and texto_original.strip():
                    lista_inicial = [{"texto": texto_original.strip(), "imagem": '', "nome": ''}]
                elif not lista_inicial:
                    lista_inicial = [{"texto": '', "imagem": '', "nome": ''}]
            _slides_estado = {
                "modo": False,
                "lista": lista_inicial,
                "idx": 0,
                "w": None,
            }
            _tam_img = {"w": None, "h": None, "x": None, "y": None, "orig": None}
            # Estado da CAIXA DE TEXTO (mesma prévia): posição/tamanho/escala.
            _tam_txt = {"w": None, "h": None, "x": None, "y": None, "s": 1.0}
            if dados_anuncio:
                try:
                    cfg = json.loads(dados_anuncio.get('config_midia') or '{}')
                    if isinstance(cfg, dict) and cfg.get("w"):
                        _tam_img["w"] = int(cfg["w"])
                        _tam_img["h"] = int(cfg["h"] or 0)
                        _tam_img["x"] = int(cfg.get("x") or 0)
                        _tam_img["y"] = int(cfg.get("y") or 0)
                        # Caixa de texto salva (tx/ty/tw/th/ts), se houver.
                        tw = int(cfg.get("tw") or 0)
                        th = int(cfg.get("th") or 0)
                        if tw > 0 and th > 0:
                            _tam_txt["w"] = tw
                            _tam_txt["h"] = th
                            _tam_txt["x"] = int(cfg.get("tx") or 0)
                            _tam_txt["y"] = int(cfg.get("ty") or 0)
                            _tam_txt["s"] = float(cfg.get("ts") or 1.0)
                except (ValueError, TypeError):
                    pass

            def _ler_texto() -> str:
                """Lê o texto atual (widget ou slides abertos) e sincroniza.

                Para anúncios de slide (múltiplas telas), devolve o texto que
                representa TODOS os slides separados por linha em branco
                (um slide por parágrafo — mesmo formato da projeção).
                """
                if _slides_estado["modo"]:
                    lista = _slides_estado["lista"]
                    idx = _slides_estado["idx"]
                    if 0 <= idx < len(lista):
                        _widget_texto_slide = _slides_estado.get("w")
                        if _widget_texto_slide is not None:
                            lista[idx]["texto"] = _widget_texto_slide.get(
                                '1.0', tk.END).strip()
                        _texto_salvo["t"] = "\n\n".join(
                            s.get("texto", '') for s in lista)
                    return _texto_salvo["t"]
                w = _widget_texto.get("w")
                if w is not None:
                    _texto_salvo["t"] = w.get('1.0', tk.END).strip()
                return _texto_salvo["t"]

            def _copiar_texto_editor():
                """Copia o conteúdo em edição para a área de transferência.

                No modo slide (múltiplas telas), copia APENAS o slide
                atualmente em edição; nos demais tipos, copia o texto todo.
                """
                if _slides_estado["modo"]:
                    lista = _slides_estado["lista"]
                    idx = _slides_estado["idx"]
                    _widget_slide = _slides_estado.get("w")
                    if _widget_slide is not None and 0 <= idx < len(lista):
                        lista[idx]["texto"] = _widget_slide.get(
                            '1.0', tk.END).strip()
                    texto = (lista[idx].get("texto", '')
                             if 0 <= idx < len(lista) else '')
                else:
                    texto = _ler_texto()
                texto = (texto or '').strip()
                if not texto:
                    tkinter.messagebox.showinfo(
                        "Copiar", "Não há texto para copiar neste slide.",
                        parent=editar_win)
                    return
                editar_win.clipboard_clear()
                editar_win.clipboard_append(texto)
                btn_copiar_texto.config(text="✅ Copiado!", bg='#238636',
                                        fg='white')
                editar_win.after(
                    1500, lambda: btn_copiar_texto.config(
                        text="📋 Copiar", bg='#21262d', fg='#f0c040'))

            def _montar_painel_imagem(container, texto_widget, caminho,
                                      tam_img=None, tam_txt=None,
                                      texto_salvo=None, widget_texto=None) -> None:
                """Prévia única: o texto + a imagem no MESMO canvas, como será projetado.

                Coordenadas em espaço virtual 1440x1080 (o mesmo da composição no
                telão); o canvas mostra uma miniatura proporcional. A imagem fica
                por cima do texto, arrastável e redimensionável pelas alças.

                Por padrão usa o estado compartilhado do anúncio de imagem única.
                Passando tam_img/tam_txt/texto_salvo/widget_texto (e o container
                de um Toplevel), a MESMA prévia edita um slide específico do modo
                multi-slide, sem tocar no estado do editor principal.
                """
                if tam_img is None:
                    tam_img = _tam_img
                if tam_txt is None:
                    tam_txt = _tam_txt
                if texto_salvo is None:
                    texto_salvo = _texto_salvo
                if widget_texto is None:
                    widget_texto = _widget_texto
                try:
                    from PIL import Image
                    with Image.open(caminho) as im:
                        tam_img["orig"] = im.size
                except Exception:
                    tam_img["orig"] = None

                VW, VH = 1440, 1080
                ESCALA = 1 / 3.0
                CW = int(VW * ESCALA)
                CH = int(VH * ESCALA)
                LIN_V = 1
                MINV_V = 120
                margem_hv = int(VW * 0.04) or 40
                margem_vv = int(VH * 0.06) or 60
                area_wv = VW - margem_hv * 2
                area_hv = VH - margem_vv * 2

                def _clamp_v(v, lo, hi):
                    return max(lo, min(hi, v))

                painel = tk.Frame(container, bg='#0d1117')
                painel.pack(fill='both', expand=True)

                texto_widget.config(height=5)
                texto_widget.pack(fill='x', side='top', pady=(0, 6))
                widget_texto["w"] = texto_widget

                quadro = tk.Frame(painel, bg='#0d1117')
                quadro.pack(fill='both', expand=True)
                canvas = tk.Canvas(quadro, bg='#0d1117', width=CW, height=CH,
                                   highlightthickness=0)
                canvas.pack(anchor='center')

                origem_img = tam_img.get("orig")
                if not origem_img:
                    canvas.create_text(CW // 2, CH // 2,
                                       text="Imagem inválida", fill='#8b949e',
                                       font=("Arial", 11))
                    return
                ow, oh = origem_img
                aspect = ow / max(1, oh)

                prefe_w = tam_img.get("w")
                prefe_h = tam_img.get("h")
                prefe_x = tam_img.get("x")
                prefe_y = tam_img.get("y")
                tem_posicao = bool(prefe_w and prefe_h and prefe_x and prefe_y)

                if tem_posicao:
                    # Formato novo (virtual 1440x1080): usa o que foi salvo.
                    novo_w = _clamp_v(int(prefe_w), MINV_V, area_wv)
                    novo_h = _clamp_v(int(prefe_h), MINV_V, area_hv)
                    novo_x = _clamp_v(int(prefe_x), LIN_V, VW - LIN_V - novo_w)
                    novo_y = _clamp_v(int(prefe_y), LIN_V, VH - LIN_V - novo_h)
                elif prefe_w and prefe_h:
                    # Migra config antiga (canvas 320x250, sem posição): escala
                    # para o espaço virtual e mantém o layout à direita.
                    s = min(VW / 320.0, VH / 250.0)
                    novo_w = _clamp_v(int(prefe_w * s), MINV_V, area_wv)
                    novo_h = _clamp_v(int(prefe_h * s), MINV_V, area_hv)
                    novo_x = VW - margem_hv - novo_w
                    novo_y = (VH - novo_h) // 2
                else:
                    novo_w = min(int(area_wv * 0.5), int(area_hv * aspect))
                    novo_h = max(MINV_V, int(novo_w / aspect))
                    if novo_h > area_hv:
                        novo_h = int(area_hv)
                        novo_w = max(MINV_V, int(novo_h * aspect))
                    novo_w = max(MINV_V, novo_w)
                    novo_x = VW - margem_hv - novo_w
                    novo_y = (VH - novo_h) // 2

                pos = {"x": novo_x, "y": novo_y, "w": novo_w, "h": novo_h}
                tam = pos
                tam_img.update({"w": novo_w, "h": novo_h, "x": novo_x, "y": novo_y})

                PREVIEW_OK = [True]
                _photo_atual = [None]
                try:
                    from PIL import Image
                except Exception:
                    PREVIEW_OK[0] = False

                def _gerar_foto(w, h):
                    if not PREVIEW_OK[0]:
                        return None
                    try:
                        from PIL import Image, ImageTk
                        with Image.open(caminho) as im:
                            orig = im.convert("RGBA")
                        redim = getattr(Image, "LANCZOS", None) or getattr(Image, "BICUBIC", None)
                        pw, ph = max(1, int(w * ESCALA)), max(1, int(h * ESCALA))
                        foto = ImageTk.PhotoImage(orig.resize((pw, ph), redim), master=canvas)
                        _photo_atual[0] = foto
                        return foto
                    except Exception:
                        return None

                itens = {}

                # Caixa de texto padrão quando o anúncio ainda não salvou uma
                # (layout lado a lado, com a mesma largura/dimensão da projeção).
                if tam_txt.get("w") is None:
                    caixa = _caixa_texto_padrao(
                        texto_salvo.get("t") or "", area_wv, area_hv,
                        margem_hv, margem_vv, aspect_imagem=aspect)
                    tam_txt.update({"w": caixa["w"], "h": caixa["h"],
                                     "x": caixa["x"], "y": caixa["y"],
                                     "s": float(caixa.get("s") or 1.0)})

                def _limpar_canvas():
                    for valor in list(itens.values()):
                        lista = valor if isinstance(valor, (list, tuple)) else (valor,)
                        for it in lista:
                            try:
                                canvas.delete(it)
                            except tk.TclError:
                                pass
                    itens.clear()

                def _desenhar_alcas(x, y, w, h, prefixo, cor):
                    s = 10
                    posicoes = {
                        "nw": (x, y), "n": (x + w // 2, y), "ne": (x + w, y),
                        "w": (x, y + h // 2), "e": (x + w, y + h // 2),
                        "sw": (x, y + h), "s": (x + w // 2, y + h),
                        "se": (x + w, y + h),
                    }
                    for nome, (px, py) in posicoes.items():
                        itens[prefixo + "_" + nome] = canvas.create_rectangle(
                            px - s // 2, py - s // 2, px + s // 2, py + s // 2,
                            fill=cor, outline='white')

                def _alca_em(px, py, prefixo):
                    for nome in ("nw", "n", "ne", "w", "e", "sw", "s", "se"):
                        it_id = itens.get(prefixo + "_" + nome)
                        if it_id is None:
                            continue
                        try:
                            bx1, by1, bx2, by2 = canvas.coords(it_id)
                        except tk.TclError:
                            continue
                        if bx1 <= px <= bx2 and by1 <= py <= by2:
                            return nome
                    return None

                def _renderizar_texto_caixa():
                    """Desenha a caixa de texto (contorno + alças + conteúdo).

                    A caixa é SEMPRE desenhada (mesmo com texto vazio) para que
                    o usuário possa arrastá-la pelo centro e redimensioná-la.
                    O preenchimento translúcido deixa o "meio" da caixa visível
                    e arrastável, exatamente como o meio da imagem.
                    """
                    for chave in list(itens):
                        if chave.startswith("t_"):
                            try:
                                canvas.delete(itens[chave])
                            except tk.TclError:
                                pass
                            del itens[chave]

                    tx = tam_txt.get("x") or 0
                    ty = tam_txt.get("y") or 0
                    tw = max(60, int(tam_txt.get("w") or 60))
                    th = max(60, int(tam_txt.get("h") or 60))
                    px, py = int(tx * ESCALA), int(ty * ESCALA)
                    pw, ph = max(1, int(tw * ESCALA)), max(1, int(th * ESCALA))
                    # Preenchimento translúcido que torna a região arrastável.
                    itens["t_fill"] = canvas.create_rectangle(
                        px, py, px + pw, py + ph, fill='#5c4304', outline='')
                    itens["t_box"] = canvas.create_rectangle(
                        px, py, px + pw, py + ph, outline='#f0c040',
                        dash=(4, 3), width=2)

                    ww = widget_texto.get("w")
                    txt = ww.get('1.0', tk.END).strip() if ww else (
                        str(texto_salvo.get("t") or ""))
                    if not txt:
                        return
                    escala = float(tam_txt.get("s") or 1.0)
                    limite = int(VH * 0.92)
                    fonte_pil, linhas = _calcular_texto_em_caixa(
                        txt, tw, th, base_pct=_PCT_FONTE_CAIXA * escala,
                        limite_alt=limite)
                    familia = _fonte_familia_do_pil(fonte_pil)
                    passo = fonte_pil.size + max(1, fonte_pil.size // 5)
                    cx = px + pw // 2
                    # Mesmo travamento do telão: o bloco fica centralizado na
                    # caixa, mas não sai do espaço virtual 1440x1080.
                    alt_bloco = int(passo * len(linhas) * ESCALA)
                    cy_txt = py + ph // 2 - alt_bloco // 2
                    if cy_txt < 0:
                        cy_txt = 0
                    elif cy_txt + alt_bloco > CH:
                        cy_txt = max(0, CH - alt_bloco)
                    for i, ln in enumerate(linhas):
                        if ln:
                            itens["t_txt_" + str(i)] = canvas.create_text(
                                cx, cy_txt + i * passo * ESCALA, text=ln,
                                anchor='n', width=pw, fill='#c9d1d9',
                                font=(familia, max(
                                    8, int(fonte_pil.size * ESCALA)), 'bold'))
                    # Alças do texto por cima do conteúdo.
                    _desenhar_alcas(px, py, pw, ph, "t_", '#e3b341')

                def _redesenhar(final=False):
                    _limpar_canvas()
                    w, h = tam["w"], tam["h"]
                    x, y = pos["x"], pos["y"]
                    tam_img["x"] = int(x)
                    tam_img["y"] = int(y)
                    tam_img["w"] = int(w)
                    tam_img["h"] = int(h)
                    # 1) texto em caixa ajustável (posição/tamanho próprios)
                    _renderizar_texto_caixa()
                    # 2) imagem, na posição ajustada
                    px, py = int(x * ESCALA), int(y * ESCALA)
                    pw, ph = max(1, int(w * ESCALA)), max(1, int(h * ESCALA))
                    itens["fundo"] = canvas.create_rectangle(
                        px, py, px + pw, py + ph, fill='#0d1117',
                        outline=('#58a6ff' if not final else '#3fb950'),
                        width=2 if final else 1)
                    foto = _gerar_foto(w, h) if final else None
                    if foto is not None:
                        itens["foto"] = canvas.create_image(px, py, image=foto, anchor="nw")
                    else:
                        itens["placeholder"] = canvas.create_text(
                            px + pw // 2, py + ph // 2,
                            text="", fill='#8b949e', font=("Arial", 12))
                    # 3) alças da imagem por cima de tudo
                    _desenhar_alcas(px, py, pw, ph, "h_", '#58a6ff')

                _estado = {"modo": None, "alvo": None, "alca": None,
                           "press_px": (0, 0), "ix": 0, "iy": 0, "iw": 0, "ih": 0}
                _estado_final = [True]

                def _em_retangulo_img(px, py):
                    vx = px / ESCALA
                    vy = py / ESCALA
                    return (pos["x"] <= vx <= pos["x"] + tam["w"]
                            and pos["y"] <= vy <= pos["y"] + tam["h"])

                def _em_retangulo_txt(px, py):
                    vx = px / ESCALA
                    vy = py / ESCALA
                    tx = int(tam_txt.get("x") or 0)
                    ty = int(tam_txt.get("y") or 0)
                    tw = max(60, int(tam_txt.get("w") or 60))
                    th = max(60, int(tam_txt.get("h") or 60))
                    return (tx <= vx <= tx + tw and ty <= vy <= ty + th)

                def _on_press(e):
                    _estado.update({"modo": None, "alvo": None, "alca": None})
                    alca_i = _alca_em(e.x, e.y, "h_")
                    if alca_i:
                        _estado.update({"modo": "resize", "alvo": "img",
                                        "alca": alca_i, "press_px": (e.x, e.y),
                                        "ix": pos["x"], "iy": pos["y"],
                                        "iw": tam["w"], "ih": tam["h"]})
                        return
                    if _em_retangulo_img(e.x, e.y):
                        _estado.update({"modo": "move", "alvo": "img",
                                        "alca": None, "press_px": (e.x, e.y),
                                        "ix": pos["x"], "iy": pos["y"],
                                        "iw": tam["w"], "ih": tam["h"]})
                        return
                    alca_t = _alca_em(e.x, e.y, "t_")
                    if alca_t:
                        _estado.update({"modo": "resize", "alvo": "txt",
                                        "alca": alca_t, "press_px": (e.x, e.y),
                                        "ix": tam_txt["x"], "iy": tam_txt["y"],
                                        "iw": tam_txt["w"], "ih": tam_txt["h"]})
                        return
                    if _em_retangulo_txt(e.x, e.y):
                        _estado.update({"modo": "move", "alvo": "txt",
                                        "alca": None, "press_px": (e.x, e.y),
                                        "ix": tam_txt["x"], "iy": tam_txt["y"],
                                        "iw": tam_txt["w"], "ih": tam_txt["h"]})
                        return

                def _mover_reg(vals, dx, dy, lw, lh):
                    vals["x"] = _clamp_v(_estado["ix"] + dx, LIN_V,
                                         max(LIN_V, VW - LIN_V - _estado["iw"]))
                    vals["y"] = _clamp_v(_estado["iy"] + dy, LIN_V,
                                         max(LIN_V, VH - LIN_V - _estado["ih"]))
                    if lw is not None and lw.get("w"):
                        lw["x"] = int(vals["x"])
                        lw["y"] = int(vals["y"])
                        lw["w"] = int(_estado["iw"])
                        lw["h"] = int(_estado["ih"])

                def _redimensionar_alca(vals, e, final):
                    alca = _estado["alca"]
                    dx = (e.x - _estado["press_px"][0]) / ESCALA
                    dy = (e.y - _estado["press_px"][1]) / ESCALA
                    esq = alca in ("nw", "w", "sw")
                    top = alca in ("nw", "n", "ne")
                    dir_ = alca in ("ne", "e", "se")
                    bot = alca in ("sw", "s", "se")
                    w_lim = ((VW - LIN_V) - _estado["ix"]) if dir_ \
                        else ((_estado["ix"] + _estado["iw"]) - LIN_V)
                    h_lim = ((VH - LIN_V) - _estado["iy"]) if bot \
                        else ((_estado["iy"] + _estado["ih"]) - LIN_V)
                    if alca in ("n", "s"):
                        novo_h = _clamp_v(_estado["ih"] + (dy if bot else -dy),
                                          MINV_V, h_lim)
                        if top:
                            vals["y"] = _estado["iy"] + (_estado["ih"] - novo_h)
                        vals["h"] = novo_h
                    elif alca in ("w", "e"):
                        novo_w = _clamp_v(_estado["iw"] + (dx if dir_ else -dx),
                                          MINV_V, w_lim)
                        if esq:
                            vals["x"] = _estado["ix"] + (_estado["iw"] - novo_w)
                        vals["w"] = novo_w
                    else:
                        # Cantos: preserva a proporção atual do elemento
                        # (imagem ou caixa de texto) — comportamento idêntico
                        # para os dois.
                        rap = _estado["ih"] / max(1, _estado["iw"])
                        delta = dx if abs(dx) >= abs(dy) else dy
                        novo_w = _clamp_v(_estado["iw"] + (delta if dir_ else -delta),
                                          MINV_V, w_lim)
                        novo_h = int(novo_w * rap)
                        if novo_h > h_lim:
                            novo_h = int(h_lim)
                            novo_w = _clamp_v(int(novo_h / rap), MINV_V, w_lim)
                            novo_h = int(novo_w * rap)
                        if novo_h < MINV_V:
                            novo_h = MINV_V
                            novo_w = _clamp_v(int(novo_h / rap), MINV_V, w_lim)
                        if esq:
                            vals["x"] = _estado["ix"] + (_estado["iw"] - novo_w)
                        if top:
                            vals["y"] = _estado["iy"] + (_estado["ih"] - novo_h)
                        vals["w"], vals["h"] = novo_w, novo_h
                    if final:
                        if vals is pos:
                            tam_img.update({"w": int(vals["w"]), "h": int(vals["h"]),
                                             "x": int(vals["x"]), "y": int(vals["y"])})
                        else:
                            tam_txt.update({"w": int(vals["w"]), "h": int(vals["h"]),
                                             "x": int(vals["x"]), "y": int(vals["y"])})

                def _on_motion(e):
                    if not _estado["modo"]:
                        return
                    if _estado["alvo"] == "img":
                        vals, lw = pos, tam_img
                    else:
                        vals, lw = tam_txt, tam_txt
                    if _estado["modo"] == "move":
                        dx = (e.x - _estado["press_px"][0]) / ESCALA
                        dy = (e.y - _estado["press_px"][1]) / ESCALA
                        _mover_reg(vals, dx, dy, lw, None)
                        _redesenhar(final=True)
                        return
                    _redimensionar_alca(vals, e, final=False)
                    _redesenhar(final=False)

                def _on_release(e):
                    if _estado["modo"]:
                        if _estado.get("alvo") == "txt" and _estado["modo"] == "resize":
                            _redimensionar_alca(tam_txt, e, final=True)
                        elif _estado.get("alvo") == "img" and _estado["modo"] == "resize":
                            _redimensionar_alca(pos, e, final=True)
                        elif _estado.get("modo") == "move":
                            if _estado.get("alvo") == "txt":
                                tam_txt.update({"x": int(tam_txt["x"]),
                                                 "y": int(tam_txt["y"])})
                            else:
                                tam_img.update({"x": int(pos["x"]),
                                                 "y": int(pos["y"])})
                        _estado["modo"] = None
                        _estado["alvo"] = None
                        _estado["alca"] = None
                        # Re-aplica alças sob a prévia final
                        _redesenhar(final=True)

                def _ao_digitar(e):
                    if _estado["modo"] is None:
                        _redesenhar(final=_estado_final[0])

                canvas.bind("<ButtonPress-1>", _on_press)
                canvas.bind("<B1-Motion>", _on_motion)
                canvas.bind("<ButtonRelease-1>", _on_release)
                texto_widget.bind("<KeyRelease>", _ao_digitar)

                _redesenhar(final=True)
                tk.Label(painel,
                         text="A prévia mostra tudo como será projetado (texto + imagem "
                              "no mesmo quadro).\n"
                              "IMAGEM: arraste no meio para mover, puxe as alças "
                              "(laterais/cantos) para redimensionar.\n"
                              "TEXTO: a caixa amarela funciona igual — arraste no meio "
                              "para mover, puxe as alças para redimensionar.",
                         bg='#0d1117', fg='#8b949e', justify='left',
                         font=("Arial", 9)).pack(fill='x', pady=(6, 0))

            def _montar_editor_slides(container) -> None:
                """Editor de MÚLTIPLOS slides.

                Cada slide é um texto (com imagem opcional); o operador adiciona
                quantos quiser (botão ➕), remove (➖), atribui imagem por slide
                (🖼️) e edita o conteúdo do slide selecionado no campo abaixo.
                Na gravação, os textos vão separados por linha em branco
                (parágrafo) e, havendo imagens, o JSON {"mslides": [...]} em
                config_midia.
                """
                _slides_estado["modo"] = True
                if not _slides_estado["lista"]:
                    _slides_estado["lista"] = [
                        {"texto": "", "imagem": "", "nome": "", "config": ""}]
                if not (0 <= _slides_estado["idx"] < len(_slides_estado["lista"])):
                    _slides_estado["idx"] = 0

                info = tk.Label(
                    container,
                    text="Adicione quantos slides quiser (texto e, se quiser, "
                         "uma imagem por slide — botão 🖼️):",
                    font=("Arial", 10, "bold"), fg='#f0c040',
                    bg='#0d1117', anchor='w')
                info.pack(fill='x', pady=(0, 4))

                barra = tk.Frame(container, bg='#0d1117')
                barra.pack(fill='x', pady=2)
                tk.Button(barra, text="➕ Adicionar slide",
                          font=("Arial", 10, "bold"),
                          bg='#1f6feb', fg='white', activebackground='#388bfd',
                          command=lambda: _adicionar_slide(), cursor='hand2',
                          padx=10, pady=2).pack(side='left')
                tk.Button(barra, text="➖ Remover slide",
                          font=("Arial", 10, "bold"),
                          bg='#f85149', fg='white', activebackground='#da3633',
                          command=lambda: _remover_slide(), cursor='hand2',
                          padx=10, pady=2).pack(side='left', padx=6)
                tk.Button(barra, text="🖼️ Imagem do slide",
                          font=("Arial", 10, "bold"),
                          bg='#6e40c9', fg='white', activebackground='#8957e5',
                          command=lambda: _escolher_imagem_slide(),
                          cursor='hand2', padx=10, pady=2).pack(side='left')
                tk.Button(barra, text="🗑️ Sem imagem",
                          font=("Arial", 10, "bold"),
                          bg='#30363d', fg='#c9d1d9',
                          activebackground='#484f58',
                          command=lambda: _remover_imagem_slide(),
                          cursor='hand2', padx=10, pady=2).pack(side='left', padx=6)
                contador = tk.Label(barra, text="slide 1 de 1",
                                    font=("Arial", 10),
                                    fg='#8b949e', bg='#0d1117')
                contador.pack(side='right')

                coluna = tk.Frame(container, bg='#0d1117')
                coluna.pack(fill='both', expand=True, pady=2)

                lista_box = tk.Listbox(
                    coluna, height=4, font=("Arial", 10), bg='#21262d',
                    fg='#c9d1d9', selectbackground='#1f6feb',
                    selectforeground='white', activestyle='none',
                    exportselection=False)
                lista_box.pack(fill='x', side='top', pady=(0, 2))
                barra_lista = tk.Scrollbar(coluna, orient='vertical',
                                           command=lista_box.yview)
                lista_box.configure(yscrollcommand=barra_lista.set)

                w_texto = tk.Text(coluna, font=("Arial", 11),
                                  bg='#21262d', fg='#c9d1d9',
                                  insertbackground='#f0c040',
                                  wrap='word', height=8,
                                  exportselection=False)
                _slides_estado["w"] = w_texto
                w_texto.pack(side='bottom', fill='both', expand=True)

                previa = tk.Label(coluna, text="🖼 Sem imagem neste slide",
                                  font=("Arial", 9), fg='#8b949e', bg='#161b22',
                                  height=4, anchor='center')
                previa.pack(fill='x', side='top', pady=(0, 4))

                def _atualizar_previa():
                    """Mostra a imagem do slide selecionado (miniatura)."""
                    idx = _slides_estado["idx"]
                    lista = _slides_estado["lista"]
                    caminho = ''
                    if 0 <= idx < len(lista):
                        caminho = (lista[idx].get("imagem") or '')
                    if caminho and os.path.isfile(caminho):
                        try:
                            from PIL import Image, ImageTk
                            with Image.open(caminho) as im:
                                im = im.convert("RGBA")
                                metodo = (
                                    getattr(Image, "LANCZOS", None)
                                    or getattr(Image, "BICUBIC", None)
                                    or getattr(Image, "ANTIALIAS", None))
                                im.thumbnail((max(80, coluna.winfo_width() - 12), 150),
                                             metodo)
                                foto = ImageTk.PhotoImage(im, master=editar_win)
                            previa.config(text='', image=foto, bg='#161b22',
                                          height=0)
                            previa.imagem = foto
                        except Exception as e:
                            log.warning(f"⚠️ Não foi possível mostrar a miniatura: {e}")
                            previa.config(text="⚠️ Não foi possível exibir a imagem",
                                          image='', bg='#0d1117', height=2)
                    else:
                        previa.config(text="🖼 Sem imagem neste slide", image='',
                                      bg='#161b22', height=4)

                def _atualizar_contador():
                    total = len(_slides_estado["lista"])
                    atual = total if _slides_estado["idx"] >= total else _slides_estado["idx"] + 1
                    contador.config(text=f"slide {max(atual, 1)} de {total}")

                def _atualizar_lista():
                    lista_box.delete(0, tk.END)
                    for i, t in enumerate(_slides_estado["lista"]):
                        rotulo = (t.get("texto") or '').strip().split('\n')[0] or f"(slide {i + 1})"
                        if len(rotulo) > 36:
                            rotulo = rotulo[:36] + "…"
                        marcador = "🖼" if t.get("imagem") else "·"
                        lista_box.insert(tk.END, f"{i + 1}. {marcador} {rotulo}")

                def _commit_slide():
                    """Grava o conteúdo do campo no slide atualmente selecionado."""
                    lista = _slides_estado["lista"]
                    idx = _slides_estado["idx"]
                    if 0 <= idx < len(lista):
                        lista[idx]["texto"] = w_texto.get('1.0', tk.END).strip()

                def _carregar_slide():
                    idx = _slides_estado["idx"]
                    lista = _slides_estado["lista"]
                    w_texto.delete('1.0', tk.END)
                    if 0 <= idx < len(lista):
                        w_texto.insert('1.0', lista[idx]["texto"])
                    if idx < lista_box.size():
                        lista_box.selection_clear(0, tk.END)
                        lista_box.selection_set(idx)
                        lista_box.see(idx)
                    _atualizar_contador()
                    _atualizar_previa()

                def _escolher_slide(event=None):
                    _commit_slide()
                    sel = lista_box.curselection()
                    if sel:
                        _slides_estado["idx"] = int(sel[0])
                    _carregar_slide()

                def _adicionar_slide():
                    _commit_slide()
                    _slides_estado["lista"].append(
                        {"texto": "", "imagem": "", "nome": "", "config": ""})
                    _slides_estado["idx"] = len(_slides_estado["lista"]) - 1
                    _atualizar_lista()
                    _carregar_slide()
                    w_texto.focus_set()

                def _remover_slide():
                    _commit_slide()
                    lista = _slides_estado["lista"]
                    if len(lista) <= 1:
                        tkinter.messagebox.showinfo(
                            "Dica", "É necessário manter pelo menos um slide.",
                            parent=editar_win)
                        return
                    idx = min(_slides_estado["idx"], len(lista) - 1)
                    lista.pop(idx)
                    _slides_estado["idx"] = max(0, idx - 1)
                    _atualizar_lista()
                    _carregar_slide()

                def _escolher_imagem_slide():
                    """Associa uma imagem ao slide atualmente selecionado."""
                    _commit_slide()
                    idx = _slides_estado["idx"]
                    lista = _slides_estado["lista"]
                    if not (0 <= idx < len(lista)):
                        return
                    try:
                        selecionados = _escolher_arquivos_usuario(
                            parent=editar_win, titulo="Escolher imagem do slide",
                            sufixos=tuple(sorted(SUFIXOS_IMAGEM)))
                    except Exception:
                        selecionados = ()
                    if not selecionados:
                        return
                    caminho = selecionados[0]
                    if not os.path.normcase(os.path.abspath(caminho)).startswith(
                            os.path.normcase(os.path.abspath(UPLOAD_FOLDER))):
                        copiado = _copiar_arquivo_uploads(caminho)
                        if copiado is None:
                            tkinter.messagebox.showwarning(
                                "⚠️", "Não foi possível copiar a imagem para uploads.",
                                parent=editar_win)
                            return
                        caminho = copiado
                    lista[idx]["imagem"] = caminho
                    lista[idx]["nome"] = os.path.basename(caminho)
                    _atualizar_lista()
                    _carregar_slide()

                def _remover_imagem_slide():
                    """Remove a imagem do slide atualmente selecionado."""
                    _commit_slide()
                    idx = _slides_estado["idx"]
                    lista = _slides_estado["lista"]
                    if not (0 <= idx < len(lista)) or not lista[idx].get("imagem"):
                        return
                    lista[idx]["imagem"] = ""
                    lista[idx]["nome"] = ""
                    _atualizar_lista()
                    _carregar_slide()

                def _abrir_previa_slide(idx):
                    """Abre a prévia interativa (imagem + texto) de um slide."""
                    lista = _slides_estado["lista"]
                    if not (0 <= idx < len(lista)):
                        return
                    _commit_slide()
                    slide = lista[idx]
                    caminho = (slide.get("imagem") or '').strip()
                    if not os.path.isfile(caminho):
                        tkinter.messagebox.showinfo(
                            "Prévia",
                            "Este slide não tem imagem para posicionar.\n"
                            "Associe uma imagem com o botão 🖼️ Imagem deste slide.",
                            parent=editar_win)
                        return

                    tam_img = {"w": None, "h": None, "x": None, "y": None,
                               "orig": None}
                    tam_txt = {"w": None, "h": None, "x": None, "y": None,
                               "s": 1.0}
                    txt_salvo = {"t": (slide.get("texto") or '').strip()}
                    try:
                        cfg_s = json.loads(slide.get("config") or '{}')
                        if isinstance(cfg_s, dict) and cfg_s.get("w"):
                            tam_img.update(w=int(cfg_s["w"]),
                                           h=int(cfg_s.get("h") or 0),
                                           x=int(cfg_s.get("x") or 0),
                                           y=int(cfg_s.get("y") or 0))
                            if int(cfg_s.get("tw") or 0) > 0 \
                                    and int(cfg_s.get("th") or 0) > 0:
                                tam_txt.update(
                                    w=int(cfg_s["tw"]), h=int(cfg_s["th"]),
                                    x=int(cfg_s.get("tx") or 0),
                                    y=int(cfg_s.get("ty") or 0),
                                    s=float(cfg_s.get("ts") or 1.0))
                    except (ValueError, TypeError, AttributeError):
                        pass

                    prev_win = tk.Toplevel(editar_win)
                    prev_win.title(f"Posicionar imagem e texto — slide {idx + 1}")
                    prev_win.geometry("700x760")
                    prev_win.configure(bg='#0d1117')
                    prev_win.transient(editar_win)
                    _centralizar_sobre(prev_win, editar_win)
                    _habilitar_maximizar_janela(prev_win)

                    def _salvar_previa():
                        slide["texto"] = \
                            w_texto_previa.get('1.0', tk.END).strip()
                        slide["config"] = json.dumps({
                            "w": int(tam_img.get("w") or 0),
                            "h": int(tam_img.get("h") or 0),
                            "x": int(tam_img.get("x") or 0),
                            "y": int(tam_img.get("y") or 0),
                            "tx": int(tam_txt.get("x") or 0),
                            "ty": int(tam_txt.get("y") or 0),
                            "tw": int(tam_txt.get("w") or 0),
                            "th": int(tam_txt.get("h") or 0),
                            "ts": float(tam_txt.get("s") or 1.0),
                        }, separators=(',', ':'))
                        _atualizar_lista()
                        if _slides_estado["idx"] == idx:
                            _carregar_slide()
                        prev_win.destroy()

                    def _fechar_previa(event=None):
                        prev_win.destroy()

                    barra = tk.Frame(prev_win, bg='#0d1117')
                    barra.pack(fill='x', side='bottom', pady=8)
                    tk.Button(barra, text="💾 Salvar posição deste slide",
                              font=("Arial", 11, "bold"), bg='#238636',
                              fg='white', activebackground='#2ea043',
                              command=_salvar_previa, cursor='hand2',
                              padx=18, pady=4).pack(side='left', padx=(12, 6))
                    tk.Button(barra, text="✖ Fechar", font=("Arial", 11),
                              bg='#30363d', fg='#f0f6fc',
                              activebackground='#484f58',
                              command=_fechar_previa, cursor='hand2',
                              padx=12, pady=4).pack(side='left')
                    tk.Label(barra, text="", bg='#0d1117')\
                        .pack(side='left', expand=True)

                    w_texto_previa = tk.Text(prev_win, font=("Arial", 11),
                                             bg='#21262d', fg='#c9d1d9',
                                             insertbackground='#f0c040',
                                             wrap='word', height=8,
                                             exportselection=False)
                    _montar_painel_imagem(prev_win, w_texto_previa,
                                          caminho, tam_img, tam_txt,
                                          txt_salvo, {"w": None})
                    w_texto_previa.delete('1.0', tk.END)
                    w_texto_previa.insert('1.0', txt_salvo["t"])
                    prev_win.after(60, prev_win.grab_set)
                    prev_win.bind('<Escape>', _fechar_previa)

                def _previa_duplo_clique(event=None):
                    sel = lista_box.curselection()
                    if not sel:
                        return
                    idx = int(sel[0])
                    if idx != _slides_estado["idx"]:
                        _slides_estado["idx"] = idx
                        _carregar_slide()
                    _abrir_previa_slide(idx)

                w_texto.bind('<KeyRelease>', lambda e: _commit_slide())
                lista_box.bind('<<ListboxSelect>>', _escolher_slide)
                lista_box.bind('<Double-Button-1>', _previa_duplo_clique)
                lista_box.bind('<Delete>', lambda e: _remover_slide())
                lista_box.bind('<Up>', _carregar_slide)
                lista_box.bind('<Down>', _carregar_slide)
                _atualizar_lista()
                _carregar_slide()

            def _montar_area_conteudo() -> None:
                """Constrói a área de conteúdo conforme o tipo selecionado.

                - 'imagem' com arquivo: prévia única com o texto do anúncio
                  E a imagem no mesmo canvas (sobre o texto), posicionáveis
                  de forma idêntica à projeção.
                - 'slide': editor de MÚLTIPLOS slides (uma tela por parágrafo).
                - demais: campo de texto em largura total (como antes).
                """
                for w in area_conteudo.winfo_children():
                    w.destroy()
                _widget_texto["w"] = None
                _slides_estado["modo"] = False
                _slides_estado["w"] = None

                tipo = _tipo_interno()
                caminho = arquivo_var.get().strip()

                if tipo == "slide":
                    _montar_editor_slides(area_conteudo)
                    return

                eh_imagem = (tipo == "imagem" and caminho
                             and os.path.isfile(caminho)
                             and os.path.splitext(caminho)[1].lower() in SUFIXOS_IMAGEM)

                texto_atual = tk.Text(area_conteudo, font=("Arial", 11),
                                      bg='#21262d', fg='#c9d1d9',
                                      insertbackground='#f0c040',
                                      wrap='word', height=8,
                                      exportselection=False)
                if _texto_salvo["t"]:
                    texto_atual.insert('1.0', _texto_salvo["t"])

                if tipo == "imagem":
                    if eh_imagem:
                        _montar_painel_imagem(area_conteudo, texto_atual, caminho)
                    else:
                        texto_atual.pack(fill='both', expand=True, pady=2)
                        _widget_texto["w"] = texto_atual
                        if caminho:
                            tk.Label(area_conteudo,
                                     text="Arquivo selecionado não é uma imagem.",
                                     fg='#f85149', bg='#0d1117',
                                     font=("Arial", 10)).pack(anchor='w')
                    return

                texto_atual.pack(fill='both', expand=True, pady=2)
                _widget_texto["w"] = texto_atual

            tipo_combo.bind("<<ComboboxSelected>>",
                            lambda e: (_ler_texto(), _montar_area_conteudo()))
            _montar_area_conteudo()

            if dados_anuncio:
                campos['titulo'].insert(0, dados_anuncio.get('titulo', ''))
                campos['categoria'].insert(0, dados_anuncio.get('categoria', ''))
            _atualizar_arquivo_label()

            def _salvar():
                titulo = campos['titulo'].get().strip()
                if not titulo:
                    tkinter.messagebox.showwarning("Erro", "Título é obrigatório.",
                                                   parent=editar_win)
                    return
                categoria = campos['categoria'].get().strip()
                texto = _ler_texto()
                tipo = _tipo_interno()
                nome_arquivo = ""
                arquivo = arquivo_var.get().strip()

                if tipo != "slide":
                    if not arquivo or not os.path.exists(arquivo):
                        tkinter.messagebox.showwarning(
                            "Erro", f"Selecione o arquivo de {rotulos_tipo[tipo].lower()}.",
                            parent=editar_win)
                        return
                    if not os.path.normcase(os.path.abspath(arquivo)).startswith(
                            os.path.normcase(os.path.abspath(UPLOAD_FOLDER))):
                        copiado = _copiar_arquivo_uploads(arquivo)
                        if copiado is None:
                            tkinter.messagebox.showwarning(
                                "⚠️", "Não foi possível copiar o arquivo para uploads.",
                                parent=editar_win)
                            return
                        arquivo = copiado
                    nome_arquivo = os.path.basename(arquivo)

                config_midia = ""
                if _slides_estado["modo"]:
                    # Anúncio de slides: se algum slide tem imagem, guarda o
                    # JSON {"mslides": [...]} para a projeção reutilizar.
                    lista_final = _slides_estado["lista"]
                    tem_imagem = any(
                        (s or {}).get("imagem") for s in lista_final)
                    if tem_imagem:
                        mslides = []
                        for s in lista_final:
                            s = s or {}
                            mslides.append({
                                "texto": (s.get("texto") or '').strip(),
                                "imagem": (s.get("imagem") or ''),
                                "nome": (s.get("nome") or ''),
                                "config": (s.get("config") or ''),
                            })
                        config_midia = json.dumps({"mslides": mslides})
                elif tipo == "imagem" and _tam_img.get("w"):
                    cfg_final = {
                        "w": int(_tam_img["w"]),
                        "h": int(_tam_img.get("h") or 0),
                        "x": int(_tam_img.get("x") or 0),
                        "y": int(_tam_img.get("y") or 0)}
                    tw = int(_tam_txt.get("w") or 0)
                    th = int(_tam_txt.get("h") or 0)
                    if tw > 0 and th > 0:
                        cfg_final.update({
                            "tx": int(_tam_txt.get("x") or 0),
                            "ty": int(_tam_txt.get("y") or 0),
                            "tw": tw,
                            "th": th,
                            "ts": float(_tam_txt.get("s") or 1.0)})
                    config_midia = json.dumps(cfg_final)

                dados_finais = {
                    "titulo": titulo,
                    "categoria": categoria,
                    "texto": texto,
                    "tipo_midia": tipo,
                    "arquivo_midia": arquivo,
                    "nome_arquivo_midia": nome_arquivo,
                    "config_midia": config_midia,
                }
                if anuncio_id:
                    if not _atualizar_anuncio_db(anuncio_id, dados_finais):
                        tkinter.messagebox.showwarning(
                            "⚠️", "Não foi possível gravar no banco.", parent=editar_win)
                        return
                else:
                    if _inserir_anuncio_db(dados_finais) is None:
                        tkinter.messagebox.showwarning(
                            "⚠️", "Não foi possível gravar no banco.", parent=editar_win)
                        return
                _carregar_anuncios()
                editar_win.destroy()

            tk.Button(e_main, text="💾 Salvar", font=("Arial", 12, "bold"),
                      bg='#238636', fg='white', activebackground='#2ea043',
                      command=_salvar, cursor='hand2', padx=20, pady=5
                      ).pack(pady=10)

        _migrar_anuncios_do_json()
        _carregar_anuncios()
