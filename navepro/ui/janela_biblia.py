"""Janela de janela_biblia do painel do operador (mixin).

Extraída de NavePro.py sem alteração de comportamento: a AppInterface
herda deste mixin para montar a janela.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tkinter as tk
import tkinter.messagebox
import tkinter.simpledialog
import unicodedata
import xml.etree.ElementTree as ET
from tkinter import ttk

from navepro.config import SQLITE_TIMEOUT
from navepro.core.banco import _gerador_id_livre, db_query
from navepro.core.log import get_logger
from navepro.core.paths import DB_PATH
from navepro.core.servicos import _analisar_faixa_versiculos
from navepro.core.slides import _buscar_versiculos_por_texto
from navepro.core.util_tk import _centralizar_sobre
from navepro.core.widgets_arredondados import TkArredondado
from navepro.ui.apoio import _escolher_arquivos_usuario

log = get_logger("janela_biblia")

# Botões e campos desenham cantos arredondados (fachada do tkinter).
tk = TkArredondado(tk)


class JanelaBibliaMixin:
    def janela_biblia(self) -> None:
        """Abre a janela de busca bíblica."""
        janela = tk.Toplevel(self.root)
        janela.title("✝️ Bíblia")
        janela.geometry("950x700")
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        _centralizar_sobre(janela, self.root)

        main = tk.Frame(janela, bg='#0d1117')
        main.pack(fill='both', expand=True, padx=15, pady=15)

        tk.Label(main, text="✝️ Busca Bíblica",
                 font=("Arial", 16, "bold"), fg='#f0c040', bg='#0d1117'
                 ).pack(pady=(0, 10))

        # ── Referência rápida ──
        ref_frame = tk.Frame(main, bg='#161b22')
        ref_frame.pack(fill='x', pady=5, ipady=5)

        tk.Label(ref_frame, text="📖", fg='#f0c040', bg='#161b22',
                 font=("Arial", 14)).pack(side='left', padx=(8, 5))

        # Combo de versão
        versoes_disponiveis = []
        rows_v = db_query("SELECT DISTINCT versao FROM versiculos ORDER BY versao")
        if rows_v:
            versoes_disponiveis = [r['versao'] for r in rows_v]
        if not versoes_disponiveis:
            versoes_disponiveis = ["Almeida Revista e Corrigida", "Almeida Século 21"]
        versao_padrao = ("Almeida Revista e Corrigida"
                         if "Almeida Revista e Corrigida" in versoes_disponiveis
                         else versoes_disponiveis[0])
        versao_var = tk.StringVar(value=versao_padrao)
        combo_versao = ttk.Combobox(ref_frame, textvariable=versao_var,
                                     values=versoes_disponiveis, width=28,
                                     font=("Arial", 11))
        combo_versao.pack(side='left', padx=5)

        # Combo de livro
        livro_var = tk.StringVar(value="João")
        combo_livro = ttk.Combobox(ref_frame, textvariable=livro_var,
                                    values=self.LIVROS_BIBLIA, width=18,
                                    font=("Arial", 11))
        combo_livro.pack(side='left', padx=5)

        # Capítulo (digite ou escolha na lista, como versão/livro)
        tk.Label(ref_frame, text="Cap:", fg='#c9d1d9', bg='#161b22',
                 font=("Arial", 10)).pack(side='left', padx=(5, 2))
        cap_var = tk.StringVar(value="3")
        combo_cap = ttk.Combobox(ref_frame, textvariable=cap_var, values=[],
                                 width=4, font=("Arial", 11))
        combo_cap.pack(side='left', padx=2)

        # Versículo (número = só ele, "1-7" = faixa, vazio = capítulo inteiro)
        # Também aceita escolher na lista; continua editável para faixas.
        tk.Label(ref_frame, text="V:", fg='#c9d1d9', bg='#161b22',
                 font=("Arial", 10)).pack(side='left', padx=(5, 2))
        vers_var = tk.StringVar(value="16")
        combo_vers = ttk.Combobox(ref_frame, textvariable=vers_var, values=[],
                                  width=7, font=("Arial", 11))
        combo_vers.pack(side='left', padx=2)

        # ── Área de texto da Bíblia ──
        biblia_text = tk.Text(main, font=("Arial", 13), bg='#21262d', fg='#c9d1d9',
                              insertbackground='#f0c040', wrap='word', height=20)
        biblia_text.pack(fill='both', expand=True, pady=5)

        # ── Barra de busca por texto ──
        busca_frame = tk.Frame(main, bg='#161b22')
        busca_frame.pack(fill='x', pady=5, ipady=5)

        tk.Label(busca_frame, text="🔍", fg='#f0c040', bg='#161b22',
                 font=("Arial", 14)).pack(side='left', padx=(8, 5))

        entry_busca_texto = tk.Entry(busca_frame, font=("Arial", 12),
                                     bg='#21262d', fg='#f0c040', insertbackground='#f0c040',
                                     bd=0, highlightthickness=0)
        entry_busca_texto.pack(side='left', fill='x', expand=True, padx=5, ipady=3)
        entry_busca_texto.insert(0, "Buscar versículo por texto...")

        def _busca_texto_focus_in():
            if entry_busca_texto.get() == "Buscar versículo por texto...":
                entry_busca_texto.delete(0, tk.END)
                entry_busca_texto.config(fg='#f0c040')

        def _busca_texto_focus_out():
            if not entry_busca_texto.get().strip():
                entry_busca_texto.delete(0, tk.END)
                entry_busca_texto.insert(0, "Buscar versículo por texto...")
                entry_busca_texto.config(fg='#8b949e')

        entry_busca_texto.bind("<FocusIn>", lambda e: _busca_texto_focus_in())
        entry_busca_texto.bind("<FocusOut>", lambda e: _busca_texto_focus_out())

        def _buscar_versiculos_texto():
            """Busca versículos por texto e mostra na área da Bíblia.

            Retorna as linhas encontradas (None se busca vazia ou sem dados).
            """
            termo = entry_busca_texto.get().strip()
            if not termo or termo == "Buscar versículo por texto...":
                return None
            versao = versao_var.get()
            rows = _buscar_versiculos_por_texto(versao, termo)
            biblia_text.config(state='normal')
            biblia_text.delete('1.0', tk.END)
            if rows:
                for r in rows:
                    ref = f"{r['livro']} {r['capitulo']}:{r['versiculo']}"
                    biblia_text.insert(tk.END, f"{ref} - {r['texto']}\n\n")
            else:
                biblia_text.insert(tk.END, "Nenhum versículo encontrado para esta busca.\n\n"
                                    "Dica: use o botão '📥 Importar Bíblia (XML/TXT/JSON)'\n"
                                    "para importar uma Bíblia.")
            biblia_text.config(state='disabled')
            return rows

        def _buscar_e_projetar_biblia(event=None):
            """Enter na busca de versículos: busca e já projeta os resultados.

            Mesmo efeito de buscar e clicar em "📺 Projetar", mas projetando
            exatamente o que a busca retornou ("Livro cap:vers. — texto").
            """
            nonlocal _proj_faixa
            rows = _buscar_versiculos_texto()
            if rows:
                _cap_numeros[:] = []
                _proj_faixa = None
                slides = [
                    (r['texto'], f"{r['livro']} {r['capitulo']}:{r['versiculo']}")
                    for r in rows]
                self.player.telao.projetar_slides(slides)
                _atualizar_indicador_slide()
            return "break"

        entry_busca_texto.bind("<Return>", lambda e: _buscar_e_projetar_biblia())

        def _janela_viva() -> bool:
            """True se a janela da Bíblia ainda existe (não foi fechada)."""
            try:
                return bool(janela.winfo_exists())
            except tk.TclError:
                return False

        def _escrever_na_biblia(texto: str) -> None:
            """Substitui o conteúdo da área de texto por `texto`."""
            biblia_text.config(state='normal')
            biblia_text.delete('1.0', tk.END)
            biblia_text.tag_remove('verso_atual', '1.0', tk.END)
            biblia_text.insert(tk.END, texto)
            biblia_text.config(state='disabled')

        def _carregar_capitulo(foco: int | None = None):
            """Carrega a referência atual (versão/livro/cap/V:) na área de texto.

            O campo "V:" define o trecho carregado:
              - vazio   → o capítulo inteiro
              - "7"     → somente o versículo 7
              - "1-7"   → somente os versículos de 1 a 7

            Se `foco` for informado, exibe o capítulo inteiro e destaca o
            versículo correspondente (usado para sincronizar a janela com a
            projeção no telão).
            """
            versao = versao_var.get()
            livro = livro_var.get()
            cap = cap_var.get().strip()
            vers = vers_var.get().strip()
            if not cap or not cap.isdigit():
                return
            cap = int(cap)

            if foco is not None:
                v_ini, v_fim = 1, 9999
            else:
                ok, msg_erro, ini, fim = _analisar_faixa_versiculos(vers)
                if not ok:
                    _escrever_na_biblia(
                        f"{msg_erro}\n\n"
                        "O campo \"V:\" aceita um número (\"7\"), uma faixa "
                        "(\"1-7\") ou fica vazio para o capítulo inteiro.")
                    return
                if ini is None:
                    v_ini, v_fim = 1, 9999
                else:
                    # Número único ("7") = só ele; faixa ("1-7") respeita o
                    # fim digitado (16-16 = só o 16).
                    v_ini, v_fim = ini, fim

            rows = db_query(
                "SELECT * FROM versiculos WHERE versao = ? AND livro = ? "
                "AND capitulo = ? AND versiculo >= ? AND versiculo <= ? "
                "ORDER BY versiculo",
                (versao, livro, cap, v_ini, v_fim))

            if rows:
                biblia_text.config(state='normal')
                biblia_text.delete('1.0', tk.END)
                biblia_text.tag_remove('verso_atual', '1.0', tk.END)
                try:
                    biblia_text.tag_configure('verso_atual', background='#6e40c9',
                                              foreground='#ffffff')
                except tk.TclError:
                    pass
                for r in rows:
                    biblia_text.insert(tk.END, f"{r['versiculo']}. {r['texto']}\n")
                    if foco is not None and r['versiculo'] == foco:
                        inicio_linha = biblia_text.index("end-2c")
                        linha = int(inicio_linha.split('.')[0])
                        biblia_text.tag_add('verso_atual', f"{linha}.0",
                                            f"{linha}.0 lineend")
                        biblia_text.see(f"{linha}.0")
                biblia_text.config(state='disabled')
            else:
                _escrever_na_biblia(
                    f"Nenhum versículo encontrado para {livro} {cap}:{vers or '*'} "
                    f"({versao}).\n\n"
                    "Dica: use o botão '📥 Importar Bíblia (XML/TXT/JSON)'\n"
                    "para importar uma Bíblia.")

        # ── Carga automática da referência ──
        # Versão, livro, capítulo e versículo já carregam o trecho 500 ms
        # após a última alteração, dispensando o botão "Carregar". As escritas
        # feitas pelo próprio app NÃO devem disparar recarga: o "V:" que a
        # sincronização com o telão grava a cada versículo projetado e a
        # versão escolhida pela importação de Bíblia. Por isso o bloqueio
        # _travado_recarga.
        _travado_recarga = False
        _id_recarga: str | None = None

        def _cancelar_recarga() -> None:
            """Cancela a recarga agendada (chamado antes de agendar outra)."""
            nonlocal _id_recarga
            if _id_recarga is not None:
                try:
                    janela.after_cancel(_id_recarga)
                except tk.TclError:
                    pass
                _id_recarga = None

        def _recarga_agendada() -> None:
            nonlocal _id_recarga
            _id_recarga = None
            if _janela_viva():
                _carregar_capitulo()

        def _agendar_recarga() -> None:
            nonlocal _id_recarga
            if _travado_recarga:
                return
            _cancelar_recarga()
            _id_recarga = janela.after(500, _recarga_agendada)

        def _ao_alterar_referencia(*_args) -> None:
            _agendar_recarga()

        # ── Opções dos combos de capítulo e versículo ──
        # "Cap:" e "V:" funcionam como versão/livro: o operador pode digitar ou
        # escolher na lista. As listas são recalculadas conforme a
        # versão/livro/capítulo escolhidos. Atualizar só os `values` não altera
        # as variáveis, então não dispara a recarga automática.
        def _atualizar_opcoes_versiculos(*_args) -> None:
            """Preenche o combo "V:" com os versículos do capítulo atual."""
            versao = versao_var.get()
            livro = livro_var.get()
            cap = cap_var.get().strip()
            valores: list[str] = []
            if cap.isdigit():
                linhas = db_query(
                    "SELECT DISTINCT versiculo FROM versiculos "
                    "WHERE versao = ? AND livro = ? AND capitulo = ? "
                    "ORDER BY versiculo", (versao, livro, int(cap)))
                valores = [str(r['versiculo']) for r in linhas]
            combo_vers.config(values=valores)

        def _atualizar_opcoes_capitulos(*_args) -> None:
            """Preenche o combo "Cap:" com os capítulos do livro/versão."""
            versao = versao_var.get()
            livro = livro_var.get()
            linhas = db_query(
                "SELECT DISTINCT capitulo FROM versiculos "
                "WHERE versao = ? AND livro = ? ORDER BY capitulo",
                (versao, livro))
            combo_cap.config(values=[str(r['capitulo']) for r in linhas])
            _atualizar_opcoes_versiculos()

        versao_var.trace_add('write', _atualizar_opcoes_capitulos)
        livro_var.trace_add('write', _atualizar_opcoes_capitulos)
        cap_var.trace_add('write', _atualizar_opcoes_versiculos)
        _atualizar_opcoes_capitulos()

        for _var_ref in (versao_var, livro_var, cap_var, vers_var):
            _var_ref.trace_add('write', _ao_alterar_referencia)

        def _ao_destruir_janela(event) -> None:
            if event.widget is janela:
                _cancelar_recarga()

        janela.bind("<Destroy>", _ao_destruir_janela)

        # ── Importação de Bíblia (XML / TXT) ──
        def _sem_acentos(texto: str) -> str:
            nf = unicodedata.normalize('NFKD', str(texto))
            return ''.join(c for c in nf if not unicodedata.combining(c)).casefold()

        _LIVROS_FLAT = {_sem_acentos(n): n for n in self.LIVROS_BIBLIA}
        _LIVROS_ALIAS = {
            "cantico dos canticos": "Cânticos",
            "cantares": "Cânticos",
            "lamentacoes de jeremias": "Lamentações",
        }

        def _normalizar_livro_biblia(nome: str) -> str | None:
            """Converte o nome do livro para o padrão da lista do app.

            Insensível a acentos e a variações comuns: números romanos
            (I/II) e nomes completos ('Lamentações de Jeremias',
            'Cântico dos Cânticos'). Retorna None se não reconhecer.
            """
            chave = _sem_acentos(nome or '')
            if not chave:
                return None
            if chave in _LIVROS_FLAT:
                return _LIVROS_FLAT[chave]
            if chave in _LIVROS_ALIAS:
                return _LIVROS_ALIAS[chave]
            for rom, num in (("iii", "3"), ("ii", "2"), ("i", "1")):
                prefixo = rom + " "
                if chave.startswith(prefixo):
                    cand = num + " " + chave[len(prefixo):]
                    return _LIVROS_FLAT.get(cand)
            return None

        def _parsear_biblia_xml(caminho: str) -> tuple:
            """Lê uma Bíblia em XML (estilo Zefania: BIBLEBOOK/CHAPTER/VERS).

            Retorna (versao, versiculos, livros_desconhecidos), onde
            versiculos é uma lista de tuplas (versao, livro, capitulo,
            versiculo, texto).
            """
            tree = ET.parse(caminho)
            raiz = tree.getroot()
            versao = (raiz.get('biblename') or
                      os.path.splitext(os.path.basename(caminho))[0] or
                      "Bíblia")
            versiculos = []
            desconhecidos = set()
            for bb in raiz.findall('BIBLEBOOK'):
                livro = _normalizar_livro_biblia(bb.get('bname'))
                if not livro:
                    desconhecidos.add(bb.get('bname'))
                    continue
                for ch in bb.findall('CHAPTER'):
                    cap_t = ch.get('cnumber')
                    if not cap_t or not cap_t.isdigit():
                        continue
                    cap = int(cap_t)
                    for v in ch.findall('VERS'):
                        nv_t = v.get('vnumber')
                        if not nv_t or not nv_t.isdigit():
                            continue
                        texto = (v.text or '').strip()
                        if not texto:
                            continue
                        versiculos.append((versao, livro, cap, int(nv_t), texto))
            return versao, versiculos, desconhecidos

        def _parsear_biblia_txt(caminho: str) -> tuple:
            """Lê uma Bíblia em TXT (formato Almeida Revista e Corrigida).

            Estrutura: linhas ' LIVRO CAP', linhas 'N texto do versículo',
            separadores com o nome do livro sozinho e possível continuação
            de versículo na linha seguinte. Números romanos (I/II) são
            convertidos e nomes completos são normalizados.
            """
            versao = "Almeida Revista e Corrigida"
            _re_header = re.compile(r'^\s*(.+?)(\d{1,3})\s*$')
            _re_verso = re.compile(r'^\s*(\d{1,3})\s+(.*)$')
            versiculos = []
            desconhecidos = set()
            livro_atual = None
            cap_atual = None
            for linha in open(caminho, encoding='utf-8', errors='replace'):
                s = linha.rstrip('\n')
                t = s.strip()
                if not t:
                    continue
                if t in ("ANTIGO TESTAMENTO", "NOVO TESTAMENTO"):
                    continue
                # Separador com o nome do livro sozinho (ex.: "ÊXODO")
                if _normalizar_livro_biblia(t) is not None:
                    continue
                # Cabeçalho de capítulo: '<nome do livro> <número>'
                m = _re_header.match(s)
                if m:
                    novo_livro = _normalizar_livro_biblia(m.group(1).strip())
                    if novo_livro is not None:
                        livro_atual = novo_livro
                        cap_atual = int(m.group(2))
                        continue
                # Versículo: '<número> <texto>'
                m = _re_verso.match(s)
                if m and livro_atual is not None and cap_atual is not None:
                    versiculos.append((versao, livro_atual, cap_atual,
                                       int(m.group(1)), m.group(2).strip()))
                elif versiculos and livro_atual is not None and cap_atual is not None:
                    # Continuação de versículo na linha seguinte
                    linhas = versiculos[-1][4] + " " + t
                    versiculos[-1] = (versiculos[-1][0], versiculos[-1][1],
                                      versiculos[-1][2], versiculos[-1][3], linhas)
            return versao, versiculos, desconhecidos

        def _parsear_biblia_json(caminho: str) -> tuple:
            """Lê uma Bíblia em JSON e retorna (versao, versiculos, desconhecidos).

            Aceita as estruturas mais comuns:
            - {Livro: {cap: {vers: texto}}}
            - {Livro: {cap: [texto1, texto2, ...]}}
            - {"books": [{"name": ..., "chapters": [[{"verse": n, "text": ...}]]}]}
            - [{"book": ..., "chapter": n, "verse": n, "text": ...}] (lista plana)
            A versão é lida das chaves 'version'/'versao'/'biblename' do objeto
            raiz, ou do nome do arquivo.
            """
            with open(caminho, encoding='utf-8-sig') as f:
                dados = json.load(f)
            versiculos = []
            desconhecidos = set()
            raiz = dados

            # Extrai o nome da versão das chaves de metadados do objeto raiz
            versao = None
            if isinstance(raiz, dict):
                for chave in ("version", "versao", "biblename", "translation",
                              "nome", "name"):
                    v = raiz.get(chave)
                    if isinstance(v, str) and v.strip():
                        versao = v.strip()
                        break
            if not versao:
                versao = (os.path.splitext(os.path.basename(caminho))[0] or "Bíblia")

            def _texto(obj) -> str:
                if isinstance(obj, str):
                    return obj.strip()
                if isinstance(obj, dict):
                    for chave in ("text", "texto"):
                        v = obj.get(chave)
                        if isinstance(v, str):
                            return v.strip()
                        if isinstance(v, (int, float)):
                            return str(v)
                    for v in obj.values():
                        if isinstance(v, str):
                            return v.strip()
                    return ""
                if isinstance(obj, list):
                    partes = [p for p in (_texto(x) for x in obj) if p]
                    return " ".join(partes)
                if isinstance(obj, (int, float)):
                    return str(obj)
                return ""

            def _numero(obj, *chaves) -> int | None:
                if isinstance(obj, dict):
                    for chave in chaves:
                        v = obj.get(chave)
                        if v is None:
                            continue
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            return int(v)
                        m = re.match(r'^\s*(\d+)', str(v))
                        if m:
                            return int(m.group(1))
                return None

            def _versiculos_capitulo(valor, cap, livro) -> None:
                """Extrai os versículos de um capítulo (dict ou lista)."""
                if isinstance(valor, dict):
                    for vk, vv in valor.items():
                        num = _numero({"_": vk}, "_") if str(vk).strip().isdigit() \
                            else _numero(vv, "verse", "versiculo", "n", "num")
                        if num is None:
                            continue
                        texto = _texto(vv)
                        if texto:
                            versiculos.append((versao, livro, cap, num, texto))
                elif isinstance(valor, list):
                    for i, item in enumerate(valor, start=1):
                        if isinstance(item, dict):
                            num = _numero(item, "verse", "versiculo", "n", "num", "v")
                            texto = _texto(item)
                            if num is None or not texto:
                                continue
                            versiculos.append((versao, livro, cap, num, texto))
                        else:
                            texto = _texto(item)
                            if texto:
                                versiculos.append((versao, livro, cap, i, texto))
                elif isinstance(valor, str) and valor.strip():
                    versiculos.append((versao, livro, cap, 1, valor.strip()))

            def _processar_livro(nome, valor) -> None:
                nonlocal versao
                livro = _normalizar_livro_biblia(nome)
                if not livro:
                    desconhecidos.add(str(nome))
                    return
                if isinstance(valor, dict) and any(k in valor for k in
                                                   ("chapters", "textos")):
                    # formato {name/abbrev, chapters: [[verso1, verso2, ...]]}
                    dados = valor.get("chapters")
                    if not isinstance(dados, (list, dict)):
                        dados = valor.get("textos")
                    if isinstance(dados, (list, dict)):
                        valor = dados
                    else:
                        return
                if isinstance(valor, dict):
                    cap = _numero(valor, "chapter", "capitulo", "cnumber")
                    num = _numero(valor, "verse", "versiculo", "n", "v")
                    if cap is not None and num is not None:
                        # objeto de versículo único {book, chapter, verse, text}
                        texto = _texto(valor)
                        if texto:
                            versiculos.append((versao, livro, cap, num, texto))
                        return
                    for ck, cv in valor.items():
                        cap = _numero({"_": ck}, "_") if str(ck).strip().isdigit() \
                            else _numero(cv, "chapter", "capitulo", "cnumber")
                        if cap is None:
                            # formato {livro: [{chapter: 1, verses: [...]}]}
                            if isinstance(cv, list) and cv and all(
                                    isinstance(x, dict) for x in cv):
                                for obj in cv:
                                    c2 = _numero(obj, "chapter", "capitulo")
                                    if c2 is None:
                                        continue
                                    _versiculos_capitulo(obj.get("verses",
                                                                  obj.get("textos",
                                                                         [])), c2, livro)
                                continue
                            continue
                        _versiculos_capitulo(cv, cap, livro)
                elif isinstance(valor, list):
                    if not valor:
                        return
                    if isinstance(valor[0], dict):
                        # lista plana de versículos OU de capítulos
                        tem_cap = any(any(k in v for k in ("chapter", "capitulo"))
                                      for v in valor)
                        tem_ver = any(any(k in v for k in ("verse", "versiculo",
                                                           "v", "n"))
                                      for v in valor)
                        if tem_cap and tem_ver:
                            for obj in valor:
                                cap = _numero(obj, "chapter", "capitulo")
                                num = _numero(obj, "verse", "versiculo", "v", "n")
                                texto = _texto(obj)
                                if cap is None or num is None or not texto:
                                    continue
                                versiculos.append((versao, livro, cap, num, texto))
                        else:
                            # lista de capítulos: [{n/chapter: c, verses/textos: [...]}]
                            for obj in valor:
                                cap = _numero(obj, "chapter", "capitulo", "n")
                                if cap is None:
                                    continue
                                _versiculos_capitulo(
                                    obj.get("verses", obj.get("textos", [])), cap, livro)
                    elif isinstance(valor[0], list):
                        # lista de capítulos, cada um uma lista de versículos
                        for i, cap_lista in enumerate(valor, start=1):
                            _versiculos_capitulo(cap_lista, i, livro)
                    else:
                        # lista de textos (capítulo único)
                        _versiculos_capitulo(valor, 1, livro)

            if isinstance(raiz, dict):
                for chave, valor in raiz.items():
                    if chave.lower() in ("version", "versao", "biblename",
                                         "translation", "nome", "name", "id",
                                         "info", "metadata", "language", "lang"):
                        continue
                    # {"books": [...]} -> cada item tem o nome do livro
                    if chave.lower() == "books" and isinstance(valor, list):
                        for item in valor:
                            nome = item.get("name") or item.get("nome") or \
                                   item.get("book") or item.get("livro")
                            if not nome:
                                continue
                            dados_livro = item.get("chapters") or item.get("textos") \
                                or item
                            _processar_livro(nome, dados_livro)
                    else:
                        _processar_livro(chave, valor)
            elif isinstance(raiz, list):
                for item in raiz:
                    nome = item.get("book") or item.get("livro") or \
                           item.get("name") if isinstance(item, dict) else None
                    if nome:
                        _processar_livro(nome, item)
                    else:
                        desconhecidos.add(str(item)[:40])
            return versao, versiculos, desconhecidos

        def _importar_biblia(caminhos: tuple) -> None:
            """Importa uma ou mais Bíblias (XML/TXT/JSON) para a tabela versiculos."""
            nonlocal _travado_recarga
            total_inseridos = 0
            total_pulados = 0
            erros = 0
            versoes_importadas = []
            desconhecidos = set()
            for caminho in caminhos:
                ext = os.path.splitext(caminho)[1].lower()
                try:
                    if ext == '.xml':
                        versao, vv, desc = _parsear_biblia_xml(caminho)
                    elif ext == '.txt':
                        versao, vv, desc = _parsear_biblia_txt(caminho)
                    elif ext == '.json':
                        versao, vv, desc = _parsear_biblia_json(caminho)
                    else:
                        erros += 1
                        continue
                except Exception as e:
                    log.exception(f"Erro ao importar bíblia {caminho}: {e}")
                    erros += 1
                    continue
                desconhecidos.update(desc)
                existentes = {
                    (r['versao'], r['livro'], r['capitulo'], r['versiculo'])
                    for r in db_query(
                        "SELECT versao, livro, capitulo, versiculo FROM versiculos "
                        "WHERE versao = ?", (versao,))
                }
                novos = [v for v in vv
                         if (v[0], v[1], v[2], v[3]) not in existentes]
                total_pulados += len(vv) - len(novos)
                if novos:
                    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT)
                    try:
                        ids_livres = list(
                            _gerador_id_livre("versiculos",
                                              limitar=len(novos)))
                        com_id = []
                        sem_id = []
                        for idx, ver in enumerate(novos):
                            if idx < len(ids_livres):
                                com_id.append((ids_livres[idx],) + tuple(ver))
                            else:
                                sem_id.append(tuple(ver))
                        if com_id:
                            conn.executemany(
                                "INSERT INTO versiculos "
                                "(id, versao, livro, capitulo, versiculo, texto) "
                                "VALUES (?, ?, ?, ?, ?, ?)", com_id)
                        if sem_id:
                            conn.executemany(
                                "INSERT INTO versiculos "
                                "(versao, livro, capitulo, versiculo, texto) "
                                "VALUES (?, ?, ?, ?, ?)", sem_id)
                        conn.commit()
                    finally:
                        conn.close()
                    total_inseridos += len(novos)
                if versao not in versoes_importadas:
                    versoes_importadas.append(versao)

            msg = f"✅ {total_inseridos} versículos importados, " \
                  f"{total_pulados} já existentes (pulados)."
            if versoes_importadas:
                msg += f"\n📚 Versões: {', '.join(versoes_importadas)}"
            if desconhecidos:
                msg += f"\n⚠️ {len(desconhecidos)} livro(s) não reconhecidos: " \
                       f"{', '.join(str(x) for x in sorted(desconhecidos))}"
            if erros:
                msg += f"\n⚠️ {erros} arquivo(s) com erro."
            tkinter.messagebox.showinfo("Importação de Bíblia", msg, parent=janela)

            # Atualiza lista de versões e carrega a primeira importada
            atuais = db_query("SELECT DISTINCT versao FROM versiculos ORDER BY versao")
            novas_versoes = [r['versao'] for r in atuais]
            if novas_versoes:
                combo_versao.config(values=novas_versoes)
            if versoes_importadas:
                # A escolha da versão não recarrega sozinha: a carga é feita
                # na linha seguinte, uma única vez.
                _travado_recarga = True
                try:
                    versao_var.set(versoes_importadas[0])
                finally:
                    _travado_recarga = False
                _carregar_capitulo()

        def _importar_biblia_dialog() -> None:
            selecionados = _escolher_arquivos_usuario(
                parent=janela,
                titulo="Importar Bíblia (XML / TXT / JSON)",
                pasta_inicial=os.path.expanduser("~"))
            if selecionados:
                _importar_biblia(selecionados)

        # ── Botões ──
        btn_frame = tk.Frame(main, bg='#0d1117')
        btn_frame.pack(fill='x', pady=5)

        tk.Button(btn_frame, text="🔍 Buscar Texto", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_buscar_versiculos_texto, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="📥 Importar Bíblia (XML/TXT)", font=("Arial", 11, "bold"),
                  bg='#8b5cf6', fg='white', activebackground='#a78bfa',
                  command=_importar_biblia_dialog, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="🎨 Projeção", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=lambda: self.abrir_config_projecao_dialogo(janela, mostrar_cor_ref=True),
                  cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="📺 Projetar", font=("Arial", 11, "bold"),
                  bg='#6e40c9', fg='#f0c040', activebackground='#8b5cf6',
                  command=lambda: _projetar_versiculo(), cursor='hand2', padx=12, pady=4
                  ).pack(side='right', padx=3)

        def _projetar_versiculo():
            """Projeta os versículos da referência aberta no telão.

            O campo "V:" define o que é projetado, com a mesma regra usada
            no carregamento da janela:
              - vazio    → o capítulo inteiro, começando no versículo 1
              - "7"      → somente o versículo 7
              - "9-16"   → somente os versículos de 9 a 16 (um a um)

            O administrador navega entre versículos com as setas do teclado,
            do painel ou do controle remoto. Ao passar do último versículo da
            faixa, a projeção se encerra como a tecla Esc e o telão volta a
            mostrar o relógio + temperatura.
            """
            nonlocal _proj_faixa
            versao = versao_var.get()
            livro = livro_var.get()
            cap_t = cap_var.get().strip()
            if not cap_t.isdigit():
                return
            cap = int(cap_t)
            rows = db_query(
                "SELECT versiculo, texto FROM versiculos WHERE versao = ? "
                "AND livro = ? AND capitulo = ? ORDER BY versiculo",
                (versao, livro, cap))
            if not rows:
                tkinter.messagebox.showwarning(
                    "Projeção", "Nenhum versículo para projetar neste capítulo.",
                    parent=janela)
                return
            vers_t = vers_var.get().strip()
            ok, msg_erro, ini, fim = _analisar_faixa_versiculos(vers_t)
            if not ok:
                tkinter.messagebox.showwarning("Projeção", msg_erro, parent=janela)
                return
            if ini is None:
                ini = 1
            # Número único ("16") ou faixa explícita ("9-16"): projeta só os
            # versículos pedidos; vazio mantém o capítulo inteiro.
            if vers_t:
                rows = [r for r in rows if ini <= r['versiculo'] <= fim]
                if not rows:
                    ref_ausente = f"{ini}" if ini == fim else f"{ini}-{fim}"
                    tkinter.messagebox.showwarning(
                        "Projeção",
                        f"Nenhum versículo encontrado para {livro} "
                        f"{cap}:{ref_ausente} ({versao}).", parent=janela)
                    return

            numeros = [r['versiculo'] for r in rows]
            _cap_numeros[:] = numeros
            _proj_faixa = (ini, fim) if "-" in vers_t else None
            slides = [(r['texto'], f"{livro} {cap}:{r['versiculo']}") for r in rows]
            inicio = numeros.index(ini) if ini in numeros else 0
            self.player.telao.projetar_slides(slides, indice_inicial=inicio)
            # A janela segue mostrando o trecho pedido (a carga automática já
            # trouxe "9-16"); se o versículo inicial não estiver visível, o
            # foco de sincronismo recarrega o capítulo e destaca ele.
            if not _destacar_versiculo_na_tela(numeros[inicio]):
                _carregar_capitulo(foco=numeros[inicio])
            _atualizar_indicador_slide()

        # ── Painel de controle da projeção (versículos) ──
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

        _cap_numeros = []
        # Faixa projetada ("9-16") quando a projeção não cobre o capítulo
        # inteiro; None quando é o capítulo inteiro ou uma busca por texto.
        _proj_faixa: tuple | None = None

        def _atualizar_indicador_slide():
            try:
                if not label_slide.winfo_exists():
                    return
            except tk.TclError:
                return
            telao = self.player.telao
            em_slides = getattr(telao, "_em_slides", False)
            if em_slides and telao._slides:
                idx = telao._slide_index
                if _cap_numeros and 0 <= idx < len(_cap_numeros):
                    num = f"Versículo {_cap_numeros[idx]}"
                else:
                    num = f"Versículo {idx + 1}"
                # Numa faixa "9-16" o total de slides (8) não é o total do
                # capítulo, então o rótulo mostra a faixa em vez de "de 8".
                rotulo = (f"{num} · faixa {_proj_faixa[0]}-{_proj_faixa[1]}"
                          if _proj_faixa else f"{num} de {len(telao._slides)}")
                label_slide.config(text=rotulo, fg='#3fb950', bg='#161b22')
            elif getattr(telao, "mostrando_letra", False):
                label_slide.config(text="Projeção ativa", fg='#f0c040', bg='#161b22')
            else:
                label_slide.config(text="Sem projeção", fg='#8b949e', bg='#161b22')

        def _destacar_versiculo_na_tela(num: int) -> bool:
            """Marca o versículo `num` na área de texto (True se encontrado)."""
            biblia_text.tag_remove('verso_atual', '1.0', tk.END)
            try:
                biblia_text.tag_configure('verso_atual', background='#6e40c9',
                                          foreground='#ffffff')
            except tk.TclError:
                return False
            texto_area = biblia_text.get('1.0', tk.END)
            for i, linha in enumerate(texto_area.split('\n'), start=1):
                if linha.startswith(f"{num}. "):
                    biblia_text.tag_add('verso_atual', f"{i}.0", f"{i}.0 lineend")
                    biblia_text.see(f"{i}.0")
                    return True
            return False

        def _sincronizar_biblia_com_telao():
            """Reflete na janela da Bíblia (monitor 1) o versículo projetado.

            Atualiza o campo "V:", destaca o versículo na área de texto e
            rola a visualização até ele, mantendo as duas telas em sincronia.
            """
            nonlocal _travado_recarga
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False) or not telao._slides:
                return
            idx = telao._slide_index
            if _cap_numeros and 0 <= idx < len(_cap_numeros):
                num = _cap_numeros[idx]
            else:
                num = idx + 1
            # O "V:" é reescrito a cada versículo projetado; a recarga
            # automática fica desligada aqui para não substituir o capítulo
            # inteiro (e o destaque) a cada navegação das setas.
            _travado_recarga = True
            try:
                vers_var.set(str(num))
            finally:
                _travado_recarga = False
            if not _destacar_versiculo_na_tela(num):
                _carregar_capitulo(foco=num)
            _atualizar_indicador_slide()

        def _refletir_telao_na_janela() -> None:
            """Atualiza a janela da Bíblia depois de navegar um slide.

            Enquanto há projeção, sincroniza o campo "V:", o destaque e o
            indicador. Ao passar do último versículo, o telão já encerrou a
            projeção (como a tecla Esc) e a janela limpa o destaque e volta
            para "Sem projeção".
            """
            if getattr(self.player.telao, "_em_slides", False):
                _sincronizar_biblia_com_telao()
                return
            try:
                biblia_text.tag_remove('verso_atual', '1.0', tk.END)
            except tk.TclError:
                pass
            _atualizar_indicador_slide()

        def _ao_parar_biblia():
            try:
                biblia_text.tag_remove('verso_atual', '1.0', tk.END)
            except tk.TclError:
                pass
            _atualizar_indicador_slide()

        _slide_anterior, _slide_proximo, _parar_projecao = \
            self._criar_navegacao_slides(
                ao_navegar=_refletir_telao_na_janela,
                ao_parar=_ao_parar_biblia)

        def _ajustar_fonte(delta: float):
            """Aumenta/diminui a fonte da projeção e redesenha o que está ativo."""
            self._ajustar_fonte_projecao(delta, _atualizar_indicador_slide)

        def _restaurar_fonte():
            """Volta a fonte da projeção ao padrão, desfazendo o A−/A+ manual."""
            self._restaurar_fonte_projecao(_atualizar_indicador_slide)

        # Setas do teclado e Esc (janela de bíblia).
        # No root substituímos a ligação a cada abertura para evitar acumular
        # handlers duplicados de chamadas repetidas a janela_biblia.
        self._vincular_teclas_slides(janela, _slide_anterior, _slide_proximo,
                                     _parar_projecao)

        # Passador de slides (controle remoto): durante a projeção de
        # versículos, AvPag/RetPag, espaço, F5 e BackSpace navegam como as
        # setas (mesmo esquema da janela de anúncios).
        self._criar_passador_slides(janela,
                                    ao_navegar=_refletir_telao_na_janela)

        # Abre com João 3 a partir do versículo 16 (campo "V:" = 16)
        _carregar_capitulo()
