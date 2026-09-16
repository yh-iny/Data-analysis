# 每日股票分析 - Windows 定时任务安装脚本
# 以管理员权限运行此脚本来注册定时任务
# 
# 使用方法:
#   右键 -> 以管理员身份运行 PowerShell
#   cd F:\wxapp\daily-stock-report
#   .\setup_scheduler.ps1

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ScriptDir "stock_daily.py"
$LogDir = Join-Path $ScriptDir "logs"

# 创建日志目录
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
    Write-Host "✓ 创建日志目录: $LogDir"
}

# 查找 Python 路径（优先级：项目venv > WorkBuddy托管 > 系统python3 > 系统python）
$PythonPath = $null

# 1. 项目虚拟环境
$ProjectVenv = Join-Path $ScriptDir "venv\Scripts\python.exe"
if (Test-Path $ProjectVenv) {
    $PythonPath = $ProjectVenv
    Write-Host "✓ 使用项目虚拟环境: $PythonPath" -ForegroundColor Green
}

# 2. WorkBuddy 托管 Python
if (-not $PythonPath) {
    $WbPython = "$env:USERPROFILE\.workbuddy\binaries\python\versions\3.13.12\python.exe"
    if (Test-Path $WbPython) {
        # 有托管Python但没有项目venv，直接用托管Python
        $PythonPath = $WbPython
        Write-Host "✓ 使用托管 Python 3.13.12" -ForegroundColor Green
    }
}

# 3. 系统 python3
if (-not $PythonPath) {
    $PythonPath = (Get-Command python3 -ErrorAction SilentlyContinue).Source
}

# 4. 系统 python
if (-not $PythonPath) {
    $PythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
}

if (-not $PythonPath) {
    Write-Host "❌ 未找到 Python，请先安装 Python 3.8+" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Python 路径: $PythonPath"

# ─── 定时任务配置 ───────────────────────────────────────
$TaskName = "DailyStockReport"
$TaskDesc = "每日自动采集股票数据并生成推荐日报"

# 执行命令：python stock_daily.py >> logs/YYYY-MM-DD.log 2>&1
$Action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "`"$PythonScript`"" `
    -WorkingDirectory $ScriptDir

# 触发器：每个工作日（周一~周五）下午 15:30（A股收盘后30分钟）
$TriggerWeekday = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "15:30"

# 额外触发器：每天早上 9:15（开盘前）也跑一次
$TriggerMorning = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "09:15"

$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -WakeToRun $false

# 删除旧任务（如有）
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# 注册新任务（收盘后）
Register-ScheduledTask `
    -TaskName "${TaskName}_AfterClose" `
    -Description "$TaskDesc（收盘后）" `
    -Action $Action `
    -Trigger $TriggerWeekday `
    -Principal $Principal `
    -Settings $Settings `
    -Force | Out-Null

Write-Host "✓ 定时任务已注册: ${TaskName}_AfterClose（工作日 15:30 运行）" -ForegroundColor Green

# 注册早盘任务
Register-ScheduledTask `
    -TaskName "${TaskName}_PreOpen" `
    -Description "$TaskDesc（开盘前）" `
    -Action $Action `
    -Trigger $TriggerMorning `
    -Principal $Principal `
    -Settings $Settings `
    -Force | Out-Null

Write-Host "✓ 定时任务已注册: ${TaskName}_PreOpen（工作日 09:15 运行）" -ForegroundColor Green

Write-Host ""
Write-Host "═══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  定时任务安装完成！" -ForegroundColor Cyan
Write-Host "  日报路径: $ScriptDir\reports\" -ForegroundColor Cyan
Write-Host "  查看任务: 任务计划程序 -> DailyStockReport*" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════" -ForegroundColor Cyan

# 立即运行一次测试
Write-Host ""
$RunNow = Read-Host "是否立即运行一次测试？(y/n)"
if ($RunNow -eq "y" -or $RunNow -eq "Y") {
    Write-Host "正在运行..." -ForegroundColor Yellow
    Start-Process -FilePath $PythonPath -ArgumentList "`"$PythonScript`"" `
        -WorkingDirectory $ScriptDir -Wait -NoNewWindow
    Write-Host "✓ 测试运行完成，请查看 reports\latest.html" -ForegroundColor Green
}
