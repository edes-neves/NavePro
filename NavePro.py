"""
NavePro - Sistema de Projeção Profissional
Versão: 1.9.3
Licença: GPLv3
Autor: José Edes Neves - Julho 2026 nevestecnologias@gmail.com
Aplicação para reprodução de mídia com projeção em telão,
busca inteligente no banco de dados, pastas do computador 
e informações climáticas.

"""
from __future__ import annotations

import concurrent.futures
import json
import mimetypes
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.filedialog
import tkinter.messagebox
import tkinter.simpledialog
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

from navepro.config import (
    APP_VERSION,
    BACKEND_PORT,
    BACKEND_URL,
    EXTENSOES_AUDIO,
    EXTENSOES_VIDEO,
    PLAYER_PADRAO,
    SEGUNDOS_PARA_VERIFICAR_ATUALIZACAO,
    SQLITE_TIMEOUT,
    SUFIXOS_IMAGEM,
)
from navepro.core.ambiente import (
    _ambiente_sem_appimage,
    _eh_appimage,
    _eh_windows,
    _tornar_dpi_aware,
)
from navepro.core.anuncios import (
    _atualizar_anuncio_db,
    _buscar_anuncio_por_ref,
    _buscar_anuncio_por_termo,
    _copiar_arquivo_uploads,
    _excluir_anuncios_db,
    _inserir_anuncio_db,
    _listar_anuncios_db,
    _migrar_anuncios_do_json,
    _projetar_anuncio_ordserv,
    _tipo_midia_para_arquivo,
)
from navepro.core.atualizacao import (
    FORMATO_FLATPAK,
    _buscar_release_latest,
    _comando_atualizacao_flatpak,
    _formato_instalado,
    _pasta_downloads,
    _procurar_asset_instalador,
    _rotulo_instalador,
    _versao_nova,
)
from navepro.core.banco import (
    DatabaseManager,
    _gerador_id_livre,
    _inserir_com_id_reuso,
    db_execute,
    db_query,
)
from navepro.core.busca import SearchWorker
from navepro.core.clima import (
    obter_temperatura,
)
from navepro.core.fontes_pil import (
    _PCT_FONTE_CAIXA,
    _caixa_texto_padrao,
    _calcular_texto_em_caixa,
    _fonte_familia_do_pil,
)
from navepro.core.inicializacao import (
    _sincronizar_uploads_midia,
    garantir_pasta_uploads,
    inicializar_banco,
    inicializar_config,
)
from navepro.core.log import configurar_logging, get_logger
from navepro.core.mediaplayer import MediaPlayer, _eh_url
from navepro.core.monitores import (
    _escolher_monitor_painel,
    get_monitors_config,
)
from navepro.core.paths import (
    CONFIG_FILE,
    DB_PATH,
    UPLOAD_FOLDER,
    _aplicar_icone_janela,
    _caminho_recurso,
)

# ────────────────────────────────────────────────────────────────────
# IMPORTS INTERNOS (infraestrutura modularizada)
# ────────────────────────────────────────────────────────────────────
from navepro.core.rede import _ip_da_rede
from navepro.core.servicos import (
    _SERVICO_PROXIMO_ITEM,
    _analisar_faixa_versiculos,
    _carregar_icone,
    _carregar_servicos_json,
    _extrair_texto_pdf,
    _faixa_versiculo_item,
    _migrar_servicos_do_banco,
    _proximo_id_servico_livre,
    _reordenar_itens_servico,
    _salvar_servicos_json,
    _slides_versiculo_item,
)
from navepro.core.servidor_http import ServidorAsyncHTTP
from navepro.core.slides import (
    _buscar_hino_por_termo,
    _buscar_midia_por_termo,
    _montar_slides_anuncio,
    _montar_slides_letra,
    _previa_slide,
)
from navepro.core.ssl_context import (
    _baixar,
    _ssl_context,
)
from navepro.core.tema import _OPCOES_COR_TK, _OPCOES_TEXTO, _cor_clara
from navepro.core.textos import (
    _numero_do_titulo,
    detectar_tipo_arquivo,
)
from navepro.core.transferencia import (
    EXTENSAO_TRANSFERENCIA,
    exportar_transferencia,
    importar_transferencia,
)
from navepro.core.transferencia import (
    _nome_arquivo as _nome_arquivo_transferencia,
)
from navepro.core.util_tk import _centralizar_sobre, _normalizar_escala_tk
from navepro.core.widgets_arredondados import TkArredondado

# Botões e campos de digitação de todo o app desenham cantos arredondados.
# `tk` vira uma fachada que delega tudo ao tkinter real, trocando apenas
# `Button` e `Entry` — sem alterar nenhuma chamada existente.
tk = TkArredondado(tk)

# Precisa rodar ANTES de qualquer tk.Tk(): o Tk 8.6 do Windows não é
# DPI-aware e cacheia a tela em pixels lógicos, enquanto o screeninfo ativa o
# DPI-awareness do processo e passa a medir em pixels físicos. Sem esta
# chamada, os dois discordam das unidades e o telão é reposicionado pelo
# Windows de volta para o monitor primário. No Linux é no-op.
_TORNAR_DPI_AWARE: bool = _tornar_dpi_aware()

# Logger da aplicação. A configuração (nível/handlers) é feita uma única vez em
# configurar_logging(), no ponto de entrada (__main__).
log = get_logger("app")


# ────────────────────────────────────────────────────────────────────
# TEMAS DA INTERFACE (painel do administrador / monitor 1)
# (movido para navepro/core/tema.py — ver "IMPORTS INTERNOS" no topo)
# ────────────────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────────────────
# BANCO DE DADOS – GERENCIADOR COM CACHE E CONEXÃO PERSISTENTE
# ────────────────────────────────────────────────────────────────────
# (movido para navepro/core/banco.py — ver "IMPORTS INTERNOS" no topo)


# ────────────────────────────────────────────────────────────────────
# INICIALIZAÇÃO DO BANCO
# ────────────────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────────────────
# INICIALIZAÇÃO DO BANCO E RECURSOS
# ────────────────────────────────────────────────────────────────────
# (movido para navepro/core/inicializacao.py — ver "IMPORTS INTERNOS" no topo)



# As funções inicializar_banco e garantir_pasta_uploads são
# chamadas dentro de AppInterface.__init__ para evitar efeitos
# colaterais na importação do módulo.

# ────────────────────────────────────────────────────────────────────
# WORKER DE BUSCA (ÚNICA THREAD COM FILA)
# ────────────────────────────────────────────────────────────────────
# (movido para navepro/core/busca.py — ver "IMPORTS INTERNOS" no topo)

# ────────────────────────────────────────────────────────────────────
# SERVIDOR HTTP - API REST (mantido como antes)
# ────────────────────────────────────────────────────────────────────
# (helpers de rede movidos para navepro/core/rede.py)


# Rotas POST do controle remoto → ação despachada ao AppInterface
# (movido para navepro/core/servidor_http.py — ver "IMPORTS INTERNOS" no topo)

# ────────────────────────────────────────────────────────────────────
# CLIMA - GEOLOCALIZAÇÃO E TEMPERATURA
# ────────────────────────────────────────────────────────────────────
# (movido para navepro/core/clima.py — ver "IMPORTS INTERNOS" no topo)


# ────────────────────────────────────────────────────────────────────
# MONITORES - DETECÇÃO
# ────────────────────────────────────────────────────────────────────
# (movido para navepro/core/monitores.py — ver "IMPORTS INTERNOS" no topo)


# ────────────────────────────────────────────────────────────────────
# POSICIONAMENTO DE JANELAS SECUNDÁRIAS
# ────────────────────────────────────────────────────────────────────


# (_centralizar_sobre movido para navepro/core/util_tk.py — ver "IMPORTS INTERNOS" no topo)


# ────────────────────────────────────────────────────────────────────
# TELÃO - JANELA DE PROJEÇÃO (mantido)
# ────────────────────────────────────────────────────────────────────

# (_escolher_monitor_painel/_escolher_monitor_telao movidos para
#  navepro/core/monitores.py — ver "IMPORTS INTERNOS" no topo)


# (_normalizar_escala_tk movido para navepro/core/util_tk.py — ver "IMPORTS INTERNOS" no topo)


# ────────────────────────────────────────────────────────────────────
# TELÃO - JANELA DE PROJEÇÃO
# ────────────────────────────────────────────────────────────────────
# (movido para navepro/core/telao.py — ver "IMPORTS INTERNOS" no topo)

# PLAYER DE MÍDIA (mantido)
# ────────────────────────────────────────────────────────────────────


# ────────────────────────────────────────────────────────────────────
# REPRODUÇÃO DE MÍDIA - MediaPlayer
# ────────────────────────────────────────────────────────────────────
# (movido para navepro/core/mediaplayer.py — ver "IMPORTS INTERNOS" no topo)

# ────────────────────────────────────────────────────────────────────
# INTERFACE PRINCIPAL (REFATORADA)
# ────────────────────────────────────────────────────────────────────


# ────────────────────────────────────────────────────────────────────
# SLIDES / HINOS (helpers compartilhados)
# ────────────────────────────────────────────────────────────────────
# (movido para navepro/core/slides.py — ver "IMPORTS INTERNOS" no topo)



# ───────────────────────────────────────────────────────────────────
# ANÚNCIOS — ARMAZENAMENTO EM ARQUIVO JSON (FORA DO BANCO DE DADOS)
# ───────────────────────────────────────────────────────────────────
# (movido para navepro/core/anuncios.py — ver "IMPORTS INTERNOS" no topo)


# ────────────────────────────────────────────────────────────────────
# COMPOSIÇÃO IMAGEM + TEXTO (anúncios de imagem)
# ────────────────────────────────────────────────────────────────────
# Medição e ajuste de caixas de texto em espaço virtual 1440x1080,
# usados de forma IDÊNTICA pelo editor (prévia) e pelo telão (projeção).
# Implementados em navepro/core/fontes_pil.py e importados no topo.


# ───────────────────────────────────────────────────────────────────
# ORDENS DE SERVIÇO — ARMAZENAMENTO EM ARQUIVO JSON
# ───────────────────────────────────────────────────────────────────
# (movido para navepro/core/servicos.py — ver "IMPORTS INTERNOS" no topo)


def _listar_pastas_arquivos_usuario(
        caminho: str,
        sufixos: tuple[str, ...] = (".xml", ".txt", ".json")
) -> list[tuple[str, str, bool]]:
    """Lista pastas e arquivos com os sufixos informados.

    Esconde tudo que começa com "." (pastas/arquivos ocultos do sistema).
    Retorna (caminho_completo, nome, é_pasta).
    """
    import os
    itens = []
    try:
        for e in os.scandir(caminho):
            if e.name.startswith("."):
                continue
            try:
                e_dir = e.is_dir()
            except OSError:
                continue
            if e_dir or e.name.lower().endswith(sufixos):
                itens.append((os.path.join(caminho, e.name), e.name, e_dir))
    except OSError:
        return []
    itens.sort(key=lambda t: (not t[2], t[1].lower()))
    return itens


def _escolher_arquivos_usuario(
        parent: tk.Toplevel | None,
        titulo: str,
        pasta_inicial: str | None = None,
        sufixos: tuple[str, ...] = (".xml", ".txt", ".json"),
        nome_para_salvar: str = "",
) -> tuple[str, ...]:
    """Seletor de arquivos que inicia no diretório do usuário (~).

    Mostra apenas as pastas/arquivos do usuário — esconde tudo que começa
    com "." (ocultos do sistema) e filtra os arquivos pelos sufixos dados.

    Com `nome_para_salvar` informado vira um "salvar como": mostra um campo
    com o nome sugerido, o botão principal vira "💾 Salvar" e o retorno é um
    único caminho. Nesse modo, duas cliques num arquivo existente apenas
    colocam o nome dele no campo.
    """
    import os
    pasta = {"atual": os.path.abspath(os.path.expanduser(pasta_inicial or "~"))}
    escolhidos: list[str] = []
    _itens: list[tuple[str, bool]] = []  # (caminho, é_pasta)
    salvando = bool(nome_para_salvar)
    ent_nome: tk.Entry | None = None

    dial = tk.Toplevel(parent)
    dial.title(titulo)
    dial.geometry("560x545" if salvando else "560x500")
    dial.configure(bg='#0d1117')
    if parent is not None:
        dial.transient(parent)
    _centralizar_sobre(dial, parent)

    def _encurtar(texto: str, limite: int = 58) -> str:
        return texto if len(texto) <= limite else "…" + texto[-(limite - 1):]

    def _entrar(caminho: str) -> None:
        caminho = os.path.abspath(caminho)
        itens = _listar_pastas_arquivos_usuario(caminho, sufixos)
        _itens[:] = [(cam, is_dir) for cam, _, is_dir in itens]
        pasta["atual"] = caminho
        lbl_pasta.config(text=_encurtar(caminho))
        listbox.delete(0, tk.END)
        for _cam, nome, is_dir in itens:
            listbox.insert(tk.END, f"{'📁 ' if is_dir else '📄 '}{nome}")

    def _subir() -> None:
        _entrar(os.path.dirname(pasta["atual"]))

    barra = tk.Frame(dial, bg='#161b22')
    barra.pack(fill='x', padx=6, pady=(8, 4))
    tk.Button(barra, text="⌂ Início", font=("Arial", 10, "bold"),
              bg='#21262d', fg='#c9d1d9', activebackground='#30363d',
              command=lambda: _entrar(os.path.expanduser("~"))
              ).pack(side='left', padx=(0, 4), pady=2)
    tk.Button(barra, text="⬆ Subir", font=("Arial", 10, "bold"),
              bg='#21262d', fg='#c9d1d9', activebackground='#30363d',
              command=_subir).pack(side='left', pady=2)
    lbl_pasta = tk.Label(barra, text="", fg='#f0c040', bg='#161b22',
                         font=("Arial", 10), anchor='w')
    lbl_pasta.pack(side='left', fill='x', expand=True, padx=6)

    listbox = tk.Listbox(dial, bg='#21262d', fg='#c9d1d9',
                         font=("Arial", 11), selectmode='extended',
                         highlightthickness=0, bd=0, activestyle='none')
    listbox.pack(fill='both', expand=True, padx=6, pady=4)
    scroll = tk.Scrollbar(listbox, orient='vertical', command=listbox.yview)
    listbox.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y')

    def _validar_salvar() -> str | None:
        """Monta o caminho final ou None para manter o diálogo aberto."""
        nome = ent_nome.get().strip() if ent_nome is not None else ""
        if not nome:
            tkinter.messagebox.showwarning(
                "Salvar", "Escreva o nome do arquivo para salvar.", parent=dial)
            return None
        caminho = os.path.abspath(os.path.join(pasta["atual"], nome))
        if os.path.isdir(caminho):
            # Apontou para uma pasta: entra nela em vez de salvar.
            _entrar(caminho)
            return None
        if os.path.exists(caminho) and not tkinter.messagebox.askyesno(
                "Arquivo já existe",
                f"Já existe um arquivo com esse nome:\n\n{caminho}\n\n"
                "Quer sobrescrever?",
                parent=dial):
            return None
        return caminho

    def _fechar_ok(*idxs: int) -> None:
        if salvando:
            caminho = _validar_salvar()
            if caminho is None:
                return
            escolhidos[:] = [caminho]
            dial.destroy()
            return
        caminhos = [_itens[i][0] for i in idxs if not _itens[i][1]]
        escolhidos[:] = caminhos
        dial.destroy()

    def _clicar_duplo(event) -> None:
        idx = listbox.nearest(event.y)
        if not (0 <= idx < len(_itens)):
            return
        caminho, is_dir = _itens[idx]
        if is_dir:
            _entrar(caminho)
        elif salvando and ent_nome is not None:
            ent_nome.delete(0, tk.END)
            ent_nome.insert(0, os.path.basename(caminho))
            ent_nome.icursor(tk.END)
        else:
            _fechar_ok(idx)

    def _ok(_event=None) -> None:
        _fechar_ok(*listbox.curselection())

    def _cancelar(_event=None) -> None:
        escolhidos[:] = []
        dial.destroy()

    _entrar(pasta["atual"])
    listbox.bind("<Double-Button-1>", _clicar_duplo)
    dial.bind("<Return>", _ok)
    dial.bind("<Escape>", _cancelar)

    # ── Nome do arquivo (modo "salvar como") ──
    if salvando:
        linha_nome = tk.Frame(dial, bg='#0d1117')
        linha_nome.pack(fill='x', padx=6, pady=(2, 0))
        tk.Label(linha_nome, text="Nome do arquivo:", font=("Arial", 10, "bold"),
                 fg='#f0c040', bg='#0d1117').pack(side='left', padx=(4, 6))
        ent_nome = tk.Entry(linha_nome, font=("Arial", 11), bg='#21262d',
                            fg='#f0c040', insertbackground='#f0c040',
                            bd=0, highlightthickness=0)
        ent_nome.pack(side='left', fill='x', expand=True, padx=(0, 6), ipady=3)
        ent_nome.insert(0, nome_para_salvar)
        # O nome vem selecionado: é só digitar para trocar.
        ent_nome.selection_range(0, tk.END)
        ent_nome.focus_set()

    rodape = tk.Frame(dial, bg='#0d1117')
    rodape.pack(fill='x', padx=6, pady=6)
    tk.Button(rodape, text=("💾 Salvar" if salvando else "Importar"),
              font=("Arial", 11, "bold"),
              bg=('#1f6feb' if salvando else '#238636'), fg='white',
              activebackground=('#388bfd' if salvando else '#2ea043'),
              command=_ok).pack(side='right', padx=(4, 0))
    tk.Button(rodape, text="Cancelar", font=("Arial", 11, "bold"),
              bg='#da3633', fg='white', activebackground='#f85149',
              command=_cancelar).pack(side='right')

    dial.grab_set()
    dial.wait_window()
    return tuple(escolhidos)


def _criar_faixa_secao(parent, topo: bool = True):
    """Faixa cinza no topo/base de uma seção do painel do operador.

    No tema ESCURO a faixa assume a cor do cartão e fica invisível (o visual
    escuro permanece idêntico). No tema CLARO a faixa fica num cinza carvão,
    delimitando as seções. A cor é aplicada em ``_aplicar_tema_widget`` a partir
    do atributo ``_navepro_faixa_secao``.
    """
    faixa = tk.Frame(parent, bg='#161b22', height=6)
    faixa._navepro_faixa_secao = True
    faixa.pack(fill='x', side='top' if topo else 'bottom')
    return faixa


def _marcar_area_cinza_clara(widget, escuro: str = '#21262d'):
    """Marca um widget para ficar cinza no tema CLARO (no escuro usa `escuro`).

    Usado na faixa inferior de controles do painel do operador, que deve virar
    um bloco cinza apenas no tema claro. A cor é aplicada em
    ``_aplicar_tema_widget`` (atributo ``_navepro_area_cinza_clara``).
    """
    widget._navepro_area_cinza_clara = True
    widget._navepro_area_cinza_escuro = escuro
    return widget


class AppInterface:
    """Interface gráfica principal do sistema de projeção."""

    def __init__(self) -> None:
        # Força GDK backend X11 para evitar conflito GTK Wayland no Ubuntu 22.04
        if 'GDK_BACKEND' not in os.environ:
            os.environ['GDK_BACKEND'] = 'x11'
        self.root = tk.Tk(className="NavePro")
        # Normaliza a escala de fontes (AppImage usa o python do sistema,
        # que pode ter 'tk scaling' baixo e deixar tudo minúsculo)
        _normalizar_escala_tk(self.root)
        # Força tema clam via Tcl (acima do ttk.Style)
        try:
            self.root.tk.call('tk', 'Theme', 'SetTheme', 'clam')
        except Exception:
            pass
        try:
            style = ttk.Style()
            style.theme_use('clam')
        except Exception:
            pass
        # tk_setPalette força base escura no Tk inteiro
        try:
            self.root.tk.call('tk_setPalette',
                '#0d1117', '#f0c040', '#6e40c9', '#ffffff', '#6e40c9', '#0d1117')
        except Exception:
            pass
        # option_add para tk.Button (GTK pode ignorar, mas tenta)
        self.root.option_add('*Button.background', '#21262d')
        self.root.option_add('*Button.foreground', '#f0c040')
        self.root.option_add('*Button.activeBackground', '#6e40c9')
        self.root.option_add('*Button.activeForeground', '#f0c040')
        self.root.option_add('*Button.highlightBackground', '#21262d')
        self.root.option_add('*Button.highlightColor', '#21262d')
        self.root.option_add('*Button.relief', 'flat')
        self.root.option_add('*Button.borderWidth', '0')
        self.root.option_add('*TCombobox*Listbox.background', '#21262d')
        self.root.option_add('*TCombobox*Listbox.foreground', '#c9d1d9')
        self.root.title("NAVE PRO - PRO")
        _aplicar_icone_janela(self.root)
        self.root.configure(bg='#0d1117')
        # Tamanho mínimo e estado inicial maximizado
        self.root.minsize(900, 800)
        self._maximizado = True
        try:
            monitors = get_monitors_config()
            if monitors:
                # Painel do operador abre no monitor marcado como PRIMÁRIO
                # pelo SO (ou no primeiro, se nenhum for marcado). O telão
                # escolhe o que sobrar — ver _escolher_monitor_telao.
                m = _escolher_monitor_painel(monitors)
                # Salva geometria do monitor para restaurar depois
                self._monitor_geo = (m.width, m.height, m.x, m.y)
                # Inicia maximizado respeitando a área de trabalho (barra de tarefas)
                # Usar 'zoomed' evita que a janela fique atrás da barra de tarefas
                try:
                    # Em alguns setups, setar a geometria completa antes de maximizar
                    # evita que a janela fique parcialmente atrás da barra de tarefas
                    self.root.geometry(f"{m.width}x{m.height}+{m.x}+{m.y}")
                    self.root.update_idletasks()
                    self.root.state('zoomed')
                    self.root.update_idletasks()
                    # Se ainda não cobriu direito, força a geometria para a área visível
                    if _eh_windows():
                        try:
                            import ctypes
                            rect = (ctypes.c_long * 4)()
                            ctypes.windll.user32.SystemParametersInfoW(48, 0, rect, 0)  # SPI_GETWORKAREA
                        except Exception:
                            pass
                except Exception:
                    pass
            else:
                self._monitor_geo = None
                self.root.state('zoomed')
        except Exception:
            self._monitor_geo = None
            self.root.state('zoomed')

        self.config_data: dict[str, Any] = self.carregar_config()
        self.tema: str = self.config_data.get("tema", "escuro")
        if self.tema not in ("escuro", "claro"):
            self.tema = "escuro"
        # Monitor do telão: se o operador definiu "monitor" no config, o valor
        # vira o PC alvo do vídeo (1-based na ordem de get_monitors_config).
        # Sem config, o player usa a MESMA regra do TelaoWindow (_escolher_
        # monitor_telao: o monitor NÃO primário) — o vídeo abre onde a projeção
        # Tk já aparece, independente da ordem da lista. (Antes o padrão "2" —
        # "segundo da lista" — errava quando o telão vinha enumerado antes do
        # operador.)
        _monitor_cfg = self.config_data.get("monitor")
        self.monitor_index: int | None = (
            _monitor_cfg if isinstance(_monitor_cfg, int) and _monitor_cfg > 0
            else None)
        self.player_cmd: str = self.config_data.get("player", PLAYER_PADRAO)
        self.placeholder_busca: str = "Buscar hino... [BD]"
        self.arquivos_encontrados: list[str] = []
        self.arquivo_atual: str | None = None
        # Estado do anúncio projetado (compartilhado entre a janela de
        # anúncios e o controle remoto)
        self._anuncio_proj: dict = {"id": None, "dados": {}, "config": {},
                                    "mslides": None, "idx_map": []}
        # Snapshot do player guardado durante um item de serviço (restaurado
        # quando o item termina; compartilhado com o controle remoto)
        self._snapshot_servico: dict = {"guardada": False}
        
        self.cidade_salva: str = self.config_data.get("cidade", "")
        self.estado_salvo: str = self.config_data.get("estado", "")
        self.temperatura_atual: str = ""

        self._focus_timer: str | None = None
        self._debounce_timer: str | None = None

        log.info(f"🎮 Player: {self.player_cmd} | Monitor: {self.monitor_index}")

        # Garante recursos
        inicializar_banco()
        inicializar_config()
        garantir_pasta_uploads()
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)

        # Cache e worker (DatabaseManager carrega o cache na construção)
        self.db = DatabaseManager()
        self.search_worker = SearchWorker()
        self._versao_busca: int = 0
        self._ultima_lista: list[str] = []  # para evitar redesenho desnecessário

        # Cria o player e o telão (rápido - só cria as janelas Tk)
        self.player = MediaPlayer(self.monitor_index, self.player_cmd)
        self.player.on_state_change = self.quando_midia_terminar
        self.player.on_track_change = self.quando_faixa_muda
        self.player.on_aviso = self.mostrar_aviso
        self.player._root_after = self.root

        # Aplica configuração de aparência da projeção (letra/versículo)
        # Garante telão
        try:
            if getattr(self.player, "telao", None) is None:
                try:
                    self.player._garantir_telao()  # type: ignore[attr-defined]
                except Exception:
                    pass
        except Exception:
            pass
        t = getattr(self.player, "telao", None)
        if t is not None:
            try:
                t.configurar_projecao(self.config_data.get("projecao", {}))
                t.configurar_relogio(self.config_data.get("relogio", {}))
            except Exception:
                pass

        # Estado dos medidores (cronômetro / contagem regressiva)
        self._crono = {
            "rodando": False, "pausado": False,
            "inicio": 0.0, "acumulado": 0.0, "timer_id": None,
        }
        self._contagem = {
            "rodando": False, "pausado": False,
            "fim": 0.0, "restante": 0.0, "total": 0.0, "timer_id": None,
        }

        # Quando o telão for fechado (Esc/Ctrl+Q) e recriado pelo player,
        # reaplica a aparência configurada e volta a mostrar a hora inicial.
        def _reaplicar_telao_recriado(novo_telao) -> None:
            try:
                novo_telao.configurar_projecao(
                    self.config_data.get("projecao", {}))
                novo_telao.configurar_relogio(
                    self.config_data.get("relogio", {}))
                novo_telao._exibir_hora_inicial()
            except Exception as _e_reap:
                log.exception(f"⚠️ Erro ao reaplicar config no telão recriado: "
                      f"{_e_reap}")

        self.player.on_telao_recriado = _reaplicar_telao_recriado

        self._criar_menu()

        # Corrige corrida do Tk 8.6 + XWayland (GNOME Wayland): força o flush
        # síncrono dos pedidos X pendentes (telão com alpha/fullscreen) antes de
        # criar os widgets da barra de controles. Sem isso, algumas distros
        # travam em _XReply/XSync ao medir fontes ("Falha de segmentação") e a
        # janela mal abre e fecha sozinha.
        try:
            self.root.update_idletasks()
        except Exception:
            pass

        self.criar_widgets()
        self.atualizar_relogio()

        # Aplica o tema (claro/escuro) lido do config logo após criar a UI,
        # sem alterar nenhuma cor hardcoded da construção padrão (escuro).
        self._aplicar_tema()

        # Mostra hora inicial no telão (sem temperatura ainda)
        t = getattr(self.player, "telao", None)
        if t is None:
            try:
                self.player._garantir_telao()  # type: ignore[attr-defined]
            except Exception:
                pass
        t = getattr(self.player, "telao", None)
        if t is not None:
            try:
                t._exibir_hora_inicial()
            except Exception:
                pass

        # ============================================================
        # Tarefas pesadas executadas APÓS a interface aparecer
        # ============================================================
        # Inicia servidor HTTP (thread separada) e carrega temperatura
        # em paralelo, sem travar a interface
        self.root.after(100, self._inicializar_em_segundo_plano)

        self.root.bind('<space>', self._on_space)
        # No Wayland o telão (janela Tk própria) não consegue roubar o foco
        # do compositor; se o foco ficar no painel do operador, as teclas do
        # passador de slides não chegam ao telão. Este bind_all encaminha as
        # teclas não consumidas por nenhum widget (setas, PageUp/PageDown,
        # F5, BackSpace) ao telão enquanto houver projeção em slides.
        self.root.bind_all("<KeyPress>", self._encaminhar_teclas_telao)
        self.root.protocol("WM_DELETE_WINDOW", self.fechar)

        # Captura eventos de estado da janela (maximizar/minimizar)
        self.root.bind("<Map>", self._on_window_map)
        self.root.bind("<Configure>", self._on_window_configure)
        # Atalho F11 para alternar entre maximizado e 800x600
        self.root.bind("<F11>", lambda e: self._alternar_maximizar())
        # Atalho Ctrl+T para alternar o tema (claro/escuro)
        self.root.bind("<Control-t>", lambda e: self._alternar_tema())
        # Detecta duplo clique na barra de título (maximizar/restaurar)
        self.root.bind("<Double-Button-1>", self._on_title_double_click)

    def _on_window_map(self, event: object = None) -> None:
        """Quando a janela é mapeada (restaurada/minimizada)."""
        if not hasattr(self, '_maximizado'):
            return
        estado = self.root.state()
        if estado == 'zoomed':
            self._maximizado = True

    def _on_window_configure(self, event: object = None) -> None:
        """Detecta quando o usuário clica no botão Maximizar via mouse."""
        if not hasattr(self, '_maximizado'):
            return
        estado = self.root.state()
        if estado == 'zoomed':
            self._maximizado = True

    def _on_title_double_click(self, event: object = None) -> None:
        """Alterna maximizar/restaurar ao dar duplo clique na barra de título."""
        # Só ativa se o clique foi no topo da janela (barra de título)
        if event and event.y < 30:
            self._alternar_maximizar()



    @staticmethod
    def _chave_ordenacao_busca(rec: dict) -> tuple:
        """Chave de ordenação para resultados de busca (usa DatabaseManager)."""
        return DatabaseManager._compute_sort_key(rec.get('nome_exibicao', ''))

    # ── Foco e atalhos ────────────────────────────────────────────

    def _reset_focus_timer(self, event: object = None) -> None:
        """Reinicia o timer que remove o foco dos campos de entrada."""
        if self._focus_timer:
            self.root.after_cancel(self._focus_timer)
        self._focus_timer = self.root.after(5000, self._clear_focus_timeout)

    def _cancel_focus_timer(self) -> None:
        """Cancela o timer de foco."""
        if self._focus_timer:
            self.root.after_cancel(self._focus_timer)
            self._focus_timer = None

    def _clear_focus_timeout(self) -> None:
        """Remove o foco de campos para permitir atalhos globais."""
        self.root.focus_set()
        self._focus_timer = None

    def _on_space(self, event: object = None) -> str:
        """Espaço = Play/Pause (exceto quando digitando no campo de busca).

        Durante uma projeção em slides, o espaço avança o slide (comportamento
        padrão do passador de slides); fora disso, segue exatamente como antes.
        """
        player = getattr(self, 'player', None)
        if player is not None:
            telao = getattr(player, 'telao', None)
            if telao is not None and getattr(telao, '_em_slides', False):
                telao.slide_proximo()
                return "break"
        focused = self.root.focus_get()
        if focused == self.entry_busca:
            conteudo = self.entry_busca.get().strip()
            if conteudo and conteudo != self.placeholder_busca:
                return "break"  # Deixa o Entry consumir o espaço
        self.player.play_pause()
        return "break"

    def _encaminhar_teclas_telao(self, event: object = None) -> str | None:
        """Encaminha as teclas do passador de slides ao telão.

        Só age durante uma projeção em slides, quando o foco está no painel
        do operador (Wayland não permite o telão se auto-focar). Espelha o
        que _on_space já faz para o espaço. Como usa o tag "all", só é
        chamado para teclas que nenhum widget/binding mais específico
        consumiu (digitação em Entry, listas, janelas com atalhos próprios
        continuam intactas).
        """
        if event is None:
            return None
        player = getattr(self, "player", None)
        telao = getattr(player, "telao", None) if player is not None else None
        if telao is None or not getattr(telao, "_em_slides", False):
            return None
        try:
            if not telao._raiz_viva():
                return None
        except Exception:
            return None
        # Não interfere em campos de texto: neles as setas e o BackSpace
        # pertencem à edição (o Tk pode não consumir a tecla antes do "all").
        foco = None
        try:
            foco = self.root.focus_get()
        except (KeyError, tk.TclError):
            foco = None
        if foco is not None:
            try:
                classe = str(foco.winfo_class()).lower()
            except Exception:
                classe = ""
            if classe in ("entry", "tentry", "text", "spinbox", "tspinbox",
                          "tcombobox"):
                return None
        keysym = str(getattr(event, "keysym", "") or "").lower()
        if keysym in ("right", "down", "next", "page_next", "page_down", "f5"):
            telao.slide_proximo()
            return "break"
        if keysym in ("left", "up", "prior", "page_prior", "page_up",
                      "backspace"):
            telao.slide_anterior()
            return "break"
        return None

    # ── Widgets de cidade ─────────────────────────────────────────

    def _on_focus_cidade(self) -> None:
        if self.entry_cidade.get() == "Cidade":
            self.entry_cidade.delete(0, tk.END)
            self.entry_cidade.config(fg='#1f2328')
        self._reset_focus_timer()

    def _on_focus_out_cidade(self) -> None:
        if not self.entry_cidade.get().strip():
            self.entry_cidade.delete(0, tk.END)
            self.entry_cidade.insert(0, "Cidade")
            self.entry_cidade.config(fg='#656d76')
        self._cancel_focus_timer()

    def _on_focus_estado(self) -> None:
        if self.entry_estado.get() == "UF":
            self.entry_estado.delete(0, tk.END)
            self.entry_estado.config(fg='#1f2328')
        self._reset_focus_timer()

    def _on_focus_out_estado(self) -> None:
        if not self.entry_estado.get().strip():
            self.entry_estado.delete(0, tk.END)
            self.entry_estado.insert(0, "UF")
            self.entry_estado.config(fg='#656d76')
        self._cancel_focus_timer()

    def _on_focus_in(self, event: object = None) -> None:
        if self.entry_busca.get() == self.placeholder_busca:
            self.entry_busca.delete(0, tk.END)
            self.entry_busca.config(fg='#F5BE08')
        self._reset_focus_timer()

    def _on_focus_in_busca(self, event: object = None) -> None:
        """FocusIn do campo de busca - destaca borda e mostra botão X."""
        if self.entry_busca.get() == self.placeholder_busca:
            self.entry_busca.delete(0, tk.END)
            self.entry_busca.config(fg='#f0c040')
        # Mostra botão X
        self._clear_btn.pack(side='left', padx=(0, 8))
        # Destaca borda do card
        try:
            busca_card = self.entry_busca.master.master
            busca_card.config(highlightbackground='#6e40c9')
        except Exception:
            pass
        self._reset_focus_timer()

    def _on_focus_out_busca(self, event: object = None) -> None:
        """FocusOut do campo de busca - restaura borda."""
        termo = self.entry_busca.get().strip()
        if not termo or termo == self.placeholder_busca:
            self.entry_busca.delete(0, tk.END)
            self.entry_busca.insert(0, self.placeholder_busca)
            self.entry_busca.config(fg='#8b949e')
            self._clear_btn.pack_forget()
        try:
            busca_card = self.entry_busca.master.master
            busca_card.config(highlightbackground='#30363d')
        except Exception:
            pass
        self._cancel_focus_timer()

    def _limpar_busca(self, event: object = None) -> None:
        """Limpa o campo de busca e redefine placeholder."""
        self.entry_busca.delete(0, tk.END)
        self.entry_busca.insert(0, self.placeholder_busca)
        self.entry_busca.config(fg='#8b949e')
        self._clear_btn.pack_forget()
        try:
            busca_card = self.entry_busca.master.master
            busca_card.config(highlightbackground='#30363d')
        except Exception:
            pass
        self.arquivos_encontrados = []
        self.player.carregar_playlist([])
        self.atualizar_lista()
        self.root.focus_set()

    def _on_entry_keyrelease(self, event: object) -> None:
        """Handler único para KeyRelease no entry_busca."""
        self.on_busca_digitada(event)
        self._reset_focus_timer(event)

    def _on_focus_out(self, event: object = None) -> None:
        if not self.entry_busca.get().strip():
            self.entry_busca.delete(0, tk.END)
            self.entry_busca.insert(0, self.placeholder_busca)
            self.entry_busca.config(fg='#F5BE08')
        self._cancel_focus_timer()

    # ── Configurações ─────────────────────────────────────────────

    def carregar_config(self) -> dict[str, Any]:
        dados: dict[str, Any] = {}
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE) as f:
                    dados = json.load(f)
        except Exception:
            dados = {}
        if not isinstance(dados, dict):
            dados = {}
        remoto = dados.setdefault('remoto', {})
        if not isinstance(remoto, dict):
            remoto = dados['remoto'] = {}
        remoto.setdefault('ativo', False)
        remoto.setdefault('token', '')
        return dados

    # ── Controle remoto (celular na mesma rede) ───────────────────

    def _na_thread_ui(self, fn: Callable, timeout: float = 5.0) -> Any:
        """Executa `fn` na thread do Tk e devolve o resultado.

        É a ponte usada pelo ServidorAsyncHTTP (que roda em thread
        própria): agenda no root.after e aguarda o Future, nunca tocando
        em widgets fora da thread do Tk.
        """
        fut: concurrent.futures.Future = concurrent.futures.Future()

        def _executar() -> None:
            if fut.cancelled():
                return
            try:
                fut.set_result(fn())
            except Exception as exc:  # noqa: BLE001 — repassa ao chamador
                fut.set_exception(exc)

        self.root.after(0, _executar)
        try:
            return fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            raise TimeoutError(
                "O aplicativo não respondeu a tempo") from None

    def _aplicar_acesso_remoto(self) -> None:
        """(Re)configura bind e token do servidor HTTP conforme a config."""
        if not getattr(self, '_servidor_thread', None):
            return
        remoto = self.config_data.get('remoto') or {}
        ativo = bool(remoto.get('ativo') and remoto.get('token'))
        self._servidor_thread.configurar_acesso(
            '0.0.0.0' if ativo else '127.0.0.1',
            remoto.get('token') if ativo else None)

    def info_controle_remoto(self) -> dict:
        """Estado atual do remoto: ativo, token e URL para o celular."""
        remoto = self.config_data.get('remoto') or {}
        ativo = bool(remoto.get('ativo') and remoto.get('token'))
        token = remoto.get('token') or ''
        ip = _ip_da_rede() if ativo else ''
        url = (f"http://{ip}:{BACKEND_PORT}/?t={token}" if ativo else '')
        return {'ativo': ativo, 'token': token, 'ip': ip, 'url': url}

    def alternar_controle_remoto(self, ativo: bool) -> dict:
        """Liga/desliga o controle remoto, gerando o token se preciso."""
        remoto = self.config_data.setdefault('remoto', {})
        remoto['ativo'] = bool(ativo)
        if ativo and not remoto.get('token'):
            remoto['token'] = secrets.token_urlsafe(9)
        if not ativo:
            remoto['token'] = ''
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config_data, f, indent=2)
        except Exception as e:
            log.exception(f"Erro ao salvar config de remoto: {e}")
        self._aplicar_acesso_remoto()
        log.info(('🌐 Controle remoto ATIVADO' if ativo
               else '📴 Controle remoto desativado')
              + (f" — {self.info_controle_remoto()['url']}" if ativo else ''))
        return self.info_controle_remoto()

    def abrir_controle_remoto(self) -> None:
        """Abre Configurações já na aba 🌐 Controle Remoto.

        O conteúdo (ativação, token e URL) vive na própria aba — ver
        `_conteudo_controle_remoto` — então esta janela nunca abre por
        trás de outra: é a janela de Configurações que ganha a aba.
        """
        self.abrir_config_relogio_dialogo(aba='remoto')

    def _conteudo_controle_remoto(self, parent) -> None:
        """Monta dentro de `parent` (aba 🌐 Controle Remoto) os controles.

        Ativação do controle remoto, URL com token, copiar e trocar token —
        o mesmo comportamento da antiga janela separada, agora como aba da
        janela de Configurações (aberta igual às demais abas).
        """
        tk.Label(
            parent, justify='left', bg='#0d1117', fg='#c9d1d9',
            font=("Arial", 10),
            text=("Operar o NavePro pelo celular na mesma rede Wi-Fi:\n"
                  "hinos, slides, Bíblia, anúncios, ordem de serviço e\n"
                  "medidor, sem tocar no computador.")
        ).pack(pady=(12, 10), padx=20)

        estado = {'ativo': tk.BooleanVar(
            value=bool(self.info_controle_remoto()['ativo']))}

        frame_url = tk.Frame(parent, bg='#161b22')
        frame_url.pack(fill='x', padx=20, pady=4)

        entry_url = tk.Entry(frame_url, bg='#0d1117', fg='#58a6ff',
                             insertbackground='#58a6ff', relief='flat',
                             font=("Arial", 10), readonlybackground='#161b22')
        entry_url.pack(side='left', fill='x', expand=True, padx=8, pady=8,
                       ipady=4)
        entry_url.configure(state='normal')

        def _atualizar_url() -> None:
            info = self.info_controle_remoto()
            entry_url.configure(state='normal')
            entry_url.delete(0, tk.END)
            if info['url']:
                entry_url.insert(0, info['url'])
            entry_url.configure(state='readonly')

        def _alternar() -> None:
            self.alternar_controle_remoto(estado['ativo'].get())
            _atualizar_url()

        def _copiar(event: object = None) -> None:
            url = entry_url.get().strip()
            if not url:
                return
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            btn_copiar.config(text="✅ Copiado")
            parent.after(1500, lambda: btn_copiar.config(text="📋 Copiar"))

        def _novo_token() -> None:
            self.alternar_controle_remoto(False)
            self.alternar_controle_remoto(True)
            estado['ativo'].set(True)
            _atualizar_url()

        tk.Checkbutton(
            parent, text="Ativar controle remoto", variable=estado['ativo'],
            command=_alternar, bg='#0d1117', fg='#f0c040', selectcolor='#161b22',
            activebackground='#0d1117', activeforeground='#f0c040',
            font=("Arial", 11, "bold"), anchor='w'
        ).pack(fill='x', padx=22, pady=(8, 2))

        frame_botoes = tk.Frame(parent, bg='#0d1117')
        frame_botoes.pack(fill='x', padx=20, pady=4)
        btn_copiar = tk.Button(
            frame_botoes, text="📋 Copiar", command=_copiar,
            bg='#1f6feb', fg='white', activebackground='#388bfd',
            font=("Arial", 10, "bold"), cursor='hand2', padx=10, pady=3)
        btn_copiar.pack(side='left', padx=(0, 6))
        tk.Button(
            frame_botoes, text="🔄 Novo token", command=_novo_token,
            bg='#21262d', fg='#c9d1d9', activebackground='#30363d',
            font=("Arial", 10), cursor='hand2', padx=10, pady=3
        ).pack(side='left')

        tk.Label(
            parent, justify='left', bg='#0d1117', fg='#8b949e',
            font=("Arial", 9),
            text=("Como usar:\n"
                  "1. Ative o controle remoto (acima).\n"
                  "2. No celular, abra a URL mostrada (mesma rede Wi-Fi).\n"
                  "3. O acesso é protegido por token; troque o token se\n"
                  "   alguém tiver a URL antiga.")
        ).pack(padx=20, anchor='w', pady=(12, 0))

        _atualizar_url()

    # ── Projeção reutilizável (janelas + controle remoto) ─────────

    def projetar_anuncio(self, anuncio_id: int,
                         ao_atualizar: Callable | None = None) -> dict:
        """Projeta o anúncio `anuncio_id` (vídeo/áudio/imagem/slides).

        Usado pela janela de Anúncios e pelo controle remoto. Não abre
        diálogo: devolve {'ok': False, 'erro': ...} para o chamador
        decidir o que mostrar. `ao_atualizar` é chamado após projetar
        (ex.: atualizar o indicador de slide da janela).
        """
        anuncio = next(
            (a for a in _listar_anuncios_db()
             if int(a.get('id', 0)) == anuncio_id), None)
        if not anuncio:
            return {'ok': False, 'erro': 'Anúncio não encontrado.'}
        tipo = anuncio.get('tipo_midia') or 'slide'
        arquivo = anuncio.get('arquivo_midia') or ''
        if tipo in ('video', 'audio') and arquivo and os.path.exists(arquivo):
            self._anuncio_proj["id"] = None
            self.arquivos_encontrados = [arquivo]
            self.player.carregar_playlist([arquivo])
            self.player.tocar_indice(0)
            self.atualizar_lista()
            if ao_atualizar:
                ao_atualizar()
            return {'ok': True, 'titulo': anuncio.get('titulo') or '',
                    'tipo': tipo}
        if tipo == 'imagem' and arquivo and os.path.exists(arquivo):
            texto_anuncio = (anuncio.get('texto') or '').strip()
            cfg_imagem: dict = {}
            try:
                _ci = json.loads(anuncio.get('config_midia') or '{}')
                if isinstance(_ci, dict):
                    cfg_imagem = _ci
            except (ValueError, TypeError, AttributeError):
                cfg_imagem = {}
            self._anuncio_proj.update({
                "id": anuncio_id, "dados": dict(anuncio),
                "config": cfg_imagem, "mslides": None, "idx_map": []})
            if self.player.telao.projetar_imagem_com_texto(
                    arquivo, texto_anuncio,
                    anuncio.get('config_midia') or ''):
                if ao_atualizar:
                    ao_atualizar()
                return {'ok': True, 'titulo': anuncio.get('titulo') or '',
                        'tipo': tipo}
            self._anuncio_proj["id"] = None
            # Falhou a composição projetada: tenta a imagem pura
            if self.player.telao.projetar_imagem(arquivo):
                if ao_atualizar:
                    ao_atualizar()
                return {'ok': True, 'titulo': anuncio.get('titulo') or '',
                        'tipo': tipo}
            return {'ok': False,
                    'erro': f"Não foi possível projetar:\n{arquivo}"}
        cfg_a: dict = {}
        try:
            _p = json.loads(anuncio.get('config_midia') or '{}')
            if isinstance(_p, dict):
                cfg_a = _p
        except (ValueError, TypeError, AttributeError):
            cfg_a = {}
        if isinstance(cfg_a, dict) and isinstance(cfg_a.get("mslides"), list):
            # Anúncio multi-slide texto+imagem (cada slide pode ter imagem).
            mslides_orig = cfg_a["mslides"]
            slides = []
            idx_map = []
            for i, s in enumerate(mslides_orig):
                if not isinstance(s, dict):
                    continue
                texto_s = (s.get("texto") or '').strip()
                imagem_s = (s.get("imagem") or '').strip()
                if not texto_s and not imagem_s:
                    continue
                slides.append({"texto": texto_s, "imagem": imagem_s,
                               "config": s.get("config") or ''})
                idx_map.append(i)
            if not slides:
                slides = [{"texto": "ANÚNCIO", "imagem": '', "config": ''}]
            self._anuncio_proj.update({
                "id": anuncio_id, "dados": dict(anuncio),
                "config": cfg_a, "mslides": mslides_orig, "idx_map": idx_map})
        else:
            slides = _montar_slides_anuncio(dict(anuncio))
            self._anuncio_proj.update({
                "id": None, "dados": {}, "config": {},
                "mslides": None, "idx_map": []})
        self.player.telao.projetar_slides(slides)
        if ao_atualizar:
            ao_atualizar()
        return {'ok': True, 'titulo': anuncio.get('titulo') or '',
                'tipo': tipo}

    def executar_proximo_item_servico(self, servico: dict | None, *,
                                      escolhido: int | None = None,
                                      ao_destacar: Callable | None = None
                                      ) -> dict:
        """Reproduz APENAS o próximo item de `servico` e para.

        A escolha do operador (`escolhido`) vale uma única vez: se informado,
        a próxima reprodução começa nele e a partir daí o avanço é item a item
        até o fim da lista, voltando ao primeiro ao terminar — a escolha
        anterior é esquecida. Sem seleção, segue do começo ao fim. Independente
        do tipo (hino/vídeo/áudio/texto): reproduz/projeta só o item e fica
        aguardando a próxima chamada. Não altera a playlist nem a opção de
        repetição da janela principal — o estado anterior é restaurado quando
        o item termina.

        Não abre diálogo (usado pelo controle remoto na thread do servidor):
        devolve {'ok': True, 'indice', 'id', 'titulo'} ou
        {'ok': False, 'codigo' ('sem_servico'|'vazio'|'falha'), 'erro'}.
        `ao_destacar(item)` é chamado para a janela realçar o item na lista.
        """
        if not servico:
            return {'ok': False, 'codigo': 'sem_servico',
                    'erro': 'Nenhum serviço selecionado.'}
        itens = list(servico.get("itens") or [])
        if not itens:
            return {'ok': False, 'codigo': 'vazio',
                    'erro': 'Serviço sem itens.'}
        chave = servico.get("id") or servico.get("nome") or "?"
        prox = _SERVICO_PROXIMO_ITEM.get(chave)
        if escolhido is not None:
            idx_escolhido = next((i for i, it in enumerate(itens)
                                  if it.get("id") == escolhido), None)
            if idx_escolhido is not None:
                prox = idx_escolhido
        if prox is None or prox < 0 or prox >= len(itens):
            prox = 0
        item = itens[prox]
        tipo = (item.get('tipo') or '').strip().lower()
        titulo_item = (item.get('titulo_custom') or '').strip()
        letra = (item.get('letra_snapshot') or '').strip()

        # Destaque do item em execução na lista da janela de serviço.
        # Não é escolha do operador: não registra nada em _item_escolhido.
        if ao_destacar:
            try:
                ao_destacar(item)
            except Exception:
                pass

        iniciado = False
        # Item "YouTube": a URL informada no editor vira a mídia do item.
        _url_youtube = ((item.get('youtube_url') or '').strip()
                        if tipo == 'youtube' else '')
        # Resolve o caminho de mídia do item: 1ª o arquivo escolhido
        # diretamente no editor (vídeo/áudio/PowerPoint/Impress); 2ª o
        # vídeo/áudio do acervo (tabela midia); 3ª a mídia (vídeo/áudio)
        # anexada a um anúncio.
        caminho_media = None
        _caminho_direto = (item.get('caminho_arquivo') or '').strip()
        if _url_youtube:
            caminho_media = _url_youtube
        elif tipo in ('video', 'audio', 'sermao') and _caminho_direto \
                and os.path.exists(_caminho_direto):
            caminho_media = _caminho_direto
        else:
            if tipo in ('video', 'audio') and item.get('referencia_id'):
                try:
                    rows_m = db_query(
                        "SELECT caminho_arquivo FROM midia WHERE id = ? AND ativo = 1",
                        (item['referencia_id'],))
                    if rows_m:
                        caminho_media = rows_m[0].get('caminho_arquivo') or ''
                except Exception:
                    caminho_media = None
            elif tipo == 'anuncio' and item.get('referencia_id'):
                anun = _buscar_anuncio_por_ref(item['referencia_id'])
                if anun and (anun.get('tipo_midia') or '').strip().lower() in ('video', 'audio'):
                    caminho_media = (anun.get('arquivo_midia') or '')
        if caminho_media and (_eh_url(caminho_media)
                              or os.path.exists(caminho_media)):
            caminho = caminho_media
            _ext = os.path.splitext(caminho)[1].lower()
            if _ext in ('.ppt', '.pptx', '.pps', '.ppsx', '.odp', '.pdf'):
                # Apresentação (PowerPoint/Impress) ou PDF: abre no
                # aplicativo do sistema (LibreOffice --show para
                # apresentação, visualizador padrão para PDF), escondendo
                # o telão enquanto estiver aberta.
                self.player._matar_processo()
                self.player.telao.preparar_video()
                if _eh_windows():
                    _cmd_apres = ['cmd', '/c', 'start', '', caminho]
                elif _ext == '.pdf':
                    # PDF: visualizador padrão do sistema (o LibreOffice
                    # em modo apresentação não serve para PDF).
                    _cmd_apres = ['xdg-open', caminho]
                else:
                    _cmd_apres = ['xdg-open', caminho]
                    for _so in ('libreoffice', 'soffice'):
                        if self.player._player_existe(_so):
                            _cmd_apres = [_so, '--show', caminho]
                            break
                try:
                    _proc_apres = subprocess.Popen(
                        _cmd_apres, start_new_session=True,
                        env=_ambiente_sem_appimage())
                except Exception as e:
                    log.exception(f"❌ Erro ao abrir apresentação/PDF: {e}")
                    iniciado = False
                else:
                    iniciado = True
                    if _cmd_apres[0] in ('libreoffice', 'soffice'):
                        # Monitora o fim da apresentação e restaura o telão
                        def _monitor_apres():
                            _rc = _proc_apres.poll()
                            if _rc is not None:
                                try:
                                    self.player.telao.restaurar_tela()
                                except Exception:
                                    pass
                                return
                            try:
                                self.player.telao.root.after(1000, _monitor_apres)
                            except tk.TclError:
                                pass
                        try:
                            self.player.telao.root.after(1000, _monitor_apres)
                        except tk.TclError:
                            pass
            else:
                # Snapshot da janela principal capturado UMA vez por
                # sessão (restaurado quando o item termina).
                if not self._snapshot_servico["guardada"]:
                    self._snapshot_servico["guardada"] = True
                    self._snapshot_servico["playlist"] = list(self.player.playlist or [])
                    self._snapshot_servico["index"] = self.player.index
                    self._snapshot_servico["arquivos"] = list(
                        getattr(self, 'arquivos_encontrados', []) or [])
                    self._snapshot_servico["atual"] = getattr(
                        self, 'arquivo_atual', None)

                def _fim_item_servico(estado: object = None):
                    # Restaura o handler e o estado anteriores ao item
                    self.player.on_state_change = self.quando_midia_terminar
                    if self._snapshot_servico["guardada"] and self.player.playlist == [caminho]:
                        self._snapshot_servico["guardada"] = False
                        self.player.playlist = self._snapshot_servico["playlist"]
                        self.player.index = self._snapshot_servico["index"]
                        self.arquivos_encontrados = self._snapshot_servico["arquivos"]
                        self.arquivo_atual = self._snapshot_servico["atual"]

                self.player.on_state_change = _fim_item_servico
                self.player.carregar_playlist([caminho])
                if self.player.tocar_indice(0):
                    iniciado = True
                else:
                    self.player.on_state_change = self.quando_midia_terminar

        if not iniciado:
            # Itens sem mídia (hino/anúncio/texto): projeta e para.
            if tipo == 'hino' and (titulo_item or letra):
                self.player.telao.projetar_slides(
                    _montar_slides_letra(titulo_item, letra))
                iniciado = True
            elif tipo == 'anuncio':
                anun = _buscar_anuncio_por_ref(item.get('referencia_id'))
                if anun:
                    if _projetar_anuncio_ordserv(self.player.telao, anun):
                        iniciado = True
                else:
                    texto = letra or titulo_item
                    if texto:
                        self.player.telao.projetar_texto(texto)
                        iniciado = True
            else:
                if tipo == 'versiculo' and letra:
                    # Projeta como slide persistente (igual janela Bíblia):
                    # fica no telão até o operador parar (Esc/fechar).
                    # Item com faixa (ex.: "1-7") sai um versículo por
                    # slide, navegável com ◀/▶; versículo único e
                    # capítulo inteiro seguem em um slide só.
                    self.player.telao.projetar_slides(
                        _slides_versiculo_item(item), indice_inicial=0)
                else:
                    texto = letra or titulo_item
                    if texto:
                        self.player.telao.projetar_texto(texto)
                iniciado = True if (letra if tipo == 'versiculo'
                                    else (letra or titulo_item)) else False

        if not iniciado:
            return {'ok': False, 'codigo': 'falha',
                    'erro': f"Não foi possível reproduzir o item {prox + 1}."}
        _SERVICO_PROXIMO_ITEM[chave] = prox + 1
        return {'ok': True, 'indice': prox, 'id': item.get('id'),
                'titulo': titulo_item}

    # ── Controle remoto: ações do celular ─────────────────────────

    def _persistir_escala_texto(self, escala: float) -> None:
        """Grava a nova escala de fonte ('ts') no anúncio em projeção.

        Anúncio de imagem única: grava 'ts' no JSON de config_midia.
        Anúncio multi-slide com imagem: grava 'ts' no config do slide
        atualmente exibido. Não faz nada se não houver anúncio sendo
        projetado ou se o slide em exibição não tiver imagem.
        """
        pid = self._anuncio_proj.get("id")
        if not pid:
            return
        try:
            cfg_dic = self._anuncio_proj.get("config") or {}
            if not isinstance(cfg_dic, dict):
                cfg_dic = {}
            c: dict = {}
            texto_local = ""
            mslides: list = []
            idx_ms = -1
            if self._anuncio_proj.get("mslides") is not None:
                idx_map = self._anuncio_proj.get("idx_map") or []
                tela_index = int(
                    getattr(self.player.telao, "_slide_index", 0) or 0)
                if not (0 <= tela_index < len(idx_map)):
                    return
                mslides = cfg_dic.get("mslides") or []
                idx_ms = idx_map[tela_index]
                if not (0 <= idx_ms < len(mslides)) or not isinstance(
                        mslides[idx_ms], dict):
                    return
                try:
                    c = json.loads(mslides[idx_ms].get("config") or "{}")
                    if not isinstance(c, dict):
                        c = {}
                except (ValueError, TypeError, AttributeError):
                    c = {}
                texto_local = (mslides[idx_ms].get("texto") or "").strip()
            else:
                c = cfg_dic
                texto_local = (self._anuncio_proj.get("dados") or {}).get(
                    "texto") or ""
            tw = int(c.get("tw") or 0)
            th = int(c.get("th") or 0)
            if tw <= 0 or th <= 0:
                # Config sem caixa de texto (legada): cria a caixa padrão
                # para a nova escala 'ts' valer na próxima projeção também.
                mh = int(1440 * 0.04) or 40
                mv = int(1080 * 0.06) or 60
                caixa = _caixa_texto_padrao(
                    texto_local, 1440 - mh * 2, 1080 - mv * 2, mh, mv,
                    aspect_imagem=float(getattr(
                        self.player.telao, "_composicao_aspect_imagem", 0.0)
                        or 0.0))
                c.update({"tx": int(caixa["x"]), "ty": int(caixa["y"]),
                          "tw": int(caixa["w"]), "th": int(caixa["h"])})
            c["ts"] = round(escala, 3)
            if self._anuncio_proj.get("mslides") is not None:
                mslides[idx_ms]["config"] = json.dumps(c, ensure_ascii=False)
            dados_proj = dict(self._anuncio_proj.get("dados") or {})
            dados_proj["config_midia"] = json.dumps(
                cfg_dic, ensure_ascii=False)
            self._anuncio_proj["dados"] = dados_proj
            self._anuncio_proj["config"] = cfg_dic
            _atualizar_anuncio_db(pid, dados_proj)
        except Exception as _e_persist:
            import traceback as _tb_persist
            _tb_persist.print_exc()
            log.warning(f"⚠️ Falha ao autosalvar escala do anúncio {pid}: {_e_persist}")

    def _persistir_escala_imagem(self, escala: float) -> None:
        """Grava a nova escala de imagem ('img_escala') no anúncio em projeção.

        Anúncio de imagem única: grava 'img_escala' no JSON de config_midia.
        Anúncio multi-slide com imagem: grava 'img_escala' no config do slide
        atualmente exibido. Não faz nada se não houver anúncio sendo projetado.
        """
        pid = self._anuncio_proj.get("id")
        if not pid:
            return
        try:
            cfg_dic = self._anuncio_proj.get("config") or {}
            if not isinstance(cfg_dic, dict):
                cfg_dic = {}
            c: dict = {}
            mslides: list = []
            idx_ms = -1
            if self._anuncio_proj.get("mslides") is not None:
                idx_map = self._anuncio_proj.get("idx_map") or []
                tela_index = int(
                    getattr(self.player.telao, "_slide_index", 0) or 0)
                if not (0 <= tela_index < len(idx_map)):
                    return
                mslides = cfg_dic.get("mslides") or []
                idx_ms = idx_map[tela_index]
                if not (0 <= idx_ms < len(mslides)) or not isinstance(
                        mslides[idx_ms], dict):
                    return
                try:
                    c = json.loads(mslides[idx_ms].get("config") or "{}")
                    if not isinstance(c, dict):
                        c = {}
                except (ValueError, TypeError, AttributeError):
                    c = {}
            else:
                c = cfg_dic
            c["img_escala"] = round(escala, 3)
            if self._anuncio_proj.get("mslides") is not None:
                mslides[idx_ms]["config"] = json.dumps(c, ensure_ascii=False)
            dados_proj = dict(self._anuncio_proj.get("dados") or {})
            dados_proj["config_midia"] = json.dumps(
                cfg_dic, ensure_ascii=False)
            self._anuncio_proj["dados"] = dados_proj
            self._anuncio_proj["config"] = cfg_dic
            _atualizar_anuncio_db(pid, dados_proj)
        except Exception as _e_persist_img:
            import traceback as _tb_persist_img
            _tb_persist_img.print_exc()
            log.warning(f"⚠️ Falha ao autosalvar escala da imagem do anúncio "
                  f"{pid}: {_e_persist_img}")

    def _tamanho_projecao(self) -> dict:
        """Estado atual das escalas de texto e imagem do telão."""
        telao = getattr(self.player, 'telao', None)
        if not (telao and telao._raiz_viva()):
            return {'texto_pct': 5.0, 'texto_escala': 1.0,
                    'imagem_escala': 1.0, 'composicao': False}
        cfg = getattr(telao, '_proj_cfg', None) or {}
        return {
            'texto_pct': float(cfg.get('tamanho_pct', 5.0)),
            'texto_escala': float(getattr(telao, '_texto_escala', 1.0) or 1.0),
            'imagem_escala': float(
                getattr(telao, '_imagem_escala', 1.0) or 1.0),
            'composicao': bool(
                getattr(telao, '_mostrando_imagem_com_texto', False)),
        }

    def _remoto_tamanho(self, dados: dict) -> dict:
        """Ajusta ao vivo o tamanho do texto/imagem projetado.

        Mesma lógica dos botões A−/A+ e 🖼️−/+ do painel do operador
        (inclusive a persistência no anúncio/projeção salva), acionada
        pelo celular: {'qual': 'texto'|'imagem',
        'acao': 'mais'|'menos'|'zerar'}.
        """
        qual = str(dados.get('qual') or '').strip().lower()
        acao = str(dados.get('acao') or '').strip().lower()
        if acao not in ('mais', 'menos', 'zerar'):
            return {'ok': False, 'erro': f'Ação de tamanho inválida: {acao}'}
        telao = self.player._garantir_telao()
        if qual == 'imagem':
            if not getattr(telao, '_mostrando_imagem', False):
                return {'ok': False,
                        'erro': 'Nenhuma imagem projetada no telão.'}
            if acao == 'mais':
                telao.imagem_aumentar()
            elif acao == 'menos':
                telao.imagem_diminuir()
            else:
                telao._imagem_escala = 1.0
                telao._renderizar_imagem_projetada()
            self._persistir_escala_imagem(
                float(getattr(telao, '_imagem_escala', 1.0) or 1.0))
        elif qual == 'texto':
            delta = 0.8 if acao == 'mais' else -0.8 if acao == 'menos' else 0.0
            if getattr(telao, '_mostrando_imagem_com_texto', False):
                texto = getattr(telao, '_current_text', '')
                if texto:
                    if acao == 'zerar':
                        telao._texto_escala = 1.0
                    else:
                        escala = float(
                            getattr(telao, '_texto_escala', 1.0) or 1.0)
                        telao._texto_escala = min(
                            2.5, max(0.25, escala + delta * 0.1))
                    telao._desenhar_texto_anuncio(texto)
                    self._persistir_escala_texto(
                        float(telao._texto_escala))
            else:
                cfg = getattr(telao, '_proj_cfg', None)
                if cfg is None:
                    telao.configurar_projecao()
                    cfg = telao._proj_cfg
                if acao == 'zerar':
                    cfg['tamanho_pct'] = 5.0
                else:
                    cfg['tamanho_pct'] = min(
                        15.0, max(1.0,
                                 float(cfg.get('tamanho_pct', 5.0)) + delta))
                telao._proj_cfg = cfg
                if getattr(telao, '_em_slides', False) and telao._slides:
                    telao._mostrar_slide(telao._slide_index)
                elif getattr(telao, 'mostrando_letra', False) \
                        and telao._current_text:
                    telao._desenhar_texto_no_canvas(telao._current_text)
                self.salvar_config_projecao(dict(cfg))
        else:
            return {'ok': False,
                    'erro': f'Parâmetro de tamanho inválido: {qual}'}
        return {'ok': True, 'tamanho': self._tamanho_projecao()}

    def _remoto_despacho(self, acao: str, dados: dict) -> Any:
        """Executa uma ação vinda do ServidorAsyncHTTP (na thread do Tk).

        O servidor chama isto via `_na_ui` (root.after + Future). Nunca
        abre diálogo e nunca deixa exceção escapar: devolve sempre dicts
        serializáveis — erro vira {'ok': False, 'erro': ...} (com o
        próprio JSON da resposta; o HTTP segue 200).
        """
        dados = dados if isinstance(dados, dict) else {}
        try:
            # ── Leituras (GET) ──
            if acao == 'estado':
                return self._remoto_estado()
            if acao == 'buscar_hino':
                return self._remoto_buscar_hino(str(dados.get('busca') or ''))
            if acao == 'buscar_midia':
                return self._remoto_buscar_midia(str(dados.get('busca') or ''))
            if acao == 'buscar_biblia':
                return self._remoto_buscar_biblia(
                    str(dados.get('q') or ''),
                    str(dados.get('versao') or ''))
            if acao == 'buscar_biblia_ref':
                return self._remoto_buscar_biblia_ref(dados)
            if acao == 'livros_biblia':
                return {'ok': True, 'livros': list(self.LIVROS_BIBLIA)}
            if acao == 'listar_anuncios':
                return {'ok': True, 'anuncios': [
                    {'id': a.get('id'), 'titulo': a.get('titulo') or '',
                     'tipo': a.get('tipo_midia') or 'slide'}
                    for a in _listar_anuncios_db()]}
            if acao == 'listar_servicos':
                servicos = (_carregar_servicos_json().get('servicos') or [])
                return {'ok': True, 'servicos': [
                    {'id': s.get('id'), 'nome': s.get('nome') or '',
                     'itens': len(s.get('itens') or [])}
                    for s in servicos]}
            if acao == 'servico_itens':
                return self._remoto_servico_itens(dados)
            # ── Ações (POST) ──
            if acao == 'slide':
                return self._remoto_slide(str(dados.get('acao') or ''))
            if acao == 'tamanho':
                return self._remoto_tamanho(dados)
            if acao == 'projetar_hino':
                return self._remoto_projetar_hino(dados)
            if acao == 'projetar_biblia':
                return self._remoto_projetar_biblia(dados)
            if acao == 'executar_midia':
                return self._remoto_executar_midia(dados)
            if acao == 'controle_player':
                return self._remoto_controle_player(dados)
            if acao == 'projetar_anuncio':
                self.player._garantir_telao()
                return self.projetar_anuncio(int(dados.get('id') or 0))
            if acao == 'executar_servico':
                return self._remoto_executar_servico(dados)
            if acao == 'servico_item':
                return self._remoto_servico_item(dados)
            if acao == 'medidor':
                return self._remoto_medidor(dados)
            return {'ok': False, 'erro': f'Ação desconhecida: {acao}'}
        except Exception as exc:  # noqa: BLE001 — vira JSON de erro
            log.exception(f"❌ Erro na ação remota '{acao}': {exc}")
            return {'ok': False, 'erro': str(exc) or type(exc).__name__}

    def _remoto_estado(self) -> dict:
        """Snapshot do estado do app para a tela do celular."""
        telao = getattr(self.player, 'telao', None)
        vivo = bool(telao and telao._raiz_viva())
        info_telao = {'vivo': vivo, 'modo': 'desligado'}
        if vivo:
            modo = ('slides' if getattr(telao, '_em_slides', False)
                    else 'relogio' if getattr(telao, 'mostrando_relogio', False)
                    else 'midia')
            info_telao = {
                'vivo': True, 'modo': modo,
                'slide': int(getattr(telao, '_slide_index', 0) or 0),
                'total': len(getattr(telao, '_slides', None) or []),
            }
            slides = getattr(telao, '_slides', None) or []
            idx = getattr(telao, '_slide_index', 0) or 0
            if modo == 'slides' and 0 <= idx < len(slides):
                info_telao['previa'] = _previa_slide(slides[idx])
        info_telao['tamanho'] = self._tamanho_projecao()
        pl = list(getattr(self.player, 'playlist', None) or [])
        idx_m = int(getattr(self.player, 'index', 0) or 0)
        info_midia = {
            'arquivo': os.path.basename(self.arquivo_atual)
            if self.arquivo_atual else '',
            'indice': idx_m, 'total': len(pl),
            'tocando': bool(getattr(self.player, 'is_playing', False)),
            'pausado': bool(getattr(self.player, 'is_paused', False)),
        }
        return {'ok': True, 'versao': APP_VERSION,
                'telao': info_telao, 'midia': info_midia,
                'medidor': self._remoto_medidor_estado(),
                'proximos_servico': dict(_SERVICO_PROXIMO_ITEM)}

    def _remoto_medidor_estado(self) -> dict:
        """Estado do cronômetro e da contagem regressiva."""
        agora = time.time()
        c = self._crono
        acum = c["acumulado"] + ((agora - c["inicio"])
                                 if c["rodando"] and not c["pausado"] else 0.0)
        g = self._contagem
        rest = (g["fim"] - agora) if (g["rodando"] and not g["pausado"]) \
            else g["restante"]
        return {
            'cronometro': {'rodando': bool(c["rodando"]),
                           'pausado': bool(c["pausado"]),
                           'tempo': self._formatar_cronometro(acum)},
            'contagem': {'rodando': bool(g["rodando"]),
                         'pausado': bool(g["pausado"]),
                         'restante': max(0.0, float(rest or 0.0)),
                         'titulo': g.get("titulo") or ''},
        }

    def _remoto_buscar_hino(self, busca: str) -> dict:
        """Lista hinos para o celular (resumo; sem a letra completa)."""
        busca = busca.strip()
        if busca:
            rows = _buscar_hino_por_termo(busca)
        else:
            rows = db_query("SELECT * FROM letras WHERE ativo = 1 "
                            "ORDER BY titulo LIMIT 50")
        return {'ok': True, 'hinos': [
            {'id': r.get('id'), 'titulo': r.get('titulo') or '',
             'artista': r.get('artista') or '',
             'numero': _numero_do_titulo(r.get('titulo') or '')}
            for r in rows[:50]]}

    def _remoto_projetar_hino(self, dados: dict) -> dict:
        rows = db_query("SELECT * FROM letras WHERE id = ? AND ativo = 1",
                        (int(dados.get('id') or 0),))
        if not rows:
            return {'ok': False, 'erro': 'Hino não encontrado.'}
        hino = rows[0]
        slides = _montar_slides_letra(hino.get('titulo') or '',
                                      hino.get('letra_completa') or '')
        self.player._garantir_telao()
        self.player.telao.projetar_slides(slides)
        return {'ok': True, 'titulo': hino.get('titulo') or '',
                'total': len(slides)}

    def _versoes_biblia(self) -> list[str]:
        return [r.get('versao') or '' for r in db_query(
            "SELECT DISTINCT versao FROM versiculos ORDER BY versao")]

    def _remoto_buscar_biblia(self, q: str, versao: str) -> dict:
        """Busca versículos (ou só lista as versões, se a busca vier vazia)."""
        versoes = self._versoes_biblia()
        if not versao:
            versao = versoes[0] if versoes else ''
        if not versao:
            return {'ok': True, 'versao': '', 'versoes': [], 'resultados': [],
                    'erro': 'Nenhuma Bíblia importada.'}
        if not q.strip():
            return {'ok': True, 'versao': versao, 'versoes': versoes,
                    'resultados': []}
        rows = db_query(
            "SELECT * FROM versiculos WHERE versao = ? AND texto LIKE ? "
            "ORDER BY livro, capitulo, versiculo LIMIT 50",
            (versao, f"%{q.strip()}%"))
        return {'ok': True, 'versao': versao, 'versoes': versoes,
                'resultados': [
                    {'livro': r.get('livro'), 'capitulo': r.get('capitulo'),
                     'versiculo': r.get('versiculo'), 'texto': r.get('texto')}
                    for r in rows]}

    def _remoto_projetar_biblia(self, dados: dict) -> dict:
        """Projeta versículos por texto (LIKE) ou por referência (livro/cap/V:)."""
        if (str(dados.get('livro') or '').strip()
                or str(dados.get('cap') or '').strip()):
            return self._remoto_projetar_biblia_ref(dados)
        res = self._remoto_buscar_biblia(str(dados.get('q') or ''),
                                         str(dados.get('versao') or ''))
        if not res.get('resultados'):
            return {'ok': False,
                    'erro': res.get('erro') or 'Nenhum versículo encontrado.'}
        slides = [(r['texto'], f"{r['livro']} {r['capitulo']}:{r['versiculo']}")
                  for r in res['resultados']]
        self.player._garantir_telao()
        self.player.telao.projetar_slides(slides)
        return {'ok': True, 'versao': res['versao'], 'total': len(slides),
                'primeiro': slides[0][1]}

    def _remoto_buscar_biblia_ref(self, dados: dict) -> dict:
        """Busca versículos por referência (livro + cap + V:), como no app.

        O campo "V:" segue a mesma regra da janela Bíblia
        (`_analisar_faixa_versiculos`):
          - vazio ou "1" → o capítulo inteiro
          - "7"          → do versículo 7 até o fim do capítulo
          - "1-7"        → somente os versículos de 1 a 7
        """
        versao = str(dados.get('versao') or '').strip()
        livro = str(dados.get('livro') or '').strip()
        cap_t = str(dados.get('cap') or '').strip()
        vers_t = str(dados.get('vers') or '').strip()
        versoes = self._versoes_biblia()
        if not versao:
            versao = versoes[0] if versoes else ''
        if not versao:
            return {'ok': True, 'versao': '', 'versoes': [], 'resultados': [],
                    'erro': 'Nenhuma Bíblia importada.'}
        if not livro or not cap_t.isdigit():
            return {'ok': True, 'versao': versao, 'versoes': versoes,
                    'resultados': [], 'inicio': None,
                    'erro': 'Informe o livro e o capítulo.'}
        cap = int(cap_t)
        ok, msg, ini, fim = _analisar_faixa_versiculos(vers_t)
        if not ok:
            return {'ok': False, 'versao': versao, 'versoes': versoes,
                    'resultados': [], 'erro': msg}
        if ini is None:
            v_ini, v_fim = 1, 9999
        elif '-' in vers_t:
            # Faixa explícita: respeita o fim digitado (16-16 = só o 16).
            v_ini, v_fim = ini, fim
        else:
            # Número único é o ponto de partida: vai até o fim do capítulo.
            v_ini, v_fim = ini, 9999
        rows = db_query(
            "SELECT * FROM versiculos WHERE versao = ? AND livro = ? "
            "AND capitulo = ? AND versiculo >= ? AND versiculo <= ? "
            "ORDER BY versiculo",
            (versao, livro, cap, v_ini, v_fim))
        return {'ok': True, 'versao': versao, 'versoes': versoes,
                'livro': livro, 'capitulo': cap, 'inicio': ini,
                'resultados': [
                    {'livro': r.get('livro'), 'capitulo': r.get('capitulo'),
                     'versiculo': r.get('versiculo'), 'texto': r.get('texto')}
                    for r in rows]}

    def _remoto_projetar_biblia_ref(self, dados: dict) -> dict:
        """Projeta o trecho por referência, versículo a versículo (slides)."""
        res = self._remoto_buscar_biblia_ref(dados)
        if not res.get('resultados'):
            return {'ok': False,
                    'erro': res.get('erro') or 'Nenhum versículo encontrado.'}
        livro = res['livro']
        cap = res['capitulo']
        rows = res['resultados']
        numeros = [r['versiculo'] for r in rows]
        ini = res.get('inicio')
        if ini is None:
            ini = numeros[0] if numeros else 1
        slides = [(r['texto'], f"{livro} {cap}:{r['versiculo']}") for r in rows]
        inicio = numeros.index(ini) if ini in numeros else 0
        self.player._garantir_telao()
        self.player.telao.projetar_slides(slides, indice_inicial=inicio)
        return {'ok': True, 'versao': res['versao'], 'livro': livro,
                'capitulo': cap, 'total': len(slides),
                'primeiro': slides[inicio][1]}

    def _remoto_buscar_midia(self, busca: str) -> dict:
        """Busca músicas/vídeos na tabela `midia`, como o campo da tela
        principal do app ("Buscar hino... [BD]")."""
        termo = (busca or '').strip()
        if not termo:
            return {'ok': True, 'midias': []}
        resultados = self.db.search(termo)
        return {'ok': True, 'midias': [
            {'id': r.get('id'),
             'nome': (r.get('nome_exibicao') or r.get('nome_original')
                      or os.path.basename(r.get('caminho_arquivo') or '')),
             'tipo': r.get('tipo') or '',
             'numero': _numero_do_titulo(r.get('nome_exibicao') or '')}
            for r in resultados[:50]]}

    def _remoto_executar_midia(self, dados: dict) -> dict:
        """Toca no telão a música/vídeo encontrado (áudio ou vídeo)."""
        rows = db_query("SELECT * FROM midia WHERE id = ? AND ativo = 1",
                        (int(dados.get('id') or 0),))
        if not rows:
            return {'ok': False, 'erro': 'Mídia não encontrada.'}
        caminho = rows[0].get('caminho_arquivo') or ''
        if not caminho or not os.path.exists(caminho):
            return {'ok': False, 'erro': 'Arquivo não encontrado no disco.'}
        self.player._garantir_telao()
        self.arquivo_atual = caminho
        self.player.carregar_playlist([caminho])
        self.player.tocar_indice(0)
        return {'ok': True, 'arquivo': os.path.basename(caminho),
                'tipo': rows[0].get('tipo') or ''}

    def _remoto_controle_player(self, dados: dict) -> dict:
        """Pausa/continua ou para a mídia em reprodução (controle remoto).

        Usa exatamente os mesmos caminhos do painel do operador:
        `player.play_pause()` para alternar pausa/continuar e `self.parar()`
        para encerrar — assim o telão e os labels ficam iguais aos do app.
        """
        acao = str(dados.get('acao') or '').strip().lower()
        player = self.player
        if acao in ('play_pause', 'playpause', 'pause', 'pausar', 'continuar'):
            if player is None or not player.is_playing:
                return {'ok': False, 'erro': 'Nenhuma mídia em reprodução.'}
            player.play_pause()
            return {'ok': True, 'tocando': bool(player.is_playing),
                    'pausado': bool(player.is_paused)}
        if acao in ('parar', 'stop'):
            self.parar()
            return {'ok': True, 'tocando': False, 'pausado': False}
        return {'ok': False, 'erro': f'Ação de player inválida: {acao}'}

    def _remoto_slide(self, acao: str) -> dict:
        """Navega/encerra a projeção em slides do telão."""
        telao = self.player._garantir_telao()
        if acao in ('prox', 'proximo'):
            telao.slide_proximo()
        elif acao in ('ant', 'anterior'):
            telao.slide_anterior()
        elif acao in ('parar', 'stop', 'relogio'):
            telao.parar_projecao()
        else:
            return {'ok': False, 'erro': f'Ação de slide inválida: {acao}'}
        vivo = telao._raiz_viva()
        em_slides = bool(vivo and getattr(telao, '_em_slides', False))
        idx = int(getattr(telao, '_slide_index', 0) or 0) if vivo else 0
        previa = ''
        if em_slides:
            slides = getattr(telao, '_slides', None) or []
            if 0 <= idx < len(slides):
                previa = _previa_slide(slides[idx])
        return {'ok': True, 'em_slides': em_slides, 'slide': idx,
                'total': len(getattr(telao, '_slides', None) or []) if vivo else 0,
                'previa': previa}

    def _remoto_executar_servico(self, dados: dict) -> dict:
        """Roda o próximo item de um serviço (ou o `item` escolhido)."""
        alvo = str(dados.get('id') or '')
        servicos = _carregar_servicos_json().get('servicos') or []
        serv = next((s for s in servicos
                     if str(s.get('id') or '') == alvo
                     or str(s.get('nome') or '') == alvo), None)
        if serv is None:
            return {'ok': False, 'erro': 'Serviço não encontrado.'}
        item = dados.get('item')
        escolhido = int(item) if item is not None else None
        self.player._garantir_telao()
        return self.executar_proximo_item_servico(serv, escolhido=escolhido)

    def _remoto_servico_itens(self, dados: dict) -> dict:
        """Lista os itens de UM serviço para a aba Serviço do celular."""
        serv = self._localizar_servico(str(dados.get('servico') or ''))
        if serv is None:
            return {'ok': False, 'erro': 'Serviço não encontrado.'}
        itens = serv.get('itens') or []
        return {'ok': True,
                'servico': {'id': serv.get('id'),
                            'nome': serv.get('nome') or ''},
                'itens': [self._resumo_item_servico(it, i)
                          for i, it in enumerate(itens)]}

    @staticmethod
    def _localizar_servico(alvo: str) -> dict | None:
        """Acha um serviço pelo id ou nome (mesma regra da execução)."""
        servicos = _carregar_servicos_json().get('servicos') or []
        return next((s for s in servicos
                     if str(s.get('id') or '') == alvo
                     or str(s.get('nome') or '') == alvo), None)

    @staticmethod
    def _resumo_item_servico(item: dict, indice: int) -> dict:
        """Resumo de um item de serviço para exibir no celular."""
        tipo = (item.get('tipo') or 'slide').lower()
        titulo = item.get('titulo_custom') or f'Item {indice + 1}'
        detalhe = ''
        if tipo == 'versiculo':
            detalhe = _faixa_versiculo_item(item)
        elif tipo in ('video', 'audio', 'sermao'):
            caminho = item.get('caminho_arquivo') or ''
            if caminho:
                detalhe = os.path.basename(caminho)
        elif tipo == 'anuncio':
            detalhe = 'anúncio'
        elif tipo == 'youtube':
            detalhe = 'YouTube'
        ref = None
        if tipo == 'versiculo':
            primeira = (item.get('letra_snapshot') or '').split('\n', 1)[0].strip()
            if primeira:
                if ':' in primeira:
                    cabeca, vers_txt = primeira.rsplit(':', 1)
                else:
                    cabeca, vers_txt = primeira, ''
                cabeca = cabeca.strip()
                if ' ' in cabeca:
                    liv, cap = cabeca.rsplit(' ', 1)
                    ref = {'livro': liv.strip(), 'cap': cap.strip(),
                           'vers': vers_txt.strip()}
        return {'id': item.get('id'), 'ordem': indice, 'tipo': tipo,
                'titulo': titulo,
                'duracao': item.get('duracao_estimada_segundos') or 0,
                'detalhe': detalhe,
                'caminho_arquivo': item.get('caminho_arquivo') or '',
                'ref': ref}

    def _remoto_resolver_item(self, dados: dict) -> tuple:
        """Resolve um item da Ordem de Serviço vindo do celular.

        Replica, sem Tk, a lógica da janela "Adicionar Item" do aplicativo
        (hino/versículo/vídeo/áudio/sermão/anúncio/slide). Retorna
        (ok, msg_erro, campos), já com as chaves prontas para gravar em
        servicos.json (inclui 'versiculos' quando for uma faixa).
        """
        tipo = str(dados.get('tipo') or 'hino').strip().lower()
        titulo = str(dados.get('titulo') or '').strip()
        termo = str(dados.get('termo') or '').strip()
        caminho_arquivo = str(dados.get('caminho_arquivo') or '').strip()
        try:
            duracao = int(dados.get('duracao') or 0)
        except (TypeError, ValueError):
            duracao = 0
        if tipo not in ('hino', 'versiculo', 'video', 'audio', 'slide',
                        'anuncio', 'sermao'):
            return (False, f'Tipo de item inválido: "{tipo}".', {})
        if tipo not in ('video', 'audio', 'sermao'):
            caminho_arquivo = ''

        ref = dados.get('ref') if isinstance(dados.get('ref'), dict) else {}
        versao = str(ref.get('versao') or '').strip()
        livro = str(ref.get('livro') or '').strip()
        cap_t = str(ref.get('cap') or '').strip()
        vers = str(ref.get('vers') or '').strip()
        hino_termo = str(dados.get('hino') or '').strip()
        anuncio_t = str(dados.get('anuncio') or '').strip()
        _usou_painel_biblia = bool(
            tipo == 'versiculo' and versao and livro and cap_t.isdigit())
        _usou_painel_hino = bool(tipo == 'hino' and hino_termo)
        _usou_painel_anuncio = bool(
            tipo == 'anuncio' and (anuncio_t or dados.get('referencia_id')))

        ref_id = dados.get('referencia_id')
        if isinstance(ref_id, str) and ref_id.strip().isdigit():
            ref_id = int(ref_id)
        letra_snap = ''
        vers_salvos = []
        _usou_titulo_como_busca = (not termo)
        if not termo:
            termo = titulo

        if tipo == 'hino':
            buscar = hino_termo if _usou_painel_hino else termo
            rows = _buscar_hino_por_termo(buscar)
            if not rows and buscar.isdigit():
                rows = db_query(
                    "SELECT * FROM letras WHERE id = ? AND ativo = 1", (buscar,))
            if not rows:
                return (False, f'Nenhum hino encontrado para: "{buscar}".', {})
            h = rows[0]
            ref_id = h.get('id')
            letra_snap = h.get('letra_completa', '')
            if not titulo or _usou_titulo_como_busca:
                titulo = h.get('titulo', '') or 'Item (Hino)'
        elif tipo in ('video', 'audio', 'sermao') and caminho_arquivo:
            if not os.path.exists(caminho_arquivo):
                return (False, f'Arquivo não encontrado:\n{caminho_arquivo}', {})
            if not titulo or _usou_titulo_como_busca:
                titulo = (os.path.splitext(os.path.basename(caminho_arquivo))[0]
                          or f'Item ({tipo.title()})')
        elif tipo in ('video', 'audio'):
            rows = _buscar_midia_por_termo(termo, tipo=tipo)
            if not rows and termo.isdigit():
                rows = db_query(
                    "SELECT * FROM midia WHERE id = ? AND ativo = 1", (termo,))
            if not rows:
                return (False,
                        f'Nenhuma {tipo.title()} encontrada para: "{termo}".', {})
            m = rows[0]
            ref_id = m.get('id')
            if not titulo or _usou_titulo_como_busca:
                titulo = m.get('nome_exibicao', '') or f'Item ({tipo.title()})'
        elif tipo == 'sermao':
            return (False, 'Informe o caminho do arquivo do sermão.', {})
        elif tipo == 'anuncio' and _usou_painel_anuncio:
            ref_an = _buscar_anuncio_por_ref(dados.get('referencia_id'))
            if ref_an is None and anuncio_t:
                ref_an = next((a for a in _listar_anuncios_db()
                               if (a.get('titulo') or '').strip() == anuncio_t),
                              None)
            if ref_an is None:
                return (False, 'O anúncio selecionado não foi encontrado.', {})
            ref_id = ref_an.get('id')
            letra_snap = ref_an.get('texto') or ''
            if not titulo or _usou_titulo_como_busca:
                titulo = ref_an.get('titulo') or 'Item (Anúncio)'
        elif tipo == 'anuncio':
            rows = _buscar_anuncio_por_termo(termo)
            if not rows:
                return (False,
                        f'Nenhum anúncio encontrado para: "{termo}".', {})
            ref_an = rows[0]
            ref_id = ref_an.get('id')
            letra_snap = ref_an.get('texto') or ''
            if not titulo or _usou_titulo_como_busca:
                titulo = ref_an.get('titulo') or 'Item (Anúncio)'
        elif tipo == 'versiculo' and _usou_painel_biblia:
            ok_f, msg_f, v_ini, v_fim = _analisar_faixa_versiculos(vers)
            if not ok_f:
                return (False, msg_f, {})
            cap = int(cap_t)
            if v_ini is None:
                v_ini, v_fim = 1, 9999
            elif '-' not in vers:
                v_fim = 9999
            rows = db_query(
                "SELECT * FROM versiculos WHERE versao = ? AND livro = ? "
                "AND capitulo = ? AND versiculo >= ? AND versiculo <= ? "
                "ORDER BY versiculo",
                (versao, livro, cap, v_ini, v_fim))
            if not rows:
                return (False, 'Nenhum versículo encontrado para '
                               f'{livro} {cap}:{vers or "*"} ({versao}).', {})
            if v_ini == v_fim:
                r = rows[0]
                letra_snap = f"{livro} {cap}:{vers}\n\n{r['texto']}"
                ref_display = f"{livro} {cap}:{vers}"
                ref_id = r['id']
            elif v_ini == 1 and v_fim == 9999:
                partes = [f"{r['versiculo']}. {r['texto']}" for r in rows]
                letra_snap = f"{livro} {cap}\n\n" + "\n\n".join(partes)
                ref_display = f"{livro} {cap}"
                ref_id = rows[0]['id']
            else:
                faixa_ref = f"{livro} {cap}:{v_ini}-{v_fim}"
                partes = [f"{r['versiculo']}. {r['texto']}" for r in rows]
                letra_snap = f"{faixa_ref}\n\n" + "\n\n".join(partes)
                ref_display = faixa_ref
                ref_id = rows[0]['id']
                vers_salvos = [[r['versiculo'], r['texto']] for r in rows]
            if not titulo or _usou_titulo_como_busca:
                titulo = ref_display
        elif tipo == 'versiculo':
            return (False,
                    'Selecione a versão, o livro e informe o capítulo.', {})
        elif termo.isdigit() and ref_id is None:
            ref_id = int(termo)

        if not titulo:
            titulo = f'Item ({tipo.title()})'
        if tipo == 'versiculo' and ref_id and not _usou_painel_biblia:
            rows_v = db_query("SELECT * FROM versiculos WHERE id = ?", (ref_id,))
            if rows_v:
                r = rows_v[0]
                letra_snap = (f"{r['livro']} {r['capitulo']}:{r['versiculo']}"
                              f"\n\n{r['texto']}")
                if titulo.startswith('Item'):
                    titulo = f"{r['livro']} {r['capitulo']}:{r['versiculo']}"

        campos = {
            'tipo': tipo,
            'referencia_id': ref_id,
            'titulo_custom': titulo,
            'letra_snapshot': letra_snap,
            'caminho_arquivo': caminho_arquivo,
            'duracao_estimada_segundos': duracao,
        }
        if vers_salvos:
            campos['versiculos'] = vers_salvos
        return (True, '', campos)

    def _remoto_servico_item(self, dados: dict) -> dict:
        """Adiciona/edita/apaga/move um item de um serviço (aba Serviço)."""
        operacao = str(dados.get('operacao') or '').strip().lower()
        alvo = str(dados.get('servico') or '')
        todos = _carregar_servicos_json()
        serv = next((s for s in (todos.get('servicos') or [])
                     if str(s.get('id') or '') == alvo
                     or str(s.get('nome') or '') == alvo), None)
        if serv is None:
            return {'ok': False, 'erro': 'Serviço não encontrado.'}
        itens = serv.setdefault('itens', [])
        item_id = dados.get('id')

        if operacao in ('add', 'adicionar', 'editar', 'edit'):
            ok, erro, campos = self._remoto_resolver_item(dados)
            if not ok:
                return {'ok': False, 'erro': erro}
            if operacao in ('editar', 'edit'):
                idx = next((i for i, x in enumerate(itens)
                            if str(x.get('id') or '') == str(item_id)), None)
                if idx is None:
                    return {'ok': False, 'erro': 'Item não encontrado.'}
                itens[idx].pop('versiculos', None)
                itens[idx].update(campos)
                novo_id = itens[idx].get('id')
            else:
                novo_id = int(todos.get('_proximo_id_item') or 1)
                todos['_proximo_id_item'] = novo_id + 1
                itens.append(dict(campos, id=novo_id))
            if not _salvar_servicos_json(todos):
                return {'ok': False,
                        'erro': 'Não foi possível salvar em servicos.json.'}
            return {'ok': True, 'id': novo_id, 'total': len(itens)}

        if operacao in ('apagar', 'excluir', 'delete', 'remover'):
            antes = len(itens)
            serv['itens'] = [x for x in itens
                             if str(x.get('id') or '') != str(item_id)]
            if len(serv['itens']) == antes:
                return {'ok': False, 'erro': 'Item não encontrado.'}
            if not _salvar_servicos_json(todos):
                return {'ok': False,
                        'erro': 'Não foi possível salvar em servicos.json.'}
            return {'ok': True, 'total': len(serv['itens'])}

        if operacao in ('mover', 'mover_item', 'subir', 'descer'):
            direcao = str(dados.get('direcao') or operacao).strip().lower()
            idx = next((i for i, x in enumerate(itens)
                        if str(x.get('id') or '') == str(item_id)), None)
            if idx is None:
                return {'ok': False, 'erro': 'Item não encontrado.'}
            movido = idx
            if direcao in ('subir', 'cima', 'up') and idx > 0:
                itens[idx - 1], itens[idx] = itens[idx], itens[idx - 1]
                movido = idx - 1
            elif direcao in ('descer', 'baixo', 'down') and idx < len(itens) - 1:
                itens[idx], itens[idx + 1] = itens[idx + 1], itens[idx]
                movido = idx + 1
            if not _salvar_servicos_json(todos):
                return {'ok': False,
                        'erro': 'Não foi possível salvar em servicos.json.'}
            return {'ok': True, 'total': len(itens), 'indice': movido}

        return {'ok': False, 'erro': f'Operação inválida: "{operacao}".'}

    def _remoto_medidor(self, dados: dict) -> dict:
        """Cronômetro/contagem: iniciar, parar, continuar, encerrar."""
        qual = str(dados.get('qual') or 'cronometro').strip().lower()
        acao = str(dados.get('acao') or '').strip().lower()
        if qual == 'cronometro':
            label = self._crono.get('label')
            if acao in ('iniciar', 'inicia'):
                self.cronometro_iniciar(label)
            elif acao in ('parar', 'pausar'):
                self.cronometro_parar()
            elif acao in ('continuar', 'retomar'):
                self.cronometro_continuar()
            elif acao in ('encerrar', 'zerar'):
                self.cronometro_encerrar()
            elif acao == 'projetar':
                self.cronometro_projetar(label)
            else:
                return {'ok': False,
                        'erro': f'Ação de cronômetro inválida: {acao}'}
        else:  # contagem regressiva
            label = self._contagem.get('label')
            if acao in ('iniciar', 'inicia'):
                seg = int(dados.get('seg') or 0)
                if seg <= 0:
                    return {'ok': False,
                            'erro': 'Informe o tempo da contagem (segundos).'}
                self.contagem_iniciar(seg, str(dados.get('titulo') or ''),
                                      label)
            elif acao in ('parar', 'pausar'):
                self.contagem_parar()
            elif acao in ('continuar', 'retomar'):
                self.contagem_continuar()
            elif acao in ('encerrar', 'zerar'):
                self.contagem_encerrar()
            elif acao == 'projetar':
                g = self._contagem
                total = max(0, int(g.get('total') or 0))
                tempo = (f"{total // 60:02d}:{total % 60:02d}"
                         if total < 3600 else
                         f"{total // 3600:02d}:{(total % 3600) // 60:02d}"
                         f":{total % 60:02d}")
                self.contagem_projetar(g.get('titulo') or '', tempo, label)
            else:
                return {'ok': False,
                        'erro': f'Ação de contagem inválida: {acao}'}
        return {'ok': True, 'medidor': self._remoto_medidor_estado()}

    def salvar_config_projecao(self, cfg: dict) -> None:
        """Persiste a configuração de aparência da projeção e aplica ao telão."""
        self.config_data["projecao"] = cfg
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config_data, f, indent=2)
        except Exception as e:
            log.exception(f"Erro ao salvar config de projeção: {e}")
        if self.player and self.player.telao:
            self.player.telao.configurar_projecao(cfg)

    def abrir_config_projecao_dialogo(self, parent=None,
                                      mostrar_cor_ref: bool = False) -> None:
        """Abre a janela de ajuste da aparência da projeção no telão.

        Compartilhada entre as janelas de Anúncios, Hinos e de Bíblia.
        A opção "Cor da referência bíblica" só faz sentido onde há Bíblia
        para projetar, por isso aparece somente com mostrar_cor_ref=True.
        """
        janela = parent or self.root
        cfg_atual = dict(getattr(self.player.telao, "_proj_cfg", {}))
        cfg_atual.setdefault("fonte", "Montserrat")
        cfg_atual.setdefault("tamanho_pct", 5.0)
        cfg_atual.setdefault("cor", "#FFFFFF")
        cfg_atual.setdefault("duracao_seg", 30)
        cfg_atual.setdefault("cor_ref", "#A0A0A0")
        cfg_atual.setdefault("cor_fundo", "#000000")
        cfg_atual.setdefault("fundo_opaco", True)
        cfg_atual.setdefault("fundo_imagem", "")

        cfg_win = tk.Toplevel(janela)
        cfg_win.title("🎨 Aparência da Projeção (Telão)")
        cfg_win.geometry("620x760")
        cfg_win.configure(bg='#0d1117')
        cfg_win.transient(janela)
        _centralizar_sobre(cfg_win, janela)
        cfg_win.after(50, cfg_win.grab_set)

        c_main = tk.Frame(cfg_win, bg='#0d1117')
        c_main.pack(fill='both', expand=True, padx=15, pady=15)

        tk.Label(c_main, text="🎨 Configuração da Projeção",
                 font=("Arial", 15, "bold"), fg='#f0c040', bg='#0d1117'
                 ).pack(pady=(0, 12))

        # ── Fonte ──
        tk.Label(c_main, text="Fonte:", font=("Arial", 11, "bold"),
                 fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x')
        var_fonte = tk.StringVar(value=str(cfg_atual["fonte"]))
        combo_fonte = ttk.Combobox(
            c_main, textvariable=var_fonte, state="readonly",
            values=["Montserrat", "Roboto", "Digital-7"],
            font=("Arial", 11))
        combo_fonte.pack(fill='x', pady=(0, 10), ipady=2)

        # ── Tamanho do texto ──
        tk.Label(c_main, text="Tamanho do texto (relativo à altura da tela):",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117', anchor='w'
                 ).pack(fill='x')
        var_tamanho = tk.DoubleVar(value=float(cfg_atual["tamanho_pct"]))
        scale_tamanho = tk.Scale(
            c_main, from_=1.0, to=15.0, resolution=0.2, orient="horizontal",
            variable=var_tamanho, bg='#0d1117', fg='#c9d1d9',
            troughcolor='#21262d', highlightthickness=0, font=("Arial", 10))
        scale_tamanho.pack(fill='x', pady=(0, 10))

        # ── Cor do texto ──
        tk.Label(c_main, text="Cor do texto:", font=("Arial", 11, "bold"),
                 fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x')
        lista_cores = [
            ("Branco", "#FFFFFF"), ("Amarelo", "#F5BE08"),
            ("Vermelho", "#FF5555"), ("Azul", "#58A6FF"),
            ("Verde", "#3FB950"), ("Roxo", "#D2A8FF"),
            ("Ciano", "#00E5FF"), ("Laranja", "#FF9800")]
        var_cor = tk.StringVar(value=str(cfg_atual["cor"]))
        cor_frame = tk.Frame(c_main, bg='#0d1117')
        cor_frame.pack(fill='x', pady=(0, 10))
        for nome, codigo in lista_cores:
            rb = tk.Radiobutton(
                cor_frame, text=nome, value=codigo, variable=var_cor,
                bg='#0d1117', fg='#c9d1d9', selectcolor='#0d1117',
                activebackground='#0d1117', activeforeground='#f0c040',
                font=("Arial", 10))
            rb.pack(side='left', padx=2)

        if mostrar_cor_ref:
            # ── Cor da referência bíblica (livro cap:vers. — canto inferior direito) ──
            tk.Label(c_main, text="Cor da referência bíblica (livro cap:vers.):",
                     font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117', anchor='w'
                     ).pack(fill='x')
            var_cor_ref = tk.StringVar(value=str(cfg_atual["cor_ref"]))
            cor_ref_frame = tk.Frame(c_main, bg='#0d1117')
            cor_ref_frame.pack(fill='x', pady=(0, 10))
            for nome, codigo in lista_cores:
                rb = tk.Radiobutton(
                    cor_ref_frame, text=nome, value=codigo, variable=var_cor_ref,
                    bg='#0d1117', fg='#c9d1d9', selectcolor='#0d1117',
                    activebackground='#0d1117', activeforeground='#f0c040',
                    font=("Arial", 10))
                rb.pack(side='left', padx=2)

        # ── Cor de fundo ──
        tk.Label(c_main, text="Cor de fundo:", font=("Arial", 11, "bold"),
                 fg='#f0c040', bg='#0d1117', anchor='w').pack(fill='x')
        var_cor_fundo = tk.StringVar(value=str(cfg_atual["cor_fundo"]))
        cor_fundo_frame = tk.Frame(c_main, bg='#0d1117')
        cor_fundo_frame.pack(fill='x', pady=(0, 8))
        cores_fundo = [
            ("Preto", "#000000"), ("Cinza escuro", "#1a1a2e"),
            ("Azul escuro", "#0d1b2a"), ("Verde escuro", "#0a1f0a"),
            ("Vinho", "#2d0a0a")]
        for nome, codigo in cores_fundo:
            tk.Radiobutton(
                cor_fundo_frame, text=nome, value=codigo, variable=var_cor_fundo,
                bg='#0d1117', fg='#c9d1d9', selectcolor='#0d1117',
                activebackground='#0d1117', activeforeground='#f0c040',
                font=("Arial", 10)).pack(side='left', padx=2)

        # ── Fundo opaco (sem transparência) ──
        var_fundo_opaco = tk.BooleanVar(value=bool(cfg_atual["fundo_opaco"]))
        tk.Checkbutton(
            c_main, text="Fundo opaco (sem transparência)", variable=var_fundo_opaco,
            bg='#0d1117', fg='#c9d1d9', selectcolor='#0d1117',
            activebackground='#0d1117', activeforeground='#f0c040',
            font=("Arial", 11, "bold")).pack(anchor='w', pady=(0, 8))

        # ── Imagem de fundo (opcional) ──
        tk.Label(c_main, text="Imagem de fundo (opcional):",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117', anchor='w'
                 ).pack(fill='x')
        linha_imagem = tk.Frame(c_main, bg='#0d1117')
        linha_imagem.pack(fill='x', pady=(0, 12))
        var_fundo_imagem = tk.StringVar(value=str(cfg_atual["fundo_imagem"]))
        entry_imagem = tk.Entry(
            linha_imagem, textvariable=var_fundo_imagem, font=("Arial", 10),
            bg='#21262d', fg='#c9d1d9', insertbackground='#f0c040',
            bd=0, highlightthickness=0)
        entry_imagem.pack(side='left', fill='x', expand=True, ipady=3)

        def _escolher_imagem_fundo():
            # Seletor do próprio app (não o do sistema): só as pastas do
            # usuário, sem as ocultas, e sem piscar ao abrir.
            escolhidos = _escolher_arquivos_usuario(
                cfg_win, "Escolher imagem de fundo",
                sufixos=tuple(sorted(SUFIXOS_IMAGEM)))
            if escolhidos:
                var_fundo_imagem.set(escolhidos[0])

        tk.Button(linha_imagem, text="Procurar…", font=("Arial", 10, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_escolher_imagem_fundo, cursor='hand2', padx=8, pady=2
                  ).pack(side='left', padx=3)
        tk.Button(linha_imagem, text="✖ Limpar", font=("Arial", 10, "bold"),
                  bg='#da3633', fg='white', activebackground='#f85149',
                  command=lambda: var_fundo_imagem.set(""), cursor='hand2',
                  padx=8, pady=2).pack(side='left')

        # ── Duração antes de voltar ao relógio ──
        tk.Label(c_main, text="Duração antes de voltar ao relógio (segundos):",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117', anchor='w'
                 ).pack(fill='x')
        var_duracao = tk.IntVar(value=int(cfg_atual["duracao_seg"]))
        entry_duracao = tk.Entry(c_main, textvariable=var_duracao,
                                 font=("Arial", 11), bg='#21262d', fg='#c9d1d9',
                                 insertbackground='#f0c040', bd=0, highlightthickness=0)
        entry_duracao.pack(fill='x', pady=(0, 14), ipady=3)

        def _salvar_cfg():
            try:
                duracao = max(1, int(var_duracao.get()))
            except (ValueError, TypeError):
                duracao = 1
            novo = {
                "fonte": var_fonte.get(),
                "tamanho_pct": float(var_tamanho.get()),
                "cor": var_cor.get(),
                "duracao_seg": duracao,
                "cor_fundo": var_cor_fundo.get(),
                "fundo_opaco": bool(var_fundo_opaco.get()),
                "fundo_imagem": var_fundo_imagem.get().strip(),
            }
            if mostrar_cor_ref:
                novo["cor_ref"] = var_cor_ref.get()
            self.salvar_config_projecao(novo)
            cfg_win.destroy()

        tk.Button(c_main, text="💾 Salvar", font=("Arial", 12, "bold"),
                  bg='#238636', fg='white', activebackground='#2ea043',
                  command=_salvar_cfg, cursor='hand2', padx=20, pady=5
                  ).pack(pady=6)

    def salvar_config_relogio(self, cfg: dict) -> None:
        """Persiste a configuração de aparência do relógio e aplica ao telão."""
        self.config_data["relogio"] = cfg
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config_data, f, indent=2)
        except Exception as e:
            log.exception(f"Erro ao salvar config do relógio: {e}")
        if self.player and self.player.telao:
            self.player.telao.configurar_relogio(cfg)

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

        cfg_win = tk.Toplevel(self.root)
        cfg_win.title("⚙️ Configura Relógio / Cronômetro / Contagem")
        cfg_win.geometry("680x980")
        cfg_win.configure(bg='#0d1117')
        cfg_win.transient(self.root)
        _centralizar_sobre(cfg_win, self.root)
        cfg_win.after(50, cfg_win.grab_set)

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
            self.salvar_config_relogio(novo)
            cfg_win.destroy()

        tk.Button(tab_relogio, text="💾 Salvar", font=("Arial", 12, "bold"),
                  bg='#238636', fg='white', activebackground='#2ea043',
                  command=_salvar_cfg_relogio, cursor='hand2', padx=20, pady=5
                  ).pack(pady=(4, 6))

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

    def _temperatura_valida(self, temp: str | None = None) -> bool:
        """Verifica se a string de temperatura é válida para exibição."""
        t = temp if temp is not None else self.temperatura_atual
        return bool(t and "Erro" not in t and "não encontrada" not in t and t != "--")

    def salvar_cidade(self) -> None:
        cidade = self.entry_cidade.get().strip()
        estado = self.entry_estado.get().strip().upper()

        if not cidade or cidade == "Cidade" or not estado or estado == "UF":
            self.status_label.config(text="⚠️ Preencha cidade e UF!")
            return

        self.config_data["cidade"] = cidade
        self.config_data["estado"] = estado
        self.cidade_salva = cidade
        self.estado_salvo = estado

        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config_data, f, indent=2)
        except Exception as e:
            log.exception(f"Erro ao salvar config: {e}")

        self.status_label.config(text=f"✅ Local salvo: {cidade}/{estado}")
        # Carrega temperatura em background
        def _carregar_temp():
            temp = obter_temperatura(self.cidade_salva, self.estado_salvo)
            self.root.after(0, lambda: self._aplicar_temperatura(temp))
        threading.Thread(target=_carregar_temp, daemon=True).start()

    # ── Temperatura ──────────────────────────────────────────────

    def atualizar_temperatura(self) -> None:
        if not self.cidade_salva or not self.estado_salvo:
            return

        # Executa requisição HTTP em thread para NÃO travar a interface
        threading.Thread(target=self._atualizar_temperatura_async, daemon=True).start()

    def _atualizar_temperatura_async(self) -> None:
        """Carrega temperatura em background e atualiza interface via after()."""
        temp = obter_temperatura(self.cidade_salva, self.estado_salvo)
        self.root.after(0, lambda: self._aplicar_temperatura_com_timer(temp))

    def _aplicar_temperatura_com_timer(self, temp: str) -> None:
        """Aplica temperatura na interface e agenda próxima atualização."""
        self.temperatura_atual = temp
        if self._temperatura_valida():
            t = getattr(self.player, "telao", None)
            if t is None:
                try:
                    self.player._garantir_telao()  # type: ignore[attr-defined]
                except Exception:
                    pass
                t = getattr(self.player, "telao", None)
            if t is not None:
                try:
                    t._exibir_hora_inicial(temp)
                except Exception:
                    pass
            self.temp_label.config(
                text=f"🌡️ {self.cidade_salva}: {temp}"
            )
        else:
            self.temp_label.config(text="🌡️ Temperatura indisponível")
            self.temperatura_atual = "--"

        # Cancela timer anterior antes de agendar novo
        if hasattr(self, '_temp_timer') and self._temp_timer:
            self.root.after_cancel(self._temp_timer)
        self._temp_timer = self.root.after(1_800_000, self.atualizar_temperatura)

    # ── Callbacks do player ──────────────────────────────────────

    def quando_faixa_muda(self, indice: int, arquivo: str) -> None:
        self.arquivo_atual = arquivo
        self.atualizar_status()
        # Força redesenho completo da lista para destacar a música atual
        self.atualizar_lista()

    def quando_midia_terminar(self, estado: str) -> None:
        if estado == "ended" and not getattr(self, '_shutting_down', False):
            self._tocar_proxima()

    def _tocar_proxima(self) -> None:
        """Toca a próxima música da playlist. Se não houver, repete ou para."""
        if getattr(self, '_shutting_down', False):
            return
        playlist = self.player.playlist
        if not playlist:
            return
        
        prox_index = self.player.index + 1
        
        # Se ainda há próxima música
        if prox_index < len(playlist):
            self.player.proximo()
            return
        
        # Chegou ao fim da lista
        if self.repetir_var.get():
            # Reproduzir TUDO novamente do início
            self._repetir_playlist()
        else:
            # Parar e fechar SMPlayer
            self.parar()

    def _repetir_playlist(self) -> None:
        """Reproduz toda a playlist novamente do início."""
        if not self.arquivos_encontrados:
            if self.arquivo_atual:
                self.tocar_arquivo(self.arquivo_atual)
            return
        self.player.carregar_playlist(self.arquivos_encontrados)
        self.player.tocar_indice(0)

    # ── Busca (nova implementação com worker e cache) ────────────

    def enter_busca(self, event: object = None) -> None:
        """Enter: toca o primeiro resultado da busca."""
        termo = self.entry_busca.get().strip()
        if not termo or termo == self.placeholder_busca:
            return
        # Cancela timer pendente e faz busca imediata com toque
        if self._debounce_timer:
            self.root.after_cancel(self._debounce_timer)
            self._debounce_timer = None
        self._fazer_busca(termo, tocar_primeiro=True)

    def on_busca_digitada(self, event: object = None) -> None:
        """Debounce: executa a busca 500ms após parar de digitar."""
        # Ignora teclas de navegação e modificadoras que não alteram o texto
        keysym = event.keysym if event else ""
        if keysym in ("Shift_L", "Shift_R", "Control_L", "Control_R",
                      "Alt_L", "Alt_R", "Meta_L", "Meta_R", "Caps_Lock"):
            return

        # Se for tecla Delete, BackSpace, ou qualquer tecla que altere texto,
        # reiniciamos o debounce.
        if self._debounce_timer:
            self.root.after_cancel(self._debounce_timer)
        self._debounce_timer = self.root.after(500, self._executar_busca_debounce)

    def _executar_busca_debounce(self) -> None:
        self._debounce_timer = None
        termo = self.entry_busca.get().strip()
        # Se o termo estiver vazio ou for placeholder, limpar resultados
        if not termo or termo == self.placeholder_busca:
            self.arquivos_encontrados = []
            self.player.carregar_playlist([])
            self.atualizar_lista()
            return
        self._fazer_busca(termo, tocar_primeiro=False)

    def _fazer_busca(self, termo: str, tocar_primeiro: bool = False) -> None:
        """Enfileira uma busca no worker."""
        self._versao_busca += 1
        versao = self._versao_busca

        # Submete ao worker
        self.search_worker.submit(termo, versao, self._on_search_complete)

        # Se tocar_primeiro, faremos após o retorno da busca (no callback)
        self._pending_play = tocar_primeiro

    def _on_search_complete(self, results: list[dict[str, Any]], version: int) -> None:
        """Callback chamado pelo worker na thread principal."""
        if version != self._versao_busca:
            return  # Resultado obsoleto

        # Extrair caminhos dos resultados (vazio rápido)
        caminhos = [rec['caminho_arquivo'] for rec in results] if results else []
        # Ordenar por nome_exibicao (numérico crescente)
        # Usa o nome_exibicao do registro (que já está no results) para ordenar
        # Ordena os registros (cópia para não modificar o cache do DatabaseManager)
        results_ordenados = sorted(results, key=self._chave_ordenacao_busca)
        caminhos = [rec['caminho_arquivo'] for rec in results_ordenados]
        self.arquivos_encontrados = caminhos
        self.player.carregar_playlist(caminhos)

        # Se tocar_primeiro estava pendente e há resultados
        if getattr(self, '_pending_play', False) and caminhos:
            self.tocar_arquivo(caminhos[0])
            self._pending_play = False

        self.atualizar_lista()

    # ── Criação de widgets ─────────────────────────────────────────

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

    def _abrir_email(self, assunto: str) -> None:
        """Abre o cliente de e-mail padrão do sistema apontando para o NavePro.

        Usa um link mailto: para nevestecnologias@gmail.com, com o assunto
        informado. No Linux, tenta primeiro um cliente de e-mail dedicado
        (Thunderbird, Evolution, etc.) para não cair no navegador; se nenhum
        estiver instalado, delega ao manipulador padrão via `xdg-open`.
        Se algo falhar, apenas registra o erro no console.
        """
        destino = "nevestecnologias@gmail.com"
        url = f"mailto:{destino}?subject={urllib.parse.quote(assunto)}"
        try:
            if sys.platform.startswith("win"):
                os.startfile(url)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", url], start_new_session=True)
            else:
                cliente = self._encontrar_cliente_email()
                if cliente:
                    subprocess.Popen([cliente, url], start_new_session=True)
                else:
                    subprocess.Popen(
                        ["xdg-open", url], start_new_session=True,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            log.warning(f"⚠️ Não foi possível abrir o e-mail: {e}")

    @staticmethod
    def _encontrar_cliente_email() -> str | None:
        """Procura no PATH um cliente de e-mail dedicado já instalado."""
        import shutil
        for cliente in ("thunderbird", "evolution", "geary",
                        "claws-mail", "mailspring", "kmail"):
            binario = shutil.which(cliente)
            if binario:
                return binario
        return None

    def _toggle_repetir(self) -> None:
        """Alterna o estado do checkbox Repetir."""
        self.repetir_var.set(not self.repetir_var.get())

    # ── Tema (claro/escuro) ───────────────────────────────────────

    def _alternar_tema(self) -> None:
        """Alterna entre tema escuro (padrão) e claro, persistindo a escolha."""
        novo = 'claro' if self.tema != 'claro' else 'escuro'
        self.tema = novo
        self.config_data['tema'] = novo
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.exception(f"Erro ao salvar tema: {e}")
        if getattr(self, '_var_tema_claro', None) is not None:
            self._var_tema_claro.set(novo == 'claro')
        self._aplicar_tema()

    def _aplicar_tema(self) -> None:
        """Aplica o tema ativo (claro/escuro) a toda a interface."""
        self._aplicar_tema_ttk()
        self._aplicar_tema_menu()
        try:
            self._recolorir_arvore(self.root)
        except tk.TclError:
            pass

    def _aplicar_tema_ttk(self) -> None:
        """Ajusta os estilos globais ttk (Treeview/Scrollbar) ao tema."""
        try:
            style = ttk.Style()
            if self.tema == 'claro':
                style.configure(
                    "Treeview",
                    background="#8b949e", foreground="#1f2328",
                    fieldbackground="#8b949e", font=("Arial", 10))
                style.configure(
                    "Treeview.Heading",
                    background="#6e7681", foreground="#ffffff",
                    font=("Arial", 10, "bold"))
                style.map('Treeview',
                          background=[('selected', '#0969da')],
                          foreground=[('selected', '#ffffff')])
                style.configure(
                    "Vertical.TScrollbar",
                    background="#8b949e", troughcolor="#6e7681",
                    arrowcolor="#1f2328")
            else:
                style.configure(
                    "Treeview",
                    background="#21262d", foreground="#c9d1d9",
                    fieldbackground="#21262d", font=("Arial", 10))
                style.configure(
                    "Treeview.Heading",
                    background="#161b22", foreground="#f0c040",
                    font=("Arial", 10, "bold"))
                style.map('Treeview',
                          background=[('selected', '#6e40c9')],
                          foreground=[('selected', '#ffffff')])
                style.configure(
                    "Vertical.TScrollbar",
                    background="#21262d", troughcolor="#161b22",
                    arrowcolor="#f0c040")
        except (Exception, tk.TclError):
            pass

    def _aplicar_tema_menu(self) -> None:
        """Recolore a barra de menu e os menus suspensos."""
        menus = getattr(self, '_menus', [])
        if not menus:
            return
        if self.tema == 'claro':
            menubar_cfg = dict(bg='#f6f8fa', fg='#24292f',
                               activebackground='#eaeef2',
                               activeforeground='#24292f')
            menu_cfg = dict(bg='#ffffff', fg='#1f2328',
                            activebackground='#eaeef2',
                            activeforeground='#24292f')
        else:
            menubar_cfg = dict(bg='#161b22', fg='#f0c040',
                               activebackground='#6e40c9',
                               activeforeground='#f0c040')
            menu_cfg = dict(bg='#21262d', fg='#c9d1d9',
                            activebackground='#6e40c9',
                            activeforeground='#f0c040')
        for i, menu in enumerate(menus):
            try:
                menu.configure(**(menubar_cfg if i == 0 else menu_cfg))
            except (Exception, tk.TclError):
                pass

    def _recolorir_arvore(self, base) -> None:
        """Aplica a recoloração de tema a `base` e a todos os seus filhos."""
        self._aplicar_tema_widget(base)
        try:
            for filho in base.winfo_children():
                self._recolorir_arvore(filho)
        except tk.TclError:
            pass

    def _varrer_toplevels_tema(self) -> None:
        """Recoloriza janelas auxiliares (Toplevel) criadas após o app.

        Chamado periodicamente (junto do loop do telão). Cada janela
        recria estilos escuros ao ser aberta; aqui garantimos que o tema
        ativo seja sempre respeitado sem tocar no código de criação.
        """
        try:
            self._aplicar_tema_ttk()
            if self.tema != 'claro':
                return
            self._recolorir_arvore(self.root)
            for filho in self.root.winfo_children():
                try:
                    if filho.winfo_class() == 'Toplevel':
                        self._recolorir_arvore(filho)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass

    def _aplicar_tema_widget(self, widget) -> None:
        """Ajusta as cores de um único widget conforme o tema ativo.

        No tema ESCURO restaura as cores escura originais (gravadas na
        primeira visita em claro). No CLARO registra as cores atuais como
        origem e aplica a equivalência clara. Pergunta valores sobrescritos
        dinamicamente (ex.: linha tocando na lista) como nova origem, para
        a troca de tema nunca perder o estado visual.
        """
        try:
            if not widget.winfo_exists():
                return
            # Faixas que delimitam as seções do painel: cor própria por tema
            # (carvão no claro; igual ao cartão no escuro, isto é, invisível).
            if getattr(widget, '_navepro_faixa_secao', False):
                try:
                    widget.configure(
                        bg='#30363d' if self.tema == 'claro' else '#161b22'
                    )
                except tk.TclError:
                    pass
                return
            # Área de controles do operador: bloco cinza só no tema claro.
            if getattr(widget, '_navepro_area_cinza_clara', False):
                escuro = getattr(widget, '_navepro_area_cinza_escuro', '#161b22')
                try:
                    widget.configure(
                        bg='#8b949e' if self.tema == 'claro' else escuro
                    )
                except tk.TclError:
                    pass
                return
            if isinstance(widget, ttk.Widget):
                return
            # Menus têm tratamento próprio (_aplicar_tema_menu); recolorir
            # aqui brigaria com ele e restauraria a cor errada ao voltar.
            if str(widget.winfo_class()) == 'Menu':
                return
            keys = set(widget.keys())
        except tk.TclError:
            return

        ops = [o for o in _OPCOES_COR_TK if o in keys]

        def _ler(op):
            try:
                valor = widget.cget(op)
            except tk.TclError:
                return None
            # Alguns widgets (ex.: tk.Menu) devolvem Tcl_Obj em vez de str;
            # sem normalizar, _cor_clara quebra com AttributeError.
            if valor is None or isinstance(valor, str):
                return valor
            return str(valor)

        origem = getattr(widget, '_navepro_tema_origem', None)
        aplicado = getattr(widget, '_navepro_tema_aplicado', None)

        if self.tema == 'escuro':
            if not origem:
                return
            cfg = {}
            for o in ops:
                v = origem.get(o)
                if v:
                    cfg[o] = v
            try:
                widget.configure(**cfg)
            except Exception:
                for o, v in cfg.items():
                    try:
                        widget.configure(**{o: v})
                    except Exception:
                        pass
            try:
                widget._navepro_tema_origem = None
                widget._navepro_tema_aplicado = None
            except Exception:
                pass
            return

        # ── Tema CLARO ──
        if origem is None:
            origem = {}
        if aplicado is None:
            aplicado = {}

        # Passo 1: mapeia as opções que funcionam como FUNDO e guarda o
        # resultado para decidir as cores de texto em passo 2.
        bg_final = None
        base: dict[str, str] = {}
        cfg: dict[str, str] = {}
        for o in ops:
            atual = _ler(o)
            if atual is None:
                continue
            if o in ('background', 'activebackground', 'selectbackground',
                     'troughcolor'):
                clara = _cor_clara(atual)
                if o == 'background':
                    bg_final = clara
                if aplicado.get(o) != atual:
                    origem[o] = atual
                base[o] = clara
                aplicado[o] = clara
                cfg[o] = clara

        # Passo 2: opções de TEXTO decididas com o fundo correspondente.
        def _fundo_para(op: str) -> str | None:
            if op == 'activeforeground':
                return base.get('activebackground', bg_final)
            if op == 'selectforeground':
                return base.get('selectbackground', bg_final)
            return bg_final

        for o in ops:
            if o in ('background', 'activebackground', 'selectbackground',
                     'troughcolor'):
                continue
            atual = _ler(o)
            if atual is None:
                continue
            if aplicado.get(o) != atual:
                origem[o] = atual
            escura = origem.get(o)
            if not escura:
                continue
            if o in _OPCOES_TEXTO:
                clara = _cor_clara(escura, _fundo_para(o))
            else:
                clara = _cor_clara(escura)
            aplicado[o] = clara
            cfg[o] = clara

        try:
            widget.configure(**cfg)
        except Exception:
            for o, v in cfg.items():
                try:
                    widget.configure(**{o: v})
                except Exception:
                    pass

        try:
            widget._navepro_tema_origem = origem
            widget._navepro_tema_aplicado = aplicado
        except Exception:
            pass

    def _mostrar_sobre(self) -> None:
        """Exibe a janela Sobre com informações do programa."""
        tkinter.messagebox.showinfo(
            "Sobre o NavePro",
            "NavePro - Sistema de Projeção Profissional\n"
            f"Versão: {APP_VERSION}\n"
            "Licença: GPLv3\n"
            "Autor: José Edes Neves - Julho 2026\n"
            "nevestecnologias@gmail.com\n\n"
            "Aplicação para reprodução de mídia com projeção em\n"
            "telão, busca inteligente no banco de dados, pastas\n"
            "do computador e informações climáticas.",
            parent=self.root
        )

    # ── Atualização automática (GitHub Releases) ──

    def verificar_atualizacao(self, manual: bool = False) -> None:
        """Verifica (em thread) se há versão nova no GitHub e notifica."""
        def _worker() -> None:
            release = _buscar_release_latest()
            if release is None:
                if manual:
                    self.root.after(0, lambda: tkinter.messagebox.showinfo(
                        "Atualizações",
                        "Não foi possível consultar o GitHub agora.\n"
                        "Verifique sua conexão e tente novamente.",
                        parent=self.root))
                return
            versao = str(release.get('tag_name', '')).lstrip('vV')
            if not _versao_nova(versao):
                if manual:
                    self.root.after(0, lambda: tkinter.messagebox.showinfo(
                        "Atualizações",
                        f"Você já está na versão mais recente "
                        f"({APP_VERSION}).",
                        parent=self.root))
                return
            self.root.after(0, lambda: self._oferecer_atualizacao(release))

        threading.Thread(target=_worker, daemon=True).start()

    def _oferecer_atualizacao(self, release: dict) -> None:
        """Pergunta se o usuário quer atualizar e leva ao caminho certo.

        Flatpak não baixa arquivo: a atualização é `flatpak update`. AppImage
        e Windows continuam baixando o instalador para ~/Downloads.
        """
        versao = str(release.get('tag_name', '')).lstrip('vV')
        corpo = str(release.get('body') or '').strip()
        if len(corpo) > 400:
            corpo = corpo[:400].rstrip() + '…'
        formato = _formato_instalado()
        rotulo = _rotulo_instalador(formato)
        pergunta = (
            f"NavePro {APP_VERSION} → {versao}\n\n"
            "Uma nova versão está disponível no GitHub.\n"
        )
        if corpo:
            pergunta += f"\nNovidades:\n{corpo}\n"
        if formato == FORMATO_FLATPAK:
            pergunta += (
                "\nO NavePro está instalado como Flatpak, então a "
                "atualização será feita\npelo próprio Flatpak "
                "(sem baixar arquivo).\n\n"
                "Deseja atualizar agora?"
            )
        else:
            pergunta += f"\nDeseja baixar o novo {rotulo} agora?"
        if not tkinter.messagebox.askyesno(
                "🔄 Atualização disponível", pergunta, parent=self.root):
            return
        if formato == FORMATO_FLATPAK:
            self._atualizar_como_flatpak(versao)
            return
        asset = _procurar_asset_instalador(release)
        if asset is None:
            tkinter.messagebox.showwarning(
                "Atualização",
                f"O release não contém um arquivo {rotulo}.",
                parent=self.root)
            return
        self._baixar_atualizacao(
            versao,
            str(asset.get('browser_download_url', '')),
            str(asset.get('name', f'NavePro-{versao}{rotulo}')),
        )

    def _atualizar_como_flatpak(self, versao: str) -> None:
        """Roda `flatpak update` no host e mostra o resultado."""
        comando = _comando_atualizacao_flatpak()
        texto_cmd = ' '.join(comando[2:])

        janela = tk.Toplevel(self.root)
        janela.title("⬇️ Atualizando via Flatpak")
        janela.geometry("560x300")
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        _centralizar_sobre(janela, self.root)
        janela.grab_set()

        saida = tk.Text(janela, height=9, font=("monospace", 9),
                        bg='#161b22', fg='#c9d1d9', bd=0,
                        highlightthickness=0, wrap='word')
        saida.pack(fill='both', expand=True, padx=10, pady=10)
        saida.insert('end', f"$ {texto_cmd}\n\n")
        saida.configure(state='disabled')

        def _escrever(linha: str) -> None:
            saida.configure(state='normal')
            saida.insert('end', linha)
            saida.see('end')
            saida.configure(state='disabled')

        def _worker() -> None:
            codigo = -1
            try:
                proc = subprocess.run(
                    comando, capture_output=True, text=True,
                    stdin=subprocess.DEVNULL, timeout=600,
                    env=_ambiente_sem_appimage(), cwd='/',
                )
                codigo = proc.returncode
                linhas = [linha for linha in
                          ((proc.stdout or '') + (proc.stderr or '')).splitlines()
                          if linha.strip()]
                if not linhas:
                    linhas = ["(sem saída)"]
                for linha in linhas:
                    self.root.after(0, lambda linha=linha: _escrever(linha + "\n"))
            except Exception as e:
                codigo = -1
                self.root.after(
                    0, lambda e=e: _escrever(f"Falha ao executar: {e}\n"))
            finally:
                self.root.after(0, lambda: _finalizar(codigo))

        def _finalizar(codigo: int) -> None:
            janela.grab_release()
            janela.destroy()
            if codigo == 0:
                tkinter.messagebox.showinfo(
                    "✅ Atualização concluída",
                    f"O NavePro foi atualizado para a versão {versao}.\n\n"
                    "Feche e abra o NavePro para usar a versão nova.",
                    parent=self.root)
            else:
                tkinter.messagebox.showerror(
                    "Não foi possível atualizar",
                    "O comando do Flatpak falhou.\n\n"
                    "Rode no terminal:\n\n"
                    f"  {texto_cmd}\n\n"
                    "Se pedir senha de administrador, o NavePro está "
                    "instalado no sistema (não no seu usuário) e a "
                    "atualização precisa ser feita por um administrador.",
                    parent=self.root)

        tk.Button(janela, text="Fechar", font=("Arial", 11, "bold"),
                  bg='#21262d', fg='#c9d1d9', activebackground='#30363d',
                  command=lambda: (janela.grab_release(), janela.destroy()),
                  cursor='hand2').pack(pady=(0, 10))

        threading.Thread(target=_worker, daemon=True).start()

    def _baixar_atualizacao(self, versao: str, url: str,
                            nome_arquivo: str) -> None:
        """Baixa o novo instalador para ~/Downloads com barra de progresso."""
        destino = os.path.join(_pasta_downloads(), nome_arquivo)

        janela = tk.Toplevel(self.root)
        janela.title("⬇️ Baixando atualização")
        janela.geometry("440x150")
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        _centralizar_sobre(janela, self.root)
        janela.grab_set()

        def _atualizar_progresso(pct: int, baixado: int, total: int) -> None:
            try:
                progresso['value'] = pct
                lbl.config(
                    text=f"{pct}%  ({baixado // 1024 // 1024} de "
                         f"{total // 1024 // 1024} MB)"
                )
            except tk.TclError:
                pass

        tk.Label(janela, text=f"Baixando {nome_arquivo}…",
                 font=("Arial", 11, "bold"), fg='#f0c040', bg='#0d1117'
                 ).pack(pady=(18, 6))
        progresso = ttk.Progressbar(janela, mode='determinate', length=380)
        progresso.pack(pady=6)
        lbl = tk.Label(janela, text="0%", font=("Arial", 9), fg='#c9d1d9',
                       bg='#0d1117')
        lbl.pack(pady=2)

        def _worker() -> None:
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": f"NavePro/{APP_VERSION}"})
                with urllib.request.urlopen(req, timeout=120,
                                            context=_ssl_context()) as resp:
                    total = int(resp.headers.get('Content-Length', 0) or 0)
                    temporario = destino + '.part'
                    baixado = 0
                    with open(temporario, 'wb') as f:
                        while True:
                            bloco = resp.read(8192)
                            if not bloco:
                                break
                            f.write(bloco)
                            baixado += len(bloco)
                            if total > 0:
                                pct = int(baixado * 100 / total)
                                self.root.after(
                                    0, lambda p=pct, b=baixado, t=total:
                                    _atualizar_progresso(p, b, t))
                    os.replace(temporario, destino)
                    if not _eh_windows():
                        os.chmod(destino, 0o744)
                    self.root.after(0, lambda: self._instrucoes_troca_instalador(
                        destino))
            except Exception as e:
                log.exception(f"⚠️  Erro ao baixar atualização: {e}")
                self.root.after(0, lambda e=e: (janela.destroy(),
                             tkinter.messagebox.showerror(
                                 "Erro",
                                 f"Não foi possível baixar a atualização:\n{e}",
                                 parent=self.root)))
            else:
                janela.after(300, janela.destroy)

        threading.Thread(target=_worker, daemon=True).start()

    def _instrucoes_troca_instalador(self, destino: str) -> None:
        """Mostra como substituir o instalador antigo pelo baixado e abre Downloads."""
        rotulo = _rotulo_instalador()
        if rotulo == ".exe":
            msg = (
                "O novo executável foi salvo em:\n\n"
                f"  {destino}\n\n"
                "Para instalar:\n"
                "1. Feche o NavePro.\n"
                "2. Substitua o arquivo atual por este novo "
                "(mova-o para o mesmo lugar do antigo).\n"
                "3. Abra o novo arquivo para rodar a versão atualizada.\n\n"
                "Dica: o NavePro é portátil — basta copiar o .exe novo."
            )
        else:
            msg = (
                "O novo AppImage foi salvo em:\n\n"
                f"  {destino}\n\n"
                "Para instalar:\n"
                "1. Feche o NavePro.\n"
                "2. Substitua o AppImage atual por este novo arquivo "
                "(mova-o para o mesmo lugar do antigo).\n"
                "3. Dê permissão de execução se precisar:\n"
                "     chmod +x \"<novo arquivo>\"\n"
                "4. Abra o novo arquivo para rodar a versão atualizada."
            )
            if not _eh_appimage():
                msg += (
                    "\n\nObs.: você está rodando o NavePro a partir do "
                    "código-fonte,\n então o AppImage baixado é só uma "
                    "cópia para usar\n à vontade — não substitui nada."
                )
        tkinter.messagebox.showinfo("✅ Download concluído", msg,
                                    parent=self.root)
        try:
            if _eh_windows():
                os.startfile(_pasta_downloads())
            else:
                subprocess.Popen(['xdg-open', _pasta_downloads()],
                                 stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def _alternar_maximizar(self) -> None:
        """Alterna entre maximizado (tela cheia) e minimizado (900x800 centralizado)."""
        if self._maximizado:
            # Minimizar para 900x800 centralizado
            self.root.state('normal')
            if hasattr(self, '_monitor_geo') and self._monitor_geo:
                mw, mh, mx, my = self._monitor_geo
                w, h = 900, 800
                x = mx + (mw - w) // 2
                y = my + (mh - h) // 2
                self.root.geometry(f"{w}x{h}+{x}+{y}")
            else:
                self.root.geometry("900x800+200+100")
            self._maximizado = False
        else:
            # Maximizar para ocupar todo o monitor (respeitando barra de tarefas)
            try:
                self.root.state('zoomed')
            except Exception:
                if hasattr(self, '_monitor_geo') and self._monitor_geo:
                    mw, mh, mx, my = self._monitor_geo
                    self.root.geometry(f"{mw}x{mh}+{mx}+{my}")
            self._maximizado = True

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

        # Botões de controle em estilo "pill" (ícones grandes, sem texto)
        pill_frame = tk.Frame(controls_frame, bg='#21262d', highlightthickness=0)
        pill_frame.pack(side='left', padx=5)
        _marcar_area_cinza_clara(pill_frame)

        def _criar_botao_pill(parent, icone, tooltip, comando, icone_png=None):
            """Botão-pílula: usa o PNG `icone_png` (ícone fixo) quando existe;
            senão cai para o caractere `icone` (emoji/texto do sistema)."""
            args = dict(
                bg='#21262d', fg='#f0c040', activebackground='#6e40c9',
                activeforeground='#f0c040',
                command=comando, cursor='hand2',
                bd=0, highlightthickness=0,
                padx=14, pady=6
            )
            imagem = _carregar_icone(icone_png) if icone_png else None
            if imagem is not None:
                # Botão com ícone PNG (não depende de fontes do sistema)
                args.update(text="", image=imagem, width=40, height=40,
                            compound="center")
                btn = tk.Button(parent, **args)
                btn._navepro_imagem = imagem  # mantém ref para não sumir
            else:
                args.update(text=icone, font=("Arial", 18))
                btn = tk.Button(parent, **args)
            btn.pack(side='left', padx=0)
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

        _criar_botao_pill(pill_frame, "⏮", "Anterior", self.tocar_anterior)
        _criar_botao_pill(pill_frame, "⏯", "Play / Pause", self.player.play_pause)
        _criar_botao_pill(pill_frame, "⏹", "Parar", self.parar)
        _criar_botao_pill(pill_frame, "⏭", "Próximo", self.tocar_proximo)

        # Espaçador flexível
        _espacador = tk.Frame(controls_frame, bg='#161b22')
        _marcar_area_cinza_clara(_espacador, '#161b22')
        _espacador.pack(side='left', fill='x', expand=True)

        # Botão Sorteio (canto inferior direito, mesmo estilo pílula dos demais)
        sorteio_frame = tk.Frame(controls_frame, bg='#21262d', highlightthickness=0)
        sorteio_frame.pack(side='right', padx=5)
        _marcar_area_cinza_clara(sorteio_frame)
        _criar_botao_pill(sorteio_frame, "🎲", "Sorteio Profissional", self.abrir_sorteio)

        # Botões dos novos módulos (frame separado à direita)
        modulos_frame = tk.Frame(controls_frame, bg='#21262d', highlightthickness=0)
        modulos_frame.pack(side='right', padx=5)
        _marcar_area_cinza_clara(modulos_frame)
        _criar_botao_pill(modulos_frame, "📖", "Hinos / Letras", self.janela_hinos)
        _criar_botao_pill(modulos_frame, "✝️", "Bíblia", self.janela_biblia)
        _criar_botao_pill(modulos_frame, "📋", "Ordem de Serviço", self.janela_ordem_servico)
        _criar_botao_pill(modulos_frame, "📢", "Anúncios", self.janela_anuncios)

        # Botão Gerenciar Banco (também em estilo pill)
        args_gerenciar = dict(
            bg='#21262d', fg='#f0c040', activebackground='#6e40c9',
            command=self.abrir_gerenciador, cursor='hand2',
            bd=0, highlightthickness=0,
            padx=14, pady=6
        )
        args_gerenciar.update(text="📦", font=("Arial", 16))
        btn_gerenciar = tk.Button(controls_frame, **args_gerenciar)
        btn_gerenciar.pack(side='right', padx=5)
        _marcar_area_cinza_clara(btn_gerenciar)
        _criar_tooltip(btn_gerenciar, "Gerenciar Banco")

        # Botão Configurações (barra de controles)
        btn_config_relogio = tk.Button(
            controls_frame, text="⚙️", font=("Arial", 16),
            bg='#21262d', fg='#f0c040', activebackground='#6e40c9',
            command=self.abrir_config_relogio_dialogo, cursor='hand2',
            bd=0, highlightthickness=0, padx=14, pady=6
        )
        btn_config_relogio.pack(side='right', padx=5)
        _marcar_area_cinza_clara(btn_config_relogio)
        _criar_tooltip(btn_config_relogio, "Configurações")
        _criar_faixa_secao(controls_frame, topo=False)

    # ── Lista de resultados (com cache para evitar redesenho e centralização) ────

    def _iniciar_pulse(self) -> None:
        """Inicia animação do ícone ▶ no item tocando (pisca suave)."""
        if not hasattr(self, '_pool_botoes'):
            return
        self._parar_pulse()
        self._pulse_state = 0
        self._animar_pulse()

    def _parar_pulse(self) -> None:
        """Para a animação do ícone pulsante."""
        if self._pulse_timer:
            try:
                self.root.after_cancel(self._pulse_timer)
            except (tk.TclError, ValueError):
                pass
            self._pulse_timer = None

    def _animar_pulse(self) -> None:
        """Anima o ícone ▶ alternando entre ▶ e ▷, e atualiza barra de progresso."""
        if not self.arquivo_atual or not self.player or not self.player.is_playing:
            return
        if not hasattr(self, '_pool_botoes'):
            return

        dados = self.arquivos_encontrados
        if not dados or self.arquivo_atual not in dados:
            return

        idx = dados.index(self.arquivo_atual)
        if idx >= 80:
            self._pulse_timer = self.root.after(1000, self._animar_pulse)
            return

        # Alterna entre ▶ e ▷
        self._pulse_state = 1 - self._pulse_state
        btn = self._pool_botoes[idx]
        current_text = btn.cget('text')

        if current_text.startswith('▶') or current_text.startswith('▷'):
            novo_prefixo = '▶' if self._pulse_state == 0 else '▷'
            novo_texto = novo_prefixo + current_text[1:]
            btn.config(text=novo_texto)

        # Atualiza barra de progresso (preenche proporcionalmente toda a largura)
        progress_frame, progress_bar = self._pool_progress_bars[idx]
        duracao = self.player.duracao_total
        if duracao and duracao > 0:
            elapsed = self.player.obter_tempo_decorrido()
            frac = min(elapsed / duracao, 1.0)
            progress_bar.place(relwidth=frac, relheight=1.0)

        self._pulse_timer = self.root.after(800, self._animar_pulse)

    def _criar_pool_botoes(self) -> None:
        """Cria o pool de itens recicláveis (cabeçalho + 80 linhas)."""
        self._pool_botoes = []
        self._pool_frames = []
        self._pool_progress_bars = []
        self._pool_label_count = tk.Label(
            self.scroll_frame, text="", fg='#8b949e', bg='#161b22', font=("Arial", 11)
        )
        self._pool_label_count.pack(pady=5, anchor='center')
        for i in range(80):  # Cria 80 linhas
            # Frame container (cor alternada)
            item_frame = tk.Frame(self.scroll_frame, bg='#1c2128' if i % 2 == 0 else '#21262d')
            item_frame.pack(fill='x', padx=100, pady=1)

            # Barra de progresso (inicialmente oculta) - usa place para largura relativa
            progress_frame = tk.Frame(item_frame, bg='#161b22', height=3)
            progress_bar = tk.Frame(progress_frame, bg='#6e40c9', height=3)
            progress_frame.pack_forget()  # Oculta inicialmente

            # Botão principal
            btn = tk.Button(
                item_frame,
                text="", anchor='center',
                font=("Arial", 11),
                bg='#1c2128' if i % 2 == 0 else '#21262d',
                fg='#c9d1d9',
                activebackground='#6e40c9',
                cursor='hand2', bd=0, highlightthickness=0
            )
            btn.pack(fill='x', side='top')

            self._pool_botoes.append(btn)
            self._pool_frames.append(item_frame)
            self._pool_progress_bars.append((progress_frame, progress_bar))

        # Label de vazio (inicialmente oculto)
        self._pool_label_vazio = tk.Label(
            self.scroll_frame, text="🔍 Nenhum arquivo encontrado",
            fg='#8b949e', bg='#161b22', font=("Arial", 12)
        )
        # Guarda referência do caminho atual para cada botão
        self._pool_caminhos: list[str | None] = [None] * 80
        # Timer para animação do ícone pulsante
        self._pulse_timer: str | None = None
        self._pulse_index: int = -1
        self._pulse_state: int = 0
        # Timer que segura um aviso no rodapé (ver mostrar_aviso)
        self._aviso_timer: str | None = None

    def atualizar_lista(self) -> None:
        """Atualiza a lista reciclando itens do pool (cores alternadas, barra de progresso)."""
        if not hasattr(self, '_pool_botoes'):
            self._criar_pool_botoes()

        # Esconde label vazio, mostra contagem
        self._pool_label_vazio.pack_forget()
        dados = self.arquivos_encontrados
        total = len(dados)

        if not dados:
            self._pool_label_count.config(text="")
            self._pool_label_vazio.pack(pady=20, anchor='center')
            for frame in self._pool_frames:
                frame.pack_forget()
            return

        self._pool_label_count.config(text=f"📋 {total} arquivo(s)")

        num_visiveis = min(total, 80)
        for i in range(80):
            if i < num_visiveis:
                caminho = dados[i]
                nome = os.path.basename(caminho)
                tipo = "🎵" if caminho.lower().endswith(('.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac')) else "🎬"

                # Extrai número do hino do nome do arquivo (para exibição)
                match_num = re.match(r'^(\d+)', nome)
                if match_num:
                    num_hino = match_num.group(1)
                    resto_nome = nome[len(num_hino):].lstrip(' -._')
                else:
                    num_hino = ""
                    resto_nome = nome

                # Verifica se é a música atual
                is_current = (self.arquivo_atual and caminho == self.arquivo_atual)

                # Monta texto: contagem sequencial + número do hino entre parênteses
                if num_hino:
                    texto = f"  {i+1}. {tipo} ({num_hino}) {resto_nome}"
                else:
                    texto = f"  {i+1}. {tipo} {nome}"

                # Se for a música atual, prefixo muda conforme pulse
                if is_current:
                    texto = "▶" + texto[1:] if getattr(self, '_pulse_state', 0) == 0 else "▷" + texto[1:]

                frame = self._pool_frames[i]
                btn = self._pool_botoes[i]

                # Cor de fundo: verde se tocando, alternado caso contrário
                if is_current:
                    bg_cor = '#238636'
                    fg_cor = '#f0c040'
                else:
                    bg_cor = '#1c2128' if i % 2 == 0 else '#21262d'
                    fg_cor = '#c9d1d9'

                btn.config(text=texto, bg=bg_cor, fg=fg_cor)
                self._pool_caminhos[i] = caminho
                btn.config(command=lambda c=caminho: self.tocar_arquivo(c))

                frame.pack(fill='x', padx=100, pady=1)

                # Barra de progresso para item atual (ocupa toda a largura do frame)
                progress_frame, progress_bar = self._pool_progress_bars[i]
                if is_current and self.player and self.player.is_playing:
                    duracao = self.player.duracao_total
                    if duracao and duracao > 0:
                        elapsed = self.player.obter_tempo_decorrido()
                        frac = min(elapsed / duracao, 1.0)
                        progress_frame.pack(fill='x', side='top', before=btn)
                        # place com relwidth = fração, ocupando toda a largura
                        progress_bar.place(relwidth=frac, relheight=1.0)
                    else:
                        # Se não tem duração, mostra barra cheia (indeterminado)
                        progress_frame.pack(fill='x', side='top', before=btn)
                        progress_bar.place(relwidth=1.0, relheight=1.0)
                else:
                    progress_frame.pack_forget()
            else:
                self._pool_frames[i].pack_forget()

        # Inicia animação do ícone pulsante se há música tocando
        if self.arquivo_atual and self.player and self.player.is_playing:
            self._iniciar_pulse()
        else:
            self._parar_pulse()


    # ── Controles de reprodução ──────────────────────────────────

    def tocar_arquivo(self, caminho: str) -> None:
        """Inicia a reprodução de um arquivo específico."""
        if self.arquivos_encontrados and caminho in self.arquivos_encontrados:
            self.player.carregar_playlist(self.arquivos_encontrados)
            self.player.tocar_indice(
                self.arquivos_encontrados.index(caminho)
            )
        else:
            self.arquivo_atual = caminho
            self.player.carregar_playlist([caminho])
            self.player.play_pause()

        self._cancel_focus_timer()
        self.root.focus_set()

    def tocar_proximo(self) -> bool:
        return self.player.proximo()

    def tocar_anterior(self) -> bool:
        return self.player.anterior()

    def mostrar_aviso(self, mensagem: str, segundos: float = 9.0) -> None:
        """Mostra um aviso no rodapé, sem travar a interface nem sumir cedo.

        `atualizar_status` roda a cada ~2 s e reescreve o status_label com a
        faixa atual, então um texto colocado ali uma única vez desapareceria
        em segundos. Por isso o aviso é reescrito a cada 1 s enquanto durar, e
        no fim o label é devolvido ao `atualizar_status`.

        Usado pelo MediaPlayer para coisas como "este player não aceita pausa".
        """
        if self._aviso_timer:
            try:
                self.root.after_cancel(self._aviso_timer)
            except Exception:
                pass
            self._aviso_timer = None

        # Contagem de repetições: cada tique reescreve e conta 1 s.
        # `nonlocal` é obrigatório: sem ele o Python trata `restantes` como
        # variável local de `_repetir` e o `restantes -= 1` estoura
        # UnboundLocalError no primeiro tique — foi o que derrubou o aviso de
        # pausa do VLC (e, com a exceção na thread do Tk, congelou a interface).
        restantes = max(1, int(segundos))

        def _repetir() -> None:
            nonlocal restantes
            try:
                self.status_label.config(text=mensagem)
            except tk.TclError:
                self._aviso_timer = None
                return
            if restantes > 0:
                restantes -= 1
                # 1 s: menos que o intervalo do atualizar_status, então o
                # aviso sempre "vence" a reescrita da faixa.
                self._aviso_timer = self.root.after(1000, _repetir)
            else:
                self._aviso_timer = None
                self.atualizar_status()

        # after(0, ...): o aviso pode vir de outra thread.
        self._aviso_timer = self.root.after(0, _repetir)

    def atualizar_status(self) -> None:
        """Atualiza o label de status com informações da faixa atual."""
        self.player.sincronizar_tempo_dbus()

        arquivo_atual = self.arquivo_atual
        if not arquivo_atual:
            self.status_label.config(text="")
            return

        nome = os.path.basename(arquivo_atual)
        arquivos = self.arquivos_encontrados
        player = self.player

        if player.is_playing:
            if arquivos and arquivo_atual in arquivos:
                pos = arquivos.index(arquivo_atual) + 1
                base_text = f"▶ {nome} ({pos}/{len(arquivos)})"
            else:
                base_text = f"▶ {nome}"
        elif player.is_paused:
            base_text = f"⏸️ {nome} (Pausado)"
        else:
            base_text = ""

        tempo_info = player.tempo_inicio is not None or player.tempo_acumulado > 0
        if tempo_info and nome:
            elapsed = player.obter_tempo_decorrido()
            duracao = player.duracao_total
            tempo_str = f" • ⏱️ {self._formatar_tempo(elapsed)}"
            if duracao:
                tempo_str += f" / {self._formatar_tempo(duracao)}"
            base_text += tempo_str

        self.status_label.config(text=base_text)

    @staticmethod
    def _formatar_tempo(segundos: float | None) -> str:
        if segundos is None:
            return "00:00"
        total_seg = int(segundos)
        h, resto = divmod(total_seg, 3600)
        m, s = divmod(resto, 60)
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    @staticmethod
    def _formatar_cronometro(segundos: float) -> str:
        """Formata segundos com centésimos: MM:SS.cc (HH:MM:SS.cc se >= 1h)."""
        cs = max(0, int(round(segundos * 100)))
        h, r = divmod(cs, 360000)
        m, s = divmod(r, 6000)
        s, c = divmod(s, 100)
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}.{c:02d}"
        return f"{m:02d}:{s:02d}.{c:02d}"

    # ── Cronômetro e contagem regressiva (controles do operador) ─────

    def _salvar_config_medidor(self, chave: str, cfg: dict) -> None:
        """Persiste a configuração de um medidor e aplica cores/transparência."""
        self.config_data[chave] = cfg
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config_data, f, indent=2)
        except Exception as e:
            log.exception(f"Erro ao salvar config de {chave}: {e}")

    def _projetar_medidor_seguro(self, chave: str, modo: str,
                                 subtitulo: str = "", tempo: str = "00:00") -> None:
        """Projeta um medidor no telão; recria o telão se necessário."""
        telao = self.player._garantir_telao()
        cfg = self.config_data.get(chave, {})
        telao._projetar_medidor(cfg, modo, subtitulo=subtitulo, tempo=tempo)

    def cronometro_iniciar(self, label: tk.Label | None = None) -> None:
        """Inicia (ou continua) o cronômetro e garante a projeção no telão.

        Se não estiver rodando do zero, zera o acúmulo. Se estiver pausado,
        apenas retoma. O label (do operador) recebe o tempo a cada tick.
        """
        c = self._crono
        telao = self.player._garantir_telao()

        if getattr(telao, "_modo_extra", None) != "cronometro":
            tempo_inicial = self._formatar_cronometro(c["acumulado"]) if c["pausado"] else "00:00.00"
            telao._projetar_medidor(
                self.config_data.get("cronometro", {}),
                "cronometro", tempo=tempo_inicial,
            )
        if c["rodando"] and not c["pausado"]:
            return
        if c["pausado"]:
            c["pausado"] = False
        else:
            c["acumulado"] = 0.0
        c["inicio"] = time.time()
        c["rodando"] = True
        c["label"] = label
        if c["timer_id"] is None:
            c["timer_id"] = self.root.after(50, self._loop_cronometro)
        self._atualizar_label_medidor(label, "00:00.00")
        self._marcar_botoes_crono()

    def _loop_cronometro(self) -> None:
        c = self._crono
        if not c["rodando"] or c["pausado"]:
            return
        total = c["acumulado"] + (time.time() - c["inicio"])
        texto = self._formatar_cronometro(total)
        telao = self.player.telao
        if telao and getattr(telao, "_modo_extra", None) == "cronometro" \
                and telao._raiz_viva():
            telao._atualizar_medidor(texto)
        lbl = c.get("label")
        if lbl is not None:
            try:
                if lbl.winfo_exists():
                    lbl.config(text=texto)
            except tk.TclError:
                c["label"] = None
        c["timer_id"] = self.root.after(50, self._loop_cronometro)

    def cronometro_parar(self) -> None:
        """Pausa o cronômetro (mantendo o tempo na tela)."""
        c = self._crono
        if c["rodando"] and not c["pausado"]:
            c["acumulado"] += time.time() - c["inicio"]
        c["pausado"] = True
        if c["timer_id"] is not None:
            try:
                self.root.after_cancel(c["timer_id"])
            except (tk.TclError, ValueError):
                pass
            c["timer_id"] = None
        self._marcar_botoes_crono()

    def cronometro_continuar(self) -> None:
        """Continua o cronômetro de onde parou."""
        c = self._crono
        if not c["rodando"]:
            return
        if c["pausado"]:
            c["inicio"] = time.time()
            c["pausado"] = False
            if c["timer_id"] is None:
                c["timer_id"] = self.root.after(50, self._loop_cronometro)
            self._marcar_botoes_crono()

    def cronometro_encerrar(self) -> None:
        """Para e zera o cronômetro e remove a projeção do telão."""
        self.cronometro_parar()
        c = self._crono
        c["rodando"] = False
        c["acumulado"] = 0.0
        c["timer_id"] = None
        try:
            if self.player.telao and self.player.telao._raiz_viva():
                if getattr(self.player.telao, "_modo_extra", None) == "cronometro":
                    self.player.telao.encerrar_medidor()
        except Exception:
            pass
        lbl = c.get("label")
        if lbl is not None:
            try:
                if lbl.winfo_exists():
                    lbl.config(text="00:00.00")
            except tk.TclError:
                pass
        self._marcar_botoes_crono()

    @staticmethod
    def _parsear_tempo_contagem(texto: str) -> int | None:
        """Converte entrada do operador para segundos.

        Aceita "MM:SS" ou apenas minutos (número). Ex.: "5" => 300s,
        "2:30" => 150s. Retorna None se inválido ou <= 0.
        """
        if not texto:
            return None
        texto = texto.strip().replace(",", ".")
        if ":" in texto:
            partes = texto.split(":")
            if len(partes) == 2:
                try:
                    mm = float(partes[0] or 0)
                    ss = float(partes[1] or 0)
                    total = int(mm) * 60 + int(ss)
                    return total if total > 0 else None
                except ValueError:
                    return None
            return None
        try:
            valor = float(texto)
        except ValueError:
            return None
        total = int(valor * 60)
        return total if total > 0 else None

    def contagem_iniciar(self, total_seg: int, titulo: str,
                         label: tk.Label | None = None) -> None:
        """Inicia a contagem regressiva do zero, no tempo digitado.

        Sempre reinicia a contagem, mesmo que haja uma em andamento,
        pausada ou já encerrada: cancela o loop anterior, zera o resto
        e reprojeta o telão com o novo total. Para retomar uma contagem
        pausada, use contagem_continuar().
        """
        c = self._contagem
        if total_seg is None or total_seg <= 0:
            return

        if c["timer_id"] is not None:
            try:
                self.root.after_cancel(c["timer_id"])
            except (tk.TclError, ValueError):
                pass
            c["timer_id"] = None
        c["total"] = float(total_seg)
        c["restante"] = float(total_seg)
        c["fim"] = time.time() + float(total_seg)
        c["rodando"] = True
        c["pausado"] = False
        c["titulo"] = titulo
        c["label"] = label
        self._projetar_medidor_seguro(
            "contagem", "contagem", subtitulo=titulo,
            tempo=self._formatar_tempo(total_seg))
        c["timer_id"] = self.root.after(200, self._loop_contagem)
        self._atualizar_label_medidor(label, self._formatar_tempo(total_seg))
        self._marcar_botoes_contagem()

    def _loop_contagem(self) -> None:
        c = self._contagem
        if not c["rodando"] or c["pausado"]:
            return
        restante = c["fim"] - time.time()
        if restante <= 0:
            restante = 0.0
            titulo = c.get("titulo", "")
            telao = self.player.telao
            if telao and getattr(telao, "_modo_extra", None) == "contagem" \
                    and telao._raiz_viva():
                telao._atualizar_medidor("00:00", subtitulo=titulo)
            lbl = c.get("label")
            if lbl is not None:
                try:
                    if lbl.winfo_exists():
                        lbl.config(text="00:00")
                except tk.TclError:
                    c["label"] = None
            c["rodando"] = False
            c["pausado"] = True
            c["timer_id"] = None
            self._marcar_botoes_contagem()
            return
        c["restante"] = restante
        texto = self._formatar_tempo(restante)
        telao = self.player.telao
        if telao and getattr(telao, "_modo_extra", None) == "contagem" \
                and telao._raiz_viva():
            telao._atualizar_medidor(texto)
        lbl = c.get("label")
        if lbl is not None:
            try:
                if lbl.winfo_exists():
                    lbl.config(text=texto)
            except tk.TclError:
                c["label"] = None
        c["timer_id"] = self.root.after(200, self._loop_contagem)

    def contagem_parar(self) -> None:
        """Pausa a contagem regressiva."""
        c = self._contagem
        if c["rodando"] and not c["pausado"]:
            c["restante"] = max(0.0, c["fim"] - time.time())
        c["pausado"] = True
        if c["timer_id"] is not None:
            try:
                self.root.after_cancel(c["timer_id"])
            except (tk.TclError, ValueError):
                pass
            c["timer_id"] = None
        self._marcar_botoes_contagem()

    def contagem_continuar(self) -> None:
        """Continua a contagem regressiva de onde parou."""
        c = self._contagem
        if not c["rodando"]:
            return
        if c["pausado"]:
            c["fim"] = time.time() + c["restante"]
            c["pausado"] = False
            if c["timer_id"] is None:
                c["timer_id"] = self.root.after(200, self._loop_contagem)
            self._marcar_botoes_contagem()

    def contagem_encerrar(self) -> None:
        """Para e zera a contagem e remove a projeção do telão."""
        self.contagem_parar()
        c = self._contagem
        c["rodando"] = False
        c["pausado"] = False
        c["restante"] = 0.0
        c["total"] = 0.0
        c["timer_id"] = None
        try:
            if self.player.telao and self.player.telao._raiz_viva():
                if getattr(self.player.telao, "_modo_extra", None) == "contagem":
                    self.player.telao.encerrar_medidor()
        except Exception:
            pass
        lbl = c.get("label")
        if lbl is not None:
            try:
                if lbl.winfo_exists():
                    lbl.config(text="--:--")
            except tk.TclError:
                pass
        self._marcar_botoes_contagem()

    def _atualizar_label_medidor(self, label, texto: str) -> None:
        if label is None:
            return
        try:
            if label.winfo_exists():
                label.config(text=texto)
        except tk.TclError:
            pass

    def _marcar_botoes_crono(self) -> None:
        c = self._crono
        btns = (getattr(self, "_crono_btns", None) or {}).get("botoes")
        if not btns:
            return
        try:
            rodando = bool(c["rodando"]) and not c["pausado"]
            btns.get("iniciar").config(state="disabled" if rodando else "normal")
            btns.get("parar").config(state="normal" if c["rodando"] and rodando else "disabled")
            continuar = btns.get("continuar")
            if continuar:
                continuar.config(state="normal" if (c["rodando"] and c["pausado"]) else "disabled")
        except tk.TclError:
            self._crono_btns = {"botoes": {}}

    def _marcar_botoes_contagem(self) -> None:
        c = self._contagem
        btns = (getattr(self, "_contagem_btns", None) or {}).get("botoes")
        if not btns:
            return
        try:
            rodando = bool(c["rodando"]) and not c["pausado"]
            btns.get("iniciar").config(state="disabled" if rodando else "normal")
            btns.get("parar").config(state="normal" if (c["rodando"] and rodando) else "disabled")
            continuar = btns.get("continuar")
            if continuar:
                continuar.config(state="normal" if (c["rodando"] and c["pausado"]) else "disabled")
        except tk.TclError:
            self._contagem_btns = {"botoes": {}}

    def cronometro_projetar(self, label: tk.Label | None = None) -> None:
        """Reaplica a projeção do cronômetro no telão SEM interromper a contagem.

        Usado principalmente após alterar as cores/fundo no "💾 Salvar":
        o tempo em andamento (ou pausado) é preservado.
        """
        c = self._crono
        c["label"] = label
        if c["rodando"] and not c["pausado"]:
            tempo_atual = self._formatar_cronometro(
                c["acumulado"] + time.time() - c["inicio"])
        else:
            tempo_atual = self._formatar_cronometro(c["acumulado"])
        # Não cancela o loop: a contagem continua rodando normalmente.
        self._projetar_medidor_seguro("cronometro", "cronometro",
                                      tempo=tempo_atual)
        self._atualizar_label_medidor(label, tempo_atual)
        self._marcar_botoes_crono()

    def contagem_projetar(self, titulo: str, tempo_texto: str,
                          label: tk.Label | None = None) -> int | None:
        """Reaplica a projeção da contagem regressiva SEM interromper a contagem.

        Usado principalmente após alterar as cores/fundo no "💾 Salvar":
        o tempo restante em andamento (ou pausado) é preservado. Quando
        ociosa, usa o tempo digitado como valor inicial. Se o nome/frase
        estiver vazio, o texto some do telão (só os números continuam).
        Retorna o total em segundos (ou None se o tempo for inválido).
        """
        total_digitado = self._parsear_tempo_contagem(tempo_texto)
        c = self._contagem
        c["label"] = label
        c["titulo"] = titulo or ""
        titulo_final = c["titulo"]
        if c["rodando"] and not c["pausado"]:
            tempo_atual = self._formatar_tempo(
                max(0.0, c["fim"] - time.time()))
        elif c["pausado"]:
            tempo_atual = self._formatar_tempo(c["restante"])
        else:
            if total_digitado is None:
                return None
            c["restante"] = 0.0
            c["total"] = float(total_digitado)
            c["rodando"] = False
            c["pausado"] = False
            tempo_atual = self._formatar_tempo(total_digitado)
        # Não cancela o loop: a contagem continua rodando normalmente.
        self._projetar_medidor_seguro(
            "contagem", "contagem", subtitulo=titulo_final,
            tempo=tempo_atual)
        self._atualizar_label_medidor(label, tempo_atual)
        self._marcar_botoes_contagem()
        return total_digitado

    def parar(self) -> None:
        """Para a reprodução."""
        self._parar_pulse()
        self.player.stop()
        self.arquivo_atual = None
        self.atualizar_status()
        self.atualizar_lista()

    def atualizar_relogio(self) -> None:
        """Atualiza o relógio na interface e no telão.

        Otimizado: só chama mostrar_relogio() se a hora mudou e
        usa _ultima_hora_telao para evitar redesenho do Canvas
        quando o texto não mudou.
        """
        try:
            hora_atual = datetime.now().strftime("%H:%M")
            self.hora_label.config(text=hora_atual)

            # Atualiza o status a cada 1 segundo para que o tempo da música
            # avance sem saltos de 2 segundos
            self.atualizar_status()

            # Telão: só atualiza se estiver no modo relógio
            if self.player and self.player.telao.mostrando_relogio:
                # Verifica se a hora mudou antes de chamar o telão
                ultima_hora = getattr(self, '_ultima_hora_telao', None)
                if ultima_hora is None or ultima_hora != hora_atual:
                    self._ultima_hora_telao = hora_atual
                    temp_display = self.temperatura_atual if self._temperatura_valida() else ""
                    self.player.mostrar_relogio(hora_atual, temp_display)
        except Exception:
            pass
        self.root.after(1000, self.atualizar_relogio)

    # ── Gerenciador de Banco (mantido, com recarga de cache) ────

    def abrir_gerenciador(self) -> None:
        """Abre a janela de gerenciamento de mídias."""
        self._janela_gerenciar_midias()

    def _janela_gerenciar_midias(self) -> None:
        """Janela completa para gerenciar as mídias do banco."""
        janela = tk.Toplevel(self.root)
        janela.title("📦 Gerenciar Banco de Mídia")
        janela.geometry("800x900")
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        _centralizar_sobre(janela, self.root)

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

        def _atualizar_lista():
            """Atualiza a TreeView (closure)."""
            try:
                tipo_filtro = filtro_var.get()
                filtro = "" if tipo_filtro == "todos" else f"?tipo={tipo_filtro}"
                req = urllib.request.Request(f"{BACKEND_URL}/api/midia{filtro}")
                with _baixar(req, timeout=5) as resp:
                    midias: list[dict] = json.loads(resp.read().decode())
            except Exception:
                midias = []

            total = len(midias)
            videos = sum(1 for m in midias if m['tipo'] == 'video')
            audios = sum(1 for m in midias if m['tipo'] == 'audio')
            textos = sum(1 for m in midias if m['tipo'] == 'texto')

            try:
                gerenciador_info.config(
                    text=f"📊 {total} mídia(s)  |  🎬 {videos}  🎵 {audios}  📄 {textos}"
                )
            except tk.TclError:
                pass

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
                icon = icone.get(m['tipo'], "📁")
                gerenciador_tree.insert(
                    "", tk.END, iid=str(m['id']),
                    values=(
                        m['id'],
                        f"{icon} {m['nome_exibicao']}",
                        m['tipo'],
                        tamanho_str,
                        os.path.basename(m.get('caminho_arquivo', '')),
                    )
                )

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



    # ── Seletor de arquivos personalizado (mantido) ──────────────

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

    # ────────────────────────────────────────────────────────────────────
    # SORTEIO PROFISSIONAL
    # ────────────────────────────────────────────────────────────────────

    def abrir_sorteio(self) -> None:
        """Abre a janela do Sorteio Profissional (integrada ao NavePro).

        O sorteio abre numa janela sobre o painel do operador e projeta a
        tela pública (o número/nome sorteado) no telão, por cima do relógio.
        """
        from navepro.sorteio.integracao import abrir_sorteio

        abrir_sorteio(self)

    # ────────────────────────────────────────────────────────────────────
    # JANELA DE HINOS / LETRAS
    # ────────────────────────────────────────────────────────────────────

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

        def _on_focus_entry():
            if entry_busca.get().strip() == placeholder:
                entry_busca.delete(0, tk.END)
                entry_busca.config(fg='#f0c040')

        def _on_focus_out_entry():
            if not entry_busca.get().strip():
                entry_busca.delete(0, tk.END)
                entry_busca.insert(0, placeholder)
                entry_busca.config(fg='#8b949e')

        entry_busca.bind("<FocusIn>", lambda e: _on_focus_entry())
        entry_busca.bind("<FocusOut>", lambda e: _on_focus_out_entry())

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

        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Treeview", background="#21262d", foreground="#c9d1d9",
                        fieldbackground="#21262d", font=("Arial", 10))
        style.configure("Treeview.Heading", background="#161b22", foreground="#f0c040",
                        font=("Arial", 10, "bold"))
        style.map('Treeview', background=[('selected', '#6e40c9')],
                  foreground=[('selected', '#ffffff')])

        def _carregar_hinos(busca: str = ""):
            for item in tree.get_children():
                tree.delete(item)
            if busca and busca != placeholder:
                if busca.isdigit():
                    # Número do hino está no começo do título (ex.: "11 - ...").
                    num = int(busca)
                    rows = [r for r in db_query(
                                "SELECT * FROM letras WHERE ativo = 1 ORDER BY titulo")
                            if _numero_do_titulo(r["titulo"]) == num]
                else:
                    busca_like = f"%{busca}%"
                    rows = db_query(
                        "SELECT * FROM letras WHERE ativo = 1 AND "
                        "(titulo LIKE ? OR artista LIKE ? OR letra_completa LIKE ?) "
                        "ORDER BY titulo", (busca_like, busca_like, busca_like))
            else:
                rows = db_query(
                    "SELECT * FROM letras WHERE ativo = 1 ORDER BY titulo")
            for r in rows:
                tree.insert("", tk.END, iid=str(r['id']),
                            values=(r['id'], r['titulo'], r['artista'],
                                    r['categoria'], r['ccli_numero']))

        def _buscar(event=None):
            termo = entry_busca.get().strip()
            if termo == placeholder or termo.startswith(placeholder):
                termo = termo[len(placeholder):].strip()
            _carregar_hinos(termo)

        def _buscar_e_projetar(event=None):
            """Enter na busca: filtra e já projeta o primeiro resultado.

            Mesmo efeito de buscar, selecionar a 1ª linha com o mouse e
            clicar em "📺 Projetar". Com o campo vazio não projeta nada.
            """
            termo = entry_busca.get().strip()
            if termo == placeholder or termo.startswith(placeholder):
                termo = termo[len(placeholder):].strip()
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
        _debounce_id = [None]
        def _on_key(event=None):
            if _debounce_id[0]:
                janela.after_cancel(_debounce_id[0])
            _debounce_id[0] = janela.after(400, _buscar)
        entry_busca.bind("<KeyRelease>", _on_key)

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

        def _atualizar_indicador_slide():
            try:
                if not label_slide.winfo_exists():
                    return
            except tk.TclError:
                return
            telao = self.player.telao
            em_slides = getattr(telao, "_em_slides", False)
            if em_slides and telao._slides:
                label_slide.config(
                    text=f"Slide {telao._slide_index + 1} de {len(telao._slides)}",
                    fg='#3fb950', bg='#161b22')
            elif getattr(telao, "_mostrando_imagem", False):
                label_slide.config(text="🖼️ Imagem ativa", fg='#3fb950', bg='#161b22')
            elif getattr(telao, "mostrando_letra", False):
                label_slide.config(text="Projeção ativa", fg='#f0c040', bg='#161b22')
            else:
                label_slide.config(text="Sem projeção", fg='#8b949e', bg='#161b22')

        def _slide_anterior(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            if telao.slide_anterior():
                _atualizar_indicador_slide()
            return "break"

        def _slide_proximo(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            if telao.slide_proximo():
                _atualizar_indicador_slide()
            return "break"

        def _parar_projecao(event: object = None):
            if not getattr(self.player.telao, "mostrando_letra", False):
                return None
            self.player.telao.parar_projecao()
            _atualizar_indicador_slide()
            return "break"

        def _ajustar_fonte(delta: float):
            """Aumenta/diminui a fonte da projeção e redesenha o que está ativo."""
            telao = self.player.telao
            cfg = getattr(telao, "_proj_cfg", None)
            if cfg is None:
                telao.configurar_projecao()
                cfg = telao._proj_cfg
            novo = min(15.0, max(1.0, float(cfg.get("tamanho_pct", 5.0)) + delta))
            cfg["tamanho_pct"] = novo
            telao._proj_cfg = cfg
            if getattr(telao, "_em_slides", False) and telao._slides:
                telao._mostrar_slide(telao._slide_index)
            elif getattr(telao, "mostrando_letra", False) and telao._current_text:
                telao._desenhar_texto_no_canvas(telao._current_text)
            self.salvar_config_projecao(dict(cfg))
            _atualizar_indicador_slide()

        def _restaurar_fonte():
            """Volta a fonte da projeção ao padrão, desfazendo o A−/A+ manual."""
            telao = self.player.telao
            cfg = getattr(telao, "_proj_cfg", None)
            if cfg is None:
                telao.configurar_projecao()
                cfg = telao._proj_cfg
            cfg["tamanho_pct"] = 5.0
            telao._proj_cfg = cfg
            if getattr(telao, "_em_slides", False) and telao._slides:
                telao._mostrar_slide(telao._slide_index)
            elif getattr(telao, "mostrando_letra", False) and telao._current_text:
                telao._desenhar_texto_no_canvas(telao._current_text)
            self.salvar_config_projecao(dict(cfg))
            _atualizar_indicador_slide()

        # Setas do teclado e Esc (janela de hinos).
        # No root substituímos a ligação a cada abertura para evitar acumular
        # handlers duplicados de chamadas repetidas a janela_hinos.
        janela.bind("<Left>", _slide_anterior)
        janela.bind("<Up>", _slide_anterior)
        janela.bind("<Right>", _slide_proximo)
        janela.bind("<Down>", _slide_proximo)
        janela.bind("<Escape>", _parar_projecao)
        self.root.bind("<Left>", _slide_anterior)
        self.root.bind("<Up>", _slide_anterior)
        self.root.bind("<Right>", _slide_proximo)
        self.root.bind("<Down>", _slide_proximo)
        self.root.bind("<Escape>", _parar_projecao)

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

    # ────────────────────────────────────────────────────────────────────
    # JANELA DE ANÚNCIOS (armazenados em JSON, FORA do banco de dados)
    # ────────────────────────────────────────────────────────────────────

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

        def _on_focus_entry():
            if entry_busca.get().strip() == placeholder:
                entry_busca.delete(0, tk.END)
                entry_busca.config(fg='#f0c040')

        def _on_focus_out_entry():
            if not entry_busca.get().strip():
                entry_busca.delete(0, tk.END)
                entry_busca.insert(0, placeholder)
                entry_busca.config(fg='#8b949e')

        entry_busca.bind("<FocusIn>", lambda e: _on_focus_entry())
        entry_busca.bind("<FocusOut>", lambda e: _on_focus_out_entry())

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

        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Treeview", background="#21262d", foreground="#c9d1d9",
                        fieldbackground="#21262d", font=("Arial", 10))
        style.configure("Treeview.Heading", background="#161b22", foreground="#f0c040",
                        font=("Arial", 10, "bold"))
        style.map('Treeview', background=[('selected', '#6e40c9')],
                  foreground=[('selected', '#ffffff')])

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
            termo = entry_busca.get().strip()
            if termo == placeholder or termo.startswith(placeholder):
                termo = termo[len(placeholder):].strip()
            _carregar_anuncios(termo)

        def _buscar_e_projetar(event=None):
            """Enter na busca: filtra e já projeta o primeiro anúncio.

            Mesmo efeito de buscar, selecionar a 1ª linha com o mouse e
            clicar em "📺 Projetar". Com o campo vazio não projeta nada.
            """
            termo = entry_busca.get().strip()
            if termo == placeholder or termo.startswith(placeholder):
                termo = termo[len(placeholder):].strip()
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
        _debounce_id = [None]

        def _on_key(event=None):
            if _debounce_id[0]:
                janela.after_cancel(_debounce_id[0])
            _debounce_id[0] = janela.after(400, _buscar)

        entry_busca.bind("<KeyRelease>", _on_key)

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

        def _adicionar_anuncio(dados: dict) -> bool:
            """Adiciona um anúncio na tabela 'anuncios'. True se salvou."""
            return _inserir_anuncio_db(dados) is not None

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

        def _atualizar_indicador_slide():
            try:
                if not label_slide.winfo_exists():
                    return
            except tk.TclError:
                return
            telao = self.player.telao
            em_slides = getattr(telao, "_em_slides", False)
            if em_slides and telao._slides:
                label_slide.config(
                    text=f"Slide {telao._slide_index + 1} de {len(telao._slides)}",
                    fg='#3fb950', bg='#161b22')
            elif getattr(telao, "_mostrando_imagem", False):
                label_slide.config(text="🖼️ Imagem ativa", fg='#3fb950', bg='#161b22')
            elif getattr(telao, "mostrando_letra", False):
                label_slide.config(text="Projeção ativa", fg='#f0c040', bg='#161b22')
            else:
                label_slide.config(text="Sem projeção", fg='#8b949e', bg='#161b22')

        def _slide_anterior(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            if telao.slide_anterior():
                _atualizar_indicador_slide()
            return "break"

        def _slide_proximo(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            if telao.slide_proximo():
                _atualizar_indicador_slide()
            return "break"

        def _parar_projecao(event: object = None):
            if not getattr(self.player.telao, "mostrando_letra", False):
                return None
            self.player.telao.parar_projecao()
            _atualizar_indicador_slide()
            return "break"

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
            cfg = getattr(telao, "_proj_cfg", None)
            if cfg is None:
                telao.configurar_projecao()
                cfg = telao._proj_cfg
            novo = min(15.0, max(1.0, float(cfg.get("tamanho_pct", 5.0)) + delta))
            cfg["tamanho_pct"] = novo
            telao._proj_cfg = cfg
            if getattr(telao, "_em_slides", False) and telao._slides:
                telao._mostrar_slide(telao._slide_index)
            elif getattr(telao, "mostrando_letra", False) and telao._current_text:
                telao._desenhar_texto_no_canvas(telao._current_text)
            self.salvar_config_projecao(dict(cfg))
            _atualizar_indicador_slide()

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
            cfg = getattr(telao, "_proj_cfg", None)
            if cfg is None:
                telao.configurar_projecao()
                cfg = telao._proj_cfg
            cfg["tamanho_pct"] = 5.0
            telao._proj_cfg = cfg
            if getattr(telao, "_em_slides", False) and telao._slides:
                telao._mostrar_slide(telao._slide_index)
            elif getattr(telao, "mostrando_letra", False) and telao._current_text:
                telao._desenhar_texto_no_canvas(telao._current_text)
            self.salvar_config_projecao(dict(cfg))
            _atualizar_indicador_slide()

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

        # Setas do teclado e Esc (janela de anúncios), mesmo esquema da de hinos.
        janela.bind("<Left>", _slide_anterior)
        janela.bind("<Up>", _slide_anterior)
        janela.bind("<Right>", _slide_proximo)
        janela.bind("<Down>", _slide_proximo)
        janela.bind("<Escape>", _parar_projecao)
        self.root.bind("<Left>", _slide_anterior)
        self.root.bind("<Up>", _slide_anterior)
        self.root.bind("<Right>", _slide_proximo)
        self.root.bind("<Down>", _slide_proximo)
        self.root.bind("<Escape>", _parar_projecao)

        # Passador de slides (controle remoto): AvPag/RetPag, espaço, F5 e
        # BackSpace também navegam os slides projetados (além das setas).
        # Se o foco estiver num campo de texto, as teclas seguem normais.
        def _foco_em_campo_texto() -> bool:
            foco = janela.focus_get() or self.root.focus_get()
            if foco is None:
                return False
            try:
                return foco.winfo_class() in (
                    "Entry", "TEntry", "Text", "Spinbox", "TCombobox")
            except tk.TclError:
                return False

        def _navegar_passador(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            if _foco_em_campo_texto():
                return None
            keysym = str(getattr(event, 'keysym', '') or '').lower()
            if keysym in ('next', 'page_next', 'page_down', 'space', 'f5'):
                if telao.slide_proximo():
                    _atualizar_indicador_slide()
                return "break"
            if keysym in ('prior', 'page_prior', 'page_up', 'backspace'):
                if telao.slide_anterior():
                    _atualizar_indicador_slide()
                return "break"
            return None

        for _seq in ("<Next>", "<Prior>", "<F5>", "<BackSpace>", "<space>"):
            janela.bind(_seq, _navegar_passador)
        for _seq in ("<Next>", "<Prior>", "<F5>", "<BackSpace>"):
            self.root.bind(_seq, _navegar_passador)

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
            editar_win.geometry("680x860")
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

    # ────────────────────────────────────────────────────────────────────
    # JANELA DE BÍBLIA
    # ────────────────────────────────────────────────────────────────────

    # Lista de livros da Bíblia (ordem canônica)
    LIVROS_BIBLIA = [
        "Gênesis", "Êxodo", "Levítico", "Números", "Deuteronômio",
        "Josué", "Juízes", "Rute", "1 Samuel", "2 Samuel",
        "1 Reis", "2 Reis", "1 Crônicas", "2 Crônicas", "Esdras",
        "Neemias", "Ester", "Jó", "Salmos", "Provérbios",
        "Eclesiastes", "Cânticos", "Isaías", "Jeremias", "Lamentações",
        "Ezequiel", "Daniel", "Oséias", "Joel", "Amós",
        "Obadias", "Jonas", "Miquéias", "Naum", "Habacuque",
        "Sofonias", "Ageu", "Zacarias", "Malaquias",
        "Mateus", "Marcos", "Lucas", "João", "Atos",
        "Romanos", "1 Coríntios", "2 Coríntios", "Gálatas", "Efésios",
        "Filipenses", "Colossenses", "1 Tessalonicenses", "2 Tessalonicenses",
        "1 Timóteo", "2 Timóteo", "Tito", "Filemom", "Hebreus",
        "Tiago", "1 Pedro", "2 Pedro", "1 João", "2 João",
        "3 João", "Judas", "Apocalipse"
    ]

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

        # Versículo (número = deste até o fim, "1-7" = faixa, vazio = capítulo)
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
            rows = db_query(
                "SELECT * FROM versiculos WHERE versao = ? AND texto LIKE ? "
                "ORDER BY livro, capitulo, versiculo LIMIT 50",
                (versao, f"%{termo}%"))
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
              - vazio ou "1"  → o capítulo inteiro
              - "7"            → do versículo 7 até o fim do capítulo
              - "1-7"          → somente os versículos de 1 a 7

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
                elif "-" in vers:
                    # Faixa explícita: respeita o fim digitado (16-16 = só o 16).
                    v_ini, v_fim = ini, fim
                else:
                    # Número único é o ponto de partida: vai até o fim.
                    v_ini, v_fim = ini, 9999

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
              - "7"      → do versículo 7 até o fim do capítulo
              - "9-16"   → somente os versículos de 9 a 16

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
            # Faixa explícita ("9-16"): projeta só os versículos pedidos,
            # senão mantém o capítulo inteiro começando no versículo inicial.
            if "-" in vers_t:
                rows = [r for r in rows if ini <= r['versiculo'] <= fim]
                if not rows:
                    tkinter.messagebox.showwarning(
                        "Projeção",
                        f"Nenhum versículo encontrado para {livro} "
                        f"{cap}:{ini}-{fim} ({versao}).", parent=janela)
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

        def _slide_anterior(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            if telao.slide_anterior():
                _refletir_telao_na_janela()
            return "break"

        def _slide_proximo(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            if telao.slide_proximo():
                _refletir_telao_na_janela()
            return "break"

        def _parar_projecao(event: object = None):
            if not getattr(self.player.telao, "mostrando_letra", False):
                return None
            self.player.telao.parar_projecao()
            try:
                biblia_text.tag_remove('verso_atual', '1.0', tk.END)
            except tk.TclError:
                pass
            _atualizar_indicador_slide()
            return "break"

        def _ajustar_fonte(delta: float):
            """Aumenta/diminui a fonte da projeção e redesenha o que está ativo."""
            telao = self.player.telao
            cfg = getattr(telao, "_proj_cfg", None)
            if cfg is None:
                telao.configurar_projecao()
                cfg = telao._proj_cfg
            novo = min(15.0, max(1.0, float(cfg.get("tamanho_pct", 5.0)) + delta))
            cfg["tamanho_pct"] = novo
            telao._proj_cfg = cfg
            if getattr(telao, "_em_slides", False) and telao._slides:
                telao._mostrar_slide(telao._slide_index)
            elif getattr(telao, "mostrando_letra", False) and telao._current_text:
                telao._desenhar_texto_no_canvas(telao._current_text)
            self.salvar_config_projecao(dict(cfg))
            _atualizar_indicador_slide()

        def _restaurar_fonte():
            """Volta a fonte da projeção ao padrão, desfazendo o A−/A+ manual."""
            telao = self.player.telao
            cfg = getattr(telao, "_proj_cfg", None)
            if cfg is None:
                telao.configurar_projecao()
                cfg = telao._proj_cfg
            cfg["tamanho_pct"] = 5.0
            telao._proj_cfg = cfg
            if getattr(telao, "_em_slides", False) and telao._slides:
                telao._mostrar_slide(telao._slide_index)
            elif getattr(telao, "mostrando_letra", False) and telao._current_text:
                telao._desenhar_texto_no_canvas(telao._current_text)
            self.salvar_config_projecao(dict(cfg))
            _atualizar_indicador_slide()

        # Setas do teclado e Esc (janela de bíblia).
        # No root substituímos a ligação a cada abertura para evitar acumular
        # handlers duplicados de chamadas repetidas a janela_biblia.
        janela.bind("<Left>", _slide_anterior)
        janela.bind("<Up>", _slide_anterior)
        janela.bind("<Right>", _slide_proximo)
        janela.bind("<Down>", _slide_proximo)
        janela.bind("<Escape>", _parar_projecao)
        self.root.bind("<Left>", _slide_anterior)
        self.root.bind("<Up>", _slide_anterior)
        self.root.bind("<Right>", _slide_proximo)
        self.root.bind("<Down>", _slide_proximo)
        self.root.bind("<Escape>", _parar_projecao)

        # Passador de slides (controle remoto): durante a projeção de
        # versículos, AvPag/RetPag, espaço, F5 e BackSpace navegam como as
        # setas. Mesmo esquema da janela de anúncios.
        def _foco_em_campo_texto() -> bool:
            foco = janela.focus_get() or self.root.focus_get()
            if foco is None:
                return False
            try:
                return foco.winfo_class() in (
                    "Entry", "TEntry", "Text", "Spinbox", "TCombobox")
            except tk.TclError:
                return False

        def _navegar_passador_biblia(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            if _foco_em_campo_texto():
                return None
            keysym = str(getattr(event, 'keysym', '') or '').lower()
            if keysym in ('next', 'page_next', 'page_down', 'space', 'f5'):
                if telao.slide_proximo():
                    _refletir_telao_na_janela()
                return "break"
            if keysym in ('prior', 'page_prior', 'page_up', 'backspace'):
                if telao.slide_anterior():
                    _refletir_telao_na_janela()
                return "break"
            return None

        for _seq in ("<Next>", "<Prior>", "<F5>", "<BackSpace>", "<space>"):
            janela.bind(_seq, _navegar_passador_biblia)
        for _seq in ("<Next>", "<Prior>", "<F5>", "<BackSpace>"):
            self.root.bind(_seq, _navegar_passador_biblia)

        # Abre com João 3 a partir do versículo 16 (campo "V:" = 16)
        _carregar_capitulo()

    # ────────────────────────────────────────────────────────────────────
    # JANELA DE ORDEM DE SERVIÇO
    # ────────────────────────────────────────────────────────────────────

    def janela_ordem_servico(self) -> None:
        """Abre a janela de planejamento de ordem de serviço.

        As ordens são salvas em ~/.navepro/servicos.json (nunca importam
        vídeo/slides). Oferece criar e editar serviços, excluir itens (botão
        da barra ou botão direito na lista) e arrastar e soltar os itens
        para reordená-los.
        """
        _migrar_servicos_do_banco()
        _sincronizar_uploads_midia()
        # O ponteiro de execução (_SERVICO_PROXIMO_ITEM) NÃO é limpo aqui:
        # ele persiste enquanto a janela principal estiver aberta, então ao
        # reabrir "Ordem de Serviço" a reprodução continua de onde parou.
        # Só volta do primeiro item quando o aplicativo é fechado/reaberto
        # (o dict é recriado vazio ao reiniciar o processo).
        dados = _carregar_servicos_json()
        janela = tk.Toplevel(self.root)
        janela.title("📋 Ordem de Serviço")
        janela.geometry("1100x750")
        janela.configure(bg='#0d1117')
        janela.transient(self.root)
        _centralizar_sobre(janela, self.root)

        main = tk.Frame(janela, bg='#0d1117')
        main.pack(fill='both', expand=True, padx=15, pady=15)

        tk.Label(main, text="📋 Ordem de Serviço",
                 font=("Arial", 16, "bold"), fg='#f0c040', bg='#0d1117'
                 ).pack(pady=(0, 10))

        # ── Lista de serviços salvos ──
        serv_frame = tk.Frame(main, bg='#161b22')
        serv_frame.pack(fill='x', pady=5, ipady=5)

        tk.Label(serv_frame, text="Serviço:", fg='#f0c040', bg='#161b22',
                 font=("Arial", 11, "bold")).pack(side='left', padx=8)

        servico_var = tk.StringVar()
        combo_servico = ttk.Combobox(serv_frame, textvariable=servico_var,
                                      width=40, font=("Arial", 11), state='readonly')
        combo_servico.pack(side='left', padx=5)

        servico_selecionado_id = [None]

        def _rotulo_servico(s: dict) -> str:
            return f"{s.get('id')} - {s.get('nome', '')}"

        def _servico_atual() -> dict | None:
            sid = servico_selecionado_id[0]
            if not sid:
                return None
            return next((s for s in dados["servicos"] if s.get("id") == sid), None)

        def _ordenar_servicos():
            return sorted(
                dados["servicos"],
                key=lambda s: s.get('id') or 0,
                reverse=True)

        def _carregar_servicos(escolher: bool = True):
            ord_servicos = _ordenar_servicos()
            opcoes = [_rotulo_servico(s) for s in ord_servicos]
            combo_servico['values'] = opcoes
            combo_servico._servico_ids = [s['id'] for s in ord_servicos]
            if opcoes and escolher:
                combo_servico.current(0)

        def _on_servico_select(event=None):
            sel = combo_servico.get()
            if not sel:
                return
            idx = combo_servico.current()
            ids = getattr(combo_servico, '_servico_ids', [])
            if idx >= 0 and idx < len(ids):
                servico_selecionado_id[0] = ids[idx]
                _carregar_itens()

        combo_servico.bind("<<ComboboxSelected>>", _on_servico_select)

        # ── Itens do serviço (Treeview) ──
        tree_frame = tk.Frame(main, bg='#161b22')
        tree_frame.pack(fill='both', expand=True, pady=5)

        colunas = ("#", "Tipo", "Título", "Duração")
        tree = ttk.Treeview(tree_frame, columns=colunas, show='headings', height=16)
        tree.heading("#", text="#")
        tree.heading("Tipo", text="Tipo")
        tree.heading("Título", text="Título")
        tree.heading("Duração", text="Duração (s)")
        tree.column("#", width=40)
        tree.column("Tipo", width=120)
        tree.column("Título", width=350)
        tree.column("Duração", width=100)

        scroll_y = tk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll_y.set)
        tree.pack(side='left', fill='both', expand=True)
        scroll_y.pack(side='right', fill='y')

        style = ttk.Style()
        style.configure("Treeview", background="#21262d", foreground="#c9d1d9",
                        fieldbackground="#21262d", font=("Arial", 10))
        style.configure("Treeview.Heading", background="#161b22", foreground="#f0c040",
                        font=("Arial", 10, "bold"))
        style.map('Treeview', background=[('selected', '#6e40c9')],
                  foreground=[('selected', '#ffffff')])

        # Escolha do operador na lista de itens: vale UMA única vez no
        # próximo clique em "Executar Serviço". Só é registrada por gestos
        # reais do operador na lista (clique do mouse), nunca pelo destaque
        # automático da reprodução nem por alterações internas da seleção
        # (reordenar, editar, recarregar a lista).
        _item_escolhido: dict[str, int | None] = {"id": None}

        def _registrar_escolha(row_iid: str | None):
            """Grava o item escolhido pelo operador na lista (uso único)."""
            if not row_iid:
                return
            try:
                _item_escolhido["id"] = int(row_iid)
            except (TypeError, ValueError):
                pass

        # ── Drag & drop para reordenar itens dentro da tree ──
        _drag_state: dict[str, str | None] = {"origem": None}

        def _on_tree_button_press(event):
            if tree.identify_region(event.x, event.y) in ("heading", "separator"):
                return
            item = tree.identify_row(event.y)
            if not item:
                return
            _registrar_escolha(item)
            _drag_state["origem"] = item

        def _on_tree_button_release(event):
            origem = _drag_state.get("origem")
            _drag_state["origem"] = None
            if not origem:
                return
            destino = tree.identify_row(event.y)
            serv = _servico_atual()
            if not serv or not destino or destino == origem:
                return
            itens = list(serv.get("itens") or [])
            novo = _reordenar_itens_servico(itens, int(origem), int(destino))
            if novo != itens:
                serv["itens"] = novo
                if _salvar_servicos_json(dados):
                    _carregar_itens()
                    tree.selection_set(destino)
                    tree.focus(destino)

        tree.bind("<ButtonPress-1>", _on_tree_button_press)
        tree.bind("<ButtonRelease-1>", _on_tree_button_release)

        def _on_tree_double_click(event):
            if tree.identify_region(event.x, event.y) == "heading":
                return
            if not tree.identify_row(event.y):
                return
            _editar_item_selecionado()

        tree.bind("<Double-1>", _on_tree_double_click)

        # ── Menu de contexto (clique direito): apagar item ──
        _menu_ctx_aberto = {"menu": None}

        def _fechar_menu_contexto(event=None):
            """Fecha o menu de contexto caso esteja aberto (clique fora dele)."""
            m = _menu_ctx_aberto["menu"]
            if m is not None:
                _menu_ctx_aberto["menu"] = None
                try:
                    m.unpost()
                except tk.TclError:
                    pass

        def _apagar_item_contexto():
            _fechar_menu_contexto()
            sel = tree.selection()
            if not sel:
                return
            serv = _servico_atual()
            if not serv:
                return
            item_id = int(sel[0])
            it = next((x for x in (serv.get("itens") or [])
                       if x.get("id") == item_id), None)
            if it is None:
                return
            titulo = (it.get("titulo_custom") or "").strip() or f"Item {item_id}"
            if not tkinter.messagebox.askyesno(
                    "Confirmar", f"Remover o item \"{titulo}\"?", parent=janela):
                return
            serv["itens"] = [x for x in serv.get("itens", [])
                             if x.get("id") != item_id]
            if not _salvar_servicos_json(dados):
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar a remoção em servicos.json.",
                    parent=janela)
                return
            _carregar_itens()

        def _menu_contexto_item(event):
            _fechar_menu_contexto()
            if tree.identify_region(event.x, event.y) in ("heading", "separator"):
                return "break"
            item_id = tree.identify_row(event.y)
            if not item_id:
                return "break"
            _registrar_escolha(item_id)
            tree.selection_set(item_id)
            tree.focus(item_id)
            menu_ctx = tk.Menu(janela, tearoff=0, bg='#21262d', fg='#c9d1d9',
                               activebackground='#6e40c9',
                               activeforeground='#ffffff', font=("Arial", 10))
            menu_ctx.add_command(label="🗑️ Apagar Item",
                                 command=_apagar_item_contexto)
            _menu_ctx_aberto["menu"] = menu_ctx
            menu_ctx.tk_popup(event.x_root, event.y_root, 0)
            return "break"

        tree.bind("<Button-3>", _menu_contexto_item)

        # Clicar em qualquer outro lugar da janela (ou rolar/teclar Esc) fecha
        # o menu de contexto se ele estiver aberto. O bind na janela propaga
        # para os widgets internos, cobrindo toda a área da janela.
        for _evento in ("<ButtonPress-1>", "<ButtonPress-2>",
                        "<ButtonPress-3>", "<MouseWheel>"):
            janela.bind(_evento, _fechar_menu_contexto)
        janela.bind("<Escape>", _fechar_menu_contexto)

        def _carregar_itens():
            for item in tree.get_children():
                tree.delete(item)
            serv = _servico_atual()
            if not serv:
                return
            itens = list(serv.get("itens") or [])
            for i, it in enumerate(itens):
                tipo = it.get("tipo") or "slide"
                tipo_emoji = {"hino": "📖", "versiculo": "✝️", "video": "🎬",
                              "audio": "🎵", "slide": "📄", "anuncio": "📢",
                              "sermao": "🎤", "youtube": "▶️"}.get(tipo, "📁")
                tree.insert("", tk.END, iid=str(it.get("id")),
                            values=(i + 1, f"{tipo_emoji} {tipo.title()}",
                                    it.get("titulo_custom") or f"Item {i+1}",
                                    it.get("duracao_estimada_segundos") or 0))

        # ── Botões ──
        btn_frame = tk.Frame(main, bg='#0d1117')
        btn_frame.pack(fill='x', pady=5)

        def _novo_servico():
            nome = tkinter.simpledialog.askstring("Novo Serviço",
                "Nome do serviço:", parent=janela) if hasattr(tkinter, 'simpledialog') else None
            if not nome:
                # Fallback se simpledialog não estiver disponível
                nome_win = tk.Toplevel(janela)
                nome_win.title("Novo Serviço")
                nome_win.geometry("350x120")
                nome_win.configure(bg='#0d1117')
                nome_win.transient(janela)
                _centralizar_sobre(nome_win, janela)
                nome_win.after(50, nome_win.grab_set)
                tk.Label(nome_win, text="Nome do serviço:", fg='#f0c040', bg='#0d1117',
                         font=("Arial", 11)).pack(pady=5)
                nome_entry = tk.Entry(nome_win, font=("Arial", 12), bg='#21262d',
                                      fg='#f0c040', insertbackground='#f0c040')
                nome_entry.pack(padx=15, fill='x', ipady=3)
                nome_entry.focus_set()
                resultado = [None]
                def _ok():
                    resultado[0] = nome_entry.get().strip()
                    nome_win.destroy()
                tk.Button(nome_win, text="OK", font=("Arial", 11, "bold"),
                          bg='#238636', fg='white', command=_ok).pack(pady=5)
                nome_win.wait_window()
                nome = resultado[0]
            if not nome:
                return
            novo_id = _proximo_id_servico_livre(dados)
            dados["servicos"].append({
                "id": novo_id,
                "nome": nome,
                "criado_em": datetime.now().isoformat(timespec="seconds"),
                "itens": [],
            })
            dados["_proximo_id_servico"] = max(
                dados.get("_proximo_id_servico", 1), novo_id + 1)
            if not _salvar_servicos_json(dados):
                dados["servicos"] = [s for s in dados["servicos"]
                                     if s.get("id") != novo_id]
                dados["_proximo_id_servico"] = novo_id
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar em servicos.json.", parent=janela)
                return
            _carregar_servicos()
            _on_servico_select()

        def _editar_servico():
            serv = _servico_atual()
            if not serv:
                tkinter.messagebox.showwarning("Seleção", "Selecione um serviço.", parent=janela)
                return
            nome = (tkinter.simpledialog.askstring(
                "Editar Serviço", "Nome do serviço:",
                initialvalue=serv.get("nome", ""), parent=janela)
                if hasattr(tkinter, 'simpledialog') else None)
            if not nome:
                return
            nome = nome.strip()
            if not nome:
                return
            serv["nome"] = nome
            if not _salvar_servicos_json(dados):
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar em servicos.json.", parent=janela)
                return
            _carregar_servicos()
            _on_servico_select()

        def _abrir_editor_item(item_edit: dict | None = None):
            """Abre a janela para adicionar (item_edit=None) ou editar um item."""
            sid = servico_selecionado_id[0]
            if not sid:
                tkinter.messagebox.showwarning("Seleção", "Selecione ou crie um serviço.", parent=janela)
                return
            add_win = tk.Toplevel(janela)
            add_win.title("Editar Item" if item_edit else "Adicionar Item")
            add_win.geometry("700x380")
            add_win.configure(bg='#0d1117')
            add_win.transient(janela)
            _centralizar_sobre(add_win, janela)
            add_win.after(50, add_win.grab_set)

            add_main = tk.Frame(add_win, bg='#0d1117')
            add_main.pack(fill='both', expand=True, padx=15, pady=15)

            tk.Label(add_main, text="Tipo:", fg='#f0c040', bg='#0d1117',
                     font=("Arial", 11, "bold")).pack(anchor='w')
            tipo_var = tk.StringVar(value=(item_edit or {}).get("tipo") or "hino")
            tipos = ["hino", "versiculo", "video", "audio", "slide",
                     "anuncio", "sermao"]
            tipo_frame = tk.Frame(add_main, bg='#0d1117')
            tipo_frame.pack(fill='x', pady=2)
            for t in tipos:
                tk.Radiobutton(tipo_frame, text=t.title(), variable=tipo_var, value=t,
                               bg='#0d1117', fg='#c9d1d9', selectcolor='#21262d',
                               font=("Arial", 10)).pack(side='left', padx=3)

            tk.Label(add_main, text="Título:", fg='#f0c040', bg='#0d1117',
                     font=("Arial", 11, "bold")).pack(anchor='w', pady=(8, 0))
            titulo_entry = tk.Entry(add_main, font=("Arial", 11), bg='#21262d',
                                    fg='#f0c040', insertbackground='#f0c040')
            titulo_entry.insert(0, (item_edit or {}).get("titulo_custom") or "")
            titulo_entry.pack(fill='x', ipady=3, pady=2)

            tk.Label(add_main, text="Buscar (nº ou nome do hino/mídia/anúncio):", fg='#8b949e',
                     bg='#0d1117', font=("Arial", 9)).pack(anchor='w')
            ref_entry = tk.Entry(add_main, font=("Arial", 11), bg='#21262d',
                                 fg='#c9d1d9', insertbackground='#f0c040')
            if item_edit:
                _tf = (item_edit.get("tipo") or "").lower()
                _tc = (item_edit.get("titulo_custom") or "").strip()
                if _tf in ("hino", "audio", "video", "anuncio") and _tc and not _tc.startswith("Item "):
                    ref_entry.insert(0, _tc)
                else:
                    ref_entry.insert(0, str(item_edit.get("referencia_id") or ""))
            ref_entry.pack(fill='x', ipady=3, pady=2)

            # ── Seletor de referência bíblica (tipo "versiculo") ──
            biblia_versao_var = tk.StringVar()
            biblia_livro_var = tk.StringVar()
            biblia_cap_var = tk.StringVar()
            biblia_vers_var = tk.StringVar()

            biblia_frame = tk.Frame(add_main, bg='#0d1117')
            tk.Label(biblia_frame, text="Referência bíblica:",
                     fg='#f0c040', bg='#0d1117',
                     font=("Arial", 11, "bold")).pack(anchor='w', pady=(6, 0))

            _linha_vers_livro = tk.Frame(biblia_frame, bg='#0d1117')
            _linha_vers_livro.pack(fill='x', pady=2)
            tk.Label(_linha_vers_livro, text="Versão:", fg='#c9d1d9',
                     bg='#0d1117', font=("Arial", 10)).pack(side='left')
            _versoes_sel = []
            _rows_v = db_query(
                "SELECT DISTINCT versao FROM versiculos ORDER BY versao")
            if _rows_v:
                _versoes_sel = [r["versao"] for r in _rows_v]
            if not _versoes_sel:
                _versoes_sel = ["Almeida Revista e Corrigida", "Almeida Século 21"]
            combo_bversao = ttk.Combobox(_linha_vers_livro,
                                         textvariable=biblia_versao_var,
                                         values=_versoes_sel, width=22,
                                         font=("Arial", 10))
            combo_bversao.pack(side='left', padx=(4, 10))
            tk.Label(_linha_vers_livro, text="Livro:", fg='#c9d1d9',
                     bg='#0d1117', font=("Arial", 10)).pack(side='left')
            combo_blivro = ttk.Combobox(_linha_vers_livro,
                                        textvariable=biblia_livro_var,
                                        values=self.LIVROS_BIBLIA, width=16,
                                        font=("Arial", 10))
            combo_blivro.pack(side='left', padx=(4, 0))

            _linha_cap_vers = tk.Frame(biblia_frame, bg='#0d1117')
            _linha_cap_vers.pack(fill='x', pady=2)
            tk.Label(_linha_cap_vers, text="Capítulo:", fg='#c9d1d9',
                     bg='#0d1117', font=("Arial", 10)).pack(side='left')
            entry_bcap = tk.Entry(_linha_cap_vers, textvariable=biblia_cap_var,
                                  width=4, font=("Arial", 10), bg='#21262d',
                                  fg='#f0c040', insertbackground='#f0c040',
                                  bd=0, highlightthickness=0)
            entry_bcap.pack(side='left', padx=(4, 10), ipady=2)
            tk.Label(_linha_cap_vers, text="Versículo"
                     " (ex.: 5, 1-7 ou vazio = capítulo inteiro):",
                     fg='#c9d1d9', bg='#0d1117',
                     font=("Arial", 10)).pack(side='left')
            entry_bvers = tk.Entry(_linha_cap_vers, textvariable=biblia_vers_var,
                                   width=10, font=("Arial", 10), bg='#21262d',
                                   fg='#f0c040', insertbackground='#f0c040',
                                   bd=0, highlightthickness=0)
            entry_bvers.pack(side='left', padx=(4, 8), ipady=2)
            tk.Button(_linha_cap_vers, text="🔍 Ver texto",
                      font=("Arial", 10, "bold"), bg='#21262d', fg='#f0c040',
                      activebackground='#30363d', cursor='hand2',
                      command=lambda: _preview_biblia()
                      ).pack(side='left')

            preview_text = tk.Text(biblia_frame, height=4, wrap='word',
                                   font=("Arial", 9), bg='#161b22', fg='#c9d1d9',
                                   relief='flat', exportselection=False)
            preview_text.pack(fill='x', pady=4)
            preview_text.config(state='disabled')

            def _copiar_previa(widget: tk.Text) -> None:
                try:
                    conteudo = widget.get('1.0', tk.END).strip()
                except tk.TclError:
                    conteudo = ""
                if not conteudo:
                    tkinter.messagebox.showinfo(
                        "Copiar", "Não há conteúdo para copiar.", parent=add_win)
                    return
                add_win.clipboard_clear()
                add_win.clipboard_append(conteudo)

            btn_copia_biblia = tk.Button(
                biblia_frame, text="📋 Copiar", font=("Arial", 9, "bold"),
                bg='#21262d', fg='#f0c040', activebackground='#30363d',
                cursor='hand2', padx=10, pady=1,
                command=lambda: _copiar_previa(preview_text))
            btn_copia_biblia.pack(anchor='e', pady=(0, 2))

            biblia_frame.pack_forget()

            # ── Painel de hino (tipo "hino") ──
            # O operador digita diretamente o Nº do hino (ex.: '46'); o botão
            # "🔍 Ver letra" resolve o número → título/letra da tabela letras e
            # mostra o preview. Salva referencia_id (id da letra) + snapshot.
            hino_num_var = tk.StringVar()
            hino_frame = tk.Frame(add_main, bg='#0d1117')
            tk.Label(hino_frame, text="Buscar hino por número:",
                     fg='#f0c040', bg='#0d1117',
                     font=("Arial", 11, "bold")).pack(anchor='w', pady=(6, 0))

            _linha_hino_num = tk.Frame(hino_frame, bg='#0d1117')
            _linha_hino_num.pack(fill='x', pady=2)
            tk.Label(_linha_hino_num, text="Nº do hino:", fg='#c9d1d9',
                     bg='#0d1117', font=("Arial", 10)).pack(side='left')
            entry_hino_num = tk.Entry(_linha_hino_num, textvariable=hino_num_var,
                                      width=8, font=("Arial", 11), bg='#21262d',
                                      fg='#f0c040', insertbackground='#f0c040',
                                      bd=0, highlightthickness=0)
            entry_hino_num.pack(side='left', padx=(4, 8), ipady=2)
            tk.Label(_linha_hino_num, text="(ou título/artista)",
                     fg='#8b949e', bg='#0d1117',
                     font=("Arial", 9)).pack(side='left')
            tk.Button(_linha_hino_num, text="🔍 Ver letra",
                      font=("Arial", 10, "bold"), bg='#21262d', fg='#f0c040',
                      activebackground='#30363d', cursor='hand2',
                      command=lambda: _ver_letra_hino()
                      ).pack(side='right')

            preview_hino = tk.Text(hino_frame, height=7, wrap='word',
                                   font=("Arial", 9), bg='#161b22', fg='#c9d1d9',
                                   relief='flat', state='disabled',
                                   exportselection=False)
            preview_hino.pack(fill='x', pady=4)

            btn_copia_hino = tk.Button(
                hino_frame, text="📋 Copiar", font=("Arial", 9, "bold"),
                bg='#21262d', fg='#f0c040', activebackground='#30363d',
                cursor='hand2', padx=10, pady=1,
                command=lambda: _copiar_previa(preview_hino))
            btn_copia_hino.pack(anchor='e', pady=(0, 2))

            def _ver_letra_hino():
                """Resolve o nº/termo digitado → letra do hino e mostra preview."""
                res = _resolver_hino()
                if not res[0]:
                    tkinter.messagebox.showwarning("Hino", res[1], parent=janela)
                    return
                _, _, letra_snap, ref_display, _rid = res
                preview_hino.config(state='normal')
                preview_hino.delete('1.0', tk.END)
                preview_hino.insert(tk.END, letra_snap)
                preview_hino.config(state='disabled')

            def _resolver_hino():
                """Resolve hino por nº/termo.

                Retorna (ok, msg_erro, letra_snapshot, ref_display, ref_id).
                Aceita número ('46' → hino cujo título começa com '46') ou
                trecho de título/artista/letra.
                """
                termo = hino_num_var.get().strip()
                if not termo:
                    return (False, "Informe o número do hino (ou título/artista).",
                            "", "", None)
                rows_match = _buscar_hino_por_termo(termo)
                if not rows_match:
                    return (False, f"Nenhum hino encontrado para: \"{termo}\".",
                            "", "", None)
                ref_hino = rows_match[0]
                rid = ref_hino.get("id")
                letra_snap = ref_hino.get("letra_completa", "")
                ref_disp = ref_hino.get("titulo", "") or "Item (Hino)"
                return (True, "", letra_snap, ref_disp, rid)

            # Preenche o painel ao editar um hino existente
            if item_edit and (item_edit.get("tipo") or "").lower() == "hino":
                _hid_ed = item_edit.get("referencia_id")
                if _hid_ed:
                    _rh_ed = db_query("SELECT * FROM letras WHERE id = ? AND ativo = 1",
                                      (_hid_ed,))
                    if _rh_ed:
                        _hh = _rh_ed[0]
                        letra_snap = _hh.get("letra_completa", "") or ""
                if letra_snap:
                    preview_hino.config(state='normal')
                    preview_hino.delete('1.0', tk.END)
                    preview_hino.insert(tk.END, letra_snap)
                    preview_hino.config(state='disabled')

            hino_frame.pack_forget()

            # Preenche o painel ao editar um versículo existente
            if item_edit and (item_edit.get("tipo") or "").lower() == "versiculo":
                _rid_ed = item_edit.get("referencia_id")
                if _rid_ed:
                    _rv_ed = db_query("SELECT * FROM versiculos WHERE id = ?",
                                      (_rid_ed,))
                    if _rv_ed:
                        biblia_versao_var.set(_rv_ed[0]["versao"])
                        biblia_livro_var.set(_rv_ed[0]["livro"])
                        biblia_cap_var.set(str(_rv_ed[0]["capitulo"]))
                        # Item com faixa salva (ex.: "1-7") mostra a faixa
                        # inteira no campo; os demais mostram o versículo só.
                        biblia_vers_var.set(_faixa_versiculo_item(item_edit)
                                            or str(_rv_ed[0]["versiculo"]))

            def _resolver_referencia_biblia():
                """Resolve a referência do painel bíblico.

                O campo "Versículo" aceita um número ("5"), uma faixa
                ("1-7") ou vazio (capítulo inteiro).

                Retorna (ok, msg_erro, letra_snap, ref_display, ref_id,
                versiculos). `versiculos` é a lista de [numero, texto] da
                faixa, que faz o item ser projetado um versículo por slide;
                fica vazia no versículo único e no capítulo inteiro, que
                continuam projetando em um slide só (como antes).
                """
                versao = biblia_versao_var.get().strip()
                livro = biblia_livro_var.get().strip()
                cap = biblia_cap_var.get().strip()
                vers = biblia_vers_var.get().strip()
                if not (versao and livro and cap.isdigit()):
                    return (False,
                            "Selecione a versão, o livro e informe o capítulo.",
                            "", "", None, [])
                cap = int(cap)
                ok_faixa, msg_faixa, v_ini, v_fim = _analisar_faixa_versiculos(vers)
                if not ok_faixa:
                    return (False, msg_faixa, "", "", None, [])
                if v_ini is None:
                    v_ini, v_fim = 1, 9999
                rows = db_query(
                    "SELECT * FROM versiculos WHERE versao = ? AND livro = ? "
                    "AND capitulo = ? AND versiculo >= ? AND versiculo <= ? "
                    "ORDER BY versiculo",
                    (versao, livro, cap, v_ini, v_fim))
                if not rows:
                    return (False,
                            "Nenhum versículo encontrado para "
                            f"{livro} {cap}:{vers or '*'} ({versao}).",
                            "", "", None, [])
                # Um versículo só (ou faixa de um número): comportamento antigo.
                if v_ini == v_fim:
                    r = rows[0]
                    return (True, "",
                            f"{livro} {cap}:{vers}\n\n{r['texto']}",
                            f"{livro} {cap}:{vers}", r["id"], [])
                # Capítulo inteiro: um slide só, como sempre foi.
                if v_ini == 1 and v_fim == 9999:
                    partes = [f"{r['versiculo']}. {r['texto']}" for r in rows]
                    return (True, "",
                            f"{livro} {cap}\n\n" + "\n\n".join(partes),
                            f"{livro} {cap}", rows[0]["id"], [])
                # Faixa ("1-7"): um versículo por slide na projeção.
                faixa_ref = f"{livro} {cap}:{v_ini}-{v_fim}"
                partes = [f"{r['versiculo']}. {r['texto']}" for r in rows]
                return (True, "",
                        f"{faixa_ref}\n\n" + "\n\n".join(partes),
                        faixa_ref, rows[0]["id"],
                        [[r['versiculo'], r['texto']] for r in rows])

            def _preview_biblia():
                res = _resolver_referencia_biblia()
                preview_text.config(state='normal')
                preview_text.delete('1.0', tk.END)
                preview_text.insert(tk.END, res[1] if not res[0] else res[2])
                preview_text.config(state='disabled')

            # ── Seletor de anúncio (tipo "anuncio") ──
            anuncio_var = tk.StringVar()
            _anuncios_sel = _listar_anuncios_db()
            _anuncios_titulos = [(a.get("titulo") or "").strip()
                                 for a in _anuncios_sel]

            anuncio_frame = tk.Frame(add_main, bg='#0d1117')
            tk.Label(anuncio_frame, text="Anúncio:",
                     fg='#f0c040', bg='#0d1117',
                     font=("Arial", 11, "bold")).pack(anchor='w', pady=(6, 0))
            combo_anun = ttk.Combobox(anuncio_frame, textvariable=anuncio_var,
                                      values=_anuncios_titulos, width=44,
                                      font=("Arial", 10))
            combo_anun.pack(fill='x', pady=(0, 2))
            anun_preview = tk.Text(anuncio_frame, height=3, wrap='word',
                                   font=("Arial", 9), bg='#161b22', fg='#c9d1d9',
                                   relief='flat', exportselection=False)
            anun_preview.pack(fill='x', pady=(0, 4))
            anun_preview.config(state='disabled')

            btn_copia_anuncio = tk.Button(
                anuncio_frame, text="📋 Copiar", font=("Arial", 9, "bold"),
                bg='#21262d', fg='#f0c040', activebackground='#30363d',
                cursor='hand2', padx=10, pady=1,
                command=lambda: _copiar_previa(anun_preview))
            btn_copia_anuncio.pack(anchor='e', pady=(0, 4))

            def _preview_anuncio(event: object = None):
                sel = anuncio_var.get().strip()
                an = next((a for a in _anuncios_sel
                           if (a.get("titulo") or "").strip() == sel), None)
                anun_preview.config(state='normal')
                anun_preview.delete('1.0', tk.END)
                if an:
                    cat = (an.get("categoria") or "").strip()
                    texto = (an.get("texto") or "").strip()
                    anun_preview.insert(
                        tk.END, ((cat + "\n") if cat else "") + texto[:500])
                else:
                    anun_preview.insert(
                        tk.END, "Selecione o anúncio na lista acima.")
                anun_preview.config(state='disabled')

            combo_anun.bind("<<ComboboxSelected>>", _preview_anuncio)

            anuncio_frame.pack_forget()

            # Preenche o painel ao editar um anúncio existente
            if item_edit and (item_edit.get("tipo") or "").lower() == "anuncio":
                _an_ed = _buscar_anuncio_por_ref(item_edit.get("referencia_id"))
                if _an_ed:
                    anuncio_var.set((_an_ed.get("titulo") or "").strip())
                    _preview_anuncio()

            tk.Label(add_main, text="Duração estimada (segundos):", fg='#8b949e',
                     bg='#0d1117', font=("Arial", 9)).pack(anchor='w')
            dur_entry = tk.Entry(add_main, font=("Arial", 11), bg='#21262d',
                                 fg='#c9d1d9', insertbackground='#f0c040')
            dur_entry.insert(0, str((item_edit or {}).get("duracao_estimada_segundos") or 0))
            dur_entry.pack(fill='x', ipady=3, pady=2)

            arquivo_path_var = tk.StringVar(
                value=(item_edit or {}).get("caminho_arquivo") or "")

            arquivo_frame = tk.Frame(add_main, bg='#0d1117')
            tk.Label(arquivo_frame, text="Arquivo (vídeo/áudio/PowerPoint/Impress/PDF):",
                     fg='#8b949e', bg='#0d1117',
                     font=("Arial", 9)).pack(anchor='w')
            arquivo_row = tk.Frame(arquivo_frame, bg='#0d1117')
            arquivo_row.pack(fill='x', pady=2)
            arquivo_nome_lbl = tk.Label(
                arquivo_row,
                text=os.path.basename(arquivo_path_var.get()) or
                     "Nenhum arquivo selecionado",
                fg='#c9d1d9', bg='#21262d', font=("Arial", 10),
                anchor='w', padx=6, pady=3, width=1)
            arquivo_nome_lbl.pack(side='left', fill='x', expand=True)

            def _selecionar_arquivo():
                _sufixos = (
                    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v",
                    ".flv", ".mp3", ".wav", ".ogg", ".oga", ".m4a", ".flac",
                    ".aac", ".wma", ".ppt", ".pptx", ".pps", ".ppsx", ".odp",
                )
                _titulo_busca = "Selecionar vídeo, áudio ou apresentação"
                if tipo_var.get() == "sermao":
                    # Sermão também aceita PDF (aberto no visualizador do
                    # sistema, como a apresentação).
                    _sufixos = _sufixos + (".pdf",)
                    _titulo_busca = "Selecionar vídeo, áudio, apresentação ou PDF"
                # Usa o seletor do próprio aplicativo (inicia no home do
                # usuário, esconde os "." ocultos e não "pisca" como o
                # diálogo nativo do Tk/GTK).
                escolhidos = _escolher_arquivos_usuario(
                    parent=add_win,
                    titulo=_titulo_busca,
                    pasta_inicial=os.path.expanduser("~"),
                    sufixos=_sufixos)
                if not escolhidos:
                    return
                caminho = escolhidos[0]
                arquivo_path_var.set(caminho)
                arquivo_nome_lbl.config(text=os.path.basename(caminho))
                if not titulo_entry.get().strip() or \
                        titulo_entry.get().strip().startswith("Item "):
                    _nome_base = os.path.splitext(os.path.basename(caminho))[0]
                    titulo_entry.delete(0, tk.END)
                    titulo_entry.insert(0, _nome_base)

            def _limpar_arquivo():
                arquivo_path_var.set("")
                arquivo_nome_lbl.config(text="Nenhum arquivo selecionado")

            tk.Button(arquivo_row, text="📁 Buscar", font=("Arial", 10, "bold"),
                      bg='#1f6feb', fg='white', activebackground='#388bfd',
                      cursor='hand2', padx=10,
                      command=_selecionar_arquivo
                      ).pack(side='left', padx=(5, 0))
            tk.Button(arquivo_row, text="❌", font=("Arial", 10, "bold"),
                      bg='#da3633', fg='white', activebackground='#f85149',
                      cursor='hand2', padx=8, command=_limpar_arquivo
                      ).pack(side='left', padx=(3, 0))
            arquivo_frame.pack_forget()

            # ── Item "YouTube" (caixinha + URL) ──
            # Só aparece quando o tipo é "Vídeo" (ou na edição de um item que
            # já é YouTube): marcando a caixinha, o item passa a ser um vídeo
            # do YouTube e a URL é usada na execução (mpv + yt-dlp).
            youtube_var = tk.BooleanVar(
                value=((item_edit or {}).get("tipo") or "").lower() == "youtube"
                or bool((item_edit or {}).get("youtube_url")))
            youtube_url_var = tk.StringVar(
                value=(item_edit or {}).get("youtube_url") or "")

            youtube_frame = tk.Frame(add_main, bg='#0d1117')
            tk.Checkbutton(
                youtube_frame, text="YouTube", variable=youtube_var,
                bg='#0d1117', fg='#f0c040', selectcolor='#21262d',
                activebackground='#0d1117', activeforeground='#f0c040',
                font=("Arial", 11, "bold"),
                command=lambda: _atualizar_youtube()
            ).pack(anchor='w')

            youtube_url_row = tk.Frame(youtube_frame, bg='#0d1117')
            tk.Label(youtube_url_row, text="URL do vídeo:",
                     fg='#c9d1d9', bg='#0d1117',
                     font=("Arial", 10)).pack(side='left')
            tk.Entry(youtube_url_row, textvariable=youtube_url_var,
                     font=("Arial", 10), bg='#21262d', fg='#c9d1d9',
                     insertbackground='#f0c040').pack(
                side='left', fill='x', expand=True, padx=(4, 0), ipady=2)

            def _atualizar_youtube():
                if youtube_var.get():
                    youtube_url_row.pack(fill='x', pady=(2, 0))
                else:
                    youtube_url_row.pack_forget()

            _atualizar_youtube()

            # A janela é posicionada UMA única vez, na abertura, já
            # centralizada sobre a janela "Ordem de Serviço" (via
            # _centralizar_sobre, acima). Ao trocar o tipo do item, aplicamos
            # a geometria só com o TAMANHO (sem coordenadas): o Tk/gerenciador
            # de janelas mantém a posição atual, inclusive depois de o
            # operador arrastar a janela. Reenviar coordenadas era o que fazia
            # a janela saltar (o pedido era reinterpretado com o deslocamento
            # da moldura e ia parar no canto superior esquerdo).
            def _aplicar_geometria(tamanho: str) -> None:
                """Redimensiona a janela do editor sem mudar a posição."""
                try:
                    add_win.geometry(tamanho)
                except tk.TclError:
                    pass

            def _atualizar_paineis():
                t = tipo_var.get()
                if t in ("video", "audio", "sermao"):
                    arquivo_frame.pack(fill='x')
                else:
                    arquivo_frame.pack_forget()
                if t == "versiculo":
                    biblia_frame.pack(fill='x', pady=(2, 0))
                else:
                    biblia_frame.pack_forget()
                if t == "hino":
                    hino_frame.pack(fill='x', pady=(2, 0))
                else:
                    hino_frame.pack_forget()
                if t == "anuncio":
                    anuncio_frame.pack(fill='x', pady=(2, 0))
                else:
                    anuncio_frame.pack_forget()
                # YouTube (caixinha + URL) só tem sentido com o tipo "Vídeo"
                # (ou na edição de um item que já é YouTube). Ao sair do
                # vídeo a caixinha é desmarcada — senão o _salvar_item forçaria
                # tipo "youtube" por baixo do tipo que o operador acabou de
                # marcar.
                if t in ("video", "youtube"):
                    youtube_frame.pack(fill='x', pady=(6, 0))
                else:
                    youtube_frame.pack_forget()
                    youtube_var.set(False)
                _aplicar_geometria("700x600" if t == "versiculo"
                                   else "700x600" if t == "hino"
                                   else "700x510" if t == "anuncio"
                                   else "700x450")

            tipo_var.trace_add("write", lambda *a: _atualizar_paineis())
            _atualizar_paineis()
            # A janela nasce com 380 de altura e cresce ao mostrar o painel do
            # tipo inicial; centraliza de novo com o tamanho final para não
            # abrir deslocada para baixo. Depois disto a posição nunca mais é
            # reenviada (os redimensionamentos aplicam só o tamanho).
            _centralizar_sobre(add_win, janela)

            def _salvar_item():
                serv = _servico_atual()
                if serv is None:
                    return
                tipo = tipo_var.get()
                titulo = titulo_entry.get().strip()
                termo = ref_entry.get().strip()
                duracao = int(dur_entry.get().strip()) if dur_entry.get().strip().isdigit() else 0
                caminho_arquivo = arquivo_path_var.get().strip()
                # Caixinha "YouTube": quando marcada, o item vira um vídeo do
                # YouTube e guarda a URL (em vez de um arquivo em disco).
                youtube_url = ""
                if youtube_var.get():
                    youtube_url = youtube_url_var.get().strip()
                    if not _eh_url(youtube_url):
                        tkinter.messagebox.showwarning(
                            "YouTube",
                            "Informe a URL do vídeo (começando com http:// "
                            "ou https://).", parent=janela)
                        return
                    tipo = "youtube"
                    caminho_arquivo = ""
                if tipo == "youtube" and not youtube_url:
                    # Caixinha desmarcada num item que era YouTube: evita
                    # salvar "youtube" sem URL (que ficaria sem mídia).
                    tipo = "slide"
                if tipo not in ("video", "audio", "sermao"):
                    caminho_arquivo = ""

                # Verdadeiro quando o usuário usou o seletor bíblico do
                # painel "versiculo" (versão + livro + capítulo preenchidos).
                _usou_painel_biblia = bool(
                    tipo == "versiculo"
                    and biblia_versao_var.get().strip()
                    and biblia_livro_var.get().strip()
                    and biblia_cap_var.get().strip().isdigit())
                _usou_painel_anuncio = bool(
                    tipo == "anuncio" and anuncio_var.get().strip())
                _usou_painel_hino = bool(
                    tipo == "hino" and hino_num_var.get().strip())

                # ── Resolução da referência por busca (nº ou nome) ──
                # Se o campo "Buscar" estiver vazio, o próprio Título digitado
                # já é usado como termo de busca (hino/mídia por número ou nome).
                ref_id = None
                letra_snap = ""
                vers_salvos = []
                _usou_titulo_como_busca = (not termo)
                if not termo:
                    termo = titulo
                if tipo == "hino" and _usou_painel_hino:
                    res_h = _resolver_hino()
                    if not res_h[0]:
                        tkinter.messagebox.showwarning("Hino", res_h[1],
                                                       parent=janela)
                        return
                    _, _, letra_snap, ref_display, ref_id = res_h
                    if not titulo or _usou_titulo_como_busca:
                        titulo = ref_display
                elif tipo == "hino":
                    rows_match = _buscar_hino_por_termo(termo)
                    if not rows_match and termo.isdigit():
                        rows_match = db_query(
                            "SELECT * FROM letras WHERE id = ? AND ativo = 1", (termo,))
                    if not rows_match:
                        tkinter.messagebox.showwarning(
                            "Busca", f"Nenhum hino encontrado para: \"{termo}\".",
                            parent=janela)
                        return
                    ref_hino = rows_match[0]
                    ref_id = ref_hino.get("id")
                    letra_snap = ref_hino.get("letra_completa", "")
                    if not titulo or _usou_titulo_como_busca:
                        titulo = ref_hino.get("titulo", "") or f"Item ({tipo.title()})"
                elif tipo in ("video", "audio", "sermao") and caminho_arquivo:
                    if not os.path.exists(caminho_arquivo):
                        tkinter.messagebox.showwarning(
                            "Arquivo", f"Arquivo não encontrado:\n{caminho_arquivo}",
                            parent=janela)
                        return
                    if not titulo or _usou_titulo_como_busca:
                        titulo = (os.path.splitext(os.path.basename(caminho_arquivo))[0]
                                  or f"Item ({tipo.title()})")
                elif tipo in ("video", "audio"):
                    rows_match = _buscar_midia_por_termo(termo, tipo=tipo)
                    if not rows_match and termo.isdigit():
                        rows_match = db_query(
                            "SELECT * FROM midia WHERE id = ? AND ativo = 1", (termo,))
                    if not rows_match:
                        tkinter.messagebox.showwarning(
                            "Busca", f"Nenhuma {tipo.title()} encontrada para: \"{termo}\".",
                            parent=janela)
                        return
                    ref_midia = rows_match[0]
                    ref_id = ref_midia.get("id")
                    if not titulo or _usou_titulo_como_busca:
                        titulo = ref_midia.get("nome_exibicao", "") or f"Item ({tipo.title()})"
                elif tipo == "anuncio" and _usou_painel_anuncio:
                    ref_an = next(
                        (a for a in _anuncios_sel
                         if (a.get("titulo") or "").strip()
                         == anuncio_var.get().strip()), None)
                    if ref_an is None:
                        tkinter.messagebox.showwarning(
                            "Anúncios",
                            "O anúncio selecionado não foi encontrado.",
                            parent=janela)
                        return
                    ref_id = ref_an.get("id")
                    letra_snap = ref_an.get("texto") or ""
                    if not titulo or _usou_titulo_como_busca:
                        titulo = ref_an.get("titulo") or f"Item ({tipo.title()})"
                elif tipo == "anuncio":
                    rows_match = _buscar_anuncio_por_termo(termo)
                    if not rows_match:
                        tkinter.messagebox.showwarning(
                            "Busca", f"Nenhum anúncio encontrado para: \"{termo}\".",
                            parent=janela)
                        return
                    ref_an = rows_match[0]
                    ref_id = ref_an.get("id")
                    letra_snap = ref_an.get("texto") or ""
                    if not titulo or _usou_titulo_como_busca:
                        titulo = ref_an.get("titulo") or f"Item ({tipo.title()})"
                elif tipo == "versiculo" and _usou_painel_biblia:
                    res = _resolver_referencia_biblia()
                    if not res[0]:
                        tkinter.messagebox.showwarning("Bíblia", res[1],
                                                       parent=janela)
                        return
                    _, _, letra_snap, ref_display, ref_id, vers_salvos = res
                    if not titulo or _usou_titulo_como_busca:
                        titulo = ref_display
                elif tipo == "youtube":
                    if not titulo or _usou_titulo_como_busca:
                        titulo = youtube_url or f"Item ({tipo.title()})"
                elif termo.isdigit():
                    ref_id = int(termo)
                if not titulo:
                    titulo = f"Item ({tipo.title()})"
                if tipo == "versiculo" and ref_id and not _usou_painel_biblia:
                    rows_v = db_query("SELECT * FROM versiculos WHERE id = ?", (ref_id,))
                    if rows_v:
                        r = rows_v[0]
                        letra_snap = f"{r['livro']} {r['capitulo']}:{r['versiculo']}\n\n{r['texto']}"
                        if titulo.startswith("Item"):
                            titulo = f"{r['livro']} {r['capitulo']}:{r['versiculo']}"

                itens = serv.setdefault("itens", [])
                if item_edit is not None and (item_edit.get("id") or 0):
                    item_id = item_edit.get("id")
                    idx = next((i for i, x in enumerate(itens)
                                if x.get("id") == item_id), None)
                    if idx is None:
                        return
                    original = dict(itens[idx])
                    itens[idx] = dict(original)
                    itens[idx].pop("versiculos", None)
                    itens[idx].update({
                        "tipo": tipo,
                        "referencia_id": ref_id,
                        "titulo_custom": titulo,
                        "letra_snapshot": letra_snap,
                        "caminho_arquivo": caminho_arquivo,
                        "youtube_url": youtube_url,
                        "duracao_estimada_segundos": duracao,
                    })
                    # Faixa de versículos: guarda os pares [número, texto] para
                    # a projeção mostrar um versículo por slide. Sem faixa,
                    # a chave é removida e o item volta a um slide só.
                    if vers_salvos:
                        itens[idx]["versiculos"] = vers_salvos
                    novo_id = item_id
                else:
                    novo_id = dados["_proximo_id_item"]
                    dados["_proximo_id_item"] = novo_id + 1
                    original = None
                    novo_item = {
                        "id": novo_id,
                        "tipo": tipo,
                        "referencia_id": ref_id,
                        "titulo_custom": titulo,
                        "letra_snapshot": letra_snap,
                        "caminho_arquivo": caminho_arquivo,
                        "youtube_url": youtube_url,
                        "duracao_estimada_segundos": duracao,
                    }
                    if vers_salvos:
                        novo_item["versiculos"] = vers_salvos
                    itens.append(novo_item)
                if not _salvar_servicos_json(dados):
                    if original is not None:
                        itens[idx] = original
                    else:
                        serv["itens"] = [it for it in serv.get("itens")
                                         if it.get("id") != novo_id]
                        dados["_proximo_id_item"] = novo_id
                    tkinter.messagebox.showwarning(
                        "⚠️", "Não foi possível salvar em servicos.json.", parent=janela)
                    return
                _carregar_itens()
                tree.selection_set(str(novo_id))
                tree.focus(str(novo_id))
                add_win.destroy()

            tk.Button(add_main, text="💾 Salvar", font=("Arial", 12, "bold"),
                      bg='#238636', fg='white', activebackground='#2ea043',
                      command=_salvar_item, cursor='hand2', padx=20, pady=5
                      ).pack(pady=10)

        def _editar_item_selecionado():
            serv = _servico_atual()
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showwarning("Seleção", "Selecione um item.", parent=janela)
                return
            if not serv:
                return
            it = next((x for x in (serv.get("itens") or [])
                       if x.get("id") == int(sel[0])), None)
            if it is None:
                return
            _abrir_editor_item(it)

        def _mover_item(direcao: int):
            """Move item para cima (-1) ou baixo (+1)."""
            sel = tree.selection()
            if not sel:
                return
            serv = _servico_atual()
            if not serv:
                return
            itens = list(serv.get("itens") or [])
            idx_atual = next((i for i, it in enumerate(itens)
                              if it.get("id") == int(sel[0])), None)
            if idx_atual is None:
                return
            idx_novo = idx_atual + direcao
            if idx_novo < 0 or idx_novo >= len(itens):
                return
            itens[idx_atual], itens[idx_novo] = itens[idx_novo], itens[idx_atual]
            serv["itens"] = itens
            if not _salvar_servicos_json(dados):
                tkinter.messagebox.showwarning(
                    "⚠️", "Não foi possível salvar a reordenação.", parent=janela)
                return
            _carregar_itens()
            tree.selection_set(str(itens[idx_novo].get("id")))
            tree.focus(str(itens[idx_novo].get("id")))

        # Snapshot da janela principal p/ restauração após cada item do
        # serviço vive em self._snapshot_servico (criado no __init__:
        # capturado uma única vez por sessão, compartilhado com o
        # controle remoto — não reatribuir aqui).

        def _executar_servico():
            """Reproduz APENAS o próximo item da lista e para.

            A escolha do operador vale uma única vez: se ele selecionou um
            item na lista, a próxima reprodução começa nele e o botão passa a
            avançar item a item até o fim da lista, voltando ao primeiro ao
            terminar — a escolha anterior é esquecida. Sem seleção, segue o
            mesmo avanço item a item, do começo ao fim. A lógica real está em
            `executar_proximo_item_servico` (reutilizada pelo controle
            remoto); aqui ficam só a seleção da lista e os diálogos.
            """
            serv = _servico_atual()
            if not serv:
                return
            escolhido = _item_escolhido["id"]
            # Consome a escolha do operador (uma única vez). A partir daqui a
            # seleção da lista é ignorada: o botão só avança item a item e, ao
            # terminar, volta ao primeiro — nunca mais volta ao item escolhido.
            _item_escolhido["id"] = None
            res = self.executar_proximo_item_servico(
                serv, escolhido=escolhido,
                ao_destacar=lambda it: (tree.selection_set(str(it.get('id'))),
                                        tree.see(str(it.get('id')))))
            if not res.get('ok'):
                if res.get('codigo') == 'vazio':
                    tkinter.messagebox.showinfo(
                        "Vazio", res.get('erro', ''), parent=janela)
                else:
                    tkinter.messagebox.showwarning(
                        "Executar", res.get('erro', ''), parent=janela)

        tk.Button(btn_frame, text="➕ Novo Serviço", font=("Arial", 11, "bold"),
                  bg='#238636', fg='white', activebackground='#2ea043',
                  command=_novo_servico, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="✏️ Editar Serviço", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=_editar_servico, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="🗑️ Excluir Item", font=("Arial", 11, "bold"),
                  bg='#da3633', fg='white', activebackground='#f85149',
                  command=_apagar_item_contexto, cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="🔄 Transferir", font=("Arial", 11, "bold"),
                  bg='#2f6f47', fg='white', activebackground='#3f8f57',
                  command=lambda: self.janela_transferencia(janela),
                  cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="➕ Ad. Item", font=("Arial", 11, "bold"),
                  bg='#1f6feb', fg='white', activebackground='#388bfd',
                  command=lambda: _abrir_editor_item(), cursor='hand2', padx=12, pady=4
                  ).pack(side='left', padx=3)
        tk.Button(btn_frame, text="⬆️", font=("Arial", 11, "bold"),
                  bg='#21262d', fg='#f0c040', activebackground='#30363d',
                  command=lambda: _mover_item(-1), cursor='hand2', padx=8, pady=4
                  ).pack(side='left', padx=2)
        tk.Button(btn_frame, text="⬇️", font=("Arial", 11, "bold"),
                  bg='#21262d', fg='#f0c040', activebackground='#30363d',
                  command=lambda: _mover_item(1), cursor='hand2', padx=8, pady=4
                  ).pack(side='left', padx=2)
        tk.Button(btn_frame, text="▶️ Executar Serviço", font=("Arial", 11, "bold"),
                  bg='#6e40c9', fg='#f0c040', activebackground='#8b5cf6',
                  command=_executar_servico, cursor='hand2', padx=12, pady=4
                  ).pack(side='right', padx=3)

        # ── Navegação por teclado dos slides projetados (sem sair da janela) ──
        def _slide_anterior(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            telao.slide_anterior()
            return "break"

        def _slide_proximo(event: object = None):
            telao = self.player.telao
            if not getattr(telao, "_em_slides", False):
                return None
            telao.slide_proximo()
            return "break"

        def _parar_projecao(event: object = None):
            if not getattr(self.player.telao, "mostrando_letra", False):
                return None
            self.player.telao.parar_projecao()
            return "break"

        janela.bind("<Left>", _slide_anterior)
        janela.bind("<Up>", _slide_anterior)
        janela.bind("<Right>", _slide_proximo)
        janela.bind("<Down>", _slide_proximo)
        janela.bind("<Escape>", _parar_projecao)
        self.root.bind("<Left>", _slide_anterior)
        self.root.bind("<Up>", _slide_anterior)
        self.root.bind("<Right>", _slide_proximo)
        self.root.bind("<Down>", _slide_proximo)
        self.root.bind("<Escape>", _parar_projecao)

        _carregar_servicos()
        # Se há serviços, seleciona o primeiro
        if combo_servico['values']:
            _on_servico_select()

    def _reabrir_janelas_de_ordem(self) -> None:
        """Recarrega Anúncios e Ordem de Serviço depois de uma importação.

        As duas janelas leem os dados quando abrem, então a forma segura de
        refletir o que acabou de ser importado é fechá-las e abri-las de novo
        (só as que já estavam abertas).
        """
        alvos = (("Anúncios", self.janela_anuncios),
                 ("Ordem de Serviço", self.janela_ordem_servico))
        for filho in list(self.root.winfo_children()):
            if filho.winfo_class() != 'Toplevel':
                continue
            try:
                titulo = filho.winfo_title()
            except tk.TclError:
                continue
            if "Transferir" in titulo:
                continue
            for trecho, metodo in alvos:
                if trecho in titulo:
                    try:
                        filho.destroy()
                    except tk.TclError:
                        pass
                    getattr(self, metodo)()
                    break

    def janela_transferencia(
            self, parent: tk.Misc | None = None) -> None:
        """Janela para levar anúncios e ordens de serviço a outro computador.

        Exporta um arquivo .navepro (anúncios + ordens + mídias) e importa de
        volta. A importação cria um backup antes de mexer em qualquer coisa.
        """
        janela = tk.Toplevel(self.root)
        janela.title("🔄 Transferir Anúncios e Ordens de Serviço")
        janela.geometry("640x620")
        janela.configure(bg='#0d1117')
        if parent is not None:
            janela.transient(parent)
        _centralizar_sobre(janela, parent if parent is not None else self.root)
        _aplicar_icone_janela(janela)

        estado = {"ocupado": False}
        var_status = tk.StringVar(value="")
        var_modo = tk.StringVar(value="somar")
        botoes: list[tk.Widget] = []

        def _caixa(titulo: str) -> tk.Frame:
            box = tk.Frame(janela, bg='#161b22', highlightthickness=1,
                           highlightbackground='#30363d')
            box.pack(fill='x', padx=14, pady=6, ipady=8)
            tk.Label(box, text=titulo, font=("Arial", 12, "bold"),
                     fg='#f0c040', bg='#161b22').pack(anchor='w', padx=12,
                                                      pady=(8, 2))
            return box

        def _botao(pai, texto: str, bg: str, fg: str, comando) -> tk.Button:
            b = tk.Button(pai, text=texto, font=("Arial", 11, "bold"),
                          bg=bg, fg=fg, activebackground=bg,
                          activeforeground='white', command=comando,
                          cursor='hand2', padx=12, pady=5)
            b.pack(side='left', padx=6)
            botoes.append(b)
            return b

        # ── Explicação ──
        tk.Label(
            janela,
            text=("Gere um arquivo .navepro no computador de origem e importe-o "
                  "no outro.\nVem junto: os anúncios, as ordens de serviço "
                  "(com os itens\napontando para os anúncios certos) e as mídias "
                  "usadas pelos anúncios.\n\n🛡️ Antes de importar, o NavePro "
                  "salva um backup em ~/.navepro/backups —\nnada do que já "
                  "existe é apagado sem esse backup."),
            justify='left', font=("Arial", 10), fg='#c9d1d9', bg='#0d1117',
            wraplength=590).pack(anchor='w', padx=18, pady=(12, 2))

        # ── Exportar ──
        box_exp = _caixa("📤  Exportar deste computador")
        tk.Label(box_exp, font=("Arial", 10), fg='#8b949e', bg='#161b22',
                 justify='left', wraplength=560,
                 text=("Cria um arquivo para levar em um pendrive, e-mail ou "
                       "nuvem. Ele fica, por\npadrão, na pasta que você "
                       "escolher (sugerimos a sua pasta pessoal).")
                 ).pack(anchor='w', padx=12)

        def _exportar():
            if estado["ocupado"]:
                return
            # Seletor do próprio app (e não o diálogo do sistema): mostra só as
            # pastas do usuário, sem as ocultas, e não pisca ao abrir.
            escolhidos = _escolher_arquivos_usuario(
                janela, "Salvar transferência para levar a outro computador",
                pasta_inicial=os.path.expanduser("~"),
                sufixos=(EXTENSAO_TRANSFERENCIA, ".zip"),
                nome_para_salvar=_nome_arquivo_transferencia(
                    prefixo="NavePro-Transferencia"))
            if not escolhidos:
                return
            destino = escolhidos[0]
            incluir = tkinter.messagebox.askyesno(
                "📤 Incluir as mídias dos anúncios?",
                "Incluir imagens, PDFs, áudio e vídeo usados nos anúncios?\n\n"
                "✅ Sim (recomendado): o arquivo fica maior, mas os anúncios\n"
                "    funcionam no outro computador com as mídias.\n\n"
                "⚠️ Não: o arquivo fica pequeno, mas as mídias NÃO vêm junto\n"
                "    (os textos e as ordens vêm de qualquer forma).",
                parent=janela)
            _rodar(
                "Exportando…",
                lambda prog: exportar_transferencia(
                    destino, _listar_anuncios_db(), _carregar_servicos_json(),
                    incluir_midia=incluir, progresso=prog),
                _exportou)

        _botao(box_exp, "📤  Exportar…", '#1f6feb', 'white', _exportar)

        # ── Importar ──
        box_imp = _caixa("📥  Importar para este computador")
        tk.Label(box_imp, font=("Arial", 10), fg='#8b949e', bg='#161b22',
                 justify='left', wraplength=560,
                 text="Escolha o arquivo .navepro e o que fazer com o que já "
                      "existe aqui:"
                 ).pack(anchor='w', padx=12)

        MODOS = (
            ("somar",
             "➕  Somar — acrescenta o que ainda não existe (recomendado)"),
            ("atualizar",
             "🔄  Atualizar — troca o conteúdo do anúncio/ordem de mesmo nome"),
            ("substituir",
             "♻️  Substituir tudo — apaga os anúncios e ordens deste PC"),
        )
        for valor, rotulo in MODOS:
            tk.Radiobutton(box_imp, text=rotulo, variable=var_modo,
                           value=valor, font=("Arial", 10), fg='#c9d1d9',
                           bg='#161b22', selectcolor='#161b22',
                           activebackground='#161b22', activeforeground='#f0c040',
                           cursor='hand2', anchor='w'
                           ).pack(fill='x', padx=14, pady=1)

        def _importar():
            if estado["ocupado"]:
                return
            escolhidos = _escolher_arquivos_usuario(
                janela, "Escolher transferência para importar",
                pasta_inicial=os.path.expanduser("~"),
                sufixos=(EXTENSAO_TRANSFERENCIA, ".zip"))
            if not escolhidos:
                return
            arquivo = escolhidos[0]
            modo = var_modo.get()
            if modo == "substituir" and not tkinter.messagebox.askyesno(
                    "♻️  Substituir tudo mesmo?",
                    "Os anúncios e as ordens de serviço DESTE computador serão\n"
                    "apagados e trocados pelos que estão no arquivo.\n\n"
                    "🛡️ Antes disso, o NavePro salva um backup em\n"
                    "~/.navepro/backups.\n\nTem certeza que deseja continuar?",
                    parent=janela):
                return
            _rodar(
                "Importando…",
                lambda prog: importar_transferencia(
                    arquivo, _carregar_servicos_json(),
                    listar_anuncios=_listar_anuncios_db,
                    inserir_anuncio=_inserir_anuncio_db,
                    atualizar_anuncio=_atualizar_anuncio_db,
                    copiar_midia=_copiar_arquivo_uploads,
                    excluir_anuncios=_excluir_anuncios_db,
                    salvar_servicos=_salvar_servicos_json,
                    modo=modo, progresso=prog),
                _importou)

        _botao(box_imp, "📥  Importar…", '#8b5cf6', 'white', _importar)

        # ── Rodapé ──
        tk.Label(janela, textvariable=var_status, font=("Arial", 10, "bold"),
                 fg='#f0c040', bg='#0d1117', anchor='w', wraplength=600,
                 justify='left').pack(fill='x', padx=18, pady=(10, 2))
        tk.Button(janela, text="Fechar", font=("Arial", 11, "bold"),
                  bg='#21262d', fg='#c9d1d9', activebackground='#30363d',
                  command=janela.destroy, cursor='hand2', padx=16, pady=4,
                  ).pack(pady=(2, 14))

        def _exportou(resumo: dict):
            midia = resumo.get("midia") or 0
            linhas = [f"Arquivo salvo em:\n\n{resumo['destino']}",
                      f"\n{resumo['anuncios']} anúncio(s) e "
                      f"{resumo['servicos']} ordem(ns) de serviço."]
            if midia:
                linhas.append(f"{midia} mídia(s) foram incluídas.")
            elif resumo["anuncios"]:
                linhas.append("\nNenhuma mídia foi incluída (você escolheu "
                              "não incluir).")
            tkinter.messagebox.showinfo(
                "✅ Transferência exportada", "\n".join(linhas), parent=janela)

        def _importou(resumo: dict):
            self._reabrir_janelas_de_ordem()
            linhas = [
                f"Anúncios novos: {resumo['anuncios_novos']}",
                f"Anúncios atualizados: {resumo['anuncios_atualizados']}",
                f"Anúncios mantidos como estavam: {resumo['anuncios_ignorados']}",
                f"Ordens de serviço novas: {resumo['servicos_novos']}",
                f"Ordens atualizadas: {resumo['servicos_atualizados']}",
                f"Mídias copiadas para este computador: {resumo['midia_copiada']}",
            ]
            if resumo.get("backup"):
                linhas.append(f"\n🛡️ Backup do que estava aqui antes:\n"
                              f"{resumo['backup']}")
            if resumo.get("avisos"):
                linhas.append("\nAvisos:\n• " +
                              "\n• ".join(resumo["avisos"][:8]))
            tkinter.messagebox.showinfo(
                "✅ Importação concluída", "\n".join(linhas), parent=janela)

        def _rodar(titulo: str, acao: Callable[[Callable[[str], None]], Any],
                   ao_terminar: Callable[[Any], None]) -> None:
            """Roda a exportação/importação em segundo plano (não trava a tela)."""
            if estado["ocupado"]:
                return
            estado["ocupado"] = True
            var_status.set(titulo)
            for b in botoes:
                b.config(state='disabled')
            res: dict[str, Any] = {}

            def _trabalho():
                import traceback as _tb
                try:
                    res["valor"] = acao(
                        lambda msg: res.__setitem__("progresso", msg))
                except Exception as e:  # noqa: BLE001 - mostra na interface
                    _tb.print_exc()
                    res["erro"] = e

            def _conferir():
                if "progresso" in res:
                    var_status.set(res["progresso"])
                if "erro" in res:
                    _fim()
                    tkinter.messagebox.showerror(
                        "❌ Não foi possível concluir",
                        f"{res['erro']}\n\nNada foi alterado.", parent=janela)
                    return
                if "valor" in res:
                    _fim()
                    ao_terminar(res["valor"])
                    return
                janela.after(150, _conferir)

            def _fim():
                estado["ocupado"] = False
                var_status.set("")
                for b in botoes:
                    b.config(state='normal')

            threading.Thread(target=_trabalho, daemon=True).start()
            janela.after(150, _conferir)



    def _aplicar_temperatura(self, temp: str) -> None:
        """Aplica a temperatura carregada em background na interface."""
        self.temperatura_atual = temp
        log.info(f"🌡️ Temperatura carregada: {temp}")
        if self._temperatura_valida():
            t = getattr(self.player, "telao", None)
            if t is None:
                try:
                    self.player._garantir_telao()  # type: ignore[attr-defined]
                except Exception:
                    pass
                t = getattr(self.player, "telao", None)
            if t is not None:
                try:
                    t._exibir_hora_inicial(temp)
                except Exception:
                    pass
            self.temp_label.config(
                text=f"🌡️ {self.cidade_salva}: {temp}"
            )
        else:
            self.temp_label.config(text="🌡️ Temperatura indisponível")
            self.temperatura_atual = "--"

    def _inicializar_em_segundo_plano(self) -> None:
        """Tarefas de inicialização que rodam após a interface aparecer."""
        # Registra no banco os arquivos de mídia da pasta uploads
        _sincronizar_uploads_midia()
        # Inicia servidor HTTP (API de mídia local + controle remoto)
        self._servidor_thread = ServidorAsyncHTTP()
        self._servidor_thread.ui = self._na_thread_ui
        self._servidor_thread.remoto = self._remoto_despacho
        self._aplicar_acesso_remoto()
        self._servidor_thread.iniciar()
        log.info(f"✅ Servidor async rodando em {BACKEND_URL}")
        
        # Carrega temperatura em thread separada (não bloqueia interface)
        if self.cidade_salva and self.estado_salvo:
            def _carregar_temp():
                temp = obter_temperatura(self.cidade_salva, self.estado_salvo)
                self.root.after(0, lambda: self._aplicar_temperatura(temp))
            threading.Thread(target=_carregar_temp, daemon=True).start()
        
        # Agenda atualização da temperatura a cada 30 minutos (timer cancelável)
        if hasattr(self, '_temp_timer') and self._temp_timer:
            self.root.after_cancel(self._temp_timer)
        self._temp_timer = self.root.after(1_800_000, self.atualizar_temperatura)

        # Verifica (em thread, silencioso) se há versão nova no GitHub
        self.root.after(SEGUNDOS_PARA_VERIFICAR_ATUALIZACAO * 1000,
                        lambda: self.verificar_atualizacao(manual=False))

    # ── Loop principal ────────────────────────────────────────────

    def run(self) -> None:
        """Inicia o loop principal da interface.

        O telão usa update_idletasks() (mais leve) a cada 500ms, mas
        só quando está no modo relógio. Quando o vídeo está tocando
        (mostrando_relogio=False), pula o ciclo desnecessário.
        """
        def _update_telao_lazy() -> None:
            rod = False
            if self.player:
                t = getattr(self.player, "telao", None)
                if t is None:
                    try:
                        self.player._garantir_telao()  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    t = getattr(self.player, "telao", None)
                rod = getattr(t, "rodando", False)
            if rod:
                # Só atualiza se o telão estiver no modo relógio
                # (quando vídeo está tocando, telão está oculto)
                if self.player.telao.mostrando_relogio:
                    self.player.telao.update()
            # Mantém o tema (claro/escuro) aplicado a janelas abertas depois
            self._varrer_toplevels_tema()
            self.root.after(500, _update_telao_lazy)

        _update_telao_lazy()
        self.root.mainloop()

    def fechar(self) -> None:
        """Encerra a aplicação com shutdown completo e ordenado."""
        # Flag para evitar que callbacks disparem durante shutdown
        self._shutting_down = True
        log.info("🛑 Encerrando NavePro...")
        try:
            # 1. Para a reprodução
            if self.player:
                self.player.stop()
                self.player.telao.fechar()
            # 2. Para o worker de busca
            if hasattr(self, 'search_worker'):
                self.search_worker.stop()
            # 3. Para o servidor HTTP
            if hasattr(self, '_servidor_thread') and self._servidor_thread:
                self._servidor_thread.parar()
            # 4. Libera recursos do banco
            if hasattr(self, 'db') and self.db:
                if self.db._conn:
                    try:
                        self.db._conn.close()
                    except Exception:
                        pass
                    self.db._conn = None
        except Exception as e:
            log.exception(f"Erro no shutdown: {e}")
        finally:
            try:
                self.root.destroy()
            except tk.TclError:
                pass
        log.info("✅ NavePro encerrado com sucesso.")


# ────────────────────────────────────────────────────────────────────
# PONTO DE ENTRADA
# ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    configurar_logging()
    log.info("🎵 NavePro - Iniciando...")
    app = AppInterface()
    app.run()