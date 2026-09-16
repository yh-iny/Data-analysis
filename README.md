# A股每日股票分析日报 📈

一个零依赖外部 API Key 的 A 股每日数据采集与低价股推荐系统。每天自动抓取
东方财富、同花顺、腾讯财经的公开行情，生成一份自包含的 HTML 日报，并推回仓库。

> ⚠️ 本仓库所有内容均由程序基于公开行情自动生成，**不构成任何投资建议**，据此操作盈亏自负。

---

## ✨ 功能

- 📰 全球财经快讯聚合
- 🏭 A 股行业板块涨跌排行
- 🔥 强势题材 / 涨停股追踪
- 💎 低价潜力股筛选（2~20 元）与综合评分 + 上涨预测
- 📈 短期上涨趋势股
- 🏗️ 可建仓股票 + 核心推荐池 + 回避清单（含市场环境感知）
- 📅 事件日历 / 回测验证
- 📄 一键生成单文件 HTML 日报（红涨绿跌，符合 A 股习惯）

## 🗂️ 目录结构

```
a-share-daily-report/
├── .github/workflows/daily.yml   # GitHub Actions：每天自动跑并回写报告
├── stock_daily.py                # 核心脚本：抓取 + 评分 + 生成 HTML
├── web_server.py                 # 本地查看报告用的轻量 HTTP 服务（可选）
├── requirements.txt
├── reports/                      # 每日生成的 HTML（自动更新，纳入版本库）
│   ├── latest.html               # 最新一份
│   └── stock-report-YYYY-MM-DD.html
├── tracking/                     # 每日回测追踪 JSON（自动更新）
├── deploy/                       # 自托管部署脚本（服务器/Windows 计划任务等）
├── LICENSE
└── README.md
```

## 🚀 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 生成今日日报
python stock_daily.py

# 3. 本地预览（可选，端口 8080）
python web_server.py
# 浏览器打开 http://127.0.0.1:8080
```

生成的报告位于 `reports/stock-report-<今天>.html` 与 `reports/latest.html`。

## ☁️ 在 GitHub 上每天自动更新

本仓库已内置 GitHub Actions（`.github/workflows/daily.yml`）：

- **触发时间**：北京时间每个交易日（周一至周五）`09:30` 与 `15:30` 各一次
  （对应 UTC `01:30` / `07:30`）。也可在仓库 **Actions → 每日股票分析日报 → Run workflow** 手动触发。
- **工作流程**：检出代码 → 装 Python/依赖 → 运行 `stock_daily.py` → 把新报告 `git commit` + `push` 回仓库。
- **时区处理**：通过环境变量 `TZ=Asia/Shanghai`，保证报告日期使用北京时间，不会因 UTC 错位。
- **非交易日**：脚本会自动降级为「空候选」并照常生成一份结构完整的报告，仓库日期连续。

### 上传到 GitHub 的步骤

```bash
git init
git add .
git commit -m "init: A股每日分析日报"
gh repo create a-share-daily-report --public --source=. --push
# 或在 GitHub 网页新建仓库后：
#   git remote add origin git@github.com:<你的用户名>/a-share-daily-report.git
#   git push -u origin main
```

推送后进入仓库 **Settings → Actions → General → Workflow permissions**，
确认 `Read and write permissions` 已开启（默认 `GITHUB_TOKEN` 需可写才能回写报告）。

报告可直接在仓库的 `reports/` 目录查看；如需网页展示，可在
**Settings → Pages** 选择从 `main` 分支的根目录 `/` 发布。

> 💡 想看每日最新报告？直接打开 `reports/latest.html`。

## ⚠️ 关于网络访问的说明

GitHub 的免费 Runner 位于境外，访问东方财富 / 同花顺 / 腾讯财经接口**偶尔会受到
网络限制或限速**，导致某次报告数据偏空。若你希望更新更稳定，可任选其一：

1. **使用自托管 Runner**：在 GitHub **Settings → Actions → Runners** 添加一台
   位于国内的机器（Linux/Windows 均可），Workflow 会自动调度到该 Runner。
2. **本地定时任务**：参考 `deploy/` 下的服务器/计划任务脚本，在本机定时运行，
   再 `git push` 回仓库。

## 📜 许可证

[MIT](LICENSE) — 仅供学习研究。
