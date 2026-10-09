# NavePro — Sistema de Projeção Profissional

Aplicativo desktop (Python/Tkinter) para **projeção multimídia em dois monitores**:
o monitor principal (1) controla tudo e o segundo monitor (2) exibe o **telão**
(letras de hinos, Bíblia, mídias) em tela cheia para a congregação.

Disponível para **Windows** (`NavePro.exe`) e **Linux** (AppImage ou Flatpak),
com atualização automática.

---

## ✨ Funcionalidades

| Área | Descrição |
|---|---|
| **📺 Projeção** | Letras, versículos e mídias no monitor 2 (telão), com fonte, cor e tamanho configuráveis. |
| **📖 Hinos / Letras** | CRUD de hinos (artista, CCLI, categoria, letra completa), importação XML/TXT (OpenLyrics), busca e projeção por slides. |
| **✝️ Bíblia** | Importação em XML (Zefania), TXT e JSON (4 formatos), seleção versão/livro/capítulo/versículo com carga automática, busca e projeção sincronizada com o telão. |
| **📢 Anúncios** | Texto, imagem (com ou sem texto por cima), vídeo e áudio; importação TXT/PDF/mídia; editor de imagem + texto; redimensionamento ao vivo. |
| **📋 Ordem de Serviço** | Roteiro de culto com itens (hinos, mídias, sermão), letras em snapshot e tempo estimado; arquivos locais transferíveis. |
| **🔄 Transferir** | Exporta/importa anúncios e ordens de serviço num arquivo `.navepro` para levar a outro computador (inclui ou não as mídias). |
| **🎨 Tema claro/escuro** | Painel do operador alterna com o menu **Visualizar** ou **Ctrl+T**; o telão não é afetado. |
| **📦 Gerenciar Banco de Mídia** | Organização das mídias do acervo com busca. |
| **🔄 Atualização automática** | Verifica o release mais recente no GitHub e se atualiza sozinho conforme o formato instalado (`.exe`, `.AppImage` ou `flatpak update`). |

---

## 🚀 Instalação

### Windows (.exe)

1. Baixe o **`NavePro.exe`** na página [Releases](https://github.com/edes-neves/NavePro/releases).
2. Dê dois cliques. O app é **portátil**: não usa instalador nem registro e pode
   ficar em qualquer pasta (ou pen drive). Os dados ficam em `%USERPROFILE%\.navepro`.

> Para **pausar/continuar** vídeos pelo painel, instale o mpv uma vez por máquina
> (detalhes na seção "[Player de mídia no Windows](#player-de-mídia-no-windows-mpv)").

### Linux — AppImage

1. Baixe o **`NavePro-<versão>.AppImage`** na página [Releases](https://github.com/edes-neves/NavePro/releases).
2. Dê permissão de execução e rode:

   ```bash
   chmod +x NavePro-2.1.4.AppImage
   ./NavePro-2.1.4.AppImage
   ```

O AppImage é **autocontido** (Python, Tk 8.6 e dependências embutidos), então
funciona em qualquer distro sem instalar nada. Os dados ficam em `~/.navepro`.

### Linux — Flatpak (recomendado)

O Flatpak isola o app do sistema, instala pelo repositório oficial do NavePro
(hospedado no GitHub Pages `edes-neves.github.io/NavePro` e atualizado a cada
release pelo CI) e se atualiza com `flatpak update` — sem baixar arquivo manual.

**1) Instale o Flatpak** (se ainda não tiver):

```bash
# Debian / Ubuntu
sudo apt install flatpak

# Fedora
sudo dnf install flatpak

# Arch / Manjaro / BigLinux
sudo pacman -S flatpak
```

**2) Adicione o repositório oficial do NavePro** (uma vez, por usuário):

```bash
flatpak remote-add --user --if-not-exists --no-gpg-verify navepro https://edes-neves.github.io/NavePro/
```

**3) Instale o NavePro:**

```bash
flatpak install --user navepro io.github.edes_neves.NavePro
```

A primeira instalação baixa também o runtime do Flatpak automaticamente. Ao
final, o NavePro aparece no menu de aplicativos.

**4) Execute:**

```bash
flatpak run io.github.edes_neves.NavePro
```

**Atualizar:**

```bash
flatpak update --user
```

**Desinstalar:**

```bash
flatpak uninstall --user io.github.edes_neves.NavePro
```

> **Instalação manual a partir do release:** se preferir baixar o bundle na
> página de Releases, use o `NavePro-x86_64.flatpak` (ou `-aarch64.flatpak`) e:
>
> ```bash
> flatpak install --user --assumeyes NavePro-x86_64.flatpak
> flatpak run io.github.edes_neves.NavePro
> ```
>
> Este método exige repetir a instalação a cada versão; o **repositório** dos
> passos 1–3 é o que mantém o app atualizado sozinho.

Para instalar como administrador do sistema (sem `--user`, pede senha), remova
`--user` dos comandos acima.

---

## 🔄 Atualização automática (GitHub Releases)

Ao iniciar, ~20 s depois (e também pelo menu **Ajuda ▸ Verificar atualizações…**),
o app consulta o release mais recente de `edes-neves/NavePro` em segundo plano
(sem travar a interface). Se houver versão maior que a instalada, ele mostra as
novidades e pergunta se você quer atualizar.

O **passo seguinte depende de como o NavePro foi instalado** — o app se detecta
sozinho (Flatpak > Windows > AppImage; sem sinal de instalação, vale o AppImage):

| Instalação | O que acontece ao confirmar a atualização |
|---|---|
| **Windows** | Baixa o novo `NavePro.exe` para **`~/Downloads`** com barra de progresso; feche o app e substitua o arquivo antigo pelo baixado. |
| **AppImage** | Baixa o novo `NavePro-<versão>.AppImage` para **`~/Downloads`**; feche o app, troque o AppImage antigo pelo baixado e abra de novo. |
| **Flatpak** | Não baixa arquivo: roda `flatpak update --user` no host (via `flatpak-spawn --host`) e mostra a saída na tela. A atualização vem do repositório oficial configurado na instalação. |
| Código-fonte (`python NavePro.py`) | Baixa o AppImage do release como cópia de uso avulso (o aviso informa que não substitui nada). |

> A opção **Verificar atualizações…** mostra uma mensagem mesmo quando já está
> atualizado ou quando o GitHub está inacessível.

---

## 🖥 Guia de uso

### Janela Hinos / Letras

- **Busca** (`Buscar por número, título, artista ou letra...`):
  - Placeholder real: cinza quando vazio, some ao focar e volta ao sair sem digitar.
  - **Número** → busca pelo número do hino **no início do título** (ex.: `11`
    encontra `"11 - Maior Que Tudo"`), não pelo ID interno.
  - **Texto** → busca por fragmento em título, artista e letra completa.
- **➕ Novo Hino / ✏️ Editar**: formulário com título, artista, compositor, CCLI,
  categoria e letra.
- **🗑️ Excluir**: exclusão física (`DELETE FROM letras`) — o ID sai do banco.
- **📥 Importar (XML/TXT)**: seletor no home, sem pastas ocultas, só `*.xml`/`*.txt`;
  importa coleções OpenLyrics (como `NHA/` e `HASD/`).
- **📺 Projetar**: slides no telão com **◀ Anterior / ▶ Próximo / ⏹ Parar (Esc)**,
  ajuste **A−/A+** e navegação por **setas do teclado**.

> O número da primeira coluna é o ID interno; o número real do hinário está no
> título (`"13 - ..."`). Por isso a busca numérica lê o número inicial do título.

### Janela Bíblia

- **Versão padrão**: **"Almeida Revista e Corrigida"** se existir no banco (senão,
  a primeira versão disponível).
- **📥 Importar Bíblia**: `*.xml` / `*.txt` / `*.json`, no home, sem pastas ocultas.
- **Navegação**: Livro + Capítulo + Versículo + **Ir**.
- **Carga automática**: trocar versão/livro/capítulo recarrega o texto sozinho em
  500 ms (não há botão "Carregar"; se nada mudar, use **Ir**).
- **Campo "V:"** — o que projetar:
  - vazio ou `1` → capítulo inteiro;
  - `16` → do versículo 16 até o fim do capítulo;
  - `9-16` → faixa **inclusiva** (9 a 16). Quando o texto não couber, o campo
    mostra a faixa válida (`9 a 16`).
- **Busca por texto**: LIKE no texto da versão selecionada.
- **📺 Projetar**: destaca o versículo atual (fundo `#6e40c9`) e projeta cada
  versículo no telão. Faixa parcial (`9-16`) começa no início, encerra sozinha
  (⏹ vira "⏹ Encerrar") e o painel mostra `faixa 9-16`.
- **Sincronização Monitor 1 ↔ Monitor 2**: navegar (◀ ▶ ou setas) avança o
  versículo junto no telão e na janela (campo V: acompanha, destaque se move,
  tela rola). **⏹ / Esc** encerra.

### Janela Anúncios

- Os anúncios ficam na tabela `anuncios` do `~/.navepro/midia.db` (o `anuncios.json`
  legado é migrado **uma única vez**; IDs são reaproveitados quando excluídos).
- **Tipos**: `slide` (texto), `imagem` (pode ter texto por cima) e `vídeo`/`áudio`.
- **📥 Importar Mídia**: TXT/PDF viram anúncios de texto; vídeo/áudio/imagem são
  copiados para `~/.navepro/uploads` e registrados no banco.
- **📺 Projetar**: texto → slides respeitando a digitação (slide 0 = título);
  imagem+texto → compõe e projeta uma única imagem; imagem → imagem pura;
  vídeo/áudio → player (com opção de repetir).
- No painel **🎬 Controle da Projeção**: **A−/A+** ajusta a fonte e **🖼️ Imagem: −/+**
  redimensiona a imagem **ao vivo**, sem parar a projeção.

#### Editor de anúncio (imagem + texto)

- Pré-visualização **unificada**: o texto é desenhado na base e a imagem ajustada
  por cima, no mesmo canvas, com **arrastar para mover** e **alças** para redimensionar.
- Espaço virtual de **1440×1080**, independente da resolução do telão; ao salvar,
  a posição/tamanho (`w/h/x/y`) fica em `config_midia`.
- Configurações antigas (320×250, sem posição) são migradas automaticamente.
- A projeção compõe imagem + texto na proporção do telão, mantendo exatamente a
  posição ajustada no editor.

### Janela Ordem de Serviço

- Monte o roteiro do culto com itens (hinos, mídias, sermão/PDF, anúncios), com
  letras em snapshot e tempo estimado. Salva em `~/.navepro/servicos.json`
  (migração automática do banco legado; IDs de hinos/versículos referenciados
  ficam preservados da reutilização).
- **➕ Adicionar / ✏️ Editar item**: janela que abre **centralizada sobre a Ordem
  de Serviço** e mantém a posição ao trocar o tipo ou arrastar.
- A execução do serviço começa no item selecionado e avança item a item
  (Executar Serviço); item com **Sermão** abre o PDF no visualizador em tela cheia.

### 🔄 Transferir anúncios e Ordem de Serviço

O botão **🔄 Transferir** (em Anúncios e na Ordem de Serviço) usa o mesmo seletor
de arquivos do app:

- **Transferir…** grava um arquivo `.navepro` (nome sugerido
  `NavePro-Transferencia-<data>.navepro`). Se o nome digitado for uma pasta, o
  seletor **entra** nela; se já existir, pergunta antes de sobrescrever.
- **Importar…** lê o `.navepro` (ou `.zip`) e pergunta se quer incluir as mídias;
  arquivos que não existirem mais no outro PC são avisados e ignorados.
- O seletor **não mostra arquivos/pastas ocultos** (`.`) e não usa o diálogo do sistema.

---

## 🗄 Banco de dados

Localização: **`~/.navepro/midia.db`** (SQLite).

| Tabela | Uso |
|---|---|
| `letras` | Hinos: `id`, `titulo`, `artista`, `compositor`, `ccli_numero`, `categoria`, `idioma`, `letra_completa`, `ativo` |
| `versiculos` | Bíblia: `id`, `versao`, `livro`, `capitulo`, `versiculo`, `texto` |
| `anuncios` | Anúncios: `id`, `titulo`, `categoria`, `texto`, `tipo_midia`, `arquivo_midia`, `nome_arquivo_midia`, `config_midia`, `ativo` |
| `midia` | Mídias do acervo (FTS em `midia_fts` para busca) |

Notas:

- A exclusão de hinos é **física**; não há chave estrangeira para `letras.id`. Os IDs
  de `letras`/`versiculos` são reaproveitados (lacunas preenchidas), exceto os
  ainda referenciados por itens de ordem de serviço. A Ordem de Serviço guarda
  também a cópia da letra (snapshot).
- A Ordem de Serviço migrou para **`~/.navepro/servicos.json`** (as tabelas legadas
  `servicos`/`itens_servico` só existem para migração).
- O `anuncios.json` legado é migrado uma vez para `anuncios` e deixa de ser usado.
- SQLite não suporta `COUNT(DISTINCT a, b)` — contagens compostas usam concatenação.

---

## 🛠 Para desenvolvedores

### Rodar a partir do código-fonte

Requisitos: **Python 3.10+** com **Tk 8.6** (o Tk 9.0 não resolve aliases de fonte
e gera textos minúsculos/quadradinhos) e as dependências do `requirements.txt`:

```bash
python -m pip install -r requirements.txt
python NavePro.py
```

O Tk do Windows não é DPI-aware; o `NavePro.py` chama `_tornar_dpi_aware()` antes
de abrir janelas (ver `navepro/core/ambiente.py`).

### Gerar o NavePro.exe (Windows)

```bat
build-windows.bat
```

O script confere o Tk 8.6, instala as dependências e empacota com o `NavePro.spec`
(a **fonte única** do empacotamento, mesma usada no Linux). O `.exe` sai sem
console; para ver o log de detecção de monitores:

```bat
set NAVEPRO_CONSOLE=1 && build-windows.bat
```

O ícone do executável vem de `img\Icon.ico` (variável `NAVEPRO_ICON`); sem ele o
`.exe` sai sem ícone próprio, mas as janelas continuam com ícone.

O `.exe` também é gerado automaticamente pelo GitHub Actions a cada tag `v*`.

### Gerar o AppImage (Linux)

```bash
./build.sh 2.1.4          # gera NavePro-2.1.4.AppImage
```

O `build.sh` usa o **mesmo `NavePro.spec`** do `.exe`, monta o `AppDir/` e comprime
com o `appimagetool` da raiz (variável `APPIMAGE_TOOL` para outro). Usa o `.venv`
do projeto quando existe e exige Tk 8.6. Passo a passo detalhado: `Gerar.AppImage`.

### Build e instalação local do Flatpak (Linux)

```bash
# pré-requisito: flatpak + flatpak-builder + runtime 24.08 (ver build-flatpak.sh)
./build-flatpak.sh            # gera io.github.edes_neves.NavePro.<arch>.flatpak
./build-flatpak.sh --install  # também instala no usuário
```

O CI publica o repositório oficial no `gh-pages` (branche `master` do repositório
ostree) a cada release — é o repositório que os usuários adicionam ao instalar.

### Publicar uma versão nova

1. Grave a versão em `navepro/config.py` (`APP_VERSION`) — é o que o app exibe e
   compara. Não pule a versão: um release `v2.2.0` com binário em `2.1.1` faz o
   app oferecer "atualizar" baixando a si mesmo.
2. Gere o **AppImage** no Linux (o `.exe` e os bundles `.flatpak` são construídos
   pelo GitHub Actions a partir da tag):

   ```bash
   ./build.sh 2.1.4
   ```

3. Comite, crie a tag e empurre. O push da tag `v*` dispara os workflows
   `NavePro.exe` (runner Windows) e `Flatpak` (x86_64 + aarch64), que constroem e
   **anexam os artefatos ao release** e publicam o repositório Flatpak no
   `gh-pages`:

   ```bash
   git add -A && git commit -m "NavePro 2.1.4: ..."
   git tag v2.1.4
   git push origin main v2.1.4
   ```

4. Crie o release com o AppImage (o workflow anexa o `.exe` e os `.flatpak` ao
   mesmo release):

   ```bash
   gh release create v2.1.4 NavePro-2.1.4.AppImage \
     --title "NavePro 2.1.4" --notes "O que mudou nesta versão..."
   ```

O app usa o `tag_name` do release mais recente como versão a oferecer; o primeiro
`*.exe` atende o Windows e o primeiro `*.AppImage`, o Linux. Releases precisam
carregar **os dois** — sem o do formato instalado, o aviso diz isso em vez de quebrar.

### Estrutura do projeto

```
NavePro.py            # Aplicativo principal (interface + projeção + importadores)
navepro/              # Infraestrutura reutilizável (config, caminhos, temas, textos, atualização)
  config.py           # APP_VERSION e constantes de configuração
  core/player.py      # Player de mídia no Windows: acha o executável, IPC do mpv, posiciona a janela
NavePro.spec          # Configuração do PyInstaller (fonte única do empacotamento)
build-windows.bat     # Gera o dist\NavePro.exe
build.sh              # Gera o AppImage do Linux (usa o mesmo NavePro.spec)
build-flatpak.sh      # Gera/instala o bundle Flatpak localmente
Gerar.AppImage        # Passo a passo do empacotamento do AppImage
flatpak/              # Manifestos e metainfo do Flatpak (local e Flathub)
README.md             # Este documento
AGENTS.md             # Guia para agentes de IA (testes, build, release, convenções)
LICENSE               # GPLv3
requirements.txt      # Dependências (runtime + pyinstaller)
Biblias/              # Bíblias para importar (XML do Zefania e TXT): AS21, ARC, ACF, ARA…
  AS21.xml            #   Bíblia Almeida Século 21 (XML Zefania)
  biblia-em-txt.txt   #   Bíblia Almeida Revista e Corrigida (TXT)
NHA/                  # Hinário (OpenLyrics XML) — Novo Hinário Adventista
HASD/                 # Hinário (OpenLyrics XML)
tests/                # Suítes de teste headless (ver "Testes")
img/                  # Ícones do app (Icon.png, Icon.xbm, Icon.ico…)
.github/workflows/    # CI: testes, geração do .exe e do Flatpak
.gitignore            # Arquivos locais/artefatos de build ignorados
```

### Player de mídia no Windows (mpv)

No Windows o NavePro abre o vídeo em um player externo; o **mpv** é o responsável
pelo **pausar/continuar** pelo painel, por aceitar comando remoto (IPC JSON). Ele
**não** vem embutido no `.exe` (seriam +56 MB) e precisa ser instalado **uma vez
por máquina**:

```bat
winget install mpv-player.mpv-CI.MSVC
```

Sem o mpv, o NavePro continua funcionando: detecta e usa **VLC** ou **SMPlayer**
se estiverem instalados, o vídeo abre no telão e o **parar** funciona. Só o
pausar/continuar fica indisponível — o app avisa na tela com o comando de
instalação, em vez de falhar calado.

#### Como o player é colocado no monitor do telão

| Player | Como entra no telão |
|---|---|
| **VLC** | `--fullscreen` + `--qt-fullscreen-screennumber=<n>` (o VLC se posiciona; o NavePro só esconde o painel que abre na tela principal). |
| **mpv**, **SMPlayer** | Abertos sem `--fullscreen`; a janela é colocada sobre o telão via Win32 (`posicionar_janela_player`), sem moldura e por cima das outras. |

- **VLC não pode ser reposicionado por código**: redimensionar o vout do
  VLC 3.0.24 (`direct3d11`) faz a janela crescer sem parar (medido: 1920×1080 →
  5328×9368 → 10240×21341 → 12864×27737), travando o telão. Deixando o VLC se
  posicionar, o vídeo entra no monitor certo e fica estável.
- **mpv e SMPlayer não usam `--fullscreen`**: mpv 0.41 ignora `--screen` e
  `--geometry` em tela cheia e abre no monitor primário (mesmo caso do relógio do
  telão em `TelaoWindow._aplicar_tela_cheia`).

### Testes

As suítes ficam em `tests/` e rodam **sem tela e sem servidor** — quando precisam
de interface, recriam um `Tk` falso e extraem do `NavePro.py` só o trecho testado
(via `ast`).

```bat
set PYTHONUTF8=1
python tests\test_logica.py          :: uma suíte
for %f in (tests\test_*.py) do @python %f || echo FALHOU: %f   :: todas
```

> `PYTHONUTF8=1` importa no console antigo do Windows (cmd com cp1252): sem ele,
> o print dos emojis da suíte (✅, ◀, 📁) estoura `UnicodeEncodeError`. No GitHub
> Actions o workflow já força o modo UTF-8.

No GitHub Actions (`.github/workflows/testes.yml`) a suíte roda nos **dois**
sistemas a cada push e pull request — `ubuntu-latest` e `windows-latest` — para
que uma mudança de um lado não quebre o outro sem ninguém perceber. As suítes de
bíblia/projeção apontam para `tests/fixture_biblia.py`, que monta um banco
temporário com o schema real (`init_db` extraído do `NavePro.py`).

| Suíte | O que cobre |
|---|---|
| `test_logica.py` | Regras de texto, versículos, mídia e banco |
| `test_gui.py` | Widgets e callbacks da interface (Tk falso) |
| `test_gui_reload.py` | Carga automática da Bíblia: debounce de 500 ms, timer cancelado ao fechar, recarga ignorada com a janela morta |
| `test_projecao.py` | Projeção de versículo e de hino no telão |
| `test_projecao_faixa.py` | Faixa de versículos (`9-16`): começa no 9, encerra no 16, rótulo `faixa 9-16`, entradas inválidas (`abc`, `9-3`, `1-`, `0`) |
| `test_indicador.py` | Indicador de progresso |
| `test_seletor.py` | Seletor de arquivos do app (filtros e pastas ocultas) |
| `test_imagens.py` | Imagens de fundo e transferência entre janelas |
| `test_monitores.py` | Escolha do monitor do painel e do telão: nunca os dois no mesmo monitor |
| `test_player_windows.py` | Player no Windows: descoberta de executáveis, pipe do mpv, flags (mpv sem `--fullscreen`; VLC com `--fullscreen`), posicionamento da janela, fim de faixa, aviso de pausa |
| `test_atualizacao.py` | Detecção de instalação e escolha do asset do release |

Duas suítes de verificação ligam o código à máquina e servem quando o problema só
aparece na tela:

```bat
python tests\validar_vlc_telao.py   :: toca o MP4 no telão e confere por captura de tela
python tests\validar_aviso.py        :: roda o aviso de pausa com Tk real e caça exceção
```

> Detalhe que já custou tempo: o `after()` do Tk devolve o id do timer como
> **`str`**; guardar o timer sob chave `int` num Tk falso faz o `after_cancel`
> não encontrar nada — o debounce parece quebrado quando não está.

> Outro: toda leitura de arquivo de teste precisa de `encoding="utf-8"`. Sem isso,
> o `open()` usa `cp1252` no Windows e estoura `UnicodeDecodeError` em qualquer
> acento — a suíte passa no Linux e quebra no Windows.

---

## 💾 Dados locais (`~/.navepro/`)

No Windows esta pasta é `%USERPROFILE%\.navepro`.

| Arquivo/pasta | Conteúdo |
|---|---|
| `midia.db` | Banco SQLite: hinos, versículos, anúncios e mídias |
| `servicos.json` | Ordens de Serviço (após migração) |
| `anuncios.json` | Legado — migrado uma vez para `midia.db` e não é mais lido |
| `uploads/` | Cópias das mídias importadas nos anúncios |
| `config.json` | Configuração local (cidade/estado, monitor do telão, player) — ignorado do git |

## 🔧 Ajustes comuns

- **Tamanho das janelas**: `janela.geometry("LARGURAxALTURA")` em `janela_hinos`
  (Hinos), `janela_biblia` (Bíblia) e na janela de Anúncios.
- **Configuração local** (`~/.navepro/config.json`, ignorado do git): cidade/estado,
  monitor do telão e player.

---

## 📜 Histórico recente

### 2.1.4

- **Janela de adicionar/editar item da Ordem de Serviço não abre mais no canto
  superior esquerdo**: passa a se **centralizar sobre a janela da Ordem de Serviço**
  e a **manter a posição** ao clicar nos campos ou arrastar (AppImage, `.exe` e
  Flatpak).
- **Anúncios com texto + imagem deixam de sair minúsculos** e o **A−/A+ volta a
  funcionar** em distros sem DejaVu/Liberation (ex.: **BigLinux/GNOME**): o app
  procura qualquer TTF/OTF instalado e usa o tamanho real no Pillow.
- **Janela de Anúncios mais larga (1000 px)** para o conteúdo caber sem cortes.

### 2.1.1

- **Atualização corrigida para quem instalou como Flatpak**: o NavePro detecta que
  está num Flatpak e roda `flatpak update --user`, em vez de baixar um `.AppImage`
  que não funcionaria. Era o defeito mais relatado.
- A janela de atualização do Flatpak mostra a saída em tempo real (com o comando
  exato no alto), avisa para reiniciar o app e, se falhar, mostra o comando para
  rodar no terminal.
- Textos por tipo de instalação: pergunta, rótulo e instruções certas para Flatpak,
  AppImage, Windows ou código-fonte.
- Bíblias extras (`AS21.xml`, `biblia-em-txt.txt`) no Flatpak, alinhado ao repositório.
- Suítes de teste no repositório (pasta `tests/`).

### 2.1.0

- Bíblia carrega sozinha (500 ms ao trocar versão/livro/capítulo).
- Faixa de versículos no **V:** (`9-16` inclusiva; `16` até o fim; vazio/`1` = capítulo).
- Projeção acompanha a faixa: encerra sozinha no último versículo (⏹ vira "⏹ Encerrar").
- Janela do operador sempre no monitor 1.
- Seletor de arquivos do app em tudo (transferência, imagem de fundo), sem pasta oculta e sem piscar.

### 2.0.0 e anteriores

- Anúncios no banco de dados (tabela `anuncios`, migração automática).
- Ordem de Serviço em `servicos.json` (migração automática).
- Editor de anúncio unificado (imagem + texto) em espaço 1440×1080.
- Redimensionamento ao vivo da imagem e da fonte no telão.
- Tema claro/escuro (menu Visualizar ou Ctrl+T).
- Modo Repetir para mídias.
- Atualização automática via GitHub Releases.
- Importação de Bíblia em XML/TXT e JSON (4 formatos, BOM UTF-8).
- Projeção sincronizada na Janela Bíblia.
- Busca de hinos: numérica e por texto; placeholder real; exclusão física.

---

## 📄 Licença

Distribuído sob a **GPLv3** (veja `LICENSE`).