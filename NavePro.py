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

import json
import os
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
    BACKEND_URL,
    PLAYER_PADRAO,
    SEGUNDOS_PARA_VERIFICAR_ATUALIZACAO,
    SUFIXOS_IMAGEM,
)
from navepro.core.ambiente import (
    _eh_windows,
    _tornar_dpi_aware,
)
from navepro.core.anuncios import (
    _atualizar_anuncio_db,
    _listar_anuncios_db,
)
from navepro.core.banco import (
    DatabaseManager,
)
from navepro.core.busca import SearchWorker
from navepro.core.clima import (
    obter_temperatura,
)
from navepro.core.foco_apresentacao import (
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
from navepro.core.mediaplayer import MediaPlayer
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
from navepro.core.servidor_http import ServidorAsyncHTTP
from navepro.core.slides import (
    _montar_slides_anuncio,
)
from navepro.core.util_tk import (
    _centralizar_sobre,
    _habilitar_maximizar_janela,
    _normalizar_escala_tk,
)
from navepro.core.widgets_arredondados import TkArredondado

# ────────────────────────────────────────────────────────────────────
# UI DO PAINEL (janelas extraídas do monolito — navepro/ui/)
# ────────────────────────────────────────────────────────────────────
from navepro.ui.apoio import (
    _escolher_arquivos_usuario,
)
from navepro.ui.atualizacao import AtualizacaoMixin
from navepro.ui.biblia_grade import JanelaBibliaGradeMixin
from navepro.ui.config_relogio import ConfigRelogioMixin
from navepro.ui.execucao_servico import ExecucaoServicoMixin
from navepro.ui.gerenciador_midias import GerenciadorMidiasMixin
from navepro.ui.janela_anuncios import JanelaAnunciosMixin
from navepro.ui.janela_biblia import JanelaBibliaMixin
from navepro.ui.janela_hinos import JanelaHinosMixin
from navepro.ui.janela_ordem_servico import JanelaOrdemServicoMixin
from navepro.ui.janela_transferencia import JanelaTransferenciaMixin
from navepro.ui.navegacao import NavegacaoSlidesMixin
from navepro.ui.painel import PainelMixin
from navepro.ui.remoto import ControleRemotoMixin
from navepro.ui.tema_painel import TemaPainelMixin

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


class AppInterface(NavegacaoSlidesMixin, TemaPainelMixin, ControleRemotoMixin, ExecucaoServicoMixin, AtualizacaoMixin, JanelaHinosMixin, JanelaBibliaGradeMixin, JanelaBibliaMixin, JanelaAnunciosMixin, JanelaOrdemServicoMixin, JanelaTransferenciaMixin, GerenciadorMidiasMixin, ConfigRelogioMixin, PainelMixin):
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
        self.placeholder_busca: str = "Buscar música no [BD]"
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
        self._temperatura_oculta_telao = False

        # Quando o telão for fechado (Esc/Ctrl+Q) e recriado pelo player,
        # reaplica a aparência configurada e volta a mostrar a hora inicial.
        def _reaplicar_telao_recriado(novo_telao) -> None:
            try:
                novo_telao.configurar_projecao(
                    self.config_data.get("projecao", {}))
                novo_telao.configurar_relogio(
                    self.config_data.get("relogio", {}))
                novo_telao.definir_relogio_oculto(self._relogio_oculto_telao)
                novo_telao.definir_temperatura_oculta(
                    self._temperatura_oculta_telao)
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
        # Busca com termo digitado: o operador ainda está compondo o nome.
        # Não rouba o foco no meio da digitação — reagenda a checagem
        # enquanto houver termo; ao limpar o campo, o foco volta a ser
        # liberado para os atalhos globais.
        conteudo = self.entry_busca.get().strip()
        if conteudo and conteudo != self.placeholder_busca:
            self._focus_timer = self.root.after(
                5000, self._clear_focus_timeout)
            return
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
        # Termo digitado na busca = operador compondo o nome: o espaço é do
        # texto, NUNCA Play/Pause — mesmo que o foco já tenha saído do campo
        # (ex.: pausa longa na digitação). A reprodução só acontece no Enter
        # ou no clique no resultado.
        conteudo_busca = self.entry_busca.get().strip()
        if conteudo_busca and conteudo_busca != self.placeholder_busca:
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
                try:
                    # Toda gravação usa UTF-8 (ver salvar_config_projecao,
                    # tema e controle remoto); ler com o encoding local no
                    # Windows (cp1252) transformava acentos em mojibake ou
                    # levantava UnicodeDecodeError e zerava a config.
                    with open(CONFIG_FILE, encoding="utf-8") as f:
                        dados = json.load(f)
                except UnicodeDecodeError:
                    # Arquivo antigo gravado na codificação local: mantém a
                    # leitura anterior para não perder a configuração.
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
            log.exception(f"⚠️ Falha ao autosalvar escala do anúncio {pid}: {_e_persist}")

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
            log.exception(f"⚠️ Falha ao autosalvar escala da imagem do anúncio "
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


    def salvar_config_projecao(self, cfg: dict) -> None:
        """Persiste a configuração de aparência da projeção e aplica ao telão."""
        self.config_data["projecao"] = cfg
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.exception(f"Erro ao salvar config de projeção: {e}")
        if self.player and self.player.telao:
            self.player.telao.configurar_projecao(cfg)

    def alternar_caixa_versiculo(self) -> bool:
        """Liga/desliga a caixa (cartão) atrás do versículo projetado.

        A escolha é persistida em config.json e aplicada na hora à projeção
        em slides. Devolve o novo estado (True = caixa ligada).
        """
        telao = getattr(getattr(self, "player", None), "telao", None)
        if telao is None:
            return False
        cfg = dict(getattr(telao, "_proj_cfg", None) or {})
        novo = not bool(cfg.get("biblia_mostrar_caixa", True))
        cfg["biblia_mostrar_caixa"] = novo
        self.salvar_config_projecao(cfg)
        try:
            telao.reaplicar_projecao_atual()
        except Exception as e:  # noqa: BLE001 — só redesenho visual
            log.warning(f"Não foi possível redesenhar a projeção: {e}")
        return novo

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
        cfg_atual.setdefault("biblia_caixa", "normal")
        cfg_atual.setdefault("biblia_alinhamento", "centro")
        cfg_atual.setdefault("biblia_mostrar_caixa", True)

        cfg_win = tk.Toplevel(janela)
        cfg_win.title("🎨 Aparência da Projeção (Telão)")
        cfg_win.geometry("620x760")
        cfg_win.configure(bg='#0d1117')
        cfg_win.transient(janela)
        _centralizar_sobre(cfg_win, janela)
        _habilitar_maximizar_janela(cfg_win)
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

        # Opções exclusivas da Bíblia (texto do versículo e alinhamento no
        # cartão). Ficam vivas mesmo quando a janela é de Anúncios/Hinos
        # para preservar o que o operador escolheu ao salvar de lá.
        mapa_caixa = {
            "Como está": "normal",
            "MAIÚSCULAS": "maiusculas",
            "minúsculas": "minusculas",
        }
        rev_caixa = {v: k for k, v in mapa_caixa.items()}
        mapa_alinhamento = {
            "Esquerda": "esquerda",
            "Centralizado": "centro",
            "Direita": "direita",
        }
        rev_alinhamento = {v: k for k, v in mapa_alinhamento.items()}
        var_caixa = tk.StringVar(value=rev_caixa.get(
            str(cfg_atual["biblia_caixa"]), "Como está"))
        var_alinhamento = tk.StringVar(value=rev_alinhamento.get(
            str(cfg_atual["biblia_alinhamento"]), "Centralizado"))

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

            # ── Texto do versículo: caixa e alinhamento dentro do cartão ──
            linha_versiculo = tk.Frame(c_main, bg='#0d1117')
            linha_versiculo.pack(fill='x', pady=(0, 10))
            tk.Label(linha_versiculo, text="Versículo:",
                     font=("Arial", 11, "bold"), fg='#f0c040',
                     bg='#0d1117').pack(side='left')
            combo_caixa = ttk.Combobox(
                linha_versiculo, textvariable=var_caixa, state="readonly",
                values=list(mapa_caixa), width=12, font=("Arial", 10))
            combo_caixa.pack(side='left', padx=(4, 12), ipady=1)
            combo_caixa._navepro_var = var_caixa
            tk.Label(linha_versiculo, text="Alinhamento:",
                     font=("Arial", 11, "bold"), fg='#f0c040',
                     bg='#0d1117').pack(side='left')
            combo_alinhamento = ttk.Combobox(
                linha_versiculo, textvariable=var_alinhamento, state="readonly",
                values=list(mapa_alinhamento), width=12, font=("Arial", 10))
            combo_alinhamento.pack(side='left', padx=(4, 0), ipady=1)
            combo_alinhamento._navepro_var = var_alinhamento

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
            # A caixa do versículo é togglada fora deste diálogo (Bíblia e
            # controle remoto); preserva o estado vivo para não desfazê-lo.
            cfg_vivo = getattr(
                getattr(self.player, "telao", None), "_proj_cfg", {}) or {}
            novo["biblia_mostrar_caixa"] = bool(
                cfg_vivo.get("biblia_mostrar_caixa", True))
            if mostrar_cor_ref:
                novo["cor_ref"] = var_cor_ref.get()
                novo["biblia_caixa"] = mapa_caixa.get(
                    var_caixa.get(), "normal")
                novo["biblia_alinhamento"] = mapa_alinhamento.get(
                    var_alinhamento.get(), "centro")
            else:
                # A janela de Anúncios/Hinos não mostra estes ajustes:
                # preserva o que o operador configurou na Bíblia.
                for chave in ("cor_ref", "biblia_caixa",
                              "biblia_alinhamento"):
                    novo[chave] = cfg_atual.get(chave)
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
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
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
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
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
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
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

    def alternar_temperatura_telao(self) -> None:
        """Oculta/mostra somente a temperatura no telão (monitor 2).

        A hora continua visível. Afeta só o modo relógio: projeções e
        medidores em andamento não são interrompidos (a escolha é aplicada
        quando o telão voltar ao relógio). Vale só na sessão.
        """
        novo = not self._temperatura_oculta_telao
        self._temperatura_oculta_telao = novo
        telao = getattr(self.player, "telao", None)
        if telao is not None:
            try:
                telao.definir_temperatura_oculta(novo)
            except Exception as e:
                log.exception(
                    f"Erro ao ocultar/mostrar a temperatura no telão: {e}")
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
        self._atualizar_botao_temperatura_telao()

    def _atualizar_botao_temperatura_telao(self) -> None:
        """Atualiza o rótulo do botão de mostrar/ocultar a temperatura."""
        btn = getattr(self, "_btn_temperatura_telao", None)
        if btn is None:
            return
        try:
            if not btn.winfo_exists():
                return
            btn.config(text="✅ Mostrar temperatura no telão"
                       if self._temperatura_oculta_telao
                       else "🌡️ Ocultar temperatura do telão")
        except tk.TclError:
            pass

    # ── Gerenciador de Banco (mantido, com recarga de cache) ────

    def abrir_gerenciador(self) -> None:
        """Abre a janela de gerenciamento de mídias."""
        self._janela_gerenciar_midias()


    # ── Seletor de arquivos personalizado (mantido) ──────────────


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
