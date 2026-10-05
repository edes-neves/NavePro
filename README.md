# NavePro — Sistema de Projeção para Igreja

Aplicativo desktop (Python/Tkinter) para **projeção multimídia em dois monitores**: o monitor principal (1) controla tudo e o segundo monitor (2) exibe o **telão** (letras de hinos, Bíblia, mídias) em tela cheia para a congregação.

Desenvolvido para Ubuntu (Python 3 + Tkinter), empacotado como AppImage.

---

## Funcionalidades

| Área | Descrição |
|---|---|
| **Projeção** | Exibe letras, versículos e mídias no monitor 2 (telão), com configuração de fonte, cor e tamanho. |
| **📖 Hinos / Letras** | CRUD de hinos (artista, CCLI, categoria, letra completa), importação XML/TXT, busca, projeção com navegação por slides. |
| **📢 Anúncios** | CRUD na tabela `anuncios` do SQLite (com migração automática do `anuncios.json` legado), importação de **TXT/PDF/vídeo/áudio/imagem** (mídias copiadas para `~/.navepro/uploads`) e projeção com **editor de imagem + texto**. |
| **✝️ Bíblia** | Importação de bíblias em XML/TXT/JSON, seleção de versão/livro/capítulo/versículo com **carga automática**, busca por texto e projeção sincronizada com o telão (um versículo por slide, com opção de faixa). |
| **📋 Ordem de Serviço** | Montagem de roteiros de culto com itens (hinos, mídias), com letras em snapshot e tempo estimado; salva em `~/.navepro/servicos.json` (migração automática do banco legado). |
| **🔄 Transferir** | Exporta/importa anúncios e ordens de serviço num arquivo `.navepro` para levar a outro computador (Flatpak incluído). |
| **🎨 Tema claro/escuro** | Painel do administrador (monitor 1) alterna entre tema claro e escuro — menu **Visualizar** ou atalho **Ctrl+T**; o telão não é afetado. |
| **📦 Gerenciar Banco de Mídia** | Organização das mídias utilizadas nas apresentações. |
| **🎨 Projeção (config)** | Mesmo diálogo de ajustes de aparência usado por Hinos e Bíblia. |
| **🔄 Atualização automática** | Verifica versões novas no GitHub (Releases) e baixa o novo AppImage para `~/Downloads` com instruções de instalação. |

---

## Atualizações (GitHub Releases)

O NavePro consulta o repositório **`edes-neves/NavePro`** no GitHub:

1. Ao iniciar, ~20s depois (e também pelo menu **Ajuda ▸ Verificar atualizações…**), o app consulta `https://api.github.com/repos/edes-neves/NavePro/releases/latest` em segundo plano (sem travar a interface).
2. Se a versão do release for **maior** que a instalada, mostra o aviso com as novidades e pergunta se deseja atualizar.

O **passo 3 depende de como o NavePro foi instalado** — o app se detecta sozinho
(`FLATPAK_ID`/`/.flatpak-info` = Flatpak, `APPIMAGE` = AppImage, Windows = `.exe`):

| Instalação | O que acontece ao confirmar |
|---|---|
| **Flatpak** | Roda `flatpak update --user` **no sistema** (via `flatpak-spawn --host`). Não baixa nada. |
| **AppImage** | Baixa o novo `.AppImage` do release para **`~/Downloads`** com barra de progresso. |
| **Windows** | Baixa o novo `.exe` para **`~/Downloads`** com barra de progresso. |
| Código-fonte (Linux) | Baixa o `.AppImage` como cópia para usar à vontade (o aviso diz que não substitui nada). |

Instalação Flatpak (a mais comum no Linux), depois de confirmar:

1. Abre uma janela com a **saída do `flatpak update` em tempo real** (o comando exato fica no alto, para copiar se precisar).
2. Ao final, avisa que deu certo e pede para **fechar e abrir o NavePro** de novo — o Flatpak só troca os arquivos na próxima execução.
3. Se o comando falhar, a janela mostra o erro e o comando para rodar no terminal. Instalar no **sistema** (e não no usuário) faz o app pedir confirmação de administrador; nesse caso o próprio Flatpak explica.

> Os dois comandos abaixo são o que o app executa:
> ```bash
> flatpak-spawn --host flatpak update --user --assumeyes io.github.edes_neves.NavePro
> # ou, manualmente, fora do app:
> flatpak update --user --assumeyes io.github.edes_neves.NavePro
> ```
> O `--assumeyes` é importante: sem ele o Flatpak pergunta "Prosseguir com estas alterações? [Y/n]" e, como o app roda sem terminal, a resposta seria **não** e nada seria atualizado.
>
> A opção **Verificar atualizações…** (menu Ajuda) mostra uma mensagem mesmo quando já está atualizado ou quando o GitHub está inacessível.
>
> Quem instalou pelo Flatpak e quer atualizar na mão pode usar `flatpak update --appstream` para renovar os metadados do remote antes (é o que faz o `flatpak info` mostrar a versão certa).

### Como publicar uma versão nova

1. **Publique com a versão** — o `publicar.sh` grava o `APP_VERSION` em `navepro/config.py`, chama o `./build.sh <versão>` (gera o `NavePro-<versão>.AppImage` já nomeado com a versão) e faz commit, tag, push e release:

   ```bash
   ./publicar.sh 2.1.0              # grava APP_VERSION, gera o AppImage e publica o release
   ./NavePro-2.1.0.AppImage         # teste
   ```

   Se quiser **apenas gerar** o AppImage (sem publicar), rode o `build.sh` diretamente:

   ```bash
   ./build.sh 2.1.0                 # gera NavePro-2.1.0.AppImage usando a versão passada
   ./NavePro-2.1.0.AppImage         # teste
   ```

   > ⚠️ **Não pule a versão**: se criar um release `v2.1.0` com um AppImage ainda em `2.0.0`, o binário se achará desatualizado e oferecerá "atualizar" baixando a si mesmo. O `./publicar.sh <versão>` previne isso (grava e confere o `APP_VERSION` em `navepro/config.py`).

2. Se preferir publicar **manualmente** (o `publicar.sh` já faz tudo): commite as mudanças, crie um **tag** na versão (ex.: `v2.1.0`) e crie o release no GitHub anexando o AppImage:

   ```bash
   gh release create v2.1.0 NavePro-2.1.0.AppImage --title "NavePro 2.1.0" --notes "O que mudou nesta versão..."
   ```

O app considera o `tag_name` do release mais recente como a versão a oferecer; o primeiro asset `*.AppImage` é o que será baixado.

---

## Janela Hinos / Letras

- **Busca** (campo `Buscar por número, título, artista ou letra...`):
  - É um **placeholder real**: cinza quando vazio, some ao focar e volta ao sair sem digitar.
  - **Termo numérico** → busca pelo **número do hino que está no começo do título** (ex.: digitar `11` encontra `"11 - Maior Que Tudo"`), **não** pelo ID interno.
  - **Termo de texto** → busca por fragmento em título, artista e letra completa.
- **➕ Novo Hino / ✏️ Editar**: formulário com título, artista, compositor, CCLI, categoria e letra.
- **🗑️ Excluir**: **exclusão física** (`DELETE FROM letras`) — o ID sai do banco junto com o conteúdo.
- **📥 Importar (XML/TXT)**: abre o **seletor de arquivos do usuário** (home), escondendo pastas ocultas (`.`) e mostrando só `*.xml`/`*.txt`; importa coleções em formato OpenLyrics (como as pastas `NHA/` e `HASD/`).
- **📺 Projetar**: projeta o hino selecionado em slides no telão, com painel **◀ Anterior / ▶ Próximo / ⏹ Parar (Esc)**, ajuste de tamanho **A−/A+** e navegação também por **setas do teclado**.

### Onde fica o "número" do hino?
O número exibido na primeira coluna é o **ID** interno. O número real do hinário está no **título** (`"13 - ..."`). Por isso a busca numérica lê o número inicial do título (função `_numero_do_titulo`), evitando confusão quando IDs foram apagados ou há registros desativados.

---

## Janela Bíblia

- **Versão padrão**: ao abrir, seleciona **"Almeida Revista e Corrigida"** se ela existir no banco (senão, a primeira versão disponível). A lista de versões é lida do banco (`DISTINCT versao`).
- **Importar Bíblia** (`📥`): o botão abre um **seletor no home do usuário**, sem pastas ocultas (`.`) e com apenas `*.xml` / `*.txt` / `*.json`.
- **Navegação**: Livro + Cap + Versículo (campo **V:**) + botão **Ir**.
- **Carga automática**: ao trocar versão, livro ou capítulo, o texto é recarregado sozinho (500 ms após a última mudança) — não há botão "Carregar". Se o texto não mudar (ex.: a mesma referência de novo), use **Ir**.
- **Campo "V:"** — o que projetar:
  - **vazio** ou **`1`** → capítulo inteiro;
  - **`16`** → do versículo 16 **até o fim** do capítulo;
  - **`9-16`** → faixa **inclusiva** (9 a 16).

  Quando o texto não couber na janela, o campo mostra a faixa válida (`9 a 16`).
- **Busca por texto** (`Buscar versículo por texto...`): LIKE no texto da versão selecionada.
- **📺 Projetar** (controle de projeção 🎬): exibe o capítulo na janela com o versículo atual **destacado** (fundo roxo `#6e40c9`) e projeta cada versículo no telão. Se o campo "V:" define uma faixa, a projeção **começa no início da faixa** e **termina sozinha** no último versículo (o botão ⏹ passa a ser "⏹ Encerrar"). Enquanto uma faixa parcial está projetada, o painel 🎬 mostra o indicador `faixa 9-16`.
- **Sincronização Monitor 1 ↔ Monitor 2**: ao navegar (botões ◀ ▶ **ou** setas do teclado) o versículo avança **junto** no telão e na janela — o campo "V:" acompanha, o destaque se move e a tela rola até o versículo. **⏹ / Esc** encerra e limpa o destaque.

### Formatos aceitos na importação de Bíblia

**XML (Zefania)** — `AS21.xml`:
```xml
<XMLBIBLE biblename="Almeida Século 21">
  <BIBLEBOOK bnumber="1" bname="Gênesis">
    <CHAPTER cnumber="1"><VERS vnumber="1">...</VERS></CHAPTER>
  </BIBLEBOOK>
</XMLBIBLE>
```

**TXT (Almeida Revista e Corrigida)** — `biblia-em-txt.txt`:
```
GÊNESIS
1
No princípio criou Deus os céus e a terra.
...
```
Autodetecção de livro (romanos I/II, nomes com acentos, cabeçalhos colados como `AMÓS1`).

**JSON** — 4 estruturas aceitas:

1. Objeto aninhado (versículo → texto):
```json
{"Gênesis": {"1": {"1": "No princípio..."}}}
```
2. Objeto com capítulos como listas:
```json
{"Gênesis": {"1": ["No princípio...", "Era a terra..."]}}
```
3. `books` com capítulos por objetos de versículo (formato GetBible):
```json
{
  "version": "nvi",
  "books": [{"name": "Gênesis", "chapters": [[{"verse": 1, "text": "..."}]]}]
}
```
4. Lista plana de versículos:
```json
[{"book": "Gênesis", "chapter": 1, "verse": 1, "text": "..."}]
```

Particularidades tratadas:
- Arquivos com **BOM UTF-8** são aceitos (abertura com `utf-8-sig`).
- Livros são **normalizados sem acentos** e com apelidos (`1 Coríntios`, `II Reis`, `Cânticos`, `Lamentações`...).
- A versão é lida de `version/versao/biblename/translation/nome/name` ou do **nome do arquivo**.
- Livros não reconhecidos são listados no aviso ao final da importação.

---

## Janela Anúncios

- **Banco de dados**: os anúncios ficam na tabela `anuncios` do `~/.navepro/midia.db`. O `anuncios.json` legado é importado **uma única vez** (migração automática); os IDs são reaproveitados quando o anúncio é excluído.
- **Tipos de anúncio**: `slide` (texto), `imagem` (pode ter texto por cima), `vídeo`/`áudio` (tocam no player).
- **📥 Importar Mídia**: TXT/PDF viram anúncios de texto; vídeo/áudio/imagem são copiados para `~/.navepro/uploads` e registrados no banco.
- **📺 Projetar**:
  - Anúncio de texto → slides **respeitando a digitação do operador** (slide 0 = título), navegação ◀/▶.
  - Anúncio com imagem **e** texto → compõe a imagem sobre o texto e projeta como uma única imagem.
  - Anúncio só com imagem → projeta a imagem pura.
  - Anúncio de vídeo/áudio → toca no player (com opção de repetir).
- No painel **🎬 Controle da Projeção**: **A−/A+** ajusta a fonte do texto e **🖼️ Imagem: −/+** redimensiona a imagem ao vivo, sem parar a projeção.

### Editor de anúncio (imagem + texto)

- **Novo Anúncio / Editar Anúncio** abre um editor com **pré-visualização unificada**: o texto digitado é desenhado na base e a imagem é ajustada por cima, no mesmo canvas, com **arrastar para mover** e **alças para redimensionar**.
- O espaço de edição usa um plano virtual de **1440×1080**, independente da resolução do telão; ao salvar, a posição/tamanho da imagem (`w/h/x/y`) fica em `config_midia`.
- Configurações antigas (formato 320×250, sem posição) são **migradas automaticamente**: a imagem é redimensionada e reposicionada à direita, centralizada verticalmente.
- A projeção compõe a imagem + texto na proporção do telão, mantendo exatamente a posição ajustada no editor.

### 🔄 Transferir anúncios e Ordem de Serviço

O botão **🔄 Transferir** existe na janela de **Anúncios** e na de **Ordem de Serviço** e usa o mesmo seletor de arquivos do app:

- **Transferir…** grava um arquivo `.navepro` (o campo **Nome do arquivo** já vem preenchido com `NavePro-Transferencia-<data>.navepro`). Navegue até a pasta de destino, ajuste o nome e clique em **💾 Salvar**. Se já existir um arquivo com esse nome, o NavePro pergunta antes de sobrescrever; se o nome digitado for uma **pasta**, ele **entra** na pasta em vez de salvar.
- **Importar…** lê o `.navepro` (ou um `.zip`) e pergunta se quer incluir as mídias — arquivos que não existirem mais no outro PC são avisados e ignorados.
- O seletor **não mostra pastas/arquivos ocultos** (`.`) e **não pisca** ao abrir: é o mesmo diálogo do app, não o do sistema.

---

## Banco de dados

Localização: **`~/.navepro/midia.db`** (SQLite).

Tabelas principais:

| Tabela | Uso |
|---|---|
| `letras` | Hinos: `id`, `titulo`, `artista`, `compositor`, `ccli_numero`, `categoria`, `idioma`, `letra_completa`, `ativo` |
| `versiculos` | Bíblia: `id`, `versao`, `livro`, `capitulo`, `versiculo`, `texto` |
| `anuncios` | Anúncios: `id`, `titulo`, `categoria`, `texto`, `tipo_midia`, `arquivo_midia`, `nome_arquivo_midia`, `config_midia`, `ativo` |
| `midia` | Mídias do acervo (com FTS em `midia_fts` para busca) |

Notas:
- A exclusão de hinos é **física**; não há chave estrangeira para `letras.id`. Por isso os IDs de `letras`/`versiculos` são **reaproveitados** (preenchimento das lacunas) — exceto os IDs ainda referenciados por itens de ordem de serviço, que ficam preservados; a Ordem de Serviço guarda também a cópia da letra (snapshot).
- A **Ordem de Serviço** migrou do banco para **`~/.navepro/servicos.json`** (migração automática na primeira execução). As tabelas legadas `servicos`/`itens_servico` só existem para migração.
- O `anuncios.json` legado de anúncios é migrado **uma vez** para a tabela `anuncios` e deixa de ser usado.
- SQLite não suporta `COUNT(DISTINCT a, b)` — contagens compostas usam concatenação.

---

## Como executar

**Requisitos (desenvolvimento):** Python 3 + Tkinter com **Tk 8.6** (o que
resolve os aliases de fonte do fontconfig: "Arial" → Liberation Sans).
O **Tk 9.0** (ex.: python do conda) **não** resolve esses aliases e deixa
fontes minúsculas/botões "quadradinhos" — evite. Para o logo aparecer,
instale o **Pillow (PIL)** no python usado para rodar/empacotar
(`pip install Pillow`). O AppImage usa as fontes instaladas no sistema de
destino; em qualquer Linux desktop (que tenha fontes liberation/dejavu/noto)
o "Arial" resolve para uma sans-serif equivalente.

```bash
python -m pip install -r requirements.txt
python NavePro.py
```

> O AppImage (seção abaixo) embute o mesmo Tk 8.6, então fica idêntico ao
> `python NavePro.py`.

### Gerar AppImage
O AppImage é **autocontido** (PyInstaller embute Python + **Tk 8.6**), então
não precisa de python3/tkinter na máquina de destino e as fontes ficam
idênticas em qualquer lugar. Use `build.sh` (reproduz o passo a passo do
`Gerar.AppImage`) com um python de Tk 8.6:

```bash
./build.sh 2.1.0       # usa o python com Tk 8.6; PYTHON_BIN=.venv/bin/python ./build.sh
```

Ou, manualmente:
```bash
/usr/sbin/python -m PyInstaller --noconfirm --clean --onefile \
    --name NavePro --hidden-import "PIL._tkinter_finder" \
    --add-data "img/Icon.xbm:img/" --add-data "img/Icon.png:img/" NavePro.py   # gera dist/NavePro
cp dist/NavePro AppDir/usr/bin/NavePro && chmod +x AppDir/usr/bin/NavePro
ARCH=x86_64 appimagetool AppDir NavePro-2.1.0.AppImage
./NavePro-2.1.0.AppImage
```

> **Por que PyInstaller?** O AppRun antigo usava o `python3` do sistema
> (Tk 8.6), que é o que funciona bem. A troca errada anterior para o **Tk 9.0**
> (conda) quebrava as fontes: o Tk 9.0 não resolve "Arial" → Liberation Sans
> e caía para a fonte bitmap `fixed` (minúscula + quadradinhos). O binário
> PyInstaller garante o **Tk 8.6** dentro do AppImage.
> **Edite sempre `NavePro.py` na raiz** (e os módulos de infraestrutura em
> `navepro/`, se aplicável) e repita o build;
> `AppDir/usr/bin/NavePro.py` não é mais usado (virou o binário).

### Gerar Flatpak

O Flatpak empacotado **não precisa do PyInstaller/imagetool** — o `python3` da
runtime do Flatpak roda o `NavePro.py` direto. O módulo `_tkinter` (ausente
na runtime) é compilado a partir do [tkinter-standalone](https://github.com/iwalton3/tkinter-standalone)
com **Tcl/Tk 8.6.15** (mantém as mesmas fontes do AppImage).

**Build local** (requer `flatpak-builder`):
```bash
sudo apt install flatpak-builder
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install flathub org.freedesktop.Platform//24.08 org.freedesktop.Sdk//24.08

./build-flatpak.sh              # gera io.github.edes_neves.NavePro.<arch>.flatpak
./build-flatpak.sh --install    # instala no usuário atual
```

**Build multi-arquitetura (GitHub Actions):**
A workflow `.github/workflows/flatpak.yml` gera bundles para `x86_64` e
`aarch64` em cada release (`git push origin v<versão>`). O `flatpak-builder`
usa QEMU para cross-compile em aarch64.

**Publicar no Flathub:**
O manifesto `flatpak/io.github.edes_neves.NavePro.yaml` está pronto para
submissão. O Flathub compila automaticamente para **x86_64**, **aarch64** e
**riscv64** — sem infraestrutura extra. Para submeter, crie um pull request
em [flathub/flathub](https://github.com/flathub/flathub) apontando para este
repositório.

---

## Testes

As suítes ficam em `tests/` e rodam **sem tela e sem servidor** — quando precisam
de interface, recriam um `Tk` falso e extraem do `NavePro.py` só o trecho que
está sendo testado (via `ast`). Assim dá para testar no CI e em máquina sem X.

```bash
python3 tests/test_logica.py          # uma suíte
for f in tests/test_*.py; do python3 "$f" || echo "FALHOU: $f"; done   # todas
```

| Suíte | O que cobre |
|---|---|
| `test_logica.py` | Regras de texto, versículos, mídia e banco |
| `test_gui.py` | Widgets e callbacks da interface (Tk falso) |
| `test_gui_reload.py` | Carga automática da Bíblia: debounce de 500 ms, timer cancelado ao fechar a janela, recarga ignorada com a janela morta |
| `test_projecao.py` | Projeção de versículo e de hino no telão |
| `test_projecao_faixa.py` | Faixa de versículos (`9-16`): começa no 9, encerra no 16, rótulo `faixa 9-16`, e as entradas inválidas (`abc`, `9-3`, `1-`, `0`, faixa inexistente) |
| `test_indicador.py` | Indicador de progresso |
| `test_seletor.py` | Seletor de arquivos do app (filtros e pastas ocultas) |
| `test_imagens.py` | Imagens de fundo e transferência entre janelas |
| `test_atualizacao.py` | Detecção de instalação (Flatpak/AppImage/Windows), escolha do asset e comando do `flatpak update` |

> Um detalhe que já custou tempo: o `after()` do Tk devolve o id do timer como
> **`str`**. Num Tk falso, guardar o timer sob chave `int` faz o `after_cancel`
> silenciosamente não encontrar nada — o debounce parece quebrado quando não está.

---

## Estrutura do projeto

```
NavePro.py            # Aplicativo principal (interface + projeção + importadores)
navepro/              # Infraestrutura reutilizável (config, caminhos, temas, textos, atualização)
  config.py           # APP_VERSION e constantes de configuração
NavePro.spec          # (gerado pelo PyInstaller)
README.md             # Este documento
LICENSE               # GPLv3
requirements.txt      # Dependências (runtime + pyinstaller)
build.sh              # Gera o AppImage (PyInstaller + appimagetool)
Gerar.AppImage        # Passo a passo (resumo) para empacotar o AppImage
Biblias/               # Bíbblias para importar (XML do Zefania e TXT): AS21, ARC, ACF, ARA…
  AS21.xml            #   Bíblia Almeida Século 21 (XML Zefania)
  biblia-em-txt.txt   #   Bíblia Almeida Revista e Corrigida (TXT)
NHA/                  # Hinário (OpenLyrics XML) — Novo Hinário Adventista
HASD/                 # Hinário (OpenLyrics XML)
AppDir/               # Estrutura do AppImage (AppRun, .desktop, ícones)
flatpak/              # Manifesto Flatpak + .desktop + metainfo + wrapper + repositório
tests/                # Suítes de teste headless (ver "Testes")
.github/workflows/    # CI/CD: build Flatpak multi-arquitetura (x86_64 + aarch64)
img/                    # Ícones do app (Icon.png, Icon.xbm, Icon.ico…)
.gitignore            # Arquivos locais/artefatos de build ignorados
```

---

## Dados locais (`~/.navepro/`)

| Arquivo/pasta | Conteúdo |
|---|---|
| `midia.db` | Banco SQLite: hinos, versículos, anúncios e mídias |
| `servicos.json` | Ordens de Serviço (após migração) |
| `anuncios.json` | Legado — migrado uma vez para `midia.db` e não é mais lido |
| `uploads/` | Cópias das mídias importadas nos anúncios |
| `config.json` | Configuração local (cidade/estado, monitor do telão, player) — ignorado do git |

## Ajustes comuns

- **Tamanho das janelas**: `janela.geometry("LARGURAxALTURA")` em `janela_hinos` (Hinos) e `janela_biblia` (Bíblia).
- **Configuração local** (`~/.navepro/config.json`, ignorado do git): cidade/estado, monitor do telão e player.

---

## Histórico recente

### 2.1.1

- **Atualização corrigida para quem instalou como Flatpak**: o NavePro detecta que está dentro do Flatpak e roda `flatpak update --user` no sistema, em vez de baixar um `.AppImage` que não funcionaria. Era o defeito mais relatado — o app oferecia "baixar novo AppImage" para quem já tinha o Flatpak instalado.
- **Janela de atualização do Flatpak** mostra a saída do comando em tempo real (com o comando exato no alto), avisa para reiniciar o app ao final e, se falhar, mostra o comando para rodar no terminal em vez de sumir com o erro.
- **Textos por tipo de instalação**: a pergunta, o rótulo do arquivo e as instruções de instalação dizem a coisa certa para Flatpak, AppImage, Windows ou execução a partir do código-fonte (nesse caso avisa que o AppImage baixado é só uma cópia).
- **Bíblias extras no Flatpak**: o manifesto passa a copiar `AS21.xml` e `biblia-em-txt.txt` da pasta `Biblias/`, alinhado com o repositório.
- **Suítes de testes no repositório** (pasta `tests/`, antes só existiam na máquina de desenvolvimento): 9 suítes headless, documentação de como rodar e o que cada uma cobre.

### 2.1.0

- **Bíblia carrega sozinha**: trocar versão, livro ou capítulo recarrega o texto em 500 ms (o botão **📖 Carregar** saiu da janela).
- **Faixa de versículos** no campo **V:** — `9-16` projeta só a faixa (inclusiva) e um número (`16`) projeta desse versículo até o fim; vazio/`1` continua sendo o capítulo inteiro.
- **Projeção acompanha a faixa**: começa no primeiro versículo da faixa, **encerra sozinha** no último (o ⏹ vira "⏹ Encerrar") e o painel 🎬 mostra o indicador `faixa 9-16`.
- **Janela do operador sempre no monitor 1** do sistema (antes podia abrir no telão).
- **Seletor de arquivos do app em todo lugar**: salvar transferência, importar transferência e escolher imagem de fundo não usam mais o diálogo do sistema — sem pastas ocultas (`.`) e sem piscar ao abrir.

### 2.0.0 e anteriores

- **Anúncios no banco de dados**: tabela `anuncios` no SQLite, com migração automática do `anuncios.json` legado e reaproveitamento de IDs livres.
- **Ordem de Serviço em `servicos.json`**: migração automática do banco legado; IDs de hinos/versículos referenciados ficam preservados da reutilização.
- **Editor de anúncio unificado (imagem + texto)**: pré-visualização em espaço virtual 1440×1080, mover/redimensionar a imagem sobre o texto, migração de configurações antigas.
- **Redimensionamento ao vivo da imagem no telão**: botões **🖼️ Imagem: −/+** no painel da projeção, além do **A−/A+** da fonte — sem interromper o que está projetado.
- **Tema claro/escuro** no painel do administrador (menu Visualizar ou **Ctrl+T**), sem alterar as cores do telão.
- **Modo Repetir** para mídias do player (menu Visualizar).
- **Atualização automática** via GitHub Releases com download para `~/Downloads` e instruções de instalação.
- Importação de Bíblia em **XML/TXT** com normalização de livros (acentos/apelidos).
- Importação de Bíblia em **JSON** (4 formatos, suporte a BOM UTF-8).
- Janela Bíblia com os mesmos recursos de projeção da janela Hinos (painel 🎬, atalhos de teclado, 🎨 Projeção).
- **Sincronização da projeção** entre a janela Bíblia (monitor 1) e o telão (monitor 2), com destaque do versículo atual.
- Filtro de busca de hinos: numérico = número do hino no título; texto = fragmento.
- **Placeholder** real no campo de busca de hinos.
- **Exclusão física** de hinos (remove o ID do banco).
- Versão padrão da Bíblia = **Almeida Revista e Corrigida**; remoção da versão `nvi` não utilizada.
- **Seletor de arquivos do usuário** para Importar Bíblia e Importar Hinos: abre no home, esconde pastas/arquivos ocultos (`.*`) e filtra extensões. (Desde 2.1.0 é usado também para salvar transferência e escolher imagem de fundo.)