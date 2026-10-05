@echo off
REM ===========================================================================
REM  build-windows.bat — gera o NavePro.exe (portatil, sem instalador)
REM
REM  Uso:  build-windows.bat
REM
REM  O NavePro.exe e um unico arquivo: nao precisa de instalador, nao escreve
REM  no registro e nao precisa de Python nem de pip na maquina do usuario.
REM  Os dados do usuario ficam em %USERPROFILE%\.navepro (config, banco,
REM  uploads), entao o .exe em si pode ir para qualquer pasta ou pen drive.
REM
REM  IMPORTANTE: este script tem que rodar NO WINDOWS. O PyInstaller nao faz
REM  cross-compile — nao da para gerar o .exe a partir do Linux.
REM ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PY=python"
where %PY% >nul 2>&1 || (echo [ERRO] Python nao encontrado no PATH. & goto :fim1)

%PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 (
  echo [ERRO] Python 3.10+ necessario.
  goto :fim1
)

REM --- Tk 8.6, obrigatorio. O Tk 9.0 quebra os aliases de fonte e o app
REM --- renderiza os textos em minusculas/quadradinhos.
for /f "delims=" %%v in ('%PY% -c "import tkinter;print(tkinter.TkVersion)" 2^>nul') do set TK=%%v
if not "%TK%"=="8.6" (
  echo [ERRO] Este Python usa Tk %TK%, e o NavePro precisa de Tk 8.6.
  echo         Instale o Python 3.12 do python.org ^(ele ja vem com o 8.6^).
  goto :fim1
)
echo [OK] Tk %TK%

REM --- Dependencias. --upgrade no pip evita ficar numa versao antiga em cache.
echo [..] Instalando dependencias...
%PY% -m pip install --upgrade pip --quiet
%PY% -m pip install -r requirements.txt --quiet || goto :fim1
%PY% -m pip install pyinstaller --upgrade --quiet || goto :fim1

%PY% -c "import screeninfo,PIL,pypdf" >nul 2>&1
if errorlevel 1 (
  echo [ERRO] Faltou screeninfo, Pillow ou pypdf. Sem o screeninfo a deteccao
  echo         de monitor cai na heuristica e o telao pode abrir no monitor errado.
  goto :fim1
)
echo [OK] Dependencias: screeninfo, Pillow, pypdf

REM --- Gera o .exe com o NavePro.spec (fonte unica com o Linux).
REM --- Icone do .exe: Icon.ico precisa existir. Defina NAVEPRO_ICON="" para
REM --- gerar sem icone proprio. O icone das JANELAS nao depende disso.
set "NAVEPRO_ICON=img\Icon.ico"
set "NAVEPRO_CONSOLE=0"

echo [..] Empacotando (PyInstaller onefile, pode levar alguns minutos)...
%PY% -m PyInstaller --noconfirm --clean NavePro.spec || goto :fim1

if not exist "dist\NavePro.exe" (
  echo [ERRO] dist\NavePro.exe nao foi gerado.
  goto :fim1
)

for %%A in ("dist\NavePro.exe") do set SZ=%%~zA
set /a SZMB=!SZ! / 1048576
echo.
echo [OK] dist\NavePro.exe  (!SZMB! MB)
echo.
echo Para testar com o log de deteccao de monitores visivel, gere com:
echo     set NAVEPRO_CONSOLE=1 ^&^& build-windows.bat
echo.
echo Para gerar o .exe com o icone do NavePro, a pasta img\Icon.ico precisa
echo existir. Sem ele o .exe sai sem icone, mas as janelas abrem com icone.
echo.
echo Distribuicao: envie apenas o NavePro.exe. Nao precisa instalar nada.
echo.
echo ---------------------------------------------------------------------------
echo IMPORTANTE - mpv (so no Windows):
echo     O NavePro usa o mpv para PAUSAR/CONTINUAR a midia pelo painel.
echo     O mpv NAO vem junto no NavePro.exe e precisa ser instalado em cada
echo     maquina, uma vez so:
echo         winget install mpv-player.mpv-CI.MSVC
echo     Sem o mpv, o video ainda abre no telao e o botao PARAR funciona
echo     (usa o VLC ou SMPlayer, que sao detectados automaticamente); so o
echo     pausar/continuar fica indisponivel, e o NavePro avisa na tela.
echo ---------------------------------------------------------------------------
goto :fim

:fim1
echo.
echo [FALHOU] See as mensagens acima.
exit /b 1

:fim
endlocal