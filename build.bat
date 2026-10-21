@echo off
REM ============================================================
REM  g360-erp-pedido-vigencias - Lanzador Windows
REM  Drill limpio: Vendedores -> Clientes -> Pedidos -> SKUs
REM  Uso:
REM    build.bat            -> setup completo 1ra vez, luego rapido
REM    build.bat fast       -> arranque directo (salta setup)
REM    build.bat clean      -> borra .venv y .g360_ready y reinstala
REM  Mantiene venv + deps verificadas. Marcador .venv\.g360_ready
REM  permite arranques instantaneos. Log: run_log.txt
REM ============================================================
setlocal EnableDelayedExpansion

cd /d "%~dp0"

set "VENV_DIR=.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "READY_MARK=%VENV_DIR%\.g360_ready"

REM --- clean: borra entorno ---
if /i "%~1"=="clean" (
    echo [INFO] Limpiando entorno...
    if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%"
    if exist "%READY_MARK%" del /q "%READY_MARK%" 2>nul
    echo [OK] Limpieza completa. Ejecuta build.bat para reinstalar.
    endlocal
    exit /b 0
)

REM --- fast: si venv listo, ir directo ---
if /i "%~1"=="fast" if exist "%VENV_PY%" if exist "%READY_MARK%" goto run_app

echo ============================================================
echo   g360-erp-pedido-vigencias ^| Drill Vendedor -^> Cliente -^> Pedido -^> SKU
echo   Verificando entorno (solo 1ra vez es lento)...
echo ============================================================
echo.

REM --- Detectar Python (>=3.11) ---
set "PY_CMD="
for %%P in (python "py -3" "py -3.12" "py -3.11" python3) do (
    if not defined PY_CMD (
        %%P -c "import sys; exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1 && set "PY_CMD=%%P"
    )
)
REM fallback: probar py -3.14 / python directamente
if not defined PY_CMD (
    py -3.14 -c "import sys" >nul 2>&1 && set "PY_CMD=py -3.14"
)
if not defined PY_CMD (
    python -c "import sys" >nul 2>&1 && set "PY_CMD=python"
)
if not defined PY_CMD (
    call :fail "No se encontro Python 3.11+ en el PATH. Instala Python 3.12+ y reintenta."
    exit /b 1
)
echo [OK] Python: %PY_CMD%

REM --- Crear venv si falta ---
if not exist "%VENV_PY%" (
    echo [INFO] Creando entorno virtual %VENV_DIR%...
    %PY_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        call :fail "No se pudo crear el entorno virtual."
        exit /b 1
    )
    echo [OK] Entorno creado.
)

REM --- Verificar dependencias (todas de requirements.txt) ---
echo [INFO] Verificando dependencias...
"%VENV_PY%" -c "import flet, pandas, openpyxl, xlrd, requests, pydantic_settings" 2>nul
if errorlevel 1 (
    echo [INFO] Instalando/actualizando dependencias...
    "%VENV_PY%" -m pip install --upgrade pip >nul 2>&1
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        call :fail "No se pudieron instalar dependencias. Revisa requirements.txt y tu conexion."
        exit /b 1
    )
    echo [OK] Dependencias instaladas.
) else (
    echo [OK] Dependencias verificadas.
)

REM --- Marcar listo para fast ---
if not exist "%READY_MARK%" type nul > "%READY_MARK%"

:run_app
echo.
echo [INFO] Lanzando aplicacion...
echo       Interfaz limpia: lista simple de vendedores con drill al click
echo       Log: run_log.txt  ^|  Cierre la ventana para salir
echo.
"%VENV_PY%" main.py
if errorlevel 1 (
    call :fail "La aplicacion termino con error. Revisa run_log.txt en la carpeta del proyecto."
)
endlocal
exit /b 0

:fail
set "MSG=%~1"
powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('%MSG%', 'g360-erp-pedido-vigencias', 'OK', 'Error')" >nul 2>nul
if errorlevel 1 echo [ERROR] %MSG% & pause
exit /b 0
