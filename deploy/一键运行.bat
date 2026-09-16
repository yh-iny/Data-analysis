@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

:: ═════════════════════════════════════════════════
::  股票分析系统 - 一键运行
::  自动配置环境，无需手动安装依赖
:: ═════════════════════════════════════════════════
title 股票分析系统 v2.0

set "ROOT=%~dp0"
cd /d "%ROOT%"

:: ── 检测 Python ──
set "PYTHON="
set "PIP="
set "USE_VENV=0"

:: 优先使用 WorkBuddy 托管 Python
if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" (
    set "PYTHON=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
    set "PIP=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" -m pip
    echo [OK] 使用托管 Python 3.13.12
    goto :check_venv
)

:: 备选：系统 python3
for /f "delims=" %%i in ('where python3 2^>nul') do (
    set "PYTHON=%%i"
    set "PIP=%%i -m pip"
    echo [OK] 使用系统 Python3: %%i
    goto :check_venv
)

:: 备选：系统 python
for /f "delims=" %%i in ('where python 2^>nul') do (
    set "PYTHON=%%i"
    set "PIP=%%i -m pip"
    echo [OK] 使用系统 Python: %%i
    goto :check_venv
)

echo [ERROR] 未找到 Python！请安装 Python 3.8+ 后重试。
echo         下载: https://www.python.org/downloads/
pause
exit /b 1

:: ── 检查/创建虚拟环境 ──
:check_venv
if not exist "%ROOT%venv\" (
    echo [INFO] 首次运行，正在创建虚拟环境...
    "%PYTHON%" -m venv "%ROOT%venv"
    if errorlevel 1 (
        echo [WARN] 创建 venv 失败，尝试直接使用系统 Python
        goto :skip_venv
    )
    echo [OK] 虚拟环境创建完成
)

:: 激活 venv
if exist "%ROOT%venv\Scripts\python.exe" (
    set "PYTHON=%ROOT%venv\Scripts\python.exe"
    set "PIP=%ROOT%venv\Scripts\pip.exe"
    set "USE_VENV=1"
    echo [OK] 使用虚拟环境
)
:skip_venv

:: ── 检查并安装依赖 ──
echo [INFO] 检查依赖包...
"%PYTHON%" -c "import requests, pandas" 2>nul
if errorlevel 1 (
    echo [INFO] 正在安装依赖 (requests, pandas)...
    "%PIP%" install -r "%ROOT%requirements.txt" -q
    if errorlevel 1 (
        echo [WARN] 部分包安装失败，尝试单独安装...
        "%PIP%" install requests pandas -q
    )
)
echo [OK] 依赖检查完成

:: ── 检查并安装 pywin32（用于浏览器自动打开）─
"%PYTHON%" -c "import webbrowser" 2>nul
if errorlevel 1 (
    echo [WARN] webbrowser 模块不可用，将使用 start 命令打开浏览器
)

:: ═════════════════════════════════════════════════
:menu
cls
echo ╔════════════════════════════════════════════════╗
echo ║        股票分析系统 v2.0 - 一键运行           ║
echo ║         数据驱动 · 智能推荐 · 风控护航          ║
echo ╠════════════════════════════════════════════════╣
echo ║                                                ║
echo ║  [1] 📊 生成每日股票分析报告                    ║
echo ║      采集数据 → 多维评分 → 生成 HTML 报告        ║
echo ║                                                ║
echo ║  [2] 📺 启动实时看盘终端                        ║
echo ║      大盘指数 + 个股搜索 + K线 + 资金流向        ║
echo ║                                                ║
echo ║  [3] 🚀 全部运行（日报 + 终端）                 ║
echo ║      一边生成报告，一边启动看盘                  ║
echo ║                                                ║
echo ║  [4] ⏰ 安装每日定时任务                        ║
echo ║      工作日自动运行（需管理员权限）              ║
echo ║                                                ║
echo ║  [0] 退出                                      ║
echo ║                                                ║
echo ╚════════════════════════════════════════════════╝
echo.
set /p choice=请输入选项 (0-4): 

if "%choice%"=="1" goto :run_report
if "%choice%"=="2" goto :run_terminal
if "%choice%"=="3" goto :run_both
if "%choice%"=="4" goto :run_scheduler
if "%choice%"=="0" goto :quit
echo 无效选项，请重新选择
timeout /t 2 >nul
goto :menu

:: ═════════════════════════════════════════════════
::  [1] 生成日报
:: ═════════════════════════════════════════════════
:run_report
cls
echo ╔════════════════════════════════════════════════╗
echo ║          📊 生成每日股票分析报告                ║
echo ╚════════════════════════════════════════════════╝
echo.
echo 正在采集数据（约需 60-120 秒）...
echo   → 市场环境感知（上证指数 + 20日均线）
echo   → 全球财经新闻
echo   → 行业板块排名
echo   → 强势股题材扫描
echo   → 低价潜力股筛选
echo   → 建仓评分 + 风控计算
echo   → 历史回测 + 事件日历
echo.
echo ═════════════════════════════════════════════════

"%PYTHON%" "%ROOT%stock_daily.py"

if errorlevel 1 (
    echo.
    echo [ERROR] 报告生成失败，请检查上方错误信息
    pause
    goto :menu
)

echo.
echo ═════════════════════════════════════════════════
echo  ✅ 日报生成完成！
echo  📁 报告位置: %ROOT%reports\
echo ═════════════════════════════════════════════════
echo.
set /p open_report=是否在浏览器中打开报告？(y/n):

if /i "%open_report%"=="y" (
    echo 正在打开...
    start "" "%ROOT%reports\latest.html"
)

echo.
pause
goto :menu

:: ═════════════════════════════════════════════════
::  [2] 启动看盘终端
:: ═════════════════════════════════════════════════
:run_terminal
cls
echo ╔════════════════════════════════════════════════╗
echo ║          📺 启动实时看盘终端                    ║
echo ╚════════════════════════════════════════════════╝
echo.
echo 正在启动本地代理服务器 (端口 18888)...
echo 浏览器将自动打开 http://localhost:18888/terminal.html
echo.
echo ╔════════════════════════════════════════════════╗
echo ║  功能：大盘指数 | 个股搜索 | K线图 | 资金流向  ║
echo ║  新闻：全球财经快讯（每5分钟自动刷新）         ║
echo ║  按 Ctrl+C 停止服务                            ║
echo ╚════════════════════════════════════════════════╝
echo.

:: 先杀掉旧进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":18888" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%a 2>nul
    echo [INFO] 已停止旧的终端服务 (PID: %%a)
)

timeout /t 1 >nul

:: 启动服务器
start "" "http://localhost:18888/terminal.html"
"%PYTHON%" "%ROOT%server.py"

goto :menu

:: ═════════════════════════════════════════════════
::  [3] 全部运行
:: ═════════════════════════════════════════════════
:run_both
cls
echo ╔════════════════════════════════════════════════╗
echo ║       🚀 全部运行（日报 + 看盘终端）           ║
echo ╚════════════════════════════════════════════════╝
echo.

:: 先杀旧进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":18888" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%a 2>nul
)
timeout /t 1 >nul

:: 后台启动服务器
echo [1/2] 启动看盘终端服务...
start /B "%PYTHON%" "%ROOT%server.py" >nul 2>&1
timeout /t 2 >nul

:: 打开浏览器
start "" "http://localhost:18888/terminal.html"
echo       ✓ 看盘终端已启动

:: 运行日报
echo [2/2] 生成股票分析报告...
echo.
"%PYTHON%" "%ROOT%stock_daily.py"

echo.
echo ═════════════════════════════════════════════════
echo  ✅ 全部完成！
echo  📺 看盘终端: http://localhost:18888/terminal.html
echo  📁 最新报告: %ROOT%reports\latest.html
echo ═════════════════════════════════════════════════
echo.
echo 按任意键打开最新报告...
pause >nul
start "" "%ROOT%reports\latest.html"

echo.
echo 终端服务仍在后台运行，关闭此窗口将停止服务。
pause
goto :menu

:: ═════════════════════════════════════════════════
::  [4] 安装定时任务
:: ═════════════════════════════════════════════════
:run_scheduler
cls
echo ╔════════════════════════════════════════════════╗
echo ║       ⏰ 安装每日定时任务                       ║
echo ╚════════════════════════════════════════════════╝
echo.
echo 此操作需要管理员权限。
echo 将以管理员身份运行 setup_scheduler.ps1
echo.
echo 定时任务：
echo   - 每个工作日 09:15（开盘前）
echo   - 每个工作日 15:30（收盘后）
echo.
set /p confirm=确认安装定时任务？(y/n):

if /i not "%confirm%"=="y" goto :menu

echo.
echo 正在请求管理员权限...
powershell -Command "Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy Bypass -File \"%ROOT%setup_scheduler.ps1\"'"
echo.
echo 请在弹出的管理员窗口中完成安装。
pause
goto :menu

:: ═════════════════════════════════════════════════
:quit
echo.
echo 再见！👋
timeout /t 1 >nul
exit /b 0
