"""execucao_servico (mixin).

Extraído de NavePro.py sem alteração de comportamento: a AppInterface
herda deste mixin.
"""

from __future__ import annotations

import os
import subprocess
import tkinter as tk
import tkinter.messagebox
import tkinter.simpledialog
from collections.abc import Callable

from navepro.core.ambiente import _ambiente_sem_appimage, _eh_flatpak, _eh_windows
from navepro.core.anuncios import _buscar_anuncio_por_ref, _projetar_anuncio_ordserv
from navepro.core.apresentacao import (
    _ambiente_apresentacao,
    _comando_apresentacao,
    _monitorar_apresentacao,
)
from navepro.core.banco import db_query
from navepro.core.foco_apresentacao import (
    _agendar_captura_janela_apresentacao,
    _criar_alvo_apresentacao,
)
from navepro.core.log import get_logger
from navepro.core.mediaplayer import _eh_url
from navepro.core.servicos import _SERVICO_PROXIMO_ITEM, _slides_versiculo_item
from navepro.core.slides import _montar_slides_letra
from navepro.core.widgets_arredondados import TkArredondado

log = get_logger("execucao_servico")

# Botões e campos desenham cantos arredondados (fachada do tkinter).
tk = TkArredondado(tk)


class ExecucaoServicoMixin:
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
