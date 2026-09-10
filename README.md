# NavePro — repositório Flatpak

Este repositório permite instalar o [NavePro](https://github.com/edes-neves/NavePro) (sistema
de projeção multimídia para igreja) como um aplicativo Flatpak atualizável.

## Instalar

Requer Flatpak instalado (Debian/Ubuntu: `sudo apt install flatpak`).

```bash
flatpak remote-add --if-not-exists --user navepro https://edes-neves.github.io/NavePro/io.github.edesneves.NavePro.flatpakrepo
flatpak install --user navepro io.github.edesneves.NavePro
```

> O repositório não é assinado com GPG; por isso o `--no-gpg-verify` é aplicado
> automaticamente pelo `.flatpakrepo` quando necessário. Em caso de aviso de
> verificação GPG, use:
> `flatpak remote-add --if-not-exists --user --no-gpg-verify navepro <url acima>`

## Executar

```bash
flatpak run io.github.edesneves.NavePro
```

## Atualizar

```bash
flatpak update --user io.github.edesneves.NavePro
```

## Notas

- Usa o player de vídeo do sistema (SMPlayer/MPV) para reproduzir as mídias no telão.
- Arquiteturas: x86_64 (a64/aarch64 futuramente).
- O idioma principal do aplicativo é o português (Brasil).