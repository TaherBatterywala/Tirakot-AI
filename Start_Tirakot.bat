@echo off
setlocal enabledelayedexpansion

:: Check if Ollama is running
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo Ollama is already running.
) else (
    echo Starting Ollama in the background...
    start /B "" ollama serve
    timeout /t 3 /nobreak >nul
)

:: Boot python environment
echo Booting Tirakot Environment...
venv\Scripts\python.exe main.py
