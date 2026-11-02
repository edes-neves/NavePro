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
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.filedialog
import tkinter.messagebox
import tkinter.simpledialog
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime
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
    SUFIXOS_IMAGEM,
)
from navepro.core.ambiente import (
    _ambiente_sem_appimage,
    _eh_appimage,
    _eh_flatpak,
    _eh_windows,
    _tornar_dpi_aware,
)
from navepro.core.anuncios import (
    _atualizar_anuncio_db,
    _buscar_anuncio_por_ref,
    _buscar_anuncio_por_termo,
    _listar_anuncios_db,
    _projetar_anuncio_ordserv,
)
from navepro.core.apresentacao import (
    _ambiente_apresentacao,
    _comando_apresentacao,
    _monitorar_apresentacao,
)
from navepro.core.atualizacao import (
    FORMATO_FLATPAK,
    _buscar_release_latest,
    _comando_atualizacao_flatpak,
    _formato_instalado,
    _ler_checksum_sha256,
    _nome_arquivo_seguro,
    _pasta_downloads,
    _procurar_asset_instalador,
    _procurar_checksum_sha256,
    _rotulo_instalador,
    _sha256_do_arquivo,
    _url_asset_valida,
    _versao_nova,
)
from navepro.core.banco import (
    DatabaseManager,
    db_execute,
    db_query,
)
from navepro.core.busca import SearchWorker
from navepro.core.clima import (
    obter_temperatura,
)
from navepro.core.foco_apresentacao import (
    _agendar_captura_janela_apresentacao,
    _criar_alvo_apresentacao,
    _focar_apresentacao,
)
from navepro.core.fontes_pil import (
    _caixa_texto_padrao,
)
from navepro.core.inicializacao import (
    _sincronizar_uploads_midia,
    criar_backup_diario,
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
    UPLOAD_FOLDER,
    _aplicar_icone_janela,
)

# ────────────────────────────────────────────────────────────────────
# IMPORTS INTERNOS (infraestrutura modularizada)
# ────────────────────────────────────────────────────────────────────
from navepro.core.rede import _ip_da_rede
from navepro.core.servicos import (
    _SERVICO_PROXIMO_ITEM,
    _analisar_faixa_versiculos,
    _carregar_servicos_json,
    _faixa_versiculo_item,
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
    _ssl_context,
)
from navepro.core.tema import _OPCOES_COR_TK, _OPCOES_TEXTO, _cor_clara
from navepro.core.textos import (
    _numero_do_titulo,
    detectar_tipo_arquivo,
)
from navepro.core.util_tk import (
    _centralizar_sobre,
    _normalizar_escala_tk,
)
from navepro.core.widgets_arredondados import TkArredondado

# ────────────────────────────────────────────────────────────────────
# UI DO PAINEL (janelas extraídas do monolito — navepro/ui/)
# ────────────────────────────────────────────────────────────────────
from navepro.ui.apoio import (
    _escolher_arquivos_usuario,
    _menu_contexto_campo,
)
from navepro.ui.config_relogio import ConfigRelogioMixin
from navepro.ui.gerenciador_midias import GerenciadorMidiasMixin
from navepro.ui.janela_anuncios import JanelaAnunciosMixin
from navepro.ui.janela_biblia import JanelaBibliaMixin
from navepro.ui.janela_hinos import JanelaHinosMixin
from navepro.ui.janela_ordem_servico import JanelaOrdemServicoMixin
from navepro.ui.janela_transferencia import JanelaTransferenciaMixin
from navepro.ui.navegacao import NavegacaoSlidesMixin
from navepro.ui.painel import PainelMixin

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


# ────────────────────────────────────────────────────────────────────
# HELPERS DE UI DO PAINEL (menu de contexto, colar, seletor de arquivos,
# faixas de seção e listagem de mídias ativas)
# (movido para navepro/ui/apoio.py e navepro/core/banco.py —
#  ver "IMPORTS INTERNOS" no topo)
# ────────────────────────────────────────────────────────────────────


class AppInterface(NavegacaoSlidesMixin, JanelaHinosMixin, JanelaBibliaMixin, JanelaAnunciosMixin, JanelaOrdemServicoMixin, JanelaTransferenciaMixin, GerenciadorMidiasMixin, ConfigRelogioMixin, PainelMixin):
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
        # Tamanho mínimo e estado inicial maximizado.
        # O app precisa funcionar de 1024x768 até resoluções maiores: o mínimo
        # fica abaixo da altura útil de 768 (descontando barra de tarefas) para
        # a janela sempre caber na menor resolução suportada.
        self.root.minsize(900, 620)
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
        # Apresentação (PowerPoint/Impress) aberta pelo serviço: guarda o
        # caminho/PID e a janela do slide show para devolver o foco quando
        # uma projeção de versículo terminar.
        self._apresentacao_alvo: dict | None = None
        
        self.cidade_salva: str = self.config_data.get("cidade", "")
        self.estado_salvo: str = self.config_data.get("estado", "")
        self.temperatura_atual: str = ""

        self._focus_timer: str | None = None
        self._debounce_timer: str | None = None

        log.info(f"🎮 Player: {self.player_cmd} | Monitor: {self.monitor_index}")

        # Garante recursos
        criar_backup_diario()
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
            self._registrar_foco_apresentacao_telao(t)

        # Estado dos medidores (cronômetro / contagem regressiva)
        self._crono = {
            "rodando": False, "pausado": False,
            "inicio": 0.0, "acumulado": 0.0, "timer_id": None,
        }
        self._contagem = {
            "rodando": False, "pausado": False,
            "fim": 0.0, "restante": 0.0, "total": 0.0, "timer_id": None,
        }
        # Medidor que o operador deixou projetado ("contagem"/"cronometro"/None):
        # usado para reprojetá-lo quando uma projeção comum (slide/letra) ou
        # música/vídeo termina, em vez de o relógio voltar por cima da frase.
        self._medidor_projetado: str | None = None

        # Relógio/temperatura ocultos no telão pelo operador (só na sessão).
        self._relogio_oculto_telao = False

        # Quando o telão for fechado (Esc/Ctrl+Q) e recriado pelo player,
        # reaplica a aparência configurada e volta a mostrar a hora inicial.
        def _reaplicar_telao_recriado(novo_telao) -> None:
            try:
                novo_telao.configurar_projecao(
                    self.config_data.get("projecao", {}))
                novo_telao.configurar_relogio(
                    self.config_data.get("relogio", {}))
                novo_telao.definir_relogio_oculto(self._relogio_oculto_telao)
                novo_telao._exibir_hora_inicial()
                self._registrar_foco_apresentacao_telao(novo_telao)
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
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, indent=2)
            # O config.json guarda o token do controle remoto: restringe a
            # leitura ao próprio usuário (no Windows a proteção real vem
            # das permissões do perfil; o chmod não atrapalha).
            os.chmod(CONFIG_FILE, 0o600)
        except Exception as e:
            log.exception(f"Erro ao salvar config de remoto: {e}")
        self._aplicar_acesso_remoto()
        info = self.info_controle_remoto()
        # Nunca loga a URL completa: ela carrega o token na query (?t=).
        log.info(('🌐 Controle remoto ATIVADO' if ativo
               else '📴 Controle remoto desativado')
              + (f" — http://{info['ip']}:{BACKEND_PORT}/ (token protegido)"
                 if ativo else ''))
        return info

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

        _menu_contexto_campo(entry_url, [("📋 Copiar", _copiar)])

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
                _cmd_apres = _comando_apresentacao(
                    caminho, windows=_eh_windows(), flatpak=_eh_flatpak())
                _env_apres = _ambiente_sem_appimage()
                if not _eh_windows():
                    if _monitorar_apresentacao(_cmd_apres):
                        # Mantém o slide show no XWayland
                        # (ver foco_apresentacao).
                        _env_apres = _ambiente_apresentacao(_env_apres)
                    # O LibreOffice abre as janelas no monitor da janela
                    # ativa. Devolve o foco ao painel (primário) antes de
                    # lançar, senão editor e apresentação podem nascer os
                    # dois no telão.
                    try:
                        self.root.lift()
                        self.root.focus_force()
                        self.root.update_idletasks()
                    except tk.TclError:
                        pass
                try:
                    _proc_apres = subprocess.Popen(
                        _cmd_apres, start_new_session=True,
                        env=_env_apres)
                except Exception as e:
                    log.exception(f"❌ Erro ao abrir apresentação/PDF: {e}")
                    iniciado = False
                else:
                    iniciado = True
                    # Guarda a apresentação aberta e captura a janela do
                    # slide show em segundo plano: quando a projeção de um
                    # versículo terminar, o foco volta para ela.
                    _alvo_anterior = self._apresentacao_alvo
                    if _alvo_anterior is not None:
                        _alvo_anterior["cancelado"] = True
                    try:
                        _geom_monitor_apres = self.player._get_monitor_geometry()
                    except Exception:
                        _geom_monitor_apres = None
                    _geom_painel_apres = None
                    if getattr(self, "_monitor_geo", None):
                        _mw, _mh, _mx, _my = self._monitor_geo
                        _geom_painel_apres = (_mx, _my, _mw, _mh)
                    _alvo_apres = _criar_alvo_apresentacao(
                        caminho, getattr(_proc_apres, "pid", None),
                        _geom_monitor_apres, _geom_painel_apres)
                    self._apresentacao_alvo = _alvo_apres
                    _agendar_captura_janela_apresentacao(
                        self.root, _alvo_apres)
                    if _monitorar_apresentacao(_cmd_apres):
                        # Monitora o fim da apresentação e restaura o telão
                        def _monitor_apres():
                            _rc = _proc_apres.poll()
                            if _rc is not None:
                                _alvo_atual = getattr(
                                    self, "_apresentacao_alvo", None)
                                if _alvo_atual is _alvo_apres:
                                    _alvo_apres["cancelado"] = True
                                    self._apresentacao_alvo = None
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
            if acao == 'biblia_opcoes':
                return self._remoto_biblia_opcoes(dados)
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
            if acao == 'sorteio_estado':
                return self._remoto_sorteio_estado()
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
            if acao == 'sorteio_abrir':
                return self._remoto_sorteio_abrir()
            if acao == 'sorteio_fechar':
                return self._remoto_sorteio_fechar()
            if acao == 'sorteio_configurar':
                return self._remoto_sorteio_configurar(dados)
            if acao == 'sorteio_sortear':
                return self._remoto_sorteio_sortear()
            if acao == 'sorteio_reiniciar':
                return self._remoto_sorteio_reiniciar()
            return {'ok': False, 'erro': f'Ação desconhecida: {acao}'}
        except Exception as exc:  # noqa: BLE001 — vira JSON de erro
            log.exception(f"❌ Erro na ação remota '{acao}': {exc}")
            return {'ok': False, 'erro': str(exc) or type(exc).__name__}

    def _remoto_sorteio_estado(self) -> dict:
        """Estado do Sorteio Profissional (para o controle remoto)."""
        from navepro.sorteio.integracao import estado_sorteio
        return {'ok': True, **estado_sorteio(self)}

    def _remoto_sorteio_abrir(self) -> dict:
        """Abre (ou traz para frente) a janela do Sorteio pelo celular."""
        from navepro.sorteio.integracao import estado_sorteio
        self.abrir_sorteio()
        return {'ok': True, **estado_sorteio(self)}

    def _remoto_sorteio_fechar(self) -> dict:
        """Fecha a janela do Sorteio pelo celular."""
        from navepro.sorteio.integracao import fechar_sorteio
        return fechar_sorteio(self)

    def _remoto_sorteio_configurar(self, dados: dict) -> dict:
        """Configura o sorteio (faixa/nomes) pelo celular."""
        from navepro.sorteio.integracao import configurar_sorteio
        return configurar_sorteio(self, dados)

    def _remoto_sorteio_sortear(self) -> dict:
        """Faz o próximo sorteio pelo celular (via janela do operador)."""
        from navepro.sorteio.integracao import sortear
        return sortear(self)

    def _remoto_sorteio_reiniciar(self) -> dict:
        """Limpa/reinicia o sorteio pelo celular."""
        from navepro.sorteio.integracao import reiniciar
        return reiniciar(self)

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
          - vazio   → o capítulo inteiro
          - "7"     → somente o versículo 7
          - "1-7"   → somente os versículos de 1 a 7
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
        else:
            # Número único ("7") = só ele; faixa ("1-7") respeita o fim
            # digitado (16-16 = só o 16).
            v_ini, v_fim = ini, fim
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

    def _remoto_biblia_opcoes(self, dados: dict) -> dict:
        """Opções dos combos "Cap:"/"V:" da aba Bíblia (controle remoto).

        Mesmos ``SELECT DISTINCT`` da janela Bíblia (``_atualizar_opcoes_*``):
        os capítulos seguem versão+livro e os versículos dependem do capítulo
        informado (vazio/não numérico → sem opções, como o combo do app).
        """
        versao = str(dados.get('versao') or '').strip()
        livro = str(dados.get('livro') or '').strip()
        cap = str(dados.get('cap') or '').strip()
        if not versao:
            versoes = self._versoes_biblia()
            versao = versoes[0] if versoes else ''
        capitulos = [str(r.get('capitulo')) for r in db_query(
            "SELECT DISTINCT capitulo FROM versiculos "
            "WHERE versao = ? AND livro = ? ORDER BY capitulo",
            (versao, livro))] if (versao and livro) else []
        versiculos = []
        if cap.isdigit() and versao and livro:
            versiculos = [str(r.get('versiculo')) for r in db_query(
                "SELECT DISTINCT versiculo FROM versiculos "
                "WHERE versao = ? AND livro = ? AND capitulo = ? "
                "ORDER BY versiculo", (versao, livro, int(cap)))]
        return {'ok': True, 'capitulos': capitulos, 'versiculos': versiculos}

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
        letra = (item.get('letra_snapshot') or '').strip()
        linhas = [ln.strip() for ln in letra.splitlines() if ln.strip()]
        if tipo == 'versiculo' and len(linhas) > 1:
            linhas = linhas[1:]
        previa = ' '.join(linhas)
        if len(previa) > 180:
            previa = previa[:177].rstrip() + '...'
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
                'detalhe': detalhe, 'previa': previa,
                'caminho_arquivo': item.get('caminho_arquivo') or '',
                'youtube_url': item.get('youtube_url') or '',
                'ref': ref}

    def _remoto_resolver_item(self, dados: dict) -> tuple:
        """Resolve um item da Ordem de Serviço vindo do celular.

        Replica, sem Tk, a lógica da janela "Adicionar Item" do aplicativo
        (hino/versículo/vídeo/áudio/sermão/anúncio/slide/youtube). Retorna
        (ok, msg_erro, campos), já com as chaves prontas para gravar em
        servicos.json (inclui 'versiculos' quando for uma faixa).
        """
        tipo = str(dados.get('tipo') or 'hino').strip().lower()
        titulo = str(dados.get('titulo') or '').strip()
        termo = str(dados.get('termo') or '').strip()
        caminho_arquivo = str(dados.get('caminho_arquivo') or '').strip()
        youtube_url = str(dados.get('youtube_url') or '').strip()
        try:
            duracao = int(dados.get('duracao') or 0)
        except (TypeError, ValueError):
            duracao = 0
        if tipo not in ('hino', 'versiculo', 'video', 'audio', 'slide',
                        'anuncio', 'sermao', 'youtube'):
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
        elif tipo == 'youtube':
            if not _eh_url(youtube_url):
                return (False,
                        'Informe a URL do vídeo (começando com http:// ou '
                        'https://).', {})
            caminho_arquivo = ''
            if not titulo:
                titulo = youtube_url or f'Item ({tipo.title()})'
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
            'youtube_url': youtube_url,
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
        """Persiste a configuração de aparência do relógio e aplica ao telão.

        O dict pode incluir os campos do medidor (contagem/cronômetro)
        preservados pelo diálogo, para eles não se perderem ao salvar.
        """
        self.config_data["relogio"] = cfg
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config_data, f, indent=2)
        except Exception as e:
            log.exception(f"Erro ao salvar config do relógio: {e}")
        if self.player and self.player.telao:
            self.player.telao.configurar_relogio(cfg)


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

    def _registrar_foco_apresentacao_telao(self, telao) -> None:
        """Registra no telão o retorno de foco para a apresentação aberta.

        Precisa ser reaplicado sempre que o telão é recriado pelo player.
        """
        if telao is None:
            return
        try:
            telao.definir_retorno_apresentacao(self._ao_encerrar_projecao)
        except Exception as e:
            log.warning(f"⚠️ Falha ao registrar foco da apresentação: {e}")

    def _ao_encerrar_projecao(self) -> None:
        """Devolve o foco ao PowerPoint/Impress ao fim de uma projeção.

        Chamado pelo telão depois de restaurar o relógio/medidor. Se a
        apresentação já tiver sido fechada, `_focar_apresentacao` recusa e
        nada é trazido para a frente.
        """
        alvo = getattr(self, "_apresentacao_alvo", None)
        if not alvo:
            return
        try:
            _focar_apresentacao(alvo)
        except Exception as e:
            log.warning(f"⚠️ Falha ao devolver foco à apresentação: {e}")


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
            # No claro, a captura das cores escuras de origem precisa rodar
            # ANTES de qualquer pintura: alguns pais (CampoArredondado)
            # empurram bg/fg para o filho ao serem recoloridos e, se a cor
            # clara chegasse primeiro, ela seria gravada como se fosse a
            # escura (campos Cidade/UF/busca voltavam claros no escuro).
            if self.tema == 'claro':
                self._recolorir_arvore(self.root, capturar=True)
            self._recolorir_arvore(self.root)
            # O campo de resultados é recolorido à parte (fica fora do passe
            # genérico para o cinza claro não distorcer a cada visita).
            self._pintar_lista_cores()
        except tk.TclError:
            pass
        # Rede de segurança: garante o fundo correto de Cidade/UF/busca em
        # cada tema, mesmo que o passe genérico tenha deixado para trás.
        self._garantir_campos_tema()
        # Mantém o Sorteio Profissional (quando aberto) no mesmo tema.
        sync_sorteio = getattr(self, '_sorteio_sync_tema', None)
        if sync_sorteio is not None:
            try:
                sync_sorteio()
            except Exception as e:
                log.debug("Falha ao sincronizar o tema do sorteio: %s", e)

    def _garantir_campos_tema(self) -> None:
        """Reafirma, por tema, a cor de fundo dos campos Cidade/UF/busca.

        Independente do passe genérico de recoloração (que depende das cores
        de origem gravadas). As cores reafirmadas são exatamente as corretas
        de cada tema, então nada muda quando o passe genérico já acertou —
        só corrige o caso em que um campo tivesse ficado com a cor do outro
        tema (ex.: Cidade/UF/busca claros no tema escuro).
        """
        claro = self.tema == 'claro'
        # Cidade/UF: CampoArredondado (área cinza); no escuro usa o próprio
        # fundo escuro gravado ao marcar o campo.
        for campo in (getattr(self, 'entry_cidade', None),
                      getattr(self, 'entry_estado', None)):
            if campo is None:
                continue
            if claro:
                alvo = _cor_clara('#eaeef2')
            else:
                alvo = getattr(
                    campo, '_navepro_area_cinza_escuro', '#eaeef2')
            try:
                campo.configure(bg=alvo)
            except tk.TclError:
                pass
        # Busca: fundo escuro próprio (#21262d) e o mesmo cinza claro.
        busca = getattr(self, 'entry_busca', None)
        if busca is not None:
            try:
                busca.configure(bg=_cor_clara('#21262d') if claro else '#21262d')
            except tk.TclError:
                pass

    def _aplicar_tema_ttk(self) -> None:
        """Ajusta os estilos globais ttk (Treeview/Scrollbar) ao tema."""
        try:
            style = ttk.Style()
            if self.tema == 'claro':
                style.configure(
                    "Treeview",
                    background=_cor_clara('#21262d'), foreground='#1f2328',
                    fieldbackground=_cor_clara('#21262d'), font=("Arial", 10))
                style.configure(
                    "Treeview.Heading",
                    background=_cor_clara('#161b22'), foreground='#1f2328',
                    font=("Arial", 10, "bold"))
                style.map('Treeview',
                          background=[('selected', '#0969da')],
                          foreground=[('selected', '#ffffff')])
                style.configure(
                    "Vertical.TScrollbar",
                    background=_cor_clara('#21262d'), troughcolor=_cor_clara('#161b22'),
                    arrowcolor='#1f2328')
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

    def _recolorir_arvore(self, base, capturar: bool = False) -> None:
        """Aplica a recoloração de tema a `base` e a todos os seus filhos.

        Com `capturar=True` faz só a passada de captura das cores de origem
        (sem pintar), que precisa ocorrer para toda a árvore antes de
        qualquer `configure` (ver `_aplicar_tema`).
        """
        # Janelas que gerenciam o próprio tema (ex.: Sorteio Profissional):
        # a subárvore inteira fica de fora do passe genérico.
        if getattr(base, '_navepro_tema_proprio', False):
            return
        self._aplicar_tema_widget(base, capturar=capturar)
        try:
            for filho in base.winfo_children():
                self._recolorir_arvore(filho, capturar=capturar)
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
            self._recolorir_arvore(self.root, capturar=True)
            self._recolorir_arvore(self.root)
            for filho in self.root.winfo_children():
                try:
                    if filho.winfo_class() == 'Toplevel':
                        self._recolorir_arvore(filho, capturar=True)
                        self._recolorir_arvore(filho)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass

    def _aplicar_tema_widget(self, widget, capturar: bool = False) -> None:
        """Ajusta as cores de um único widget conforme o tema ativo.

        No tema ESCURO restaura as cores escura originais (gravadas na
        primeira visita em claro). No CLARO registra as cores atuais como
        origem e aplica a equivalência clara. Pergunta valores sobrescritos
        dinamicamente (ex.: linha tocando na lista) como nova origem, para
        a troca de tema nunca perder o estado visual.

        Com `capturar=True` faz apenas o registro das cores de origem (sem
        pintar): é a passada que roda para toda a árvore antes de qualquer
        `configure`, para não gravar cores já empurradas por um pai.
        """
        try:
            if not widget.winfo_exists():
                return
            # Widgets do campo de resultados têm cores próprias por tema
            # (ver _pintar_lista_cores): fora da recolorização genérica para
            # o cinza claro da lista não "escorregar" a cada visita.
            if getattr(widget, '_navepro_tema_ignorar', False):
                return
            # Faixas que delimitam as seções do painel: cor própria por tema
            # (carvão no claro; igual ao cartão no escuro, isto é, invisível).
            if getattr(widget, '_navepro_faixa_secao', False):
                if not capturar:
                    try:
                        widget.configure(
                            bg='#30363d' if self.tema == 'claro' else '#161b22'
                        )
                    except tk.TclError:
                        pass
                return
            # Área de controles do operador: bloco cinza só no tema claro.
            if getattr(widget, '_navepro_area_cinza_clara', False):
                if not capturar:
                    escuro = getattr(
                        widget, '_navepro_area_cinza_escuro', '#161b22')
                    try:
                        widget.configure(
                            bg=(_cor_clara(escuro) if self.tema == 'claro' else escuro)
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
        # Se já houve a passada de captura, a origem está correta e não deve
        # ser tocada aqui (o valor atual pode ter sido empurrado por um pai).
        pre_capturado = origem is not None
        if origem is None:
            origem = {}
        if aplicado is None:
            aplicado = {}

        if capturar:
            # Passada só de captura, sem pintar: grava as cores escuras
            # atuais como origem. Roda para toda a árvore antes de qualquer
            # `configure`, pois um pai (CampoArredondado) empurra bg/fg ao
            # filho e ler depois gravaria a cor clara como se fosse a escura.
            for o in ops:
                atual = _ler(o)
                if atual is None:
                    continue
                if aplicado.get(o) != atual:
                    origem[o] = atual
            try:
                widget._navepro_tema_origem = origem
                widget._navepro_tema_aplicado = aplicado
            except Exception:
                pass
            return

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
                if not pre_capturado and aplicado.get(o) != atual:
                    origem[o] = atual
                # Mapeia sempre a partir da cor ESCURA de origem: reler a cor
                # atual faz o cinza claro (#8b949e) "escorregar" para #656d76
                # a cada visita, pois #8b949e também é chave do mapa claro.
                clara = _cor_clara(origem.get(o) or atual)
                if o == 'background':
                    bg_final = clara
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
            if not pre_capturado and aplicado.get(o) != atual:
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
            release,
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
                            nome_arquivo: str,
                            release: dict | None = None) -> None:
        """Baixa o novo instalador para ~/Downloads com barra de progresso."""
        # O nome vem do JSON da API: sem basename, um nome "..\..\evil"
        # escaparia de ~/Downloads (path traversal).
        nome_arquivo = (_nome_arquivo_seguro(nome_arquivo)
                        or f'NavePro-{versao}{_rotulo_instalador()}')
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
                if not _url_asset_valida(url):
                    raise ValueError(
                        "A URL do instalador é inválida (não é HTTPS).")
                # Verificação de integridade opcional e retroativa: se o
                # release publicar um .sha256 ao lado do instalador, o
                # arquivo baixado é conferido; releases sem .sha256 seguem
                # como antes (HTTPS verificado, sem execução automática).
                hex_esperado = None
                url_checksum = _procurar_checksum_sha256(
                    release, nome_arquivo)
                if url_checksum:
                    hex_esperado = _ler_checksum_sha256(url_checksum)
                req = urllib.request.Request(url, headers={
                    "User-Agent": f"NavePro/{APP_VERSION}"})
                with urllib.request.urlopen(req, timeout=120,
                                            context=_ssl_context()) as resp:
                    if not str(getattr(resp, 'url', '')).lower().startswith(
                            'https://'):
                        raise ValueError(
                            "O download foi redirecionado para fora do "
                            "HTTPS; atualização cancelada.")
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
                if hex_esperado is not None and \
                        _sha256_do_arquivo(temporario) != hex_esperado:
                    try:
                        os.remove(temporario)
                    except OSError:
                        pass
                    raise ValueError(
                        "A verificação de integridade do arquivo baixado "
                        "falhou; a atualização foi cancelada.")
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
        """Alterna entre maximizado (tela cheia) e restaurado (centralizado).

        O tamanho restaurado é derivado do monitor (≈78% da área útil), com
        limites que garantem caber de 1024x768 até resoluções maiores, em vez
        de um 900x800 fixo que estourava a altura de telas pequenas.
        """
        if self._maximizado:
            self.root.state('normal')
            if hasattr(self, '_monitor_geo') and self._monitor_geo:
                mw, mh, mx, my = self._monitor_geo
                w = max(900, min(1180, int(mw * 0.78)))
                h = max(620, min(880, int(mh * 0.78)))
                x = mx + max(0, (mw - w) // 2)
                y = my + max(0, (mh - h) // 2)
                self.root.geometry(f"{w}x{h}+{x}+{y}")
            else:
                self.root.geometry("900x620+200+100")
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

    def _area_monitor_operador(self) -> tuple[int, int, int, int] | None:
        """Retângulo `(x, y, largura, altura)` do monitor do operador.

        Em multi-monitor a janela principal pode aparecer maximizada sobre a
        tela virtual inteira (X11/Wayland), então `winfo_x()`/`winfo_width()`
        não servem para centralizar diálogos: o centro da tela virtual cai no
        telão. A geometria do monitor primário é guardada em `_monitor_geo`
        ao iniciar; os diálogos usam esta área.
        """
        geo = getattr(self, "_monitor_geo", None)
        if not geo:
            return None
        largura, altura, x, y = geo
        return (x, y, largura, altura)


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

    def _pintar_lista_cores(self) -> None:
        """Recolore o campo de resultados (lista de hinos/músicas) no tema atual.

        No tema claro o campo usa o mesmo cinza da faixa de botões do rodapé
        (``#8b949e``). As cores claras saem sempre das cores ESCURAS originais
        (via ``_cor_clara``), sem reler a cor já clareada — reler fazia o cinza
        "escorregar" para ``#656d76`` a cada visita do tema.
        """
        claro = self.tema == 'claro'

        # No tema claro o campo usa a mesma cor da faixa de botões do rodapé
        # ("por baixo dos botões"), lida direto do frame dos controles.
        face_clara = _cor_clara('#161b22')
        if claro:
            barra = getattr(self, 'controls_frame', None)
            if barra is not None:
                try:
                    face_clara = barra.cget('background')
                except tk.TclError:
                    pass

        def _neutro(escura: str) -> str:
            # Superfícies cinza do campo (container, linha, fundo do rótulo).
            return face_clara if claro else escura

        def _acc(escura: str) -> str:
            # Cores de destaque (verde da linha atual, roxo do hover/progresso).
            return _cor_clara(escura) if claro else escura

        def _fg(escura: str, bg_escura: str) -> str:
            if not claro:
                return escura
            return _cor_clara(escura, _cor_clara(bg_escura))

        superficies = [
            (getattr(self, 'list_container', None), '#161b22'),
            (getattr(self, 'canvas_lista', None), '#161b22'),
            (getattr(self, 'scroll_frame', None), '#161b22'),
        ]
        for w, escura in superficies:
            if w is None:
                continue
            try:
                w.configure(bg=_neutro(escura))
            except tk.TclError:
                pass

        sb = getattr(self, 'scrollbar_lista', None)
        if sb is not None:
            try:
                sb.configure(bg=_neutro('#21262d'), troughcolor=_neutro('#161b22'),
                             activebackground=_acc('#6e40c9'))
            except tk.TclError:
                pass

        if not hasattr(self, '_pool_frames'):
            return

        for lbl in (getattr(self, '_pool_label_count', None),
                    getattr(self, '_pool_label_vazio', None)):
            if lbl is None:
                continue
            try:
                lbl.configure(bg=_neutro('#161b22'), fg=_fg('#8b949e', '#161b22'))
            except tk.TclError:
                pass

        for i in range(len(self._pool_frames)):
            escura = '#1c2128' if i % 2 == 0 else '#21262d'
            frame = self._pool_frames[i]
            btn = self._pool_botoes[i]
            atual = (self.arquivo_atual is not None
                     and self._pool_caminhos[i] == self.arquivo_atual)
            try:
                frame.configure(bg=_neutro(escura))
            except tk.TclError:
                pass
            try:
                if atual:
                    btn.configure(bg=_acc('#238636'),
                                  fg=_fg('#f0c040', '#238636'),
                                  activebackground=_acc('#6e40c9'),
                                  activeforeground=_fg('#c9d1d9', '#6e40c9'))
                else:
                    btn.configure(bg=_neutro(escura), fg=_fg('#c9d1d9', escura),
                                  activebackground=_acc('#6e40c9'),
                                  activeforeground=_fg('#c9d1d9', '#6e40c9'))
            except tk.TclError:
                pass
            progress_frame, progress_bar = self._pool_progress_bars[i]
            try:
                progress_frame.configure(bg=_neutro('#161b22'))
                progress_bar.configure(bg=_acc('#6e40c9'))
            except tk.TclError:
                pass

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

        # O campo tem cor própria por tema; fora da recolorização genérica.
        for w in (self._pool_label_count, self._pool_label_vazio,
                  *self._pool_frames, *self._pool_botoes):
            try:
                w._navepro_tema_ignorar = True
            except Exception:
                pass
        for progress_frame, progress_bar in self._pool_progress_bars:
            try:
                progress_frame._navepro_tema_ignorar = True
                progress_bar._navepro_tema_ignorar = True
            except Exception:
                pass
        self._pintar_lista_cores()

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

                btn.config(text=texto)
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

        # Aplica as cores do tema ao campo (verde na linha atual, cinza claro
        # no tema claro etc.) sempre a partir das cores escuras originais.
        self._pintar_lista_cores()

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
                                 subtitulo: str = "", tempo: str = "00:00",
                                 guardar_temp: bool = True) -> None:
        """Projeta um medidor no telão; recria o telão se necessário.

        Também registra no telão o retorno usado quando uma projeção comum
        (slide/texto/imagem) termina: o medidor que o operador deixou
        projetado volta no lugar do relógio (ver `_reprojetar_medidor_ativo`).
        """
        telao = self.player._garantir_telao()
        if telao is None:
            return
        cfg = self.config_data.get(chave, {})
        telao._projetar_medidor(cfg, modo, subtitulo=subtitulo, tempo=tempo,
                                guardar_temp=guardar_temp)
        self._medidor_projetado = modo
        telao.definir_retorno_medidor(self._reprojetar_medidor_ativo)

    def _reprojetar_medidor_ativo(self) -> bool:
        """Reprojeta o medidor (contagem/cronômetro) que está ativo na UI.

        Chamado pelo telão quando uma projeção comum termina (fim de slide,
        letra ou anúncio) ou quando a música/vídeo termina com uma projeção
        na tela. Usa o tempo real do medidor, preservando a frase. Retorna
        True se assumiu a tela; False deixa o telão ir para o relógio.
        """
        modo = getattr(self, "_medidor_projetado", None)
        if modo not in ("contagem", "cronometro"):
            return False
        if modo == "contagem":
            c = self._contagem
            if not c.get("rodando") and not c.get("pausado") \
                    and not c.get("total"):
                return False
            if c.get("rodando") and not c.get("pausado"):
                tempo = self._formatar_tempo(max(0.0, c["fim"] - time.time()))
            elif c.get("pausado"):
                tempo = self._formatar_tempo(max(0.0, c.get("restante", 0.0)))
            else:
                tempo = self._formatar_tempo(c.get("total", 0.0) or 0.0)
            self._projetar_medidor_seguro(
                "contagem", "contagem", subtitulo=c.get("titulo", "") or "",
                tempo=tempo, guardar_temp=False)
            return True
        c = self._crono
        if c.get("rodando") and not c.get("pausado"):
            tempo = self._formatar_cronometro(
                c["acumulado"] + time.time() - c["inicio"])
        else:
            tempo = self._formatar_cronometro(c.get("acumulado", 0.0))
        self._projetar_medidor_seguro("cronometro", "cronometro",
                                      tempo=tempo, guardar_temp=False)
        return True

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
        # Com o cronômetro em uso, uma projeção comum que terminar depois
        # volta a ele (e não ao relógio): registra o retorno no telão.
        self._medidor_projetado = "cronometro"
        telao.definir_retorno_medidor(self._reprojetar_medidor_ativo)
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
        self._medidor_projetado = None
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
        self._medidor_projetado = None
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

    def alternar_relogio_telao(self) -> None:
        """Oculta/mostra o relógio e a temperatura no telão (monitor 2).

        Afeta só o modo relógio: projeções e medidores em andamento não são
        interrompidos (a escolha é aplicada quando o telão voltar ao
        relógio). O fundo do telão (cor/imagem) permanece. Vale só na sessão.
        """
        novo = not self._relogio_oculto_telao
        self._relogio_oculto_telao = novo
        telao = getattr(self.player, "telao", None)
        if telao is not None:
            try:
                telao.definir_relogio_oculto(novo)
            except Exception as e:
                log.exception(f"Erro ao ocultar/mostrar o relógio no telão: {e}")
        # Força o redesenho imediato: o cache de hora impediria a atualização.
        self._ultima_hora_telao = None
        try:
            if telao is not None and getattr(telao, "mostrando_relogio", False):
                hora_atual = datetime.now().strftime("%H:%M")
                temp_display = (self.temperatura_atual
                                if self._temperatura_valida() else "")
                self._ultima_hora_telao = hora_atual
                self.player.mostrar_relogio(hora_atual, temp_display)
        except Exception as e:
            log.exception(f"Erro ao atualizar o relógio do telão: {e}")
        self._atualizar_botao_relogio_telao()

    def _atualizar_botao_relogio_telao(self) -> None:
        """Atualiza o rótulo do botão de mostrar/ocultar o relógio no telão."""
        btn = getattr(self, "_btn_relogio_telao", None)
        if btn is None:
            return
        try:
            if not btn.winfo_exists():
                return
            btn.config(text="✅ Mostrar relógio no telão"
                       if self._relogio_oculto_telao
                       else "🚫 Ocultar relógio do telão")
        except tk.TclError:
            pass

    # ── Gerenciador de Banco (mantido, com recarga de cache) ────

    def abrir_gerenciador(self) -> None:
        """Abre a janela de gerenciamento de mídias."""
        self._janela_gerenciar_midias()


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


    # ────────────────────────────────────────────────────────────────────
    # JANELA DE ANÚNCIOS (armazenados em JSON, FORA do banco de dados)
    # ────────────────────────────────────────────────────────────────────


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


    # ────────────────────────────────────────────────────────────────────
    # JANELA DE ORDEM DE SERVIÇO
    # ────────────────────────────────────────────────────────────────────


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
        # Inicia servidor HTTP (API de mídia local + controle remoto)
        self._servidor_thread = ServidorAsyncHTTP()
        self._servidor_thread.ui = self._na_thread_ui
        self._servidor_thread.remoto = self._remoto_despacho
        self._aplicar_acesso_remoto()
        self._servidor_thread.iniciar()
        log.info(f"✅ Servidor async rodando em {BACKEND_URL}")

        # Registra no banco os arquivos de mídia da pasta uploads sem travar
        # a interface: com muitos arquivos, a varredura + INSERTs + stat do
        # reload_cache seguravam o Tk logo depois da janela aparecer.
        def _sincronizar_uploads():
            try:
                _sincronizar_uploads_midia()
            except Exception as e:
                log.exception(f"⚠️ Erro ao sincronizar uploads: {e}")

        threading.Thread(target=_sincronizar_uploads, daemon=True).start()
        
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
            # 1. Para a reprodução (imediato: o fade ficaria agendado e a
            #    janela é destruída logo abaixo, deixando o player vivo)
            if self.player:
                self.player.parar_agora()
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