# 股票日报系统 - 云服务器部署指南

## 一、操作系统推荐对比

| 系统 | 难度 | 推荐度 | 说明 |
|------|------|--------|------|
| **Ubuntu** (22.04/24.04) | ⭐ 简单 | ⭐⭐⭐⭐⭐ **首选** | 文档最多、apt包管理最简单、社区最活跃 |
| **Debian** (12) | ⭐⭐ 简单 | ⭐⭐⭐⭐ | 与Ubuntu类似，更稳定但部分软件版本较旧 |
| **CentOS/Rocky Linux** | ⭐⭐⭐ 中等 | ⭐⭐⭐ | 你当前已有CentOS 7.9，可直接用，但CentOS 7已停止维护 |
| **Windows Server** | ⭐⭐⭐⭐ 复杂 | ⭐⭐ | 已有Windows部署脚本，适合Windows环境 |

> **结论：选 Ubuntu 22.04 或 24.04 最省心，一行命令搞定一切。**

---

## 二、你当前的云服务器信息

```
系统:    CentOS 7.9.2111-x64
IP:      43.255.30.182
区域:    香港二区
状态:    开机中 ✓
远程端口: 20250（SSH端口可能不是默认22）
```

---

## 三、部署方案：3种方式从简到全

### 方式 A：一键上传部署（最简单，推荐）

在你本地电脑上执行一条命令即可：

```bash
# Windows (Git Bash / PowerShell):
cd F:\wxapp\daily-stock-report
bash upload_deploy.sh root@43.255.30.182 -p 20250

# 或手动指定：
bash upload_deploy.sh root@43.255.30.182
```

**流程自动完成：**
1. SCP上传4个核心文件到服务器 → `/tmp/stock-report/`
2. SSH远程执行 `deploy.sh` 自动化安装
3. 安装Python → 创建venv → 装依赖 → 配置systemd服务 → 放行防火墙 → 启动服务

### 方式 B：手动SSH分步部署（可控性强）

```bash
# 1. 连接服务器
ssh root@43.255.30.182 -p 20250

# 2. 一键运行部署脚本（先上传文件）
mkdir -p /tmp/stock-report
# 从本地上传 deploy.sh stock_daily.py web_server.py requirements.txt 到此目录

# 3. 执行部署
cd /tmp/stock-report && chmod +x deploy.sh && ./deploy.sh
```

### 方式 C：完全手动部署（学习用）

```bash
# ====== 第1步：安装Python和基础依赖 ======
# Ubuntu/Debian:
apt update && apt install -y python3 python3-pip python3-venv
# CentOS:
yum install -y python3 python3-pip

# ====== 第2步：创建项目目录 ======
mkdir -p /opt/stock-report/{reports,tracking,logs}
cd /opt/stock-report

# ====== 第3步：上传项目文件 ======
# 将以下4个文件上传到 /opt/stock-report/
#   stock_daily.py    web_server.py    requirements.txt

# ====== 第4步：创建虚拟环境并装依赖 ======
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# ====== 第5步：首次采集测试 ======
python3 stock_daily.py
# 如果成功生成 reports/ 目录下的HTML文件，说明OK

# ====== 第6步：配置后台运行 ======
# 使用 systemd（Ubuntu/Debian/CentOS通用）
cat > /etc/systemd/system/stock-report.service << 'EOF'
[Unit]
Description=Stock Daily Report Web Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/stock-report
ExecStart=/opt/stock-report/venv/bin/python3 /opt/stock-report/web_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable stock-report
systemctl start stock-report

# ====== 第7步：放行防火墙 ======
# Ubuntu (ufw):
ufw allow 8080/tcp
# CentOS (firewall-cmd):
firewall-cmd --permanent --add-port=8080/tcp && firewall-cmd --reload

# ====== 第8步：访问验证 ======
# 浏览器打开: http://43.255.30.182:8080
```

---

## 四、部署完成后

| 项目 | 命令/地址 |
|------|-----------|
| **访问地址** | `http://43.255.30.182:8080` |
| **查看状态** | `systemctl status stock-report` |
| **查看日志** | `journalctl -u stock-report -f` |
| **重启服务** | `systemctl restart stock-report` |
| **停止服务** | `systemctl stop stock-report` |
| **手动更新数据** | 访问 `http://43.255.30.182:8080/api/update` |

### 自动更新机制
- 工作日 **09:15 ~ 15:30** 每 **30分钟** 自动采集最新数据
- 可随时通过 `/api/update` 手动触发更新
- 服务崩溃后 **10秒内** 自动重启

---

## 五、文件清单（需上传的文件）

```
daily-stock-report/
├── stock_daily.py       # 核心：数据采集+生成HTML报告
├── web_server.py        # Web服务器：提供HTTP访问
├── requirements.txt     # Python依赖列表
├── deploy.sh            # 服务器端一键部署脚本
└── upload_deploy.sh     # 本地上传+远程部署脚本
```

---

## 六、常见问题

### Q: SSH连接不上？
```bash
# 检查防火墙是否放行了20250端口（你的自定义SSH端口）
ssh root@43.255.30.182 -p 20250

# 如果还是连不上，检查云服务商控制台的「安全组」是否放行了20250端口入站规则
```

### Q: 端口8080无法访问？
- 检查云服务器**安全组**是否放行8080端口（TCP入站）
- 检查服务器防火墙：`iptables -L -n | grep 8080`

### Q: 数据不更新？
```bash
# 手动触发一次更新
curl http://127.0.0.1:8080/api/update

# 查看日志排查问题
journalctl -u stock-report -f --no-pager
```
