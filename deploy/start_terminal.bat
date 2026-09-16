@echo off
chcp 65001 > nul
echo ================================================
echo   股票看盘终端 - 启动代理服务器
echo   %date% %time%
echo ================================================

cd /d "%~dp0"

echo 正在启动本地代理服务器...
echo 启动后在浏览器打开: http://localhost:18888/terminal.html
echo 按 Ctrl+C 停止服务
echo.

start "" "http://localhost:18888/terminal.html"

python server.py
