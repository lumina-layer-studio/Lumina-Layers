@echo off
chcp 65001 >nul 2>&1
title Lumina Studio Dev Launcher
color 0B

:: ========================================
::   Lumina Studio 2.0 - Dev Launcher
:: ========================================

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║     Lumina Studio 2.0 - Dev Launcher     ║
echo  ╚══════════════════════════════════════════╝
echo.

:: 检查是否有残留进程
echo [检查] 正在检查残留进程...

:: 检查占用 8000 端口的进程
netstat -ano | findstr ":8000" >nul 2>&1
if %errorlevel% == 0 (
    echo [警告] 端口 8000 被占用，尝试清理...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000"') do (
        if not "%%a"=="0" (
            taskkill /F /PID %%a >nul 2>&1
            echo [清理] 已终止占用端口 8000 的进程 (PID: %%a)
        )
    )
)

:: 检查占用 5174 端口的进程
netstat -ano | findstr ":5174" >nul 2>&1
if %errorlevel% == 0 (
    echo [警告] 端口 5174 被占用，尝试清理...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5174"') do (
        if not "%%a"=="0" (
            taskkill /F /PID %%a >nul 2>&1
            echo [清理] 已终止占用端口 5174 的进程 (PID: %%a)
        )
    )
)

:: 尝试清理残留的 Python 后端进程
for /f "skip=1 tokens=1" %%a in ('wmic process where "CommandLine like '%%api_server.py%%'" get ProcessId 2^>nul') do (
    set "pid=%%a"
    call :trim_pid
)

:: 短暂延迟确保端口释放
timeout /t 1 /nobreak >nul 2>&1

:: 检查 Python 可用性
echo [检查] 正在查找 Python 解释器...

set "PYTHON_CMD="

:: 优先尝试虚拟环境
if exist "%~dp0venv\Scripts\python.exe" (
    set "PYTHON_CMD=%~dp0venv\Scripts\python.exe"
    echo [信息] 使用虚拟环境: venv
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%~dp0.venv\Scripts\python.exe"
    echo [信息] 使用虚拟环境: .venv
) else (
    :: 尝试系统 Python
    python --version >nul 2>&1
    if %errorlevel% == 0 (
        set "PYTHON_CMD=python"
        echo [信息] 使用系统 Python
    ) else (
        python3 --version >nul 2>&1
        if %errorlevel% == 0 (
            set "PYTHON_CMD=python3"
            echo [信息] 使用系统 Python3
        )
    )
)

if "%PYTHON_CMD%"=="" (
    echo [错误] 无法找到 Python 解释器！
    echo.
    echo 请确保以下之一可用：
    echo   - .\venv\Scripts\python.exe
    echo   - .\.venv\Scripts\python.exe
    echo   - python （系统 PATH 中）
    echo   - python3 （系统 PATH 中）
    echo.
    pause
    exit /b 1
)

echo [信息] Python: %PYTHON_CMD%
echo.

:: 启动主程序
echo [启动] 正在启动 Lumina Studio...
echo.

%PYTHON_CMD% "%~dp0start_dev.py" %*

:: 捕获退出码
set "EXIT_CODE=%errorlevel%"

:: 如果异常退出，提供诊断信息
if %EXIT_CODE% neq 0 (
    echo.
    echo [错误] 程序异常退出 (代码: %EXIT_CODE%)
    echo 子进程已由 Job Object 自动清理。
    echo.
    pause
)

exit /b %EXIT_CODE%

:: 辅助函数：清理 PID 中的空格
:trim_pid
if not defined pid exit /b
set "pid=%pid: =%"
if "%pid%"=="" exit /b
:: 不要终止当前窗口自己的进程
for /f "tokens=2" %%b in ('tasklist ^| findstr "cmd.exe" ^| findstr /N "^" ^| findstr "^1:"') do (
    if not "%%b"=="%pid%" (
        taskkill /F /PID %pid% >nul 2>&1
        echo [清理] 已终止残留后端进程 (PID: %pid%)
    )
)
set "pid="
exit /b
