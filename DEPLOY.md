# 🌐 武汉道路病害监测平台 — 公网部署指南

## 当前状态

- **前端**: 已部署到 CloudStudio → `https://402b816337ea4626afc93b7888956ca2.app.codebuddy.work`
- **后端 API**: 需要部署到公网才能实现多人协作
- **生产版服务器**: `server_prod.py` (Flask + SQLite, 已准备就绪)

---

## 方案对比

| 方案 | 费用 | 持久化 | 冷启动 | 设置难度 | 适合场景 |
|------|------|--------|--------|----------|----------|
| A. Render.com | 免费 | ✅ SQLite | ~30秒 | ⭐⭐ (需注册) | 国际访问,原型演示 |
| B. Railway.app | $5/月赠金 | ✅ | 无 | ⭐⭐ (需注册) | 生产环境 |
| C. 飞书/钉钉内网穿透 | 免费 | ✅ 本机 | 无 | ⭐⭐⭐ | 企业内网使用 |
| D. 云服务器(VPS) | ¥50+/月 | ✅ | 无 | ⭐⭐⭐ | 正式运营 |

---

## 推荐方案 A: Render.com 免费部署 (最快 5 分钟)

### 第一步: 准备文件

以下文件已在工作区就绪:
```
server_prod.py    ← Flask + SQLite 生产版服务器
requirements.txt  ← Python 依赖 (仅 flask)
Procfile          ← 启动配置
render.yaml       ← Render 部署描述
index.html        ← 前端 (API_BASE 需改)
```

### 第二步: 注册 Render

1. 打开 https://dashboard.render.com
2. 用 GitHub / Google / GitLab 账号登录 (免费)
3. 点击 **"New +"** → **"Web Service"**

### 第三步: 连接代码

**方式1 — 推荐: 通过 GitHub (自动部署)**
1. 在 GitHub 创建一个新仓库 (例如 `wuhan-road-monitor`)
2. 将以下文件推送到仓库:
   ```bash
   git init && git add server_prod.py requirements.txt Procfile render.yaml index.html vendor/
   git commit -m "武汉道路病害监测平台 - 生产版"
   git remote add origin https://github.com/你的用户名/wuhan-road-monitor.git
   git push -u origin main
   ```
3. 在 Render dashboard: Connect → 选择你的 GitHub 仓库
4. Render 自动检测到 Python 应用

**方式2: 通过 Deploy CLI**
```bash
# 安装 Render CLI (需要 Go 环境)
# 或者直接在 Dashboard 手动填写:

Build Command:     pip install -r requirements.txt
Start Command:     python server_prod.py
Instance:          Free (免费层)
```

### 第四步: 配置环境变量

在 Render Dashboard 的 "Environment" 中添加:

| 变量名 | 值 | 说明 |
|--------|-----|------|
| PORT | `10000` | Render 注入的端口 (必须) |
| DEEPSEEK_API_KEY | `sk-abb99d75...` | DeepSeek API 密钥 (可选, AI功能用) |

> ⚠️ 生产环境建议通过环境变量设置 API Key, 不要硬编码

### 第五步: 部署并获取 URL

1. 点击 **"Create Web Service"**
2. 等待构建完成 (~2-3分钟)
3. Render 会给你一个 URL, 例如: `https://wuhan-road-monitor.onrender.com`

### 第六步: 更新前端 API 地址

编辑 `index.html` 第 1793 行左右:
```javascript
// 改为:
const API_BASE = 'https://wuhan-road-monitor.onrender.com';
```

重新部署 CloudStudio 前端即可!

---

## 备选方案 B: Railway.app

Railway 的免费额度更慷慨, 且没有冷启动问题:

1. 打开 https://railway.app
2. 登录后点击 "+ New Project"
3. 选择 "Deploy from GitHub repo" 或上传文件
4. Railway 自动检测 Python + Flask
5. 部署完成后获得公网 URL
6. 同样修改 `index.html` 的 `API_BASE`

---

## 备选方案 C: 局域网/内网协作 (无需公网)

如果你的用户都在同一个局域网或企业内网:

```bash
# 1. 启动服务器
python server_prod.py

# 2. 查看本机 IP
ipconfig  # Windows
# 找到 "IPv4地址", 例如 192.168.1.100

# 3. 局域网内其他电脑访问:
# http://192.168.1.100:8777
```

所有在局域网内的人都可以:
- 访问同一个页面
- 新增/修改/删除道路数据
- 实时同步 (点「同步」按钮或刷新页面)

### 内网穿透 (让外网也能访问)

如果需要从外部网络访问局域网内的服务:

**选项1: cpolar (国产, 免费)**
```bash
# 下载安装 cpolar: https://www.cpolar.com/
cpolar http 8777
# 会得到类似: https://xxxx.cpolar.top 的公网地址
```

**选项2: ngrok (国际)**
```bash
# 下载 ngrok: https://ngrok.com/download
ngrok http 8777
# 会得到类似: https://xxxx.ngrok-free.app 的公网地址
```

**选项3: cloudflared tunnel (免费, 稳定)**
```bash
# 安装: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
cloudflared tunnel --url http://localhost:8777
# 会得到: https://xxx.trycloudflare.com
```

---

## 备选方案 D: 云服务器 (VPS)

正式生产环境推荐:

| 供应商 | 最低配置 | 价格 | 适合 |
|--------|----------|------|------|
| 腾讯云轻量 | 2C2G | ~50元/月 | 国内用户 |
| 阿里云ECS | 2C2G | ~60元/月 | 国内用户 |
| Vultr | 1C1G | $5/月 | 海外用户 |

部署步骤:
```bash
# 1. SSH 到服务器
ssh root@你的服务器IP

# 2. 上传项目文件
scp -r * root@你的服务器IP:/opt/road-monitor/

# 3. SSH 进去安装依赖并启动
ssh root@你的服务器IP
cd /opt/road-monitor
pip install -r requirements.txt
nohup python server_prod.py > server.log 2>&1 &

# 4. 开放防火墙端口
# 腾讯云/阿里云需要在控制台放行 8777/tcp

# 5. 访问: http://你的服务器IP:8777
```

### 用 systemd 保持服务开机自启
```bash
sudo tee /etc/systemd/system/road-monitor.service << 'EOF'
[Unit]
Description=Wuhan Road Monitor API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/road-monitor
ExecStart=/usr/bin/python3 server_prod.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable road-monitor
sudo systemctl start road-monitor
```

---

## 文件说明

| 文件 | 用途 |
|------|------|
| `server_prod.py` | **生产版 Flask 服务器** (用于部署) |
| `server.py` | **开发版 HTTP 服务器** (仅本地测试) |
| `requirements.txt` | Python 依赖列表 |
| `Procfile` | PaaS 平台启动命令 |
| `render.yaml` | Render.com 部署配置 |
| `index.html` | 前端单页应用 |
| `vendor/mammoth.browser.min.js` | Word 文档解析库 |

---

## 快速检查清单

- [ ] 选择一个部署方案 (A/B/C/D)
- [ ] 注册相应平台的账号 (如果需要)
- [ ] 部署 server_prod.py 到目标平台
- [ ] 修改 index.html 中的 `API_BASE` 指向后端 URL
- [ ] 重新部署前端到 CloudStudio (或直接由后端托管)
- [ ] 测试: 打开公网URL → 新增道路 → 刷新页面 → 数据还在 ✅
- [ ] 测试: 手机/另一台电脑打开 → 点「同步」→ 能看到数据 ✅
