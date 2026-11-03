"""remoto (mixin).

Extraído de NavePro.py sem alteração de comportamento: a AppInterface
herda deste mixin.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import secrets
import time
import tkinter as tk
import tkinter.messagebox
import tkinter.simpledialog
from collections.abc import Callable
from typing import Any

from navepro.config import APP_VERSION, BACKEND_PORT
from navepro.core.anuncios import (
    _buscar_anuncio_por_ref,
    _buscar_anuncio_por_termo,
    _listar_anuncios_db,
)
from navepro.core.banco import db_query
from navepro.core.log import get_logger
from navepro.core.mediaplayer import _eh_url
from navepro.core.paths import CONFIG_FILE
from navepro.core.rede import _ip_da_rede
from navepro.core.servicos import (
    _SERVICO_PROXIMO_ITEM,
    _analisar_faixa_versiculos,
    _carregar_servicos_json,
    _faixa_versiculo_item,
    _salvar_servicos_json,
)
from navepro.core.slides import (
    _buscar_hino_por_termo,
    _buscar_hino_por_termo_ou_id,
    _buscar_midia_por_termo_ou_id,
    _buscar_versiculos_por_texto,
    _montar_slides_letra,
    _previa_slide,
)
from navepro.core.textos import _numero_do_titulo
from navepro.core.widgets_arredondados import TkArredondado
from navepro.ui.apoio import _menu_contexto_campo

log = get_logger("remoto")

# Botões e campos desenham cantos arredondados (fachada do tkinter).
tk = TkArredondado(tk)


class ControleRemotoMixin:
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
            handlers = {
                # ── Leituras (GET) ──
                'estado': lambda d: self._remoto_estado(),
                'buscar_hino': lambda d: self._remoto_buscar_hino(
                    str(d.get('busca') or '')),
                'buscar_midia': lambda d: self._remoto_buscar_midia(
                    str(d.get('busca') or '')),
                'buscar_biblia': lambda d: self._remoto_buscar_biblia(
                    str(d.get('q') or ''), str(d.get('versao') or '')),
                'buscar_biblia_ref': lambda d: self._remoto_buscar_biblia_ref(d),
                'biblia_opcoes': lambda d: self._remoto_biblia_opcoes(d),
                'livros_biblia': lambda d: {'ok': True,
                                            'livros': list(self.LIVROS_BIBLIA)},
                'listar_anuncios': lambda d: {'ok': True, 'anuncios': [
                    {'id': a.get('id'), 'titulo': a.get('titulo') or '',
                     'tipo': a.get('tipo_midia') or 'slide'}
                    for a in _listar_anuncios_db()]},
                'listar_servicos': lambda d: {'ok': True, 'servicos': [
                    {'id': s.get('id'), 'nome': s.get('nome') or '',
                     'itens': len(s.get('itens') or [])}
                    for s in (_carregar_servicos_json().get('servicos') or [])]},
                'servico_itens': lambda d: self._remoto_servico_itens(d),
                'sorteio_estado': lambda d: self._remoto_sorteio_estado(),
                # ── Ações (POST) ──
                'slide': lambda d: self._remoto_slide(str(d.get('acao') or '')),
                'tamanho': lambda d: self._remoto_tamanho(d),
                'projetar_hino': lambda d: self._remoto_projetar_hino(d),
                'projetar_biblia': lambda d: self._remoto_projetar_biblia(d),
                'executar_midia': lambda d: self._remoto_executar_midia(d),
                'controle_player': lambda d: self._remoto_controle_player(d),
                'projetar_anuncio': lambda d: self._remoto_projetar_anuncio(d),
                'executar_servico': lambda d: self._remoto_executar_servico(d),
                'servico_item': lambda d: self._remoto_servico_item(d),
                'medidor': lambda d: self._remoto_medidor(d),
                'sorteio_abrir': lambda d: self._remoto_sorteio_abrir(),
                'sorteio_fechar': lambda d: self._remoto_sorteio_fechar(),
                'sorteio_configurar': lambda d: self._remoto_sorteio_configurar(d),
                'sorteio_sortear': lambda d: self._remoto_sorteio_sortear(),
                'sorteio_reiniciar': lambda d: self._remoto_sorteio_reiniciar(),
            }
            handler = handlers.get(acao)
            if handler is None:
                return {'ok': False, 'erro': f'Ação desconhecida: {acao}'}
            return handler(dados)
        except Exception as exc:  # noqa: BLE001 — vira JSON de erro
            log.exception(f"❌ Erro na ação remota '{acao}': {exc}")
            return {'ok': False, 'erro': str(exc) or type(exc).__name__}

    def _remoto_projetar_anuncio(self, dados: dict) -> dict:
        """Projeta anúncio pedido pelo celular (garante o telão antes)."""
        self.player._garantir_telao()
        return self.projetar_anuncio(int(dados.get('id') or 0))

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
        rows = _buscar_versiculos_por_texto(versao, q)
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
        principal do app ("Buscar música no [BD]")."""
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
            rows = _buscar_hino_por_termo_ou_id(buscar)
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
            rows = _buscar_midia_por_termo_ou_id(termo, tipo=tipo)
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
