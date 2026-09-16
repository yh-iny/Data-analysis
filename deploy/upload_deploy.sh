#!/bin/bash
# ══════════════════════════════════════════════════════════════
#  一键上传部署到云服务器
#
#  使用方法:
#    1. 修改下方的 SERVER 变量为你的服务器IP
#    2. chmod +x upload_deploy.sh
#    3. ./upload_deploy.sh
#
#  也可以手动上传:
#    scp deploy.sh stock_daily.py web_server.py requirements.txt root@SERVER:/tmp/stock-report/
#    ssh root@SERVER "cd /tmp/stock-report && chmod +x deploy.sh && ./deploy.sh"
# ══════════════════════════════════════════════════════════════

set -e

# ── 修改这里: 你的云服务器IP ──
SERVER="${1:-root@YOUR_SERVER_IP}"
PORT="${2:-22}"

echo ""
echo "╔═══════════════════════════════════════════════════╗"
echo "║     股票日报系统 - 一键上传部署                     ║"
echo "╚═══════════════════════════════════════════════════╝"
echo ""
echo "目标服务器: $SERVER"
echo "SSH端口: $PORT"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# SSH/SCP 基础选项
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10 -p $PORT"

echo ""
echo "━━━ 第1步: 上传文件 ━━━"
# 在远程创建临时目录
ssh $SSH_OPTS "$SERVER" "mkdir -p /tmp/stock-report"

# 上传核心文件
scp $SSH_OPTS "$SCRIPT_DIR/deploy.sh" "$SCRIPT_DIR/stock_daily.py" \
    "$SCRIPT_DIR/web_server.py" "$SCRIPT_DIR/requirements.txt" \
    "$SERVER:/tmp/stock-report/"

echo "文件上传完成"

# 上传已有报告（可选）
if [ -d "$SCRIPT_DIR/reports" ]; then
    echo "上传已有报告..."
    ssh $SSH_OPTS "$SERVER" "mkdir -p /tmp/stock-report/reports"
    scp $SSH_OPTS "$SCRIPT_DIR/reports/"*.html "$SERVER:/tmp/stock-report/reports/" 2>/dev/null || true
    echo "报告上传完成"
fi

echo ""
echo "━━━ 第2步: 远程执行部署 ━━━"
ssh $SSH_OPTS "$SERVER" "cd /tmp/stock-report && chmod +x deploy.sh && bash deploy.sh"

echo ""
echo "✅ 部署流程全部完成!"
echo "现在可以通过浏览器访问: http://$(echo $SERVER | cut -d@ -f2):8080/"
