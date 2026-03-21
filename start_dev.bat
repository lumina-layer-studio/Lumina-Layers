@echo off
title Lumina Studio Dev Launcher
echo ========================================
echo   Lumina Studio 2.0 - Dev Launcher
echo ========================================
echo.

echo [1/2] Starting backend (python api_server.py) ...
start "Lumina-Backend" cmd /k "python api_server.py"

echo [2/2] Starting frontend (npm run dev) ...
start "Lumina-Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo Both services launched in separate windows.
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo.
echo Close this window or press any key to exit.
pause >nul
