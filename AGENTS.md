# AGENTS.md — NavePro

Guia para agentes de IA que trabalham neste repositório. Idioma do projeto:
**português** (mensagens de commit, comentários, textos da interface).

## Sobre o projeto

- **O que é:** aplicativo desktop (Python/Tkinter) de projeção multimídia em **dois
  monitores** para igrejas — monitor 1 controla, monitor 2 é o telão.
- **Repositório:** `github.com/edes-neves/NavePro` · Licença GPLv3.
- **Monolito principal:** `NavePro.py` (~15 mil linhas). Infraestrutura em `navepro/`.
- **Distribuição:** `NavePro.exe` (Windows), `NavePro-<versão>.AppImage` (Linux) e
  Flatpak (`io.github.edes_neves.NavePro`). Versão atual em `navepro/config.py` → `APP_VERSION`.
- **Idioma do app:** português, com emojis na interface.

## Requisitos / Tk 8.6 (IMPORTANTE)

- Python **3.10+** com **Tk 8.6**. O **Tk 9.0 quebra as fontes** (aliases de fonte
  do fontconfig não são resolvidos: textos minúsculos/quadradinhos). Sempre
  empacote com um Python de Tk 8.6 (o `.venv` do projeto serve).
- Dependências (`requirements.txt`): `screeninfo`, `Pillow>=10.0.0`, `pypdf>=4.0.0`
  e `pyinstaller>=6.22.0` (só build).

## Rodar / testar

```bash
python3 -m pip install -r requirements.txt   # (ou use o .venv/)
python3 NavePro.py                           # roda o app (fonte)

# Suíte headless (NÃO é pytest): um comando por arquivo
for f in tests/test_*.py; do python3 "$f"; done

# Lint (ruff, config em pyproject.toml) — roda no CI a cada push/PR
python3 -m pip install 'ruff==0.17.0'   # ou use o .venv/
ruff check .
```

- As suítes rodam **sem tela/servidor**; quando precisam da interface, recriam um
  `Tk` falso e extraem o trecho do `NavePro.py` via `ast`.
- **Windows:** prefixar os testes com `set PYTHONUTF8=1` (emojis quebram no cp1252).
- CI (`.github/workflows/testes.yml`) roda a suíte em `ubuntu-latest` **e**
  `windows-latest` **e** o ruff (só em `ubuntu-latest`) a cada push/PR.
- O ruff 0.17 mudou o default para um seleto gigante (YTT/ASYNC/S/BLE...); o
  `pyproject.toml` fixa as regras do projeto (`E,F,I,UP,B`, sem E501/E701/E702) —
  **não** rode `ruff check` sem esse arquivo e não mexa nele sem rodar a suíte e
  o repositório ficar limpo.

## Build e release

| Artefato | Comando | Obs. |
|---|---|---|
| AppImage | `./build.sh 2.1.4` | usa o `.venv`; exige Tk 8.6; gera `NavePro-2.1.4.AppImage` |
| .exe | `build-windows.bat` (só Windows) | usa o `NavePro.spec` |
| Flatpak (bundle local) | `./build-flatpak.sh` | manifest: `flatpak/io.github.edes_neves.NavePro.yaml` |

- `NavePro.spec` é a **fonte única** do PyInstaller para Linux e Windows.
  `NAVEPRO_CONSOLE=0/1` controla a janela de console; `NAVEPRO_ICON=img\Icon.ico` o ícone.
- **Release 2.1.x+ (fluxo atual):** bump de `APP_VERSION` → `./build.sh <versão>`
  → commit + `git tag v<versão>` → push de `main` + tag. O push da tag dispara o CI,
  que constrói/anexa `.exe` e `.flatpak` (x86_64 + aarch64) ao release e publica o
  repositório Flatpak no `gh-pages` (`edes-neves.github.io/NavePro`). O **AppImage**
  é anexado manualmente: `gh release create v<versão> NavePro-<versão>.AppImage --title ... --notes ...`
  (ou `gh release upload ... --clobber` se o release já existir).
- Os workflows de release usam `softprops/action-gh-release` com `overwrite_files: true`.
- **Não mude de versão sem o usuário pedir** (não pule para a próxima release por conta própria).

## Estrutura

```
NavePro.py          # interface + projeção + importadores (banco, Hinos, Bíblia, Anúncios, Ordem de Serviço)
navepro/
  config.py         # APP_VERSION, GITHUB_USER/REPO, BACKEND_PORT=5897, APP_ID_FLATPAK, EXTENSOES_*
  core/ambiente.py  # _eh_windows(), _tornar_dpi_aware()
  core/log.py       # logging central (nível por NAVEPRO_LOG), usado por NavePro.py e navepro/
  core/paths.py     # _caminho_base/_caminho_recurso (suporta PyInstaller), DATA_USER_DIR, DB_PATH
  core/player.py    # player no Windows (mpv IPC JSON, VLC/SMPlayer detectados, posiciona janela)
assets/
  Biblias/, NHA/, HASD/    # bíblias XML/TXT e hinários OpenLyrics para importação
tests/                     # suítes headless (ver acima)
flatpak/                   # manifests (local + flathub/) e metainfo
img/                       # ícones (Icon.png, Icon.xbm, Icon.ico)
.github/workflows/         # testes.yml, exe.yml, flatpak.yml
```

## Dados locais (`~/.navepro/`; no Windows `%USERPROFILE%\.navepro`)

- `midia.db` — SQLite: tabelas `letras`, `versiculos`, `anuncios`, `midia` (+ `midia_fts`).
- `servicos.json` — Ordem de Serviço (migrada do banco legado).
- `config.json` — config local (cidade/estado, monitor do telão, player) — **ignorado do git**.
- `uploads/` — cópias das mídias importadas em anúncios.
- `anuncios.json` — legado, migrado uma vez para `midia.db`.
- `navepro.log` — log da aplicação (rotativo, 1 MB × 3); nível por `NAVEPRO_LOG`.

## Convenções e gotchas

- **Tk `after()` devolve o id do timer como `str`.** Guardar sob chave `int` num Tk
  falso faz o `after_cancel` falhar em silêncio (bug de debounce da Bíblia).
- **Toda leitura de arquivo em teste precisa de `encoding="utf-8"`** (senão usa
  cp1252 no Windows e quebra em qualquer acento).
- **Logging:** use `navepro.core.log.get_logger()` (o app expõe `log` no nível do
  módulo em `NavePro.py`); **não** use `print` em código de produção. Nível por
  `NAVEPRO_LOG` (padrão `WARNING`), arquivo `~/.navepro/navepro.log`. Trechos
  extraídos via AST nos testes referenciam `log`: injete o stub de `tests/fixture_log.py`.
- **Janela do editor da Ordem de Serviço:** ao alterar a geometria, aplique **só o
  tamanho** (`geometry("WxH")`, nunca coordenadas) e use `_centralizar_sobre(...)`;
  coordenadas fixas fazem a janela pular para o canto superior esquerdo
  (GNOME/mutter aplica offset de moldura no pedido de geometria).
- **Fontes (PIL):** o texto dos anúncios é medido/desenhado com o Pillow e o tamanho
  reage ao A−/A+. `_localizar_fonte_ttf()` procura DejaVu/Liberation/FreeSans e, se
  nada existir, aceita **qualquer** `.ttf/.otf` do sistema (caso de distros sem
  DejaVu, ex. BigLinux) — evite voltar ao `load_default()` sem `size`.
- **Players no Windows:** o **VLC não pode** ser reposicionado/redimensionado por
  código (`direct3d11` faz a janela crescer sem parar); usar `--fullscreen --qt-fullscreen-screennumber=<n>`.
  mpv/SMPlayer abrem sem `--fullscreen` e são posicionados via Win32.
- **Flatpak:** manifest com `finish-args` que dão acesso a `~/.navepro`, players do
  host (`--filesystem=host-os`, `flatpak-spawn`) e D-Bus MPRIS (mpv/smplayer/vlc.
  Runtime `org.freedesktop.Platform//24.08` — o Tcl/Tk é construído no build (8.6.15).
- **Repositório Flatpak oficial** é auto-hospedado (GitHub Pages) e **não assinado**:
  os usuários adicionam com `flatpak remote-add --user --no-gpg-verify navepro https://edes-neves.github.io/NavePro/`.

## Fontes de verdade

- Documentação e instruções de instalação: `README.md` (atualizado, inclui Flatpak).
- Passo a passo do AppImage: `Gerar.AppImage`.
- Histórico de releases: seção "Histórico recente" do `README.md` e `flatpak/io.github.edes_neves.NavePro.metainfo.xml`.