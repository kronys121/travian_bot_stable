@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Travian Bot - launcher

rem ---------------------------------------------------------------
rem  Ищем интерпретатор: сначала локальное venv, потом системный.
rem  "python" из PATH берём последним - в venv лежат уже уставновленные
rem  зависимости, и запускать мимо него почти всегда ошибка.
rem ---------------------------------------------------------------
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"
if not defined PY (
    where python >nul 2>nul
    if errorlevel 1 (
        echo.
        echo   [!] Python не найден. Установи Python 3.10+ и отметь
        echo       галочку "Add python.exe to PATH" при установке.
        echo.
        pause
        exit /b 1
    )
    set "PY=python"
)

if not defined PORT set "PORT=8000"

:menu
cls
echo.
echo   ================================================
echo              T R A V I A N   B O T
echo   ================================================
echo.
echo     Интерпретатор : %PY%
echo.
echo     [1]  Веб-панель      (браузер, http://127.0.0.1:%PORT%)
echo     [2]  Десктопное GUI  (отдельное окно)
echo     [3]  Установить / обновить зависимости
echo     [4]  Запустить бота в консоли (без панели)
echo.
echo     [0]  Выход
echo.
set "choice="
set /p "choice=  Выбор: "

if "%choice%"=="1" goto web
if "%choice%"=="2" goto gui
if "%choice%"=="3" goto deps
if "%choice%"=="4" goto console
if "%choice%"=="0" exit /b 0
goto menu

:web
cls
echo.
echo   Запускаю веб-панель на http://127.0.0.1:%PORT%
echo   Закрыть - Ctrl+C в этом окне.
echo.
rem Браузер открываем с задержкой в фоне: uvicorn поднимается ~2 секунды,
rem без паузы вкладка успевала открыться раньше сервера и показать ошибку.
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start "" http://127.0.0.1:%PORT%"
"%PY%" -m uvicorn app:app --host 127.0.0.1 --port %PORT%
echo.
echo   Веб-панель остановлена.
pause
goto menu

:gui
cls
echo.
echo   Запускаю десктопное GUI...
echo.
"%PY%" gui.py
if errorlevel 1 (
    echo.
    echo   [!] GUI завершилось с ошибкой.
    echo       Если не хватает customtkinter - выбери пункт [3].
    echo.
    pause
)
goto menu

:deps
cls
echo.
echo   Установка зависимостей...
echo.
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
echo.
echo   Ставлю браузер для Playwright (нужен один раз)...
"%PY%" -m playwright install chromium
echo.
echo   Готово.
pause
goto menu

:console
cls
echo.
set "acc="
set /p "acc=  Имя аккаунта (пусто = все из config.yaml): "
if "%acc%"=="" (
    "%PY%" main.py
) else (
    "%PY%" runner.py --account "%acc%"
)
echo.
pause
goto menu
