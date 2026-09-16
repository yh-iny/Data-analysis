#!/bin/bash
# ══════════════════════════════════════════════════════════════
#  股票日报系统 - 云服务器一键部署脚本
#  支持: Ubuntu 20.04+ / Debian 11+ / CentOS 8+
#
#  使用方法:
#    chmod +x deploy.sh
#    ./deploy.sh
#
#  或一键部署到远程服务器:
#    scp deploy.sh root@your-server:/tmp/
#    ssh root@your-server "bash /tmp/deploy.sh"
# ══════════════════════════════════════════════════════════════

set -e

# ── 颜色 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ── 配置 ──
INSTALL_DIR="/opt/stock-report"
SERVICE_NAME="stock-report"
WEB_PORT="${STOCK_WEB_PORT:-8080}"

echo ""
echo "╔═══════════════════════════════════════════════════╗"
echo "║     股票日报系统 - 云服务器一键部署                 ║"
echo "╚═══════════════════════════════════════════════════╝"
echo ""

# ══════════════════════════════════════════════════
#  第1步: 检测系统环境
# ══════════════════════════════════════════════════
echo "━━━ 第1步: 检测系统环境 ━━━"

# 检测操作系统
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_ID=$ID
    OS_VER=$VERSION_ID
    info "操作系统: $PRETTY_NAME"
else
    error "无法检测操作系统"
fi

# 检测是否 root
if [ "$(id -u)" -ne 0 ]; then
    error "请以 root 用户运行此脚本 (sudo ./deploy.sh)"
fi

# 检测架构
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
    info "架构: x86_64"
elif [ "$ARCH" = "aarch64" ]; then
    info "架构: ARM64"
else
    warn "架构: $ARCH (未充分测试)"
fi

# ══════════════════════════════════════════════════
#  第2步: 安装系统依赖
# ══════════════════════════════════════════════════
echo ""
echo "━━━ 第2步: 安装系统依赖 ━━━"

if command -v python3 &>/dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    info "Python已安装: $PYTHON_VERSION"
else
    info "安装 Python3 ..."
    if [ "$OS_ID" = "ubuntu" ] || [ "$OS_ID" = "debian" ]; then
        apt-get update -qq
        apt-get install -y -qq python3 python3-pip python3-venv
    elif [ "$OS_ID" = "centos" ] || [ "$OS_ID" = "rhel" ]; then
        dnf install -y python3 python3-pip
    else
        apt-get update -qq 2>/dev/null || yum install -y python3 python3-pip
    fi
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    info "Python安装完成: $PYTHON_VERSION"
fi

# ══════════════════════════════════════════════════
#  第3步: 创建项目目录
# ══════════════════════════════════════════════════
echo ""
echo "━━━ 第3步: 创建项目目录 ━━━"

if [ ! -d "$INSTALL_DIR" ]; then
    mkdir -p "$INSTALL_DIR"
    info "创建目录: $INSTALL_DIR"
else
    warn "目录已存在: $INSTALL_DIR (保留现有文件)"
fi

mkdir -p "$INSTALL_DIR/reports"
mkdir -p "$INSTALL_DIR/tracking"
mkdir -p "$INSTALL_DIR/logs"
info "子目录已创建: reports/ tracking/ logs/"

# ══════════════════════════════════════════════════
#  第4步: 复制项目文件
# ══════════════════════════════════════════════════
echo ""
echo "━━━ 第4步: 复制项目文件 ━━━"

# 脚本所在目录（本地或/tmp）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 复制核心文件
for file in stock_daily.py web_server.py requirements.txt; do
    if [ -f "$SCRIPT_DIR/$file" ]; then
        cp "$SCRIPT_DIR/$file" "$INSTALL_DIR/$file"
        info "复制: $file"
    else
        error "缺少文件: $file"
    fi
done

# 复制已有报告（如有）
if [ -d "$SCRIPT_DIR/reports" ]; then
    cp -r "$SCRIPT_DIR/reports/"* "$INSTALL_DIR/reports/" 2>/dev/null || true
    info "复制已有报告"
fi

# ══════════════════════════════════════════════════
#  第5步: 创建虚拟环境并安装依赖
# ══════════════════════════════════════════════════
echo ""
echo "━━━ 第5步: 安装Python依赖 ━━━"

if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
    info "虚拟环境已创建"
fi

"$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
info "依赖安装完成"

# ══════════════════════════════════════════════════
#  第6步: 设置权限
# ══════════════════════════════════════════════════
echo ""
echo "━━━ 第6步: 设置权限 ━━━"

# 创建专用用户（安全）
if ! id -u stock-report &>/dev/null; then
    useradd -r -s /usr/sbin/nologin stock-report 2>/dev/null || true
    info "创建用户: stock-report"
fi

chown -R stock-report:stock-report "$INSTALL_DIR"
info "权限设置完成"

# ══════════════════════════════════════════════════
#  第7步: 配置 systemd 服务
# ══════════════════════════════════════════════════
echo ""
echo "━━━ 第7步: 配置 systemd 服务 ━━━"

# 更新 service 文件中的端口和用户
cat > "/etc/systemd/system/${SERVICE_NAME}.service" << EOF
[Unit]
Description=Stock Daily Report Web Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=stock-report
Group=stock-report
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/web_server.py
Restart=always
RestartSec=10
TimeoutStartSec=300
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
Environment=STOCK_WEB_PORT=$WEB_PORT
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
info "systemd 服务已配置并启用"

# ══════════════════════════════════════════════════
#  第8步: 配置防火墙
# ══════════════════════════════════════════════════
echo ""
echo "━━━ 第8步: 配置防火墙 ━━━"

# ufw
if command -v ufw &>/dev/null && ufw status | grep -q "active"; then
    ufw allow "$WEB_PORT/tcp" >/dev/null 2>&1
    info "ufw: 已开放端口 $WEB_PORT"
fi

# firewalld
if command -v firewall-cmd &>/dev/null && systemctl is-active firewalld >/dev/null 2>&1; then
    firewall-cmd --permanent --add-port="$WEB_PORT/tcp" >/dev/null 2>&1
    firewall-cmd --reload >/dev/null 2>&1
    info "firewalld: 已开放端口 $WEB_PORT"
fi

# ══════════════════════════════════════════════════
#  第9步: 启动服务
# ══════════════════════════════════════════════════
echo ""
echo "━━━ 第9步: 启动服务 ━━━"

systemctl start "$SERVICE_NAME"
sleep 3

if systemctl is-active "$SERVICE_NAME" >/dev/null 2>&1; then
    info "服务已启动!"
else
    error "服务启动失败，请查看日志: journalctl -u $SERVICE_NAME -f"
fi

# ══════════════════════════════════════════════════
#  第10步: (可选) 配置 Nginx 反向代理
# ══════════════════════════════════════════════════
echo ""
echo "━━━ 第10步: Nginx 反向代理 (可选) ━━━"

if command -v nginx &>/dev/null; then
    read -p "是否配置 Nginx 反向代理? (y/n): " SETUP_NGINX
    if [ "$SETUP_NGINX" = "y" ] || [ "$SETUP_NGINX" = "Y" ]; then
        SERVER_NAME=$(hostname -I | awk '{print $1}')
        read -p "域名 (留空使用IP $SERVER_NAME): " DOMAIN
        if [ -n "$DOMAIN" ]; then
            SERVER_NAME=$DOMAIN
        fi

        cat > "/etc/nginx/sites-available/${SERVICE_NAME}" << EOF
server {
    listen 80;
    server_name $SERVER_NAME;

    location / {
        proxy_pass http://127.0.0.1:$WEB_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_cache_bypass \$http_upgrade;
    }

    # 静态文件缓存
    location /reports/ {
        proxy_pass http://127.0.0.1:$WEB_PORT;
        proxy_cache_valid 200 5m;
        expires 5m;
    }
}
EOF

        ln -sf "/etc/nginx/sites-available/${SERVICE_NAME}" "/etc/nginx/sites-enabled/${SERVICE_NAME}"
        nginx -t 2>/dev/null && {
            systemctl reload nginx
            info "Nginx 反向代理已配置: http://$SERVER_NAME"
        } || warn "Nginx 配置测试失败，请手动检查"
    fi
else
    info "Nginx 未安装，跳过（直接通过端口 $WEB_PORT 访问）"
fi

# ══════════════════════════════════════════════════
#  完成!
# ══════════════════════════════════════════════════
SERVER_IP=$(hostname -I | awk '{print $1}')

echo ""
echo "╔═══════════════════════════════════════════════════╗"
echo "║            部署完成!                              ║"
echo "╠═══════════════════════════════════════════════════╣"
echo "║                                                   ║"
echo "║  访问地址: http://$SERVER_IP:$WEB_PORT"
echo "║  状态查询: systemctl status $SERVICE_NAME"
echo "║  查看日志: journalctl -u $SERVICE_NAME -f"
echo "║  重启服务: systemctl restart $SERVICE_NAME"
echo "║  停止服务: systemctl stop $SERVICE_NAME"
echo "║                                                   ║"
echo "║  自动更新策略:                                     ║"
echo "║    工作日 09:15 ~ 15:30 每隔30分钟自动采集         ║"
echo "║    也可通过 /api/update 手动触发                   ║"
echo "║                                                   ║"
echo "╚═══════════════════════════════════════════════════╝"
echo ""
