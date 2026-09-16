#!/usr/bin/env python3
# ══════════════════════════════════════════════════════════════
#  股票日报系统 - WorkBuddy 一键远程部署脚本
#  通过 SSH 连接云服务器，自动上传文件并完成全部配置
# ══════════════════════════════════════════════════════════════

import sys
import os
import time
import io

import paramiko

# ── 配置 ──
SERVER_HOST = "43.255.30.182"
SERVER_PORT = 20250
SERVER_USER = "root"
SERVER_PASS = "Smile1007"
REMOTE_DIR = "/tmp/stock-report"
INSTALL_DIR = "/opt/stock-report"
WEB_PORT = 8080

# 本地项目目录
LOCAL_DIR = r"F:\wxapp\daily-stock-report"

# 需要上传的文件
UPLOAD_FILES = [
    "deploy.sh",
    "stock_daily.py", 
    "web_server.py",
    "requirements.txt",
]


def print_step(title):
    print(f"\n{'━'*50}")
    print(f"  {title}")
    print(f"{'━'*50}")


def create_ssh():
    """创建SSH连接"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    print(f"正在连接 {SERVER_USER}@{SERVER_HOST}:{SERVER_PORT} ...")
    client.connect(SERVER_HOST, port=SERVER_PORT, username=SERVER_USER,
                   password=SERVER_PASS, timeout=30)
    print("✓ SSH连接成功!")
    return client


def upload_files(client):
    """通过SFTP上传文件（使用paramiko内置SFTP）"""
    print_step("第1步: 上传项目文件")
    
    # 创建远程目录
    stdin, stdout, stderr = client.exec_command(f"mkdir -p {REMOTE_DIR} && mkdir -p {REMOTE_DIR}/reports")
    stdout.read()
    
    # SFTP上传
    sftp = client.open_sftp()
    
    for filename in UPLOAD_FILES:
        local_path = os.path.join(LOCAL_DIR, filename)
        if os.path.exists(local_path):
            remote_path = f"{REMOTE_DIR}/{filename}"
            sftp.put(local_path, remote_path)
            size = os.path.getsize(local_path)
            print(f"  ✓ 已上传: {filename} ({size:,} bytes)")
        else:
            print(f"  ✗ 文件不存在: {local_path}")
            raise FileNotFoundError(f"缺少文件: {filename}")
    
    # 上传已有的报告HTML（可选）
    reports_dir = os.path.join(LOCAL_DIR, "reports")
    if os.path.isdir(reports_dir):
        for f in os.listdir(reports_dir):
            if f.endswith(".html"):
                local_path = os.path.join(reports_dir, f)
                try:
                    sftp.put(local_path, f"{REMOTE_DIR}/reports/{f}")
                    size = os.path.getsize(local_path)
                    print(f"  ✓ 已上传报告: {f} ({size:,} bytes)")
                except Exception as e:
                    print(f"  - 跳过报告 {f}: {e}")
    
    sftp.close()
    print("✓ 文件上传完成!")


def run_deploy(client):
    """远程执行部署脚本"""
    print_step("第2步: 远程执行部署脚本 (deploy.sh)")
    print("  这一步会自动完成:")
    print("    → 安装Python3 + pip")
    print("    → 创建虚拟环境并安装依赖")
    print("    → 配置systemd服务")
    print("    → 放行防火墙")
    print("    → 启动Web服务")
    print()
    
    cmd = f"cd {REMOTE_DIR} && chmod +x deploy.sh && bash -x deploy.sh"
    stdin, stdout, stderr = client.exec_command(cmd, timeout=600)
    
    # 实时输出日志
    while not stdout.channel.exit_status_ready():
        if stdout.channel.recv_ready():
            line = stdout.readline()
            if line:
                print(f"  | {line.rstrip()}")
        if stderr.channel.recv_stderr_ready():
            line = stderr.readline()
            if line and line.strip():
                print(f"  ! {line.rstrip()}")
        time.sleep(0.5)
    
    # 输出剩余内容
    remaining = stdout.read().decode("utf-8", errors="replace").strip()
    if remaining:
        for line in remaining.split("\n"):
            print(f"  | {line}")
    
    exit_code = stdout.channel.recv_exit_status()
    if exit_code != 0:
        err_out = stderr.read().decode("utf-8", errors="replace").strip()
        print(f"\n⚠️ 部署脚本退出码: {exit_code}")
        if err_out:
            print(f"错误输出: {err_out[:500]}")
    return exit_code


def verify_deployment(client):
    """验证部署结果"""
    print_step("验证: 检查服务状态")
    
    commands = [
        ("检查服务状态", "systemctl status stock-report --no-pager -l 2>/dev/null || echo 'service not found'"),
        ("检查端口监听", f"ss -tlnp | grep {WEB_PORT} || netstat -tlnp 2>/dev/null | grep {WEB_PORT} || echo 'port check failed'"),
        ("测试本地访问", f"curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{WEB_PORT}/"),
        ("查看最近日志", "journalctl -u stock-report --no-pager -n 20 2>/dev/null || tail -n 20 /opt/stock-report/logs/*.log 2>/dev/null || echo 'log check skipped'"),
    ]
    
    for title, cmd in commands:
        print(f"\n  ▸ {title}:")
        try:
            stdin, stdout, stderr = client.exec_command(cmd, timeout=15)
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            if out:
                for line in out.split("\n")[:10]:
                    print(f"    {line}")
            if err:
                print(f"    [err] {err[:200]}")
        except Exception as e:
            print(f"    执行失败: {e}")


def main():
    print("="*60)
    print("   股票日报系统 - 远程一键部署")
    print("="*60)
    print(f"  目标服务器: {SERVER_HOST}:{SERVER_PORT}")
    print(f"  用户名:     {SERVER_USER}")
    print(f"  项目目录:   {INSTALL_DIR}")
    print(f"  Web端口:    {WEB_PORT}")
    
    client = None
    try:
        # 1. 连接
        client = create_ssh()
        
        # 2. 上传文件
        upload_files(client)
        
        # 3. 执行部署
        exit_code = run_deploy(client)
        
        # 4. 验证
        verify_deployment(client)
        
        # 完成
        print("\n" + "="*60)
        if exit_code == 0:
            print("  ✅ 部署流程执行完毕!")
        else:
            print(f"  ⚠️ 部署流程结束 (退出码={exit_code})，可能需要手动排查")
        print("="*60)
        print(f"\n  🌐 访问地址: http://{SERVER_HOST}:{WEB_PORT}")
        print(f"  📋 状态查询: ssh root@{SERVER_HOST} -p {SERVER_PORT} 'systemctl status stock-report'")
        print(f"  📋 查看日志: ssh root@{SERVER_HOST} -p {SERVER_PORT} 'journalctl -u stock-report -f'")
        print()
        
    except Exception as e:
        print(f"\n❌ 错误: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if client:
            client.close()
            print("SSH连接已关闭")


if __name__ == "__main__":
    main()
