# NavePro — repositório Flatpak

Este repositório permite instalar o [NavePro](https://github.com/edes-neves/NavePro) (sistema
de projeção multimídia para igreja) como um aplicativo Flatpak atualizável.

## Instalar

Requer Flatpak instalado (Debian/Ubuntu: `sudo apt install flatpak`).

```bash
flatpak remote-add --if-not-exists --user navepro https://edes-neves.github.io/NavePro/io.github.edes_neves.NavePro.flatpakrepo
flatpak install --user navepro io.github.edes_neves.NavePro
```

> O repositório não é assinado com GPG; por isso o `--no-gpg-verify` é aplicado
> automaticamente pelo `.flatpakrepo` quando necessário. Em caso de aviso de
> verificação GPG, use:
> `flatpak remote-add --if-not-exists --user --no-gpg-verify navepro <url acima>`

## Executar

```bash
flatpak run io.github.edes_neves.NavePro
```

## Atualizar

```bash
flatpak update --user io.github.edes_neves.NavePro
```

## Notas

- Versão publicada neste repositório: **2.3.0** (x86_64 e aarch64).
- Usa o player de vídeo do sistema (SMPlayer/MPV) para reproduzir as mídias no telão.
- O idioma principal do aplicativo é o português (Brasil).
- Documentação completa e histórico de versões:
  https://github.com/edes-neves/NavePro
