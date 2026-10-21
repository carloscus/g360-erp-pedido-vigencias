@echo off
REM ============================================================
REM  g360-erp-pedido-vigencias - Generar reporte de acciones
REM  Doble click o arrastrar un .xls sobre este archivo.
REM  No requiere la interfaz grafica (Flet).
REM ============================================================
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=py"

REM Argumento opcional: ruta de origen arrastrada sobre el .bat
set "ARGS="
if not "%~1"=="" set "ARGS=--fuente %~1"

echo.
echo  ========================================================
echo   Reporte de acciones de vigencias - CIPSA
echo  ========================================================
echo.

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" reporte.py %ARGS% %*
) else (
    py reporte.py %ARGS% %*
)

set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo  Listo. El reporte quedo en el escritorio.
) else (
    echo  Hubo un problema (codigo %RC%). Revisa el mensaje de arriba.
    pause
)
exit /b %RC%
