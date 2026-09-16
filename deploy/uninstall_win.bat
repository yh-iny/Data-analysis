@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

:: ═════════════════════════════════════════════════════════════
::  股票日报系统 - Windows 卸载脚本
::  停止服务 → 删除计划任务 → 关闭防火墙端口
::
::  使用方法：
::    右键此文件 → 以管理员身份运行
:: ═════════════════════════════════════════════════════════════
title 股票日报系统 - 卸载

set "ROOT=%~dp0"
cd /d "%ROOT%"

:: 检查管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo   [ERROR] 请右键此文件，选择"以管理员身份运行"
    pause
    exit /b 1
)

echo.
echo ╔════════════════════════════════════════════════════╗
echo ║     股票日报系统 - 卸载                           ║
echo ╚════════════════════════════════════════════════════╝
echo.
echo   即将执行以下操作：
echo     1. 停止 Web 服务器进程
echo     2. 删除 Windows 计划任务
echo     3. 删除防火墙规则
echo   注意：不会删除报告数据和虚拟环境
echo.
set /p confirm=确认卸载？(y/n):

if /i not "!confirm!"=="y" (
    echo   已取消
    pause
    exit /b 0
)

echo.
echo ── [1/3] 停止 Web 服务器进程 ──
:: 查找并终止占用 8080 端口的进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%a 2>nul
    echo   已停止进程 PID: %%a
)
echo   [OK] 服务进程已停止

echo.
echo ── [2/3] 删除计划任务 ──
schtasks /Delete /TN "StockReport_Service" /F >nul 2>&1
if %errorlevel% equ 0 (echo   [OK] 已删除 StockReport_Service) else (echo   [SKIP] StockReport_Service 不存在)

schtasks /Delete /TN "StockReport_Update_AM" /F >nul 2>&1
if %errorlevel% equ 0 (echo   [OK] 已删除 StockReport_Update_AM) else (echo   [SKIP] StockReport_Update_AM 不存在)

schtasks /Delete /TN "StockReport_Update_PM" /F >nul 2>&1
if %errorlevel% equ 0 (echo   [OK] 已删除 StockReport_Update_PM) else (echo   [SKIP] StockReport_Update_PM 不存在)

schtasks /Delete /TN "DailyStockReport_AfterClose" /F >nul 2>&1
schtasks /Delete /TN "DailyStockReport_PreOpen" /F >nul 2>&1

echo.
echo ── [3/3] 删除防火墙规则 ──
netsh advfirewall firewall delete rule name="StockReport Web 8080" >nul 2>&1
echo   [OK] 防火墙规则已删除

echo.
echo ═════════════════════════════════════════════════════
echo   卸载完成！
echo   报告文件和虚拟环境已保留在: %ROOT%
echo   如需完全删除，请手动删除整个目录
echo ═════════════════════════════════════════════════════
echo.
pause
