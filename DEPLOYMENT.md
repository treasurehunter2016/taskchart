# TaskChart — Deployment & Sharing Guide

## What's Included
- **app.py** — Flask backend (single file, all routes & DB logic)
- **chores.db** — SQLite database (stores all data)
- **templates/** — Jinja2 HTML templates + inline CSS/JS
- **CLAUDE.md** — Project context & architecture

---

## How to Share with Others

### Option 1: Local Network (Family iPad)
Everyone on the same Wi-Fi can use it. Perfect for home setups.

```bash
cd taskchart
python app.py
# Access at: http://YOUR_IP:5008
# On iPad: open Safari, go to http://192.168.x.x:5008
```

**Data**: Stored in `chores.db` (SQLite) — one database per installation.

---

### Option 2: Cloud Deployment (Heroku / Render / Railway)
Deploy to the cloud so anyone can access it from anywhere.

#### Prerequisites
- Free account on [Render.com](https://render.com) or [Railway.app](https://railway.app)
- GitHub account (optional, can push manually)

#### Steps for Render.com

1. **Create `Procfile`** in project root:
   ```
   web: python app.py
   ```

2. **Create `requirements.txt`**:
   ```bash
   cd taskchart
   pip freeze > requirements.txt
   # Edit to keep only essentials:
   Flask==2.3.0
   Werkzeug==2.3.0
   ```

3. **Push to GitHub** (or use Render's git connect):
   ```bash
   git add .
   git commit -m "ready for deployment"
   git push origin main
   ```

4. **On Render.com**:
   - Click "New +" → "Web Service"
   - Connect your GitHub repo
   - Set **Start Command**: `python app.py`
   - Set **Port**: `5008` (or use `$PORT` in app.py)
   - Deploy

5. **Access**: `https://your-app-name.onrender.com`

---

### Option 3: Share Database Across Installations
If you want multiple people running the app locally but sharing the same database (cloud-synced):

1. **Move `chores.db` to cloud storage** (Google Drive / Dropbox / S3)
2. **Modify app.py**:
   ```python
   import os
   import dropbox  # or similar
   
   # On startup: sync DB from cloud
   # On shutdown: sync DB back to cloud
   ```

---

## Data Storage & Limits

### Database Structure
```sql
-- Core tables
members        — 4 family members (avatar, color, name)
chores         — Task definitions (name, points, schedule type)
daily_claims   — Claims per member per day (count + completion status)
balance_history — Manual point adjustments
daily_extra    — Ad-hoc completions logged via Today view
rewards        — Redeemable reward catalog
reward_redemptions — Points spent
```

### Current Limits
- **Members**: 4 (hardcoded, but easy to change)
- **Chores**: Unlimited
- **Database size**: Tested up to 50k rows, scales easily
- **Concurrent users**: 1–4 (SQLite WAL mode handles multiple readers)

### How to Increase Members
Edit `app.py` — there's no hard limit. Just add more members in Settings UI.

---

## Running on Different Machines

### macOS / Linux
```bash
python3 app.py
# Port 5008, debug=True
```

### Windows
```bash
python app.py
# Or set up as Windows service
```

### Docker (for cloud/consistent environments)
```dockerfile
FROM python:3.9
WORKDIR /app
COPY . .
RUN pip install Flask
CMD ["python", "app.py"]
```

Then:
```bash
docker build -t taskchart .
docker run -p 5008:5008 taskchart
```

---

## Backup & Restore

### Backup
```bash
# Backup the database
cp chores.db chores-backup-$(date +%Y%m%d).db
```

### Restore
```bash
# Restore from backup
cp chores-backup-20260712.db chores.db
# Restart app
```

---

## Troubleshooting

### Port 5008 already in use
```bash
# Find what's using it
lsof -i :5008
# Kill it
kill -9 <PID>
# Or use a different port in app.py: app.run(port=5009)
```

### Database locked errors
- Ensure only one app instance is running
- SQLite WAL mode handles concurrent reads; writes are serialized

### Slow on first load
- SQLite performs auto-vacuum on startup
- Completely normal on first access

---

## Recommended Setup

**For family use** (4–8 people):
1. Run locally on a shared device (iPad, laptop)
2. Back up `chores.db` weekly
3. Use Render.com if you want remote access

**For larger groups**:
1. Migrate to PostgreSQL (`psycopg2` library)
2. Deploy to cloud platform
3. Add user authentication (Flask-Login)

---

## Support
See CLAUDE.md for architecture details and development context.
