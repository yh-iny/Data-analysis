#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票日报 Web 服务器
提供报告页面访问 + 触发数据更新

功能:
  1. 静态文件服务（reports/ 目录）
  2. 触发 stock_daily.py 重新采集数据
  3. 自动刷新：交易时段每30分钟自动更新
  4. 后台线程执行数据采集，不阻塞Web服务
"""

import os
import sys
import json
import time
import signal
import threading
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 北京时间时区 ──
BEIJING_TZ = timezone(timedelta(hours=8))

# ── 配置 ──
WEB_PORT = int(os.environ.get("STOCK_WEB_PORT", 8080))
PROJECT_DIR = Path(__file__).parent.absolute()
REPORTS_DIR = PROJECT_DIR / "reports"
PYTHON_BIN = os.environ.get("STOCK_PYTHON", sys.executable)
SCRIPT_PATH = PROJECT_DIR / "stock_daily.py"

# A股交易时段 (北京时间)
TRADING_START = 9 * 60 + 30    # 09:30
TRADING_END = 15 * 60 + 30      # 15:30 (收盘后30分钟继续更新)
PRE_MARKET_START = 9 * 60 + 15  # 09:15 盘前更新

# 自动更新间隔（秒）
UPDATE_INTERVAL = 1800  # 30分钟

# ── 全局状态 ──
_last_update_time = 0
_update_lock = threading.Lock()
_update_status = {"running": False, "last_time": "", "message": "", "next_time": ""}

log_lock = threading.Lock()


def log(msg):
    with log_lock:
        ts = _beijing_now().strftime("%H:%M:%S")
        print(f"[{ts}] {msg}")


def _beijing_now():
    """返回北京时间（UTC+8）"""
    return datetime.now(BEIJING_TZ)


def is_trading_time():
    """判断当前是否在交易时段或盘前盘后（北京时间）"""
    now = _beijing_now()
    # 周末不更新
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    # 盘前15分钟到收盘后30分钟
    return PRE_MARKET_START <= minutes <= TRADING_END


def run_stock_daily():
    """在后台执行 stock_daily.py"""
    global _last_update_time
    with _update_lock:
        if _update_status["running"]:
            log("数据更新已在运行中，跳过")
            return
        _update_status["running"] = True
        _update_status["message"] = "正在采集数据..."
        log("开始执行 stock_daily.py ...")

    try:
        result = subprocess.run(
            [PYTHON_BIN, str(SCRIPT_PATH)],
            cwd=str(PROJECT_DIR),
            capture_output=True,
            text=True,
            timeout=300,
            encoding="utf-8",
            errors="replace"
        )
        _last_update_time = time.time()
        _update_status["last_time"] = _beijing_now().strftime("%Y-%m-%d %H:%M:%S")
        if result.returncode == 0:
            _update_status["message"] = f"更新成功 (耗时{result.stdout.count(chr(10))}行输出)"
            log("数据更新成功")
        else:
            _update_status["message"] = f"更新失败: {result.stderr[-200:]}"
            log(f"数据更新失败: {result.stderr[-200:]}")
    except subprocess.TimeoutExpired:
        _update_status["message"] = "更新超时（>5分钟）"
        log("数据更新超时")
    except Exception as e:
        _update_status["message"] = f"更新异常: {e}"
        log(f"数据更新异常: {e}")
    finally:
        _update_status["running"] = False


def auto_update_loop():
    """定时自动更新（首次立即执行一次，之后定时执行）"""
    # 启动时先执行一次采集
    try:
        run_stock_daily()
    except Exception as e:
        log(f"初始采集异常(不影响后续): {e}")
    
    while True:
        try:
            time.sleep(UPDATE_INTERVAL)
            if is_trading_time():
                log(f"交易时段，触发自动更新")
                try:
                    run_stock_daily()
                except Exception as e:
                    log(f"自动更新异常: {e}")
        except Exception as e:
            log(f"自动更新循环异常: {e}")
            time.sleep(60)  # 出错后等待1分钟再重试


def get_next_update_time():
    """计算下次自动更新时间（北京时间）"""
    now = _beijing_now()
    minutes = now.hour * 60 + now.minute

    if now.weekday() >= 5:
        # 周末 -> 下周一09:15
        days_until_mon = (7 - now.weekday()) % 7
        if days_until_mon == 0:
            days_until_mon = 7
        next_dt = (now + timedelta(days=days_until_mon)).replace(hour=9, minute=15, second=0, microsecond=0)
    elif minutes < PRE_MARKET_START:
        # 盘前 -> 今天09:15
        next_dt = now.replace(hour=9, minute=15, second=0, microsecond=0)
    elif minutes > TRADING_END:
        # 收盘后 -> 明天09:15
        next_dt = (now + timedelta(days=1)).replace(hour=9, minute=15, second=0, microsecond=0)
    else:
        # 交易时段 -> 30分钟后
        next_dt = now + timedelta(minutes=30)

    return next_dt.strftime("%Y-%m-%d %H:%M")


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程HTTP服务器，每个请求独立线程处理，避免阻塞"""
    daemon_threads = True


class ReportHandler(BaseHTTPRequestHandler):
    """HTTP请求处理器"""

    def log_message(self, format, *args):
        # 静默日志
        pass

    def do_GET(self):
        path = self.path.split("?")[0]

        # ── 首页: 最新报告 ──
        if path == "/" or path == "/latest":
            self._serve_report("latest.html")
            return

        # ── 触发更新 ──
        if path == "/api/update":
            self._trigger_update()
            return

        # ── 更新状态 ──
        if path == "/api/status":
            self._send_json({
                "running": _update_status["running"],
                "last_time": _update_status["last_time"],
                "message": _update_status["message"],
                "next_time": get_next_update_time(),
                "trading": is_trading_time(),
            })
            return

        # ── 历史报告列表 ──
        if path == "/api/reports":
            self._list_reports()
            return

        # ── 静态文件: reports/ 目录 ──
        if path.startswith("/reports/"):
            filename = path[len("/reports/"):]
            self._serve_report(filename)
            return

        # ── 404 ──
        self._send_json({"error": "not found"}, 404)

    def _serve_report(self, filename):
        filepath = REPORTS_DIR / filename
        if not filepath.exists():
            self._send_json({"error": f"{filename} not found"}, 404)
            return
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _trigger_update(self):
        if _update_status["running"]:
            self._send_json({"status": "already_running", "message": "数据采集正在执行中"})
            return
        # 后台线程执行
        t = threading.Thread(target=run_stock_daily, daemon=True)
        t.start()
        self._send_json({"status": "started", "message": "已触发数据更新，请稍后刷新页面查看"})

    def _list_reports(self):
        reports = []
        if REPORTS_DIR.exists():
            for f in sorted(REPORTS_DIR.glob("stock-report-*.html"), reverse=True):
                reports.append(f.name)
        self._send_json({"reports": reports, "latest": "latest.html"})

    def _send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))


def main():
    print("""
╔═══════════════════════════════════════════════════╗
║        股票日报系统 - 云服务器版                    ║
║        24小时运行 · 交易时段自动更新                 ║
╚═══════════════════════════════════════════════════╝
    """)

    log(f"项目目录: {PROJECT_DIR}")
    log(f"报告目录: {REPORTS_DIR}")
    log(f"Python:   {PYTHON_BIN}")
    log(f"端口:     {WEB_PORT}")
    log(f"自动更新: 交易时段每{UPDATE_INTERVAL // 60}分钟")

    # 启动自动更新线程（后台执行，不阻塞服务器启动）
    t = threading.Thread(target=auto_update_loop, daemon=True)
    t.start()
    log(f"定时更新线程已启动，下次更新: {get_next_update_time()}")

    # 启动Web服务器（多线程，每个请求独立处理，避免阻塞）
    server = ThreadedHTTPServer(("0.0.0.0", WEB_PORT), ReportHandler)
    print(f"""
  访问地址: http://0.0.0.0:{WEB_PORT}/
  手动更新: http://0.0.0.0:{WEB_PORT}/api/update
  运行状态: http://0.0.0.0:{WEB_PORT}/api/status
  历史报告: http://0.0.0.0:{WEB_PORT}/api/reports

  按 Ctrl+C 停止服务
""")

    def shutdown(sig=None, frame=None):
        log("收到停止信号，正在关闭...")
        import os as _os
        _os._exit(0)

    signal.signal(signal.SIGINT, shutdown)
    try:
        signal.signal(signal.SIGTERM, shutdown)
    except (OSError, ValueError):
        pass  # Windows 非 GUI 模式下 SIGTERM 可能不可用

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
    log("服务已停止")


if __name__ == "__main__":
    main()
