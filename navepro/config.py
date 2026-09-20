"""NavePro - configurações de topo (constantes da aplicação).

Módulo de configuração: define constantes globais simples que não
dependem da interface nem do servidor HTTP. Depende apenas de
navepro.core.ambiente para detectar o sistema operacional.
"""

from navepro.core.ambiente import _eh_windows

APP_VERSION: str = "1.9.7"
PLAYER_PADRAO: str = "mpv" if _eh_windows() else "smplayer"
BACKEND_PORT: int = 5897
BACKEND_URL: str = f"http://127.0.0.1:{BACKEND_PORT}"

# ── Atualização automática (GitHub Releases) ──
# O NavePro consulta o release mais recente em
# https://github.com/{GITHUB_REPO}/releases/latest e, se houver versão
# nova, oferece baixar o AppImage para ~/Downloads com instruções de
# substituição do arquivo antigo.
GITHUB_USER: str = "edes-neves"
GITHUB_REPO: str = "NavePro"
RELEASES_API_URL: str = (
    f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/releases/latest"
)
SEGUNDOS_PARA_VERIFICAR_ATUALIZACAO: int = 20

EXTENSOES_VIDEO: frozenset = frozenset({'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.webm'})
EXTENSOES_AUDIO: frozenset = frozenset({'.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac'})
EXTENSOES_TEXTO: frozenset = frozenset({'.txt', '.pdf', '.doc', '.docx', '.md'})
EXTENSOES_TODAS: frozenset = EXTENSOES_VIDEO | EXTENSOES_AUDIO | EXTENSOES_TEXTO

SQLITE_TIMEOUT: int = 10
CACHE_TTL_SEGUNDOS: int = 60
CACHE_LRU_MAXSIZE: int = 256

# Extensões de imagem aceitas como "slide" nos anúncios
SUFIXOS_IMAGEM: frozenset = frozenset({'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif'})

# Siglas dos estados brasileiros -> nome completo
MAPA_ESTADOS: dict[str, str] = {
    'AC': 'Acre', 'AL': 'Alagoas', 'AP': 'Amapá', 'AM': 'Amazonas',
    'BA': 'Bahia', 'CE': 'Ceará', 'DF': 'Distrito Federal',
    'ES': 'Espírito Santo', 'GO': 'Goiás', 'MA': 'Maranhão',
    'MT': 'Mato Grosso', 'MS': 'Mato Grosso do Sul', 'MG': 'Minas Gerais',
    'PA': 'Pará', 'PB': 'Paraíba', 'PR': 'Paraná', 'PE': 'Pernambuco',
    'PI': 'Piauí', 'RJ': 'Rio de Janeiro', 'RN': 'Rio Grande do Norte',
    'RS': 'Rio Grande do Sul', 'RO': 'Rondônia', 'RR': 'Roraima',
    'SC': 'Santa Catarina', 'SP': 'São Paulo', 'SE': 'Sergipe',
    'TO': 'Tocantins',
}