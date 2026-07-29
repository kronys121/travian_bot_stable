@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Travian Bot

rem Порт веб-панели. Можно переопределить: set PORT=9000 && start.bat
if "%PORT%"=="" set PORT=8080

rem Ищем интерпретатор: сначала локальное окружение, потом системный.
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"
if not defined PY set "PY=python"

"%PY%" --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Python не найден. Установите Python 3.10+ с python.org
    echo   и отметьте галочку "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

:menu
cls
echo.
echo   ================================================
echo                    TRAVIAN BOT
echo   ================================================
echo.
echo     [1]  Запустить веб-панель   (порт %PORT%)
echo     [2]  Установить / обновить зависимости
echo     [3]  Запуск бота в консоли (без панели)
echo     [0]  Выход
echo.
set "choice="
set /p choice="  Выбор: "

if "%choice%"=="1" goto web
if "%choice%"=="2" goto deps
if "%choice%"=="3" goto console
if "%choice%"=="0" exit /b 0
goto menu

:web
cls
echo.
echo   Веб-панель: http://127.0.0.1:%PORT%
echo   Остановить: Ctrl+C
echo.
rem Браузер открываем с задержкой: uvicorn поднимается не мгновенно.
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start "" http://127.0.0.1:%PORT%"
"%PY%" -m uvicorn app:app --host 127.0.0.1 --port %PORT%
echo.
pause
goto menu

:deps
cls
echo.
echo   Установка зависимостей...
echo.
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
echo.
echo   Установка браузера для Playwright...
"%PY%" -m playwright install chromium
echo.
echo   Готово.
pause
goto menu

:console
cls
echo.
set "acc="
set /p acc="  Имя аккаунта (Enter — все сразу): "
echo.
if "%acc%"=="" (
    "%PY%" main.py
) else (
    "%PY%" runner.py --account "%acc%"
)
echo.
pause
goto menu
