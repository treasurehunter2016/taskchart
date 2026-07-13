# TaskChart — 云部署指南（任何iPad都能用）

## 最简单的方案：Render.com（推荐）

Render.com 提供免费部署，无需信用卡，最快5分钟上线。

### Step 1: 准备代码（GitHub）

1. **创建 GitHub repo**
   - 访问 https://github.com/new
   - 库名: `taskchart`
   - 选择 "Public" （Render可以看到）
   - 点击 Create

2. **上传代码到 GitHub**
   ```bash
   cd /Users/lqiang/code/taskchart
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/YOUR_USERNAME/taskchart.git
   git branch -M main
   git push -u origin main
   ```

---

### Step 2: 在 Render.com 上部署

1. **访问** https://render.com （用 GitHub 账号登录）

2. **点击** "New +" → "Web Service"

3. **连接 GitHub repo**
   - 选择 `taskchart` repo
   - 点击 "Connect"

4. **配置部署**
   - **Name**: `taskchart` （自动生成URL）
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python app.py`
   - **Region**: 选择离你近的（如 Singapore）
   - **Plan**: 选择 "Free"

5. **点击 "Create Web Service"**

6. **等待部署完成** ✅
   - Render会显示你的应用 URL: `https://taskchart-xxxx.onrender.com`
   - 首次启动可能需要 1-2 分钟

---

### Step 3: 在任何 iPad 上访问

在 **Safari 浏览器**中打开：
```
https://taskchart-xxxx.onrender.com
```

就这样！任何有 Wi-Fi 的地方都能用。

---

## 数据存储（重要）

### 问题
Render 上的免费部署每次重启都会丢失数据库文件。

### 解决方案 A：使用 PostgreSQL（推荐）
Render 提供免费 PostgreSQL，数据永久保存。

**修改 app.py** 使用 PostgreSQL 而不是 SQLite：
```python
import psycopg2
# 连接到 Render 的 PostgreSQL
db_url = os.environ.get('DATABASE_URL')
conn = psycopg2.connect(db_url)
```

（这需要改动比较大，暂不建议）

### 解决方案 B：定期备份（简单可靠）
1. 在 Render 上设置 **cron job**，每天备份数据库到 Google Drive
2. 或手动下载 `chores.db` 并上传到云存储

### 解决方案 C：改用 Railway.app（自动持久化）
Railway 的免费层自动保存数据库，更简单。

**步骤类似，但 Railway 会自动处理数据持久化**。

---

## 方案 C：Railway.app（更简单的数据持久化）

1. **访问** https://railway.app
2. **用 GitHub 登录**
3. **"New Project" → "Deploy from GitHub"**
4. **选择 `taskchart` repo**
5. **自动配置完成** ✅

Railway 会自动识别 `Procfile` 和 `requirements.txt`，数据库永久保存。

---

## 方案 D：Vercel + Firebase（更复杂但数据更安全）

适合长期生产环境。这里不详述，因为有点复杂。

---

## 快速对比

| 方案 | 部署时间 | 数据持久化 | 免费额度 | 推荐指数 |
|------|--------|---------|--------|--------|
| Render.com | 5分钟 | ⚠️ 需配置 | ✅ 充足 | ⭐⭐⭐⭐ |
| Railway.app | 5分钟 | ✅ 自动 | ✅ 充足 | ⭐⭐⭐⭐⭐ |
| Heroku | 5分钟 | ✅ 自动 | ❌ 已取消免费 | ❌ 不推荐 |

---

## 部署后的常见问题

### Q: 为什么很慢？
A: 免费层会在 15 分钟无访问后休眠。再次访问时需要 10-30 秒冷启。建议付费升级或定期访问保活。

### Q: 数据会丢失吗？
A: 取决于你选择的方案。建议：
- **Railway**: 数据自动保存 ✅
- **Render**: 需要手动配置备份

### Q: 多人同时使用会怎样？
A: SQLite 在云上会有并发问题。建议迁移到 PostgreSQL。

### Q: 可以自定义域名吗？
A: 可以，升级到付费版后可以绑定自己的域名。

---

## 本地测试

部署前，在本地测试一遍：

```bash
cd /Users/lqiang/code/taskchart

# 安装依赖
pip install -r requirements.txt

# 运行（模拟云环境）
FLASK_ENV=production PORT=5008 python app.py

# 访问 http://localhost:5008
```

---

## 总结

**最推荐：Railway.app**
- ✅ 部署简单（5分钟）
- ✅ 数据自动保存
- ✅ 免费额度充足
- ✅ 任何 iPad + Safari 都能用

**其次：Render.com**
- ✅ 部署简单
- ⚠️ 需要手动配置数据备份
- ✅ 免费额度充足

---

## 下一步

1. **创建 GitHub 账号**（如果还没有）
2. **上传 `taskchart` 到 GitHub**
3. **在 Railway / Render 上点击部署**
4. **分享 URL 给家人** 
5. **在任何 iPad 上访问** 🎉

有问题？查看 DEPLOYMENT.md。
