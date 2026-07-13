# TaskChart — Family Chore Tracking on iPad

**在任何 iPad 上使用的家庭任务追踪应用**

## 🚀 快速开始

### 本地运行（同一Wi-Fi）
```bash
cd taskchart
pip install -r requirements.txt
python app.py
# 访问: http://YOUR_IP:5008
```

### 云部署（任何地方都能用）
看 **[CLOUD-DEPLOY.md](CLOUD-DEPLOY.md)** — 5分钟快速部署到 Railway 或 Render

---

## 功能

✅ **Today View** — 每天的任务清单 + 实时分数  
✅ **Calendar** — 6am-11pm 日程，拖拽排期  
✅ **Chart** — 周度完成情况热力图  
✅ **Rewards** — 分数兑换奖励  
✅ **Balances** — 成员历史和积分  

---

## 数据

- **数据库**: SQLite (`chores.db`)
- **成员**: 4人（Quinn, Hailey, Lili, Jiajun）
- **云部署建议**: Railway.app（数据自动保存）

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `app.py` | Flask 后端（所有逻辑） |
| `chores.db` | SQLite 数据库 |
| `Procfile` | 云部署配置 |
| `requirements.txt` | Python 依赖 |
| `CLOUD-DEPLOY.md` | ⭐ 云部署步骤 |
| `DEPLOYMENT.md` | 详细部署指南 |
| `CLAUDE.md` | 项目架构文档 |
| `templates/` | HTML 模板 |

---

## 推荐部署方案

**Railway.app** （最简单）
1. 用 GitHub 账号登录 https://railway.app
2. 点击 "New Project" → "Deploy from GitHub"
3. 选择 `taskchart` repo
4. ✅ 自动部署完成！
5. 分享 URL 给家人

详见 [CLOUD-DEPLOY.md](CLOUD-DEPLOY.md)

---

## iPad 使用

任何 iPad 上打开 Safari，输入你的应用 URL：
```
https://your-app.railway.app
```

就这样！无需 App Store，实时同步数据。

---

## 技术栈

- **后端**: Python + Flask
- **数据库**: SQLite (WAL mode)
- **前端**: Jinja2 + vanilla JS
- **响应式**: iPad 优化
- **主题**: Dark / Light / Green

---

## 部署帮助

遇到问题？查看：
- [CLOUD-DEPLOY.md](CLOUD-DEPLOY.md) — 云部署步骤
- [DEPLOYMENT.md](DEPLOYMENT.md) — 详细配置
- [CLAUDE.md](CLAUDE.md) — 架构和开发

---

## License
Personal use by Lili & family.
