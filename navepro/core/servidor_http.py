"""Servidor HTTP assíncrono (API de mídia + controle remoto).

Extraído de NavePro.py sem alterar o comportamento (ver AGENTS.md).
"""
from __future__ import annotations

import asyncio
import hmac
import json
import mimetypes
import os
import re
import threading
import unicodedata
import urllib.parse
from collections.abc import Callable
from typing import Any

from navepro.config import BACKEND_PORT
from navepro.core.banco import DatabaseManager, db_execute, db_query
from navepro.core.log import get_logger
from navepro.core.paths import UPLOAD_FOLDER
from navepro.core.rede import _eh_loopback
from navepro.core.textos import detectar_tipo_arquivo, remover_acentos

log = get_logger("servidor_http")


_ACOES_POST_REMOTO: dict = {
    '/api/remoto/slide': 'slide',
    '/api/remoto/hino': 'projetar_hino',
    '/api/remoto/biblia': 'projetar_biblia',
    '/api/remoto/midia': 'executar_midia',
    '/api/remoto/player': 'controle_player',
    '/api/remoto/anuncio': 'projetar_anuncio',
    '/api/remoto/servico': 'executar_servico',
    '/api/remoto/servico_item': 'servico_item',
    '/api/remoto/medidor': 'medidor',
    '/api/remoto/tamanho': 'tamanho',
    '/api/remoto/sorteio/abrir': 'sorteio_abrir',
    '/api/remoto/sorteio/configurar': 'sorteio_configurar',
    '/api/remoto/sorteio/sortear': 'sorteio_sortear',
    '/api/remoto/sorteio/reiniciar': 'sorteio_reiniciar',
}

# Limites do parser HTTP: evitam memória ilimitada com cabeçalho/corpo
# gigantes. O corpo comporta uploads de mídia (vídeo) com folga.
_LIMITE_CABECALHO = 64 * 1024
_LIMITE_CORPO = 200 * 1024 * 1024


class ServidorAsyncHTTP:
    """Servidor HTTP assíncrono usando asyncio.
    
    Substitui HTTPServer (bloqueante) por um servidor asyncio que não
    interfere com o event loop do Tk. Roda em uma thread separada
    com seu próprio event loop asyncio.

    Além da API interna de mídias (sempre restrita ao loopback), serve o
    CONTROLE REMOTO pelo celular (`/` e `/api/remoto/*`): quando ativado
    nas configurações, passa a escutar na rede local protegido por token.
    """
    
    def __init__(self, port: int = BACKEND_PORT) -> None:
        self.port = port
        self.host: str = '127.0.0.1'
        self.token: str | None = None
        # Injetados pelo AppInterface:
        #   ui(fn[, timeout]) → executa fn na thread do Tk e devolve o resultado
        #   remoto(a,d) → executa a ação remota `a` com dados `d` no app
        self.ui: Callable[..., Any] | None = None
        self.remoto: Callable[[str, dict], Any] | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.AbstractServer | None = None

    def iniciar(self) -> None:
        """Inicia o servidor em uma thread separada com event loop asyncio."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_async, daemon=True)
        self._thread.start()

    def configurar_acesso(self, host: str, token: str | None) -> None:
        """Define bind (127.0.0.1 ou 0.0.0.0) e token do controle remoto.

        Reinicia o socket de escuta se o host mudar (thread-safe).
        """
        self.token = token or None
        if host == self.host:
            return
        self.host = host
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._reiniciar_escuta)

    def _reiniciar_escuta(self) -> None:
        """Fecha e reabre o socket de escuta no host atual (no loop asyncio)."""
        if self._server is not None:
            try:
                self._server.close()
            except Exception:
                pass
            self._server = None
        self._loop.create_task(self._abrir_escuta())

    def _run_async(self) -> None:
        """Executa o event loop asyncio (chamado pela thread)."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._servir())
            self._loop.run_forever()
        except Exception as e:
            log.exception(f"Erro no servidor async: {e}")
        finally:
            self._loop.close()

    async def _servir(self) -> None:
        """Configura e inicia o servidor HTTP assíncrono."""
        await self._abrir_escuta()

    async def _abrir_escuta(self) -> None:
        """Abre o socket de escuta em self.host:self.port."""
        try:
            self._server = await asyncio.start_server(
                self._handle_connection,
                self.host, self.port
            )
            if self.host == '127.0.0.1':
                log.info(f"✅ Servidor async rodando em 127.0.0.1:{self.port}")
            else:
                log.info(f"🌐 Controle remoto ativo em {self.host}:{self.port} "
                      f"(token {'definido' if self.token else 'AUSENTE'})")
        except OSError as e:
            log.exception(f"❌ Não consegui escutar em {self.host}:{self.port}: {e}")

    # ── Ponte com a thread do Tk ──────────────────────────────────

    def _na_ui(self, fn: Callable, timeout: float = 5.0) -> Any:
        """Executa `fn` na thread do Tk e devolve o resultado.

        O servidor nunca toca em widgets fora da thread do Tk: tudo que
        envolve a interface passa por aqui (padrão root.after + Future).
        """
        if self.ui is None:
            raise RuntimeError("Interface não conectada ao servidor")
        return self.ui(fn, timeout)

    async def _ler_requisicao(self, reader: asyncio.StreamReader,
                              ) -> tuple | bytes | None:
        """Lê cabeçalhos + corpo (Content-Length) de uma requisição HTTP.

        Devolve `(method, path, headers, body)` em requisição válida, a
        resposta de erro pronta (413/431) se passar dos limites, ou None se
        a conexão fechar antes. O corpo nunca é decodificado como texto
        (é binário nos uploads) e é lido em blocos até Content-Length — a
        leitura única de 64 KB truncava qualquer arquivo maior.
        """
        dados = b''
        while b'\r\n\r\n' not in dados:
            bloco = await reader.read(65536)
            if not bloco:
                return None
            dados += bloco
            if len(dados) > _LIMITE_CABECALHO:
                return self._responder_erro_bytes("Cabeçalhos muito grandes", 431)

        cabecalho, _, corpo = dados.partition(b'\r\n\r\n')
        linhas = cabecalho.decode('utf-8', errors='replace').split('\r\n')
        partes = linhas[0].split() if linhas else []
        if len(partes) < 2:
            return None
        method, path_line = partes[0], partes[1]

        headers: dict[str, str] = {}
        for linha in linhas[1:]:
            if ':' in linha:
                chave, valor = linha.split(':', 1)
                headers[chave.strip().lower()] = valor.strip()

        try:
            tamanho = int(headers.get('content-length') or 0)
        except ValueError:
            tamanho = 0
        if tamanho < 0 or tamanho > _LIMITE_CORPO:
            return self._responder_erro_bytes("Corpo muito grande", 413)

        while len(corpo) < tamanho:
            bloco = await reader.read(min(65536, tamanho - len(corpo)))
            if not bloco:
                break
            corpo += bloco

        # Descarta bytes além do corpo declarado (Content-Length inválido
        # ou requisições pipelined — o servidor responde e fecha).
        return method, path_line, headers, corpo[:tamanho]

    async def _handle_connection(self, reader: asyncio.StreamReader, 
                                  writer: asyncio.StreamWriter) -> None:
        """Handler de conexão HTTP assíncrono."""
        try:
            requisicao = await self._ler_requisicao(reader)
            if requisicao is None:
                writer.close()
                return
            if isinstance(requisicao, bytes):
                writer.write(requisicao)
                await writer.drain()
                return

            method, path_line, headers, body_bytes = requisicao

            # Endereço do cliente (para restringir API de mídia ao loopback)
            peer = writer.get_extra_info('peername')
            peer_ip = peer[0] if isinstance(peer, tuple) and peer else ''

            # Processar requisição
            response = await self._process_request(
                method, path_line, headers, body_bytes, peer_ip)
            
            writer.write(response)
            await writer.drain()
        except Exception as e:
            log.exception(f"Erro ao processar requisição: {e}")
            error_response = (
                b"HTTP/1.1 500 Internal Server Error\r\n"
                b"Content-Type: application/json; charset=utf-8\r\n"
                b"Access-Control-Allow-Origin: *\r\n"
                b"Connection: close\r\n"
                b"\r\n"
                b'{"erro": "Erro interno do servidor"}'
            )
            try:
                writer.write(error_response)
                await writer.drain()
            except Exception:
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _process_request(self, method: str, path_full: str,
                                headers: dict, body: bytes,
                                peer_ip: str = '') -> bytes:
        """Processa uma requisição HTTP e retorna a resposta."""
        parsed = urllib.parse.urlparse(path_full)
        path = parsed.path
        params = dict(urllib.parse.parse_qsl(parsed.query))

        # A API de mídia (listar/upload/download/deletar) é do painel local:
        # quando o servidor escuta na rede, ela NUNCA sai do loopback.
        if path.startswith('/api/midia') and not _eh_loopback(peer_ip):
            return self._responder_erro_bytes(
                "API de mídia restrita ao computador local", 403)

        # CORS preflight
        if method == 'OPTIONS':
            return (
                b"HTTP/1.1 200 OK\r\n"
                b"Access-Control-Allow-Origin: *\r\n"
                b"Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS\r\n"
                b"Access-Control-Allow-Headers: Content-Type, X-Token\r\n"
                b"Content-Length: 0\r\n"
                b"\r\n"
            )
        
        # ROTEAMENTO
        if method == 'GET':
            return await self._handle_get(path, params, headers, peer_ip)
        elif method == 'POST':
            return await self._handle_post(path, params, headers, body, peer_ip)
        elif method == 'DELETE':
            return await self._handle_delete(path, headers, peer_ip)
        else:
            return self._responder_erro_bytes("Método não suportado", 405)

    # ── Controle remoto: autenticação e despacho ──────────────────

    def _remoto_autorizado(self, headers: dict, params: dict) -> bool:
        """True se a requisição trouxer o token vigente do controle remoto."""
        if not self.token:
            return False
        enviado = (headers.get('x-token')
                   or params.get('t')
                   or '').strip()
        # Tempo constante: comparação com == em str curto vaza o token por
        # medição de timing pela rede. Bytes evita TypeError com não-ASCII.
        return hmac.compare_digest(
            enviado.encode('utf-8'), self.token.encode('utf-8'))

    def _remoto(self, acao: str, dados: dict) -> Any:
        """Despacha uma ação remota para o app (na thread do Tk)."""
        remoto = self.remoto
        if remoto is None:
            raise RuntimeError("Controle remoto não conectado ao servidor")
        return self._na_ui(lambda: remoto(acao, dados))

    def _exige_remoto(self, headers: dict, params: dict) -> bytes | None:
        """Retorna None se autorizado, ou a resposta de erro a enviar."""
        if not self.token:
            return self._responder_erro_bytes(
                "Controle remoto desativado no computador", 403)
        if not self._remoto_autorizado(headers, params):
            return self._responder_erro_bytes("Token inválido", 403)
        if self.remoto is None or self.ui is None:
            return self._responder_erro_bytes(
                "Aplicativo ainda inicializando", 503)
        return None

    async def _handle_get(self, path: str, params: dict, headers: dict,
                          peer_ip: str = '') -> bytes:
        """Processa requisições GET."""
        # ── Controle remoto ──
        if path == '/' or path == '/index.html':
            # A página só é servida com o token (a URL da UI já o traz em ?t=)
            if not self._remoto_autorizado(headers, params):
                return (
                    b"HTTP/1.1 403 Forbidden\r\n"
                    b"Content-Type: text/html; charset=utf-8\r\n"
                    b"Content-Length: 0\r\n"
                    b"\r\n"
                )
            from navepro.remoto_web import PAGINA
            corpo = PAGINA.encode('utf-8')
            return (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                "Cache-Control: no-store\r\n"
                f"Content-Length: {len(corpo)}\r\n"
                "Connection: close\r\n"
                "\r\n"
            ).encode() + corpo
        if path.startswith('/api/remoto'):
            bloqueio = self._exige_remoto(headers, params)
            if bloqueio is not None:
                return bloqueio
            try:
                acao, dados = self._remoto_get(path, params)
            except KeyError:
                return self._responder_erro_bytes("Rota não encontrada", 404)
            return self._executar_remoto(acao, dados)
        # ── API de mídia (somente loopback; checado no _process_request) ──
        if path == '/api/midia':
            return self._handle_get_midia_bytes(params)
        elif path == '/api/midia/contagem':
            resultados = db_query(
                "SELECT tipo, COUNT(*) as total FROM midia WHERE ativo = 1 GROUP BY tipo"
            )
            contagem: dict[str, int] = {r['tipo']: r['total'] for r in resultados}
            return self._responder_json_bytes(contagem)
        elif (match := re.match(r'^/api/midia/(\d+)$', path)):
            midia_id = int(match.group(1))
            row = db_query("SELECT * FROM midia WHERE id = ? AND ativo = 1", (midia_id,))
            if row:
                return self._responder_json_bytes(row[0])
            else:
                return self._responder_erro_bytes("Mídia não encontrada", 404)
        elif path.startswith('/api/midia/') and path.endswith('/download'):
            return await self._handle_download_bytes(path)
        else:
            return self._responder_erro_bytes("Rota não encontrada", 404)

    def _remoto_get(self, path: str, params: dict) -> tuple:
        """Mapeia uma rota GET do controle remoto em (ação, dados)."""
        if path == '/api/remoto/estado':
            return ('estado', {})
        if path == '/api/remoto/hinos':
            return ('buscar_hino', {'busca': params.get('busca', '')})
        if path == '/api/remoto/midias':
            return ('buscar_midia', {'busca': params.get('busca', '')})
        if path == '/api/remoto/biblia':
            return ('buscar_biblia', {'q': params.get('q', ''),
                                      'versao': params.get('versao', '')})
        if path == '/api/remoto/biblia_ref':
            return ('buscar_biblia_ref', {
                'versao': params.get('versao', ''),
                'livro': params.get('livro', ''),
                'cap': params.get('cap', ''),
                'vers': params.get('vers', '')})
        if path == '/api/remoto/livros':
            return ('livros_biblia', {})
        if path == '/api/remoto/anuncios':
            return ('listar_anuncios', {})
        if path == '/api/remoto/servicos':
            return ('listar_servicos', {})
        if path == '/api/remoto/servico_itens':
            return ('servico_itens', {'servico': params.get('servico', '')})
        if path == '/api/remoto/sorteio':
            return ('sorteio_estado', {})
        raise KeyError(path)

    def _executar_remoto(self, acao: str, dados: dict) -> bytes:
        """Executa a ação remota na thread do Tk e monta a resposta."""
        try:
            return self._responder_json_bytes(self._remoto(acao, dados))
        except Exception as e:
            return self._responder_erro_bytes(str(e) or "Falha na ação", 400)

    def _handle_get_midia_bytes(self, params: dict) -> bytes:
        """Busca mídias (igual ao handler anterior, retorna bytes)."""
        tipo = params.get('tipo')
        busca = params.get('busca', '').strip()
        query = "SELECT * FROM midia WHERE ativo = 1"
        query_params: list[object] = []

        if busca:
            if busca.isdigit():
                num = busca
                query += (
                    " AND (\n"
                    "    nome_exibicao = ? OR\n"
                    "    nome_exibicao LIKE ? OR\n"
                    "    nome_exibicao LIKE ? OR\n"
                    "    nome_original = ? OR\n"
                    "    nome_original LIKE ? OR\n"
                    "    nome_original LIKE ? OR\n"
                    "    id = ?\n"
                    ")"
                )
                query_params.extend([
                    num, f"{num} -%", f"{num}-%",
                    num, f"{num} -%", f"{num}-%",
                ])
            else:
                busca_nfc = unicodedata.normalize('NFC', busca)
                busca_like = busca_nfc.casefold()
                query += (
                    " AND (\n"
                    "    LOWER(nome_exibicao) LIKE ? OR\n"
                    "    LOWER(nome_original) LIKE ?\n"
                    ")"
                )
                query_params.extend([f"%{busca_like}%", f"%{busca_like}%"])

        if tipo:
            query += " AND tipo = ?"
            query_params.append(tipo)

        query += (
            " ORDER BY\n"
            "    CASE WHEN nome_exibicao GLOB '[0-9]*' THEN 0 ELSE 1 END,\n"
            "    CAST(SUBSTR(nome_exibicao, 1, INSTR(nome_exibicao || ' ', ' ') - 1) AS INTEGER),\n"
            "    SUBSTR(nome_exibicao, INSTR(nome_exibicao || ' ', ' ') + 1) ASC"
        )

        resultados = db_query(query, query_params)

        # Pós-filtro fonético
        if busca and resultados and not busca.isdigit():
            busca_nfc = unicodedata.normalize('NFC', busca)
            busca_ascii = remover_acentos(busca_nfc).casefold()
            cache_norm = {
                r['id']: remover_acentos(
                    unicodedata.normalize('NFC',
                        r.get('nome_exibicao', '') + ' ' + r.get('nome_original', '')
                    )
                ).casefold()
                for r in resultados
            }
            resultados = [r for r in resultados if busca_ascii in cache_norm[r['id']]]

        return self._responder_json_bytes(resultados)

    async def _handle_download_bytes(self, path: str) -> bytes:
        """Processa download de arquivo."""
        try:
            midia_id = int(path.split('/')[3])
        except (IndexError, ValueError):
            return self._responder_erro_bytes("ID inválido", 400)

        row = db_query("SELECT * FROM midia WHERE id = ? AND ativo = 1", (midia_id,))
        if not row:
            return self._responder_erro_bytes("Mídia não encontrada", 404)

        midia = row[0]
        caminho = midia['caminho_arquivo']
        if not os.path.exists(caminho):
            return self._responder_erro_bytes("Arquivo não encontrado no disco", 404)

        mime, _ = mimetypes.guess_type(caminho)
        try:
            with open(caminho, 'rb') as f:
                conteudo = f.read()
        except Exception:
            return self._responder_erro_bytes("Erro ao ler arquivo", 500)

        header = (
            f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: {mime or 'application/octet-stream'}\r\n"
            f"Content-Disposition: attachment; filename=\"{os.path.basename(caminho)}\"\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"Content-Length: {len(conteudo)}\r\n"
            f"\r\n"
        ).encode()
        return header + conteudo

    async def _handle_post(self, path: str, params: dict, headers: dict,
                           body: bytes, peer_ip: str = '') -> bytes:
        """Processa requisições POST."""
        if path == '/api/midia/upload':
            return self._handle_upload_bytes(headers, body)
        if path.startswith('/api/remoto'):
            bloqueio = self._exige_remoto(headers, params)
            if bloqueio is not None:
                return bloqueio
            acao = _ACOES_POST_REMOTO.get(urllib.parse.urlparse(path).path)
            if acao is None:
                return self._responder_erro_bytes("Rota não encontrada", 404)
            try:
                dados = json.loads(body.decode('utf-8')) if body else {}
                if not isinstance(dados, dict):
                    raise ValueError("JSON deve ser um objeto")
            except (ValueError, UnicodeDecodeError) as e:
                return self._responder_erro_bytes(f"Corpo inválido: {e}", 400)
            return self._executar_remoto(acao, dados)
        return self._responder_erro_bytes("Rota não encontrada", 404)

    def _handle_upload_bytes(self, headers: dict, body: bytes) -> bytes:
        """Processa upload de arquivo."""
        content_type = headers.get('content-type', '')
        if 'multipart/form-data' not in content_type:
            return self._responder_erro_bytes("Content-Type deve ser multipart/form-data")

        try:
            boundary = content_type.split('boundary=')[1].encode()
        except (IndexError, ValueError):
            return self._responder_erro_bytes("Boundary não encontrado")

        parts = body.split(b'--' + boundary)
        arquivo_dados = None
        nome_arquivo = None
        nome_exibicao = None

        for part in parts:
            if b'Content-Disposition' not in part:
                continue
            if b'filename="' in part:
                match = re.search(rb'filename="([^"]*)"', part)
                if match:
                    nome_arquivo = match.group(1).decode('utf-8', errors='ignore')
                header_end = part.find(b'\r\n\r\n')
                if header_end != -1:
                    arquivo_dados = part[header_end + 4:-2]
            elif b'name="nome_exibicao"' in part:
                header_end = part.find(b'\r\n\r\n')
                if header_end != -1:
                    nome_exibicao = part[header_end + 4:-2].decode(
                        'utf-8', errors='ignore'
                    ).strip()

        if not arquivo_dados or not nome_arquivo:
            return self._responder_erro_bytes("Nenhum arquivo enviado")

        # O filename vem do cliente e pode trazer caminho absoluto ou ".."
        # (escape de UPLOAD_FOLDER). No POSIX "\" não é separador, por isso
        # o replace antes do basename — resultado igual em Linux e Windows.
        nome_arquivo = os.path.basename(nome_arquivo.replace('\\', '/'))
        if not nome_arquivo or nome_arquivo in ('.', '..'):
            return self._responder_erro_bytes("Nome de arquivo inválido")

        tipo = detectar_tipo_arquivo(nome_arquivo)
        if not tipo:
            return self._responder_erro_bytes(
                f"Tipo não suportado: {os.path.splitext(nome_arquivo)[1].lower()}"
            )

        caminho = os.path.join(UPLOAD_FOLDER, nome_arquivo)
        contador = 1
        while os.path.exists(caminho):
            nome_base, ext_arq = os.path.splitext(nome_arquivo)
            caminho = os.path.join(UPLOAD_FOLDER, f"{nome_base}_{contador}{ext_arq}")
            contador += 1

        with open(caminho, 'wb') as f:
            f.write(arquivo_dados)

        if not nome_exibicao:
            nome_exibicao = os.path.splitext(os.path.basename(caminho))[0]

        mime, _ = mimetypes.guess_type(caminho)
        tamanho = os.path.getsize(caminho)

        midia_id = db_execute("""
            INSERT INTO midia
                (nome_original, nome_exibicao, tipo, caminho_arquivo,
                 tamanho_bytes, mime_type, data_upload, data_modificacao)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """, (os.path.basename(caminho), nome_exibicao, tipo, caminho,
              tamanho, mime or ''))

        DatabaseManager().reload_cache()

        return self._responder_json_bytes({
            "mensagem": "✅ Upload realizado!",
            "id": midia_id,
            "nome": nome_exibicao,
            "tipo": tipo,
            "caminho": caminho
        }, 201)

    async def _handle_delete(self, path: str, headers: dict,
                             peer_ip: str = '') -> bytes:
        """Processa requisições DELETE."""
        match = re.match(r'^/api/midia/(\d+)$', path)
        if match:
            midia_id = int(match.group(1))
            db_execute(
                "UPDATE midia SET ativo = 0, data_modificacao = datetime('now') WHERE id = ?",
                (midia_id,)
            )
            DatabaseManager().reload_cache()
            return self._responder_json_bytes({"mensagem": "✅ Mídia removida!"})
        else:
            return self._responder_erro_bytes("Rota não encontrada", 404)

    # ── Utilitários de resposta ───────────────────────────────────

    def _responder_json_bytes(self, dados: Any, status: int = 200) -> bytes:
        """Gera resposta HTTP JSON como bytes."""
        body = json.dumps(dados, ensure_ascii=False, default=str).encode('utf-8')
        status_text = {200: "OK", 201: "Created", 400: "Bad Request",
                       404: "Not Found", 405: "Method Not Allowed",
                       413: "Payload Too Large",
                       431: "Request Header Fields Too Large",
                       500: "Internal Server Error"}
        header = (
            f"HTTP/1.1 {status} {status_text.get(status, 'OK')}\r\n"
            f"Content-Type: application/json; charset=utf-8\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS\r\n"
            f"Access-Control-Allow-Headers: Content-Type, X-Token\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode()
        return header + body

    def _responder_erro_bytes(self, msg: str, status: int = 400) -> bytes:
        """Gera resposta HTTP de erro como bytes."""
        return self._responder_json_bytes({"erro": msg}, status)

    # ── Compatibilidade ───────────────────────────────────────────
    def parar(self) -> None:
        """Para o servidor HTTP de forma segura."""
        if self._server:
            self._server.close()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        log.info("✅ Servidor async parado")

    def run(self) -> None:
        self._run_async()

    def start(self) -> None:
        self.iniciar()
