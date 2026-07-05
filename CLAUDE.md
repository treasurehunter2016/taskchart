# TaskChart — Claude Code Context

## Project Identity
- **Name:** TaskChart (originally "Chore Chart")
- **Purpose:** iPad-optimized family chore tracking web app
- **Owner:** Lili Qiang (eBay P&A analytics manager)
- **Location:** `~/code/taskchart/`
- **Port:** 5008 (`python app.py`)

## How to Run
```bash
cd ~/code/taskchart
python app.py          # dev server with debug=True, port 5008
```
Access at: `http://localhost:5008` — open in **Chrome work profile** (not personal).

## Tech Stack
- **Backend:** Python / Flask (single file: `app.py`)
- **Database:** SQLite (`chores.db`) — WAL mode, schema versioned
- **Frontend:** Jinja2 server-rendered HTML + vanilla JavaScript, no build step
- **Themes:** CSS variables (`data-theme="dark|green"`), stored in `localStorage`

## File Layout
```
~/code/taskchart/
├── app.py               # All backend logic (routes, DB, helpers)
├── chores.db            # SQLite database (auto-created by init_db())
├── config.example.py    # Config template (copy to config.py for production)
├── CLAUDE.md            # This file — project context for Claude
└── templates/
    ├── base.html        # Shared layout, CSS vars, tab bar, theme system
    ├── household.html   # Home: member list with streak badges
    ├── member.html      # Individual member's chore view + celebration
    ├── chores.html      # Chore catalog
    ├── chore_form.html  # Create/edit chore (auto-save, icon picker)
    ├── chart.html       # Weekly grid + Review mode (JS toggle, no reload)
    ├── balances.html    # Points, history (completions + adjustments), rewards
    ├── settings.html    # Members, theme, Admin link
    └── admin.html       # Admin: stats, version history, actions, export
```

## Database Schema (current: v4)
| Table | Purpose |
|---|---|
| `schema_version` | Single-row version counter for migrations |
| `members` | Family member profiles (avatar emoji, hex color) |
| `chores` | Chore definitions — **versioned** (see below) |
| `chore_members` | Join table: chore ↔ member (specific/rotate only) |
| `completions` | One row = one member completed one chore on one date |
| `rewards` | Redeemable rewards catalog |
| `balance_history` | Manual point adjustments (positive = bonus, negative = spend) |
| `app_settings` | Key-value store (reserved for future use) |

### Chore Versioning (v4)
`chores` has `parent_id` and `version` columns. When a chore that has been
completed at least once is edited:
1. Old chore row is set `active=0` (preserved — completions still JOIN to it)
2. A new chore row is inserted with `parent_id = old_root_id`, `version = N+1`
3. The frontend receives the new `chore_id` and updates its URL

This makes historical completions immutable — they always reference the original
chore definition (name/icon/points) at the time they were created.

If a chore has **zero completions**, edits update in-place (no version needed).

### Schema Migration Rule
Always append-only. Add a new entry to `SCHEMA_MIGRATIONS` dict + increment
`CURRENT_SCHEMA_VERSION`. Use `ALTER TABLE … ADD COLUMN` or `CREATE TABLE IF NOT EXISTS`.
Never DROP or rename existing columns.

## Key Design Patterns

### Concurrency
- `_write_lock = threading.Lock()` — all write routes hold this lock
- SQLite WAL mode — reads never block writes
- `PRAGMA busy_timeout=5000` — writes retry up to 5s
- Toggle-completion uses delete-first atomicity (no check-then-act race)

### Points Calculation
`calc_points()` = `SUM(completions × chore.points)` + `SUM(balance_history.points_delta)`
Joins to `chores` without filtering `active=1`, so legacy versioned chores still
contribute their original point values.

### Streak Calculation
`calc_streak()` walks back day-by-day from today; stops at first gap. Max 365-day lookback.

### Theme System
CSS variables per `[data-theme="dark|green"]` selector. Theme applied in `<head>` 
before first paint (reads `localStorage`) to prevent flash. Set with `setTheme(name)`.

### Auto-Save (chore_form.html)
700ms debounce on all field changes → POST `/api/save-chore`. On version bump,
response includes `versioned: true` and the new `chore_id`; JS updates the URL
via `history.replaceState`.

### Chart Toggle (no page reload)
Profiles/Chores group toggle uses `fetch()` + `DOMParser` to swap only the
`<tbody>` in-place. Week navigation also uses fetch+swap. Updates URL with
`history.replaceState`.

## Admin Page
`/admin` — accessible from Settings → Admin Dashboard:
- Stats overview (members, chores, completions, DB size)
- System info (schema version, SQLite version, uptime)
- Table row counts
- Top members / top chores (completion bar charts)
- Chore version history (all versions including legacy)
- Recent completions feed
- Actions: Vacuum DB, Export JSON backup, Integrity check, Purge old completions

## Current Users (in chores.db)
Quinn, Hailey, Lili, Jiajun — 4 family members.

## Future Deployment Notes
- For LAN deployment: Flask is already bound to `host='0.0.0.0'`
- For production: use `config.py` (see `config.example.py`) and run behind gunicorn
- The `chores.db` file is the single source of truth — back it up before upgrades

## What This Project Does NOT Have (by design)
- No authentication / login (single-household, shared iPad, trust model)
- No push notifications
- No offline support (requires local Flask server)
- No image uploads (emoji avatars only)
- No cloud sync
