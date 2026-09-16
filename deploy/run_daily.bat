@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

:: ═════════════════════════════════════════════════
::  股票分析系统 - 快速运行（无菜单版）
::  直接采集数据并生成最新报告
:: ═════════════════════════════════════════════════

set "ROOT=%~dp0"
cd /d "%ROOT%"

title 股票分析 - 数据采集中...

:: ── 检测 Python ──
set "PYTHON="

:: 优先使用 WorkBuddy 托管 Python
if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" (
    set "PYTHON=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
    goto :run
)

:: 使用项目 venv
if exist "%ROOT%venv\Scripts\python.exe" (
    set "PYTHON=%ROOT%venv\Scripts\python.exe"
    goto :run
)

:: 系统 python
for /f "delims=" %%i in ('where python 2^>nul') do (
    set "PYTHON=%%i"
    goto :run
)

echo [ERROR] 未找到 Python！请先运行"一键运行.bat"安装环境。
pause
exit /b 1

:run
echo.
echo ═════════════════════════════════════════════════
echo   开始采集股票数据...
echo   时间: %date% %time%
echo ═════════════════════════════════════════════════
echo.

"%PYTHON%" "%ROOT%stock_daily.py"

if errorlevel 1 (
    echo.
    echo [ERROR] 数据采集失败，请检查上方错误信息。
    pause
    exit /b 1
)

echo.
echo ═════════════════════════════════════════════════
echo   ✅ 报告已生成！
echo   📁 最新报告: %ROOT%reports\latest.html
echo ═════════════════════════════════════════════════
echo.

start "" "%ROOT%reports\latest.html"
