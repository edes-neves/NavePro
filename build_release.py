#!/usr/bin/env python3
"""Build protegido do NavePro (PyArmor + PyInstaller).

Ofusca ``license_manager.py`` (e o script de entrada, quando a licença do
PyArmor permitir) e gera o binário standalone com o mesmo ``NavePro.spec``
usado nos builds normais. No Linux, também monta o AppImage com o
``appimagetool``.

Uso:
    .venv/bin/python build_release.py --target linux
    .venv/bin/python build_release.py --target windows

O PyArmor trial não ofusca scripts grandes (o ``NavePro.py`` passa do limite
"out of license"); nesse caso o build continua e ofusca só o módulo de
licenciamento, que é o alvo principal. Para ofuscar também a entrada, defina
``PYARMOR_LICENSE`` apontando para uma licença registrada (ou instale em
``~/.pyarmor/license.lic``).

    Saídas:
        dist/NavePro                              (Linux)
        dist/NavePro.exe                          (Windows)
        NavePro-<versão>.AppImage                 (Linux; --no-appimage omite)

"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
OFB = os.path.join(RAIZ, "obf")
DIST = os.path.join(RAIZ, "dist")


def _log(mensagem: str) -> None:
    print(f"[build] {mensagem}", flush=True)


def _falhar(mensagem: str) -> None:
    raise SystemExit(f"[build] ERRO: {mensagem}")


def _versao_padrao() -> str:
    sys.path.insert(0, RAIZ)
    try:
        from navepro.config import APP_VERSION
    finally:
        sys.path.pop(0)
    return APP_VERSION


def _rodar(comando: list[str], *, env: dict | None = None,
           capturar: bool = False) -> subprocess.CompletedProcess:
    _log("$ " + " ".join(comando))
    return subprocess.run(
        comando,
        cwd=RAIZ,
        env=env,
        text=True,
        capture_output=capturar,
        check=False,
    )


def _pyarmor_disponivel() -> bool:
    try:
        import pyarmor.cli  # noqa: F401
    except ImportError:
        return False
    return True


def _gerar_ofuscado(entrada: str, extras: list[str]) -> bool:
    """Roda o PyArmor sobre ``entrada`` + ``extras``; True se gerou tudo."""
    comando = [
        sys.executable, "-m", "pyarmor.cli", "gen", "-O", OFB,
        entrada, *extras,
    ]
    resultado = _rodar(comando, capturar=True)
    if resultado.stdout:
        print(resultado.stdout, end="")
    if resultado.stderr:
        print(resultado.stderr, end="", file=sys.stderr)
    esperados = [entrada, *extras]
    return resultado.returncode == 0 and all(
        os.path.isfile(os.path.join(OFB, os.path.basename(item)))
        for item in esperados
    )


def _obfuscar() -> None:
    if not _pyarmor_disponivel():
        _falhar(
            "PyArmor não instalado. Rode: "
            f"{sys.executable} -m pip install pyarmor"
        )

    shutil.rmtree(OFB, ignore_errors=True)
    os.makedirs(OFB, exist_ok=True)

    _log("Ofuscando NavePro.py + license_manager.py com PyArmor...")
    if _gerar_ofuscado("NavePro.py", ["license_manager.py"]):
        _log("Ofuscação completa gerada em obf/.")
        return

    # Trial do PyArmor recusa scripts grandes. O módulo de licenciamento é o
    # alvo crítico, então o build continua ofuscando apenas ele.
    _log("Aviso: a entrada NavePro.py excedeu o limite do PyArmor; "
         "ofuscando apenas license_manager.py.")
    shutil.rmtree(OFB, ignore_errors=True)
    os.makedirs(OFB, exist_ok=True)
    if not _gerar_ofuscado("license_manager.py", []):
        _falhar(
            "PyArmor não conseguiu ofuscar license_manager.py. "
            "Verifique a licença/instalação do PyArmor."
        )
    _log("Ofuscação parcial gerada em obf/.")


def _build_pyinstaller() -> str:
    _log("Empacotando com PyInstaller (NavePro.spec)...")
    env = os.environ.copy()
    entrada_ofuscada = os.path.join(OFB, "NavePro.py")
    licenca_ofuscada = os.path.join(OFB, "license_manager.py")
    runtime_ofuscado = os.path.join(OFB, "pyarmor_runtime_000000")

    if os.path.isdir(runtime_ofuscado) and os.path.isfile(licenca_ofuscada):
        env["NAVEPRO_ARMORED"] = "1"
        env["NAVEPRO_PATHEX"] = os.pathsep.join([OFB, RAIZ])
        if os.path.isfile(entrada_ofuscada):
            env["NAVEPRO_ENTRY"] = "obf/NavePro.py"
            _log("Usando a entrada ofuscada obf/NavePro.py.")
        else:
            env["NAVEPRO_ENTRY"] = "NavePro.py"
    else:
        env.pop("NAVEPRO_ARMORED", None)
        env.pop("NAVEPRO_PATHEX", None)
        env["NAVEPRO_ENTRY"] = "NavePro.py"

    # Garante que `import license_manager` resolva o módulo do obf/ mesmo que
    # o PyInstaller procure primeiro a pasta do script de entrada.
    original_licenca = os.path.join(RAIZ, "license_manager.py")
    renomeada = False
    if (env.get("NAVEPRO_ARMORED") == "1"
            and os.path.isfile(original_licenca)
            and os.path.isfile(licenca_ofuscada)):
        oculta = original_licenca + ".orig"
        shutil.move(original_licenca, oculta)
        renomeada = True
    try:
        resultado = _rodar(
            [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
             "NavePro.spec"],
            env=env,
        )
    finally:
        if renomeada:
            shutil.move(original_licenca + ".orig", original_licenca)
    if resultado.returncode != 0:
        _falhar("PyInstaller terminou com erro.")

    if sys.platform.startswith("win"):
        saida = os.path.join(DIST, "NavePro.exe")
    else:
        saida = os.path.join(DIST, "NavePro")
    if not os.path.isfile(saida) or os.path.getsize(saida) < 1_000_000:
        _falhar(f"Binário não foi gerado corretamente: {saida}")
    _log(f"Binário gerado: {saida}")
    return saida


def _localizar_appimagetool() -> str | None:
    candidato = os.environ.get("APPIMAGE_TOOL", "")
    if candidato and os.path.isfile(candidato):
        return candidato
    local = os.path.join(RAIZ, "appimagetool")
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return local
    return shutil.which("appimagetool")


def _gerar_appimage(versao: str) -> str:
    ferramenta = _localizar_appimagetool()
    if not ferramenta:
        _falhar(
            "appimagetool não encontrado. Coloque o binário em "
            "APPIMAGE_TOOL=<caminho> ou na raiz como ./appimagetool."
        )

    destino_dir = os.path.join(RAIZ, "AppDir", "usr", "bin")
    os.makedirs(destino_dir, exist_ok=True)
    destino_bin = os.path.join(destino_dir, "NavePro")
    shutil.copy2(os.path.join(DIST, "NavePro"), destino_bin)
    os.chmod(destino_bin, 0o755)

    apprun = os.path.join(RAIZ, "AppDir", "AppRun")
    if os.path.isfile(apprun):
        os.chmod(apprun, 0o755)

    saida = os.path.join(RAIZ, f"NavePro-{versao}.AppImage")
    if os.path.exists(saida):
        os.remove(saida)

    # APPIMAGE_EXTRACT_AND_RUN evita depender de FUSE/nos runners de CI.
    env = os.environ.copy()
    env["APPIMAGE_EXTRACT_AND_RUN"] = "1"
    resultado = _rodar([ferramenta, "AppDir", saida], env=env)
    if resultado.returncode != 0 or not os.path.isfile(saida):
        _falhar("Falha ao gerar o AppImage com appimagetool.")
    os.chmod(saida, 0o700)
    _log(f"AppImage gerado: {saida}")
    return saida


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build protegido do NavePro (PyArmor + PyInstaller)."
    )
    parser.add_argument(
        "--target", choices=("auto", "linux", "windows"), default="auto",
        help="Alvo do empacotamento (padrão: sistema atual).",
    )
    parser.add_argument(
        "--version", default=None,
        help="Versão usada no nome do AppImage (padrão: APP_VERSION).",
    )
    parser.add_argument(
        "--no-appimage", action="store_true",
        help="No Linux, gera só o binário PyInstaller (sem AppImage).",
    )
    parser.add_argument(
        "--skip-obfuscate", action="store_true",
        help="Pula o PyArmor (build de diagnóstico).",
    )
    args = parser.parse_args()

    alvo = args.target
    if alvo == "auto":
        alvo = "windows" if sys.platform.startswith("win") else "linux"
    if alvo == "windows" and not sys.platform.startswith("win"):
        _falhar(
            "PyInstaller não faz cross-compile: o .exe precisa ser gerado "
            "no Windows (use o workflow do GitHub Actions)."
        )

    versao = args.version or _versao_padrao()
    _log(f"Alvo: {alvo} | versão: {versao} | Python: {sys.executable}")

    if alvo == "windows" and not os.environ.get("NAVEPRO_ICON"):
        icone = os.path.join(RAIZ, "img", "Icon.ico")
        if os.path.isfile(icone):
            os.environ["NAVEPRO_ICON"] = icone

    if args.skip_obfuscate:
        _log("PyArmor ignorado (--skip-obfuscate).")
        shutil.rmtree(OFB, ignore_errors=True)
    else:
        _obfuscar()

    _build_pyinstaller()

    if alvo == "linux" and not args.no_appimage:
        _gerar_appimage(versao)

    _log("Build concluído.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
