# Publicar no Flathub

## Pré-requisitos

1. Solicite acesso à organização [flathub](https://github.com/flathub) abrindo um issue em https://github.com/flathub/new-issues/issues/new com o título:
   ```
   [App]: NavePro - io.github.edesneves.NavePro
   ```
   Descreva brevemente o app (sistema de projeção para igreja, Python/Tkinter, GPLv3).

2. Após aprovação, crie o repositório:
   ```
   flathub/io.github.edesneves.NavePro
   ```

3. Copie os arquivos desta pasta para o repositório criado:
   ```bash
   cd io.github.edesneves.NavePro
   cp ~/Público/NavePro/flatpak/flathub/* .
   git add .
   git commit -m "Initial manifest"
   git push
   ```

4. O Flathub buildbot compilará automaticamente para:
   - `x86_64`
   - `aarch64`
   - `riscv64`

## Arquivos necessários no repo `flathub/io.github.edesneves.NavePro`

| Arquivo | Função |
|---|---|
| `io.github.edesneves.NavePro.yml` | Manifesto principal (aponta para o tag do seu repo) |
| `io.github.edesneves.NavePro.desktop` | Arquivo .desktop |
| `io.github.edesneves.NavePro.metainfo.xml` | Metadados AppStream |
| `patches/` | Patches se necessário (vazio por enquanto) |

## Atualizar versão

Quando lançar uma nova versão (ex: v1.9.2):
1. Atualize o `tag` e `commit` no manifesto
2. Faça commit e push no repo `flathub/io.github.edesneves.NavePro`
3. O buildbot reconstrói automaticamente
