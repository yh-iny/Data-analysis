@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

:: ═════════════════════════════════════════════════════════════
::  股票日报系统 - Windows Server 2019 一键部署
::  自动安装环境 → 注册Windows服务 → 开机自启 → 交易时段自动更新
::
::  使用方法：
::    右键此文件 → 以管理员身份运行
:: ═════════════════════════════════════════════════════════════
title 股票日报系统 - 部署安装

set "ROOT=%~dp0"
cd /d "%ROOT%"

:: ── 检查管理员权限 ──
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ═════════════════════════════════════════════════
    echo   [ERROR] 请右键此文件，选择"以管理员身份运行"
    echo ═════════════════════════════════════════════════
    pause
    exit /b 1
)

echo.
echo ╔════════════════════════════════════════════════════╗
echo ║     股票日报系统 - Windows Server 部署工具       ║
echo ║     24小时运行 · 交易时段自动更新 · 一键部署       ║
echo ╚════════════════════════════════════════════════════╝
echo.
echo   安装目录: %ROOT%
echo.

:: ═════════════════════════════════════════════════════════════
::  第1步：检测 Python
:: ═════════════════════════════════════════════════════════════
echo ──────────────────────────────────────────────
echo  [1/6] 检测 Python 环境
echo ──────────────────────────────────────────────

set "PYTHON="
set "PIP="

:: 优先使用项目 venv
if exist "%ROOT%venv\Scripts\python.exe" (
    set "PYTHON=%ROOT%venv\Scripts\python.exe"
    set "PIP=%ROOT%venv\Scripts\pip.exe"
    echo   [OK] 使用项目虚拟环境
    goto :step2
)

:: 系统 python3
for /f "delims=" %%i in ('where python3 2^>nul') do (
    set "PYTHON=%%i"
    set "PIP=%%i -m pip"
    echo   [OK] 找到系统 Python3: %%i
    goto :step2
)

:: 系统 python
for /f "delims=" %%i in ('where python 2^>nul') do (
    set "PYTHON=%%i"
    set "PIP=%%i -m pip"
    echo   [OK] 找到系统 Python: %%i
    goto :step2
)

:: 未找到 → 尝试下载安装
echo   [WARN] 未找到 Python
echo.
set /p install_py=  是否自动下载安装 Python 3.12？(y/n):

if /i "!install_py!"=="y" (
    echo   正在下载 Python 3.12 ...
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe' -OutFile '%TEMP%\python-installer.exe'"
    if exist "%TEMP%\python-installer.exe" (
        echo   正在安装（静默模式，勾选 Add to PATH）...
        "%TEMP%\python-installer.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1
        del "%TEMP%\python-installer.exe" 2>nul
        echo   [OK] Python 安装完成
        set "PYTHON=%ProgramFiles%\Python312\python.exe"
        set "PIP=%ProgramFiles%\Python312\python.exe -m pip"
    ) else (
        echo   [ERROR] Python 下载失败
        echo   请手动安装: https://www.python.org/downloads/
        pause
        exit /b 1
    )
) else (
    echo   [ERROR] 请先安装 Python 3.8+ 后重新运行此脚本
    echo   下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:step2

:: ═════════════════════════════════════════════════════════════
::  第2步：创建虚拟环境 & 安装依赖
:: ═════════════════════════════════════════════════════════════
echo.
echo ──────────────────────────────────────────────
echo  [2/6] 配置虚拟环境 & 安装依赖
echo ──────────────────────────────────────────────

if not exist "%ROOT%venv\Scripts\python.exe" (
    echo   正在创建虚拟环境...
    "%PYTHON%" -m venv "%ROOT%venv"
    if errorlevel 1 (
        echo   [WARN] 虚拟环境创建失败，尝试直接使用系统 Python
        set "PYTHON=%PYTHON%"
    ) else (
        set "PYTHON=%ROOT%venv\Scripts\python.exe"
        set "PIP=%ROOT%venv\Scripts\pip.exe"
        echo   [OK] 虚拟环境创建完成
    )
)

:: 检查并安装依赖
"%PYTHON%" -c "import requests, pandas" 2>nul
if errorlevel 1 (
    echo   正在安装依赖包 (requests, pandas)...
    "%PIP%" install -r "%ROOT%requirements.txt" -q
    if errorlevel 1 (
        "%PIP%" install requests pandas -q
    )
    echo   [OK] 依赖安装完成
) else (
    echo   [OK] 依赖已就绪
)

:: 确保 reports 目录存在
if not exist "%ROOT%reports\" mkdir "%ROOT%reports"
if not exist "%ROOT%logs\" mkdir "%ROOT%logs"
echo   [OK] 目录就绪

:: ═════════════════════════════════════════════════════════════
::  第3步：创建服务启动脚本
:: ═════════════════════════════════════════════════════════════
echo.
echo ──────────────────────────────────────────────
echo  [3/6] 生成服务启动脚本
echo ──────────────────────────────────────────────

:: 生成 run_service.bat（Web服务器启动脚本）
(
echo @echo off
echo chcp 65001 ^> nul
echo setlocal
echo set "ROOT=%~dp0"
echo cd /d "%%ROOT%%"
echo.
echo :: 查找 Python
echo set "PYTHON="
echo if exist "%%ROOT%%venv\Scripts\python.exe" set "PYTHON=%%ROOT%%venv\Scripts\python.exe"
echo if not defined PYTHON for %%%%i in ^(where python 2^>nul^) do set "PYTHON=%%%%i"
echo if not defined PYTHON set "PYTHON=%PYTHON%"
echo.
echo :: 启动 Web 服务器（24小时运行，交易时段自动更新）
echo "%%PYTHON%%" "%%ROOT%%web_server.py"
) > "%ROOT%run_service.bat"
echo   [OK] 生成 run_service.bat

:: 生成 run_update.bat（手动更新脚本）
(
echo @echo off
echo chcp 65001 ^> nul
echo setlocal
echo set "ROOT=%~dp0"
echo cd /d "%%ROOT%%"
echo set "PYTHON="
echo if exist "%%ROOT%%venv\Scripts\python.exe" set "PYTHON=%%ROOT%%venv\Scripts\python.exe"
echo if not defined PYTHON for %%%%i in ^(where python 2^>nul^) do set "PYTHON=%%%%i"
echo if not defined PYTHON set "PYTHON=%PYTHON%"
echo "%%PYTHON%%" "%%ROOT%%stock_daily.py"
) > "%ROOT%run_update.bat"
echo   [OK] 生成 run_update.bat

:: ═════════════════════════════════════════════════════════════
::  第4步：注册 Windows 计划任务（开机自启）
:: ═════════════════════════════════════════════════════════════
echo.
echo ──────────────────────────────────────────────
echo  [4/6] 注册 Windows 计划任务（开机自启 + 自动更新）
echo ──────────────────────────────────────────────

:: 设置服务任务的 Python 路径
set "SVC_PYTHON=%PYTHON%"

:: 删除旧任务
schtasks /Delete /TN "StockReport_Service" /F >nul 2>&1
schtasks /Delete /TN "StockReport_Update_AM" /F >nul 2>&1
schtasks /Delete /TN "StockReport_Update_PM" /F >nul 2>&1

:: 注册开机自启任务（Web服务器 24小时运行）
:: 使用 SYSTEM 账户 + 最高权限运行，用户无需登录也能运行
schtasks /Create /TN "StockReport_Service" /TR "\"%SVC_PYTHON%\" \"%ROOT%web_server.py\"" /SC ONLOGON /RL HIGHEST /F >nul 2>&1

:: 如果上面失败（可能权限不足），使用当前用户
if errorlevel 1 (
    schtasks /Create /TN "StockReport_Service" /TR "\"%SVC_PYTHON%\" \"%ROOT%web_server.py\"" /SC ONLOGON /F >nul 2>&1
)

if %errorlevel% equ 0 (
    echo   [OK] 开机自启任务: StockReport_Service
) else (
    echo   [WARN] 开机自启注册失败，请手动配置
)

:: 注册交易时段更新任务（工作日 09:15 + 15:30）
schtasks /Create /TN "StockReport_Update_AM" /TR "\"%SVC_PYTHON%\" \"%ROOT%stock_daily.py\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 09:15 /RL HIGHEST /F >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] 定时任务: 工作日 09:15 盘前更新
) else (
    echo   [WARN] 09:15 定时任务注册失败
)

schtasks /Create /TN "StockReport_Update_PM" /TR "\"%SVC_PYTHON%\" \"%ROOT%stock_daily.py\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 15:30 /RL HIGHEST /F >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] 定时任务: 工作日 15:30 收盘更新
) else (
    echo   [WARN] 15:30 定时任务注册失败
)

:: ═════════════════════════════════════════════════════════════
::  第5步：配置防火墙
:: ═════════════════════════════════════════════════════════════
echo.
echo ──────────────────────────────────────────────
echo  [5/6] 配置防火墙（放行端口 8080）
echo ──────────────────────────────────────────────

netsh advfirewall firewall show rule name="StockReport Web 8080" >nul 2>&1
if %errorlevel% neq 0 (
    netsh advfirewall firewall add rule name="StockReport Web 8080" dir=in action=allow protocol=tcp localport=8080 profile=any >nul 2>&1
    if %errorlevel% equ 0 (
        echo   [OK] 防火墙规则已添加: TCP 8080
    ) else (
        echo   [WARN] 防火墙配置失败，请手动添加入站规则 TCP 8080
    )
) else (
    echo   [OK] 防火墙规则已存在
)

:: ═════════════════════════════════════════════════════════════
::  第6步：首次运行 & 启动服务
:: ═════════════════════════════════════════════════════════════
echo.
echo ──────────────────────────────────────────────
echo  [6/6] 首次数据采集 & 启动服务
echo ──────────────────────────────────────────────

echo   正在首次采集数据（约30-60秒）...
"%PYTHON%" "%ROOT%stock_daily.py"

if errorlevel 1 (
    echo   [WARN] 首次采集失败，服务启动后会在交易时段自动重试
) else (
    echo   [OK] 首次采集成功
)

:: 获取服务器IP
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    set "IP=%%a"
)
set "IP=%IP: =%"

echo.
echo ╔════════════════════════════════════════════════════╗
echo ║            部署完成！                               ║
echo ╠════════════════════════════════════════════════════╣
echo ║                                                    ║
echo ║  访问地址:                                          ║
echo ║    本机: http://localhost:8080/                     ║
echo ║    局域: http://%IP:8080/                           ║
echo ║    外网: http://服务器公网IP:8080/                   ║
echo ║                                                    ║
echo ║  手动更新: http://localhost:8080/api/update        ║
echo ║  运行状态: http://localhost:8080/api/status        ║
echo ║                                                    ║
echo ║  自动更新策略:                                       ║
echo ║    Web服务器内置: 交易时段每30分钟自动更新          ║
echo ║    计划任务备份: 工作日 09:15 + 15:30               ║
echo ║    开机自启: StockReport_Service                    ║
echo ║                                                    ║
echo ║  管理命令:                                          ║
echo ║    启动服务: 双击 run_service.bat                   ║
echo ║    手动更新: 双击 run_update.bat                    ║
echo ║    卸载服务: 双击 uninstall_win.bat                 ║
echo ║    查看任务: 打开"任务计划程序"                       ║
echo ║                                                    ║
echo ╚════════════════════════════════════════════════════╝
echo.

set /p start_now=是否立即启动 Web 服务？(y/n):

if /i "!start_now!"=="y" (
    echo   正在启动 Web 服务器...
    start "StockReport Web Server" "%PYTHON%" "%ROOT%web_server.py"
    timeout /t 3 >nul
    echo   [OK] Web 服务器已启动！
    start "" "http://localhost:8080/"
)

echo.
echo 按任意键退出安装程序（Web 服务会继续在后台运行）
pause >nul
