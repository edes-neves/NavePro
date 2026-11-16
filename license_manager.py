"""Licenciamento híbrido do NavePro (teste de 10 dias + lista negra online).

O primeiro uso em cada computador libera **todos os recursos por 10 dias**
(sem marca d'água e sem os limites do modo demonstração). O início do teste
fica em ``~/.navepro/trial.json``; depois do prazo, o app entra no modo
demonstração até receber uma licença válida.

O licenciamento offline usa **criptografia assimétrica**: o administrador
assina o conteúdo da licença com a chave privada RSA e o aplicativo verifica
a assinatura com a chave pública embutida em :data:`CHAVE_PUBLICA_PEM`. Sem a
chave privada não é possível emitir licenças válidas.

Complemento online: :func:`esta_na_lista_negra` consulta uma lista de IDs de
máquina revogados. Falhas de rede são silenciosas — o app continua funcionando
offline; a revogação só é aplicada quando a lista puder ser lida.

Formato de ``licenca.key`` (Base64 de um JSON)::

    {
      "payload": {
        "cliente": "...",
        "machine_id": "0123456789ABCDEF",
        "emitida_em": "2026-01-01",
        "expira_em": "2027-01-01"
      },
      "assinatura": "<Base64 da assinatura RSA-PSS/SHA-256 do payload>"
    }

O ``payload`` é assinado na forma canônica
``json.dumps(payload, sort_keys=True, separators=(",", ":"))``.
"""

from __future__ import annotations

import base64
import binascii
import datetime as _dt
import hashlib
import json
import os
import platform
import shutil
import uuid

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from navepro.core.log import get_logger
from navepro.core.paths import DATA_USER_DIR, DIR_BASE

log = get_logger("licenca")

NOME_ARQUIVO_LICENCA = "licenca.key"
NOME_ARQUIVO_TESTE = "trial.json"

# Tempo de teste completo (sem limites) a partir do primeiro uso no computador.
DIAS_TESTE = 10

# Lista negra pública (uma ID de máquina por linha). Falhas de rede são
# silenciosas: sem internet o app continua funcionando no modo offline.
URL_LISTA_NEGRA = (
    "https://gist.githubusercontent.com/"
    "edes-neves/"
    "fbe6e2bc21eb0849f1439a2ebcd9044b/"
    "raw/"
    "bloqueados.txt"
)

# Contato comercial exibido no modo demonstração (decisão do operador).
EMAIL_CONTATO = "nevestecnologias@gmail.com"
WHATSAPP_CONTATO = "(44) 3170-0809"

# Limites do modo demonstração.
LIMITE_DEMO_ITENS_PROJECAO = 3
LIMITE_DEMO_SLIDES_ANUNCIO = 3
LIMITE_DEMO_SORTEIO = 10

CHAVE_PUBLICA_PEM: bytes = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA2TWTukUDM1NkySe47IEf
MmMdqPiSc03Hq4dVWiGr1W70Z0YUNwGdRZ5FhTf/rgXER8DnuAgXk0M73uzUZh6f
sZjgLXIBzVpSU4MiqWKcnu8HJQv2H4877NN5qRMeIhmDns4D8VedSI0/N3BpcfHO
p3BE4gM/5Sl6rNdiguaLSOt2dMJdlM7pP7u0xWbP6+Ma4Ex+QIlb98QDp07VwRBt
wCnts7I07767GLdC4hzJynKP7jaKIkBs+TQp3hwyFkt8oaQ4uCWE3eCG5Ho5ktHA
wyLk7v7fmMOIrK9tLIi8ELhn3/f2BMc0qPwEpwPq84uOEM1jw3KIJNFQPGZgY1JI
hQIDAQAB
-----END PUBLIC KEY-----
"""

# Estado em memória da última verificação. Começa como "licenciado" para não
# alterar o comportamento de módulos importados antes da checagem no boot.
_ESTADO: dict = {
    "licenciado": True,
    "motivo": "",
    "cliente": "",
    "machine_id": "",
    "teste": False,
    "dias_restantes": 0,
}


def obter_id_maquina() -> str:
    """Identificador de hardware estável, com 16 caracteres hexadecimais.

    Combina o MAC/nó retornado por :func:`uuid.getnode` com dados da
    plataforma (sistema, arquitetura e processador). O hostname não entra:
    trocar o nome do computador não pode invalidar a licença.
    """
    base = "|".join((
        str(uuid.getnode()),
        platform.system(),
        platform.machine(),
        platform.processor(),
    ))
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16].upper()


def _diretorios_licenca() -> list[str]:
    """Locais procurados para ``licenca.key``, na ordem de preferência.

    O diretório da aplicação é o principal (requisito do projeto). O
    diretório de dados do usuário entra como fallback para instalações em
    que a pasta do programa é somente leitura (ex.: Flatpak).
    """
    diretorios = [DIR_BASE, DATA_USER_DIR]
    vistos: list[str] = []
    for diretorio in diretorios:
        if diretorio and diretorio not in vistos:
            vistos.append(diretorio)
    return vistos


def _caminhos_licenca() -> list[str]:
    return [os.path.join(d, NOME_ARQUIVO_LICENCA)
            for d in _diretorios_licenca()]


def _caminho_registro_teste() -> str:
    return os.path.join(DATA_USER_DIR, NOME_ARQUIVO_TESTE)


def _data_registro(valor: object) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None


def _ler_registro_teste() -> dict:
    try:
        with open(_caminho_registro_teste(), encoding="utf-8") as fh:
            dados = json.load(fh)
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _salvar_registro_teste(dados: dict) -> None:
    caminho = _caminho_registro_teste()
    try:
        diretorio = os.path.dirname(caminho)
        if diretorio:
            os.makedirs(diretorio, exist_ok=True)
        temporario = caminho + ".tmp"
        with open(temporario, "w", encoding="utf-8") as fh:
            json.dump(dados, fh, ensure_ascii=False, sort_keys=True)
        os.chmod(temporario, 0o600)
        os.replace(temporario, caminho)
    except OSError as exc:
        log.warning("Não foi possível gravar o registro de teste: %s", exc)


def _registro_teste_atual(machine_id: str) -> tuple[dict, _dt.date]:
    """Lê/cria o início do teste e devolve o registro + data efetiva.

    O relógio não pode voltar e aumentar o teste: se a data do sistema for
    anterior à última verificação, usamos a última data vista.
    """
    dados = _ler_registro_teste()
    hoje = _dt.date.today()
    inicio = _data_registro(dados.get("inicio"))
    if (not dados or dados.get("machine_id") != machine_id
            or inicio is None):
        dados = {
            "machine_id": machine_id,
            "inicio": hoje.isoformat(),
            "ultima_verificacao": hoje.isoformat(),
            "bloqueado": False,
        }
    else:
        ultima = _data_registro(dados.get("ultima_verificacao")) or inicio
        if hoje < ultima:
            hoje = ultima
        dados.update({
            "machine_id": machine_id,
            "inicio": inicio.isoformat(),
            "ultima_verificacao": hoje.isoformat(),
            "bloqueado": bool(dados.get("bloqueado")),
        })
    _salvar_registro_teste(dados)
    return dados, hoje


def _dias_restantes_teste(dados: dict, hoje: _dt.date) -> int:
    inicio = _data_registro(dados.get("inicio"))
    if inicio is None:
        return 0
    return max(0, DIAS_TESTE - (hoje - inicio).days)


def _avaliar_teste(dados: dict, hoje: _dt.date, machine_id: str,
                   consultar_lista_negra: bool) -> tuple[bool, str, str]:
    """Aplica o teste de 10 dias ou o modo demonstração."""
    if dados.get("bloqueado"):
        _definir_estado(False, "Licença revogada", machine_id=machine_id)
        return False, "Licença revogada", machine_id
    if consultar_lista_negra and esta_na_lista_negra(machine_id):
        dados["bloqueado"] = True
        _salvar_registro_teste(dados)
        _definir_estado(False, "Licença revogada", machine_id=machine_id)
        return False, "Licença revogada", machine_id

    restantes = _dias_restantes_teste(dados, hoje)
    if restantes > 0:
        motivo = f"Período de teste — {restantes} dia(s) restante(s)"
        _definir_estado(True, motivo, machine_id=machine_id, teste=True,
                        dias_restantes=restantes)
        return True, motivo, machine_id

    _definir_estado(False, "Período de teste encerrado",
                    machine_id=machine_id, dias_restantes=0)
    return False, "Período de teste encerrado", machine_id


def _definir_estado(licenciado: bool, motivo: str,
                    cliente: str = "", machine_id: str = "",
                    teste: bool = False, dias_restantes: int = 0) -> None:
    _ESTADO.update({
        "licenciado": bool(licenciado),
        "motivo": motivo,
        "cliente": cliente,
        "machine_id": machine_id,
        "teste": bool(teste),
        "dias_restantes": int(dias_restantes),
    })


def modo_demonstracao() -> bool:
    """True quando a última verificação não concedeu licença nem teste."""
    return not bool(_ESTADO.get("licenciado"))


def em_periodo_teste() -> bool:
    """True quando os recursos estão liberados pelo teste de 10 dias."""
    return bool(_ESTADO.get("licenciado") and _ESTADO.get("teste"))


def status_licenca() -> dict:
    """Cópia do estado atual (para a interface e para outros módulos)."""
    return dict(_ESTADO)


def limitar_slides_anuncio(slides: list) -> list:
    """No modo demonstração, mantém no máximo 3 slides por anúncio."""
    if modo_demonstracao() and len(slides) > LIMITE_DEMO_SLIDES_ANUNCIO:
        return slides[:LIMITE_DEMO_SLIDES_ANUNCIO]
    return slides


def esta_na_lista_negra(machine_id: str) -> bool:
    """Consulta online se o ID da máquina foi revogado.

    Retorna ``False`` em qualquer falha (sem internet, DNS, timeout, HTTP
    diferente de 200): o uso offline nunca é bloqueado por falta de rede.
    """
    machine_id = (machine_id or "").strip().upper()
    if not machine_id:
        return False
    try:
        resposta = requests.get(URL_LISTA_NEGRA, timeout=3)
        if resposta.status_code != 200:
            return False
        for linha in resposta.text.splitlines():
            if linha.strip().upper() == machine_id:
                return True
    except Exception as exc:  # noqa: BLE001 — offline/erro de rede é silencioso
        log.debug("Lista negra indisponível: %s", exc)
    return False


def _payload_canonico(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _ler_licenca(caminho: str) -> tuple[dict | None, bytes | None]:
    """Lê o envelope Base64 do arquivo e devolve (payload, assinatura)."""
    try:
        with open(caminho, encoding="utf-8") as fh:
            bruto = fh.read().strip()
        envelope = json.loads(base64.b64decode(bruto, validate=True))
        payload = envelope.get("payload")
        assinatura = envelope.get("assinatura")
        if not isinstance(payload, dict) or not isinstance(assinatura, str):
            return None, None
        return payload, base64.b64decode(assinatura, validate=True)
    except (OSError, ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        return None, None


def _verificar_assinatura(payload: dict, assinatura: bytes) -> bool:
    try:
        chave = serialization.load_pem_public_key(CHAVE_PUBLICA_PEM)
        chave.verify(
            assinatura,
            _payload_canonico(payload),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def _data_validade(payload: dict) -> _dt.date | None:
    valor = payload.get("expira_em") or payload.get("validade")
    if not valor:
        return None
    try:
        return _dt.date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def _remover_licenca() -> None:
    for caminho in _caminhos_licenca():
        try:
            if os.path.isfile(caminho):
                os.remove(caminho)
        except OSError as exc:
            log.warning("Não foi possível remover %s: %s", caminho, exc)


def importar_arquivo_licenca(origem: str) -> tuple[bool, str]:
    """Copia ``origem`` para o primeiro diretório gravável e revalida.

    Retorna ``(ok, mensagem)``. A cópia usa o nome canônico ``licenca.key``.
    """
    if not origem or not os.path.isfile(origem):
        return False, "Arquivo de licença não encontrado."
    destino = None
    for diretorio in _diretorios_licenca():
        try:
            os.makedirs(diretorio, exist_ok=True)
            if os.access(diretorio, os.W_OK):
                destino = os.path.join(diretorio, NOME_ARQUIVO_LICENCA)
                break
        except OSError:
            continue
    if destino is None:
        return False, "Não foi possível gravar a licença neste computador."
    try:
        if os.path.abspath(origem) != os.path.abspath(destino):
            shutil.copyfile(origem, destino)
        os.chmod(destino, 0o600)
    except OSError as exc:
        log.exception("Falha ao importar licença: %s", exc)
        return False, "Não foi possível copiar o arquivo de licença."
    ok, motivo, _ = verificar_licenca()
    return ok, motivo


def verificar_licenca(*, consultar_lista_negra: bool = True
                      ) -> tuple[bool, str, str]:
    """Valida a licença local, o teste de 10 dias ou a revogação online.

    Retorna ``(liberado, motivo, machine_id)``. ``liberado`` é True tanto para
    licença válida quanto para o período de teste. Nunca lança exceção por
    causa de arquivo ausente, licença inválida ou falta de internet.
    """
    machine_id = obter_id_maquina()
    registro_teste, hoje = _registro_teste_atual(machine_id)

    caminho = next((c for c in _caminhos_licenca() if os.path.isfile(c)), None)
    if caminho is None:
        return _avaliar_teste(registro_teste, hoje, machine_id,
                              consultar_lista_negra)

    payload, assinatura = _ler_licenca(caminho)
    if payload is None or assinatura is None:
        _definir_estado(False, "Licença inválida", machine_id=machine_id)
        return False, "Licença inválida", machine_id

    if not _verificar_assinatura(payload, assinatura):
        _definir_estado(False, "Licença inválida", machine_id=machine_id)
        return False, "Licença inválida", machine_id

    cliente = str(payload.get("cliente") or "").strip()
    licenca_machine = str(payload.get("machine_id") or "").strip().upper()
    if licenca_machine != machine_id:
        _definir_estado(False, "Licença de outra máquina", cliente,
                        machine_id)
        return False, "Licença de outra máquina", machine_id

    validade = _data_validade(payload)
    if validade is None:
        _definir_estado(False, "Licença inválida", cliente, machine_id)
        return False, "Licença inválida", machine_id
    if _dt.date.today() > validade:
        _definir_estado(False, "Licença expirada", cliente, machine_id)
        return False, "Licença expirada", machine_id

    if consultar_lista_negra and esta_na_lista_negra(machine_id):
        _remover_licenca()
        registro_teste["bloqueado"] = True
        _salvar_registro_teste(registro_teste)
        _definir_estado(False, "Licença revogada", cliente, machine_id)
        return False, "Licença revogada", machine_id

    motivo = f"Licenciado para {cliente}" if cliente else "Licenciado"
    _definir_estado(True, motivo, cliente, machine_id)
    return True, motivo, machine_id
