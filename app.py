from flask import Flask, render_template, request, jsonify, redirect, url_for, Response
import sqlite3
import json
import threading
import time as _time
from datetime import date, timedelta
import os

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(__file__), 'chores.db')

_write_lock  = threading.Lock()
_server_start = _time.time()

CURRENT_SCHEMA_VERSION = 4
MEMBER_COLORS = ['#007AFF', '#FF9F0A', '#30D158', '#BF5AF2', '#FF453A', '#64D2FF', '#FF6961', '#AC8E68']

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

# ---------------------------------------------------------------------------
# Schema migrations — append-only, applied exactly once per version number.
# To add a column/table: increment CURRENT_SCHEMA_VERSION and add an entry.
# ---------------------------------------------------------------------------
SCHEMA_MIGRATIONS = {
    1: '''
        CREATE TABLE IF NOT EXISTS members (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            avatar      TEXT    DEFAULT '🙂',
            color       TEXT    DEFAULT '#007AFF',
            sort_order  INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS chores (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            name                TEXT    NOT NULL,
            icon                TEXT    DEFAULT '📋',
            points              INTEGER DEFAULT 0,
            assignment_type     TEXT    DEFAULT 'everyone',
            schedule_type       TEXT    DEFAULT 'daily',
            schedule_days       TEXT    DEFAULT '[]',
            rotate_current_idx  INTEGER DEFAULT 0,
            active              INTEGER DEFAULT 1,
            sort_order          INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS chore_members (
            chore_id    INTEGER,
            member_id   INTEGER,
            PRIMARY KEY (chore_id, member_id)
        );
        CREATE TABLE IF NOT EXISTS completions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chore_id    INTEGER NOT NULL,
            member_id   INTEGER NOT NULL,
            date        TEXT    NOT NULL,
            UNIQUE(chore_id, member_id, date)
        );
        CREATE TABLE IF NOT EXISTS rewards (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            points_cost INTEGER NOT NULL,
            description TEXT    DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS balance_history (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id    INTEGER NOT NULL,
            points_delta INTEGER NOT NULL,
            reason       TEXT    DEFAULT '',
            created_at   TEXT    DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        );
        INSERT INTO schema_version VALUES (1);
    ''',
    2: '''
        CREATE TABLE IF NOT EXISTS app_settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );
        UPDATE schema_version SET version = 2;
    ''',
    3: '''
        CREATE INDEX IF NOT EXISTS idx_completions_date   ON completions(date);
        CREATE INDEX IF NOT EXISTS idx_completions_member ON completions(member_id);
        CREATE INDEX IF NOT EXISTS idx_completions_chore  ON completions(chore_id);
        UPDATE schema_version SET version = 3;
    ''',
    # v4: chore versioning — old versions stay in DB (active=0) so completions
    # always JOIN to the original chore definition (name/icon/points at time of completion).
    4: '''
        ALTER TABLE chores ADD COLUMN parent_id INTEGER DEFAULT NULL;
        ALTER TABLE chores ADD COLUMN version    INTEGER DEFAULT 1;
        UPDATE schema_version SET version = 4;
    ''',
    # v5: daily_claims — members claim tasks for a specific day with an optional goal.
    5: '''
        CREATE TABLE IF NOT EXISTS daily_claims (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     INTEGER NOT NULL,
            member_id   INTEGER NOT NULL,
            date        TEXT    NOT NULL,
            goal_amount REAL    DEFAULT NULL,
            goal_unit   TEXT    DEFAULT NULL,
            progress    REAL    DEFAULT 0,
            completed   INTEGER DEFAULT 0,
            created_at  TEXT    DEFAULT (datetime('now')),
            UNIQUE(task_id, member_id, date)
        );
        UPDATE schema_version SET version = 5;
    ''',
    # v6: scheduled_time on daily_claims for calendar time-slot scheduling.
    6: '''
        ALTER TABLE daily_claims ADD COLUMN scheduled_time TEXT DEFAULT NULL;
        UPDATE schema_version SET version = 6;
    ''',
    # v7: completed_count so tasks can be done multiple times in one day.
    7: '''
        ALTER TABLE daily_claims ADD COLUMN completed_count INTEGER DEFAULT 0;
        UPDATE daily_claims SET completed_count = completed;
        UPDATE schema_version SET version = 7;
    ''',
    # v8: completion_note — free-text detail logged when a task is checked off.
    8: '''
        ALTER TABLE daily_claims ADD COLUMN completion_note TEXT DEFAULT NULL;
        UPDATE schema_version SET version = 8;
    ''',
    # v9: task_groups for categorising tasks; group_id on chores; daily_extra for ad-hoc entries.
    9: '''
        CREATE TABLE IF NOT EXISTS task_groups (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT    DEFAULT (datetime('now'))
        );
        ALTER TABLE chores ADD COLUMN group_id INTEGER DEFAULT NULL;
        CREATE TABLE IF NOT EXISTS daily_extra (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT    NOT NULL,
            member_id   INTEGER NOT NULL REFERENCES members(id),
            group_id    INTEGER REFERENCES task_groups(id),
            description TEXT    NOT NULL,
            points      INTEGER DEFAULT 0,
            created_at  TEXT    DEFAULT (datetime('now'))
        );
        UPDATE schema_version SET version = 9;
    ''',
    # v10: add icon column to task_groups.
    10: '''
        ALTER TABLE task_groups ADD COLUMN icon TEXT DEFAULT '📁';
        UPDATE schema_version SET version = 10;
    ''',
    # v11: goal_comment — free-text comment stored alongside goal amount/unit.
    11: '''
        ALTER TABLE daily_claims ADD COLUMN goal_comment TEXT DEFAULT NULL;
        UPDATE schema_version SET version = 11;
    ''',
    # v12: reward_redemptions — dedicated log of every reward redemption.
    12: '''
        CREATE TABLE IF NOT EXISTS reward_redemptions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id   INTEGER NOT NULL REFERENCES members(id),
            reward_name TEXT    NOT NULL,
            points_cost INTEGER NOT NULL DEFAULT 0,
            redeemed_at TEXT    DEFAULT (datetime('now'))
        );
        UPDATE schema_version SET version = 12;
    ''',
    # v13: taken_at — tracks when a redeemed reward has been used/taken.
    13: '''
        ALTER TABLE reward_redemptions ADD COLUMN taken_at TEXT DEFAULT NULL;
        UPDATE schema_version SET version = 13;
    ''',
    # v14: manually_hidden lets users hide a scheduled task from Today for one day
    #      without changing the task's schedule. scheduled_duration (minutes) for
    #      calendar events, separate from the goal tracking field.
    14: '''
        ALTER TABLE daily_claims ADD COLUMN manually_hidden INTEGER DEFAULT 0;
        ALTER TABLE daily_claims ADD COLUMN scheduled_duration INTEGER DEFAULT NULL;
        UPDATE schema_version SET version = 14;
    ''',
    15: '''
        ALTER TABLE chores ADD COLUMN one_time INTEGER DEFAULT 0;
        UPDATE schema_version SET version = 15;
    ''',
    16: '''
        INSERT OR IGNORE INTO daily_claims (task_id, member_id, date, completed, completed_count)
        SELECT cp.chore_id, cp.member_id, cp.date, 1, 1
        FROM completions cp
        WHERE NOT EXISTS (
            SELECT 1 FROM daily_claims dc
            WHERE dc.task_id    = cp.chore_id
              AND dc.member_id  = cp.member_id
              AND dc.date       = cp.date
        );
        UPDATE schema_version SET version = 16;
    ''',
}

CURRENT_SCHEMA_VERSION = 16
GOAL_UNITS = ['pages', 'min', 'hr', 'chapters', 'count', 'times']

def init_db():
    conn = get_db()
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        current = row['version'] if row else 0
    except sqlite3.OperationalError:
        current = 0

    for v in sorted(SCHEMA_MIGRATIONS):
        if v > current:
            conn.executescript(SCHEMA_MIGRATIONS[v])
            conn.commit()

    conn.close()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_week_dates(offset=0):
    today = date.today()
    days_since_sunday = (today.weekday() + 1) % 7
    sunday = today - timedelta(days=days_since_sunday) + timedelta(weeks=offset)
    return [sunday + timedelta(days=i) for i in range(7)]

def to_day_idx(d):
    return (d.weekday() + 1) % 7

def is_chore_due(chore, d):
    st = chore['schedule_type']
    if st == 'daily':    return True
    if st == 'weekdays': return d.weekday() < 5
    if st == 'weekends': return d.weekday() >= 5
    if st == 'specific':
        return to_day_idx(d) in json.loads(chore['schedule_days'] or '[]')
    return False  # as_needed

def get_member_chores(member_id, conn):
    return conn.execute('''
        SELECT c.* FROM chores c
        WHERE c.active = 1 AND (
            c.assignment_type IN ('everyone', 'anyone')
            OR EXISTS (SELECT 1 FROM chore_members cm
                       WHERE cm.chore_id = c.id AND cm.member_id = ?)
        )
        ORDER BY c.sort_order, c.id
    ''', (member_id,)).fetchall()

def get_assigned_member_ids(chore, all_member_ids, conn):
    if chore['assignment_type'] in ('everyone', 'anyone'):
        return list(all_member_ids)
    rows = conn.execute('SELECT member_id FROM chore_members WHERE chore_id=?',
                        (chore['id'],)).fetchall()
    return [r['member_id'] for r in rows]

STREAK_MILESTONES = [(100, '💎', '100d'), (30, '🥇', '30d'), (7, '🥈', '7d'), (3, '🥉', '3d')]

def calc_badges(streak):
    return [{'emoji': e, 'label': l} for days, e, l in STREAK_MILESTONES if streak >= days]

def calc_points(member_id, conn):
    # Use daily_claims as the source of truth — same formula as Today view's
    # member_totals: SUM(completed_count * chore.points) for active chores only.
    # This guarantees the lifetime balance = sum of every day's Today view score.
    earned = conn.execute('''
        SELECT COALESCE(SUM(
            CASE WHEN dc.completed_count <= 1 THEN c.points
                 ELSE c.points + (dc.completed_count - 1) * (c.points / 2)
            END
        ), 0)
        FROM daily_claims dc
        JOIN chores c ON dc.task_id = c.id
        WHERE dc.member_id = ? AND dc.completed_count > 0 AND c.active = 1
    ''', (member_id,)).fetchone()[0]
    adj = conn.execute(
        'SELECT COALESCE(SUM(points_delta), 0) FROM balance_history WHERE member_id=?',
        (member_id,)).fetchone()[0]
    extra = conn.execute(
        'SELECT COALESCE(SUM(points), 0) FROM daily_extra WHERE member_id=?',
        (member_id,)).fetchone()[0]
    return (earned or 0) + (adj or 0) + (extra or 0)

def calc_streak(member_id, conn):
    today_obj = date.today()
    streak = 0
    for days_back in range(365):
        d = today_obj - timedelta(days=days_back)
        if conn.execute('SELECT 1 FROM daily_claims WHERE member_id=? AND date=? AND completed_count>0',
                        (member_id, d.isoformat())).fetchone():
            streak += 1
        else:
            break
    return streak

def format_bytes(b):
    if b < 1024:       return f"{b} B"
    if b < 1048576:    return f"{b/1024:.1f} KB"
    return f"{b/1048576:.1f} MB"

def member_color(idx):
    return MEMBER_COLORS[idx % len(MEMBER_COLORS)]

# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------
@app.route('/')
def household():
    conn = get_db()
    members = [dict(m) for m in conn.execute('SELECT * FROM members ORDER BY sort_order, id')]
    today_obj = date.today()
    today_str = today_obj.isoformat()
    for i, m in enumerate(members):
        if not m.get('color'):
            m['color'] = member_color(i)
        chores = get_member_chores(m['id'], conn)
        m['due_today'] = sum(
            1 for c in chores
            if is_chore_due(c, today_obj) and not conn.execute(
                'SELECT 1 FROM completions WHERE chore_id=? AND member_id=? AND date=?',
                (c['id'], m['id'], today_str)).fetchone()
        )
        m['streak'] = calc_streak(m['id'], conn)
        m['badges'] = calc_badges(m['streak'])
    conn.close()
    return render_template('household.html', members=members)

@app.route('/member/<int:member_id>')
def member_view(member_id):
    conn = get_db()
    m = conn.execute('SELECT * FROM members WHERE id=?', (member_id,)).fetchone()
    if not m:
        return redirect(url_for('household'))
    member = dict(m)
    today_obj = date.today()
    today_str = today_obj.isoformat()
    week_dates = get_week_dates(0)
    all_chores = get_member_chores(member_id, conn)
    today_chores, as_needed_chores, upcoming_chores = [], [], []
    for c in all_chores:
        done = bool(conn.execute(
            'SELECT 1 FROM completions WHERE chore_id=? AND member_id=? AND date=?',
            (c['id'], member_id, today_str)).fetchone())
        item = {'chore': dict(c), 'completed': done}
        if c['schedule_type'] == 'as_needed':
            as_needed_chores.append(item)
        elif is_chore_due(c, today_obj):
            today_chores.append(item)
        else:
            for day_offset in range(1, 7):
                nd = today_obj + timedelta(days=day_offset)
                if is_chore_due(c, nd):
                    item['next_date'] = nd.strftime('%A')
                    upcoming_chores.append(item)
                    break
    points = calc_points(member_id, conn)
    streak = calc_streak(member_id, conn)
    badges = calc_badges(streak)
    conn.close()
    return render_template('member.html', member=member,
        today_chores=today_chores, as_needed_chores=as_needed_chores,
        upcoming_chores=upcoming_chores, week_dates=week_dates,
        today=today_obj, points=points, streak=streak, badges=badges)

@app.route('/chores')
def chores_page():
    return redirect(url_for('tasks_page'))

@app.route('/chores/new')
def new_chore():
    return redirect(url_for('new_task'))

@app.route('/chores/<int:chore_id>/edit')
def edit_chore(chore_id):
    return redirect(url_for('edit_task', task_id=chore_id))

@app.route('/tasks')
def tasks_page():
    conn = get_db()
    members = [dict(m) for m in conn.execute('SELECT * FROM members ORDER BY sort_order, id')]
    all_member_ids = [m['id'] for m in members]
    chore_rows = conn.execute('SELECT * FROM chores WHERE active=1 ORDER BY sort_order, id').fetchall()
    today_str = date.today().isoformat()
    claimed_today = {(r['task_id'], r['member_id'])
                     for r in conn.execute('SELECT task_id, member_id FROM daily_claims WHERE date=?',
                                           (today_str,)).fetchall()}
    tasks_data = []
    one_time_data = []
    for c in chore_rows:
        mid_list = get_assigned_member_ids(c, all_member_ids, conn)
        assigned = [m for m in members if m['id'] in mid_list]
        entry = {'chore': dict(c), 'assigned': assigned}
        if c['one_time']:
            one_time_data.append(entry)
        else:
            tasks_data.append(entry)

    # Archived = inactive tasks that are the latest version of their lineage
    archived_rows = conn.execute('''
        SELECT * FROM chores c
        WHERE c.active = 0
        AND NOT EXISTS (SELECT 1 FROM chores c2 WHERE c2.parent_id = c.id)
        ORDER BY c.sort_order, c.id
    ''').fetchall()
    archived_data = []
    for c in archived_rows:
        mid_list = get_assigned_member_ids(c, all_member_ids, conn)
        assigned  = [m for m in members if m['id'] in mid_list]
        archived_data.append({'chore': dict(c), 'assigned': assigned})

    groups = [dict(g) for g in conn.execute('SELECT * FROM task_groups ORDER BY sort_order, id')]
    conn.close()

    # Build grouped sections for display
    task_sections = []
    for g in groups:
        group_tasks = [t for t in tasks_data if t['chore'].get('group_id') == g['id']]
        if group_tasks:
            task_sections.append({'group': g, 'tasks': group_tasks})
    ungrouped = [t for t in tasks_data if not t['chore'].get('group_id')]
    if ungrouped:
        task_sections.append({'group': None, 'tasks': ungrouped})

    return render_template('tasks.html', tasks=tasks_data, task_sections=task_sections,
                           archived=archived_data, one_time_tasks=one_time_data,
                           all_members=members, claimed_today=claimed_today,
                           goal_units=GOAL_UNITS, today_str=today_str, groups=groups)

@app.route('/tasks/new')
def new_task():
    conn = get_db()
    members = [dict(m) for m in conn.execute('SELECT * FROM members ORDER BY sort_order, id')]
    groups  = [dict(g) for g in conn.execute('SELECT * FROM task_groups ORDER BY sort_order, id')]
    conn.close()
    default_group_id = request.args.get('group_id', type=int)
    return render_template('task_form.html', chore=None, all_members=members,
                           assigned_ids=[], schedule_days_list=[], groups=groups,
                           default_group_id=default_group_id)

@app.route('/tasks/<int:task_id>/edit')
def edit_task(task_id):
    conn = get_db()
    chore = conn.execute('SELECT * FROM chores WHERE id=?', (task_id,)).fetchone()
    if not chore:
        return redirect(url_for('tasks_page'))
    members = [dict(m) for m in conn.execute('SELECT * FROM members ORDER BY sort_order, id')]
    groups  = [dict(g) for g in conn.execute('SELECT * FROM task_groups ORDER BY sort_order, id')]
    assigned_ids = [r['member_id'] for r in conn.execute(
        'SELECT member_id FROM chore_members WHERE chore_id=?', (task_id,)).fetchall()]
    schedule_days_list = json.loads(chore['schedule_days'] or '[]')
    conn.close()
    return render_template('task_form.html', chore=dict(chore), all_members=members,
                           assigned_ids=assigned_ids, schedule_days_list=schedule_days_list,
                           groups=groups)

@app.route('/today')
def today_page():
    real_today = date.today()
    date_param = request.args.get('date', '')
    try:
        today_date = date.fromisoformat(date_param)
    except (ValueError, TypeError):
        today_date = real_today
    today_str = today_date.isoformat()
    is_today  = (today_date == real_today)
    prev_str  = (today_date - timedelta(days=1)).isoformat()
    next_str  = (today_date + timedelta(days=1)).isoformat()
    delta_days = (today_date - real_today).days
    if is_today:
        date_label = 'Today'
    elif delta_days == -1:
        date_label = 'Yesterday'
    elif delta_days == 1:
        date_label = 'Tomorrow'
    elif delta_days == 7:
        date_label = 'Same Day Next Week'
    elif delta_days == -7:
        date_label = 'Same Day Last Week'
    elif 2 <= delta_days <= 6:
        date_label = f'In {delta_days} days'
    elif -6 <= delta_days <= -2:
        date_label = f'{-delta_days} days ago'
    else:
        date_label = today_date.strftime('%b %d')

    # Auto-claim all scheduled tasks for the viewed date so they appear without manual claiming.
    # Runs for any date (today, past, future) — INSERT OR IGNORE preserves existing
    # claims (including manually_hidden ones and any saved progress/goal data).
    with _write_lock:
        conn = get_db()
        try:
            members_all    = [dict(m) for m in conn.execute('SELECT * FROM members ORDER BY sort_order, id')]
            tasks_all      = [dict(t) for t in conn.execute('SELECT * FROM chores WHERE active=1 ORDER BY sort_order, id').fetchall()]
            all_member_ids = [m['id'] for m in members_all]
            done_set = {(r['chore_id'], r['member_id'])
                        for r in conn.execute('SELECT chore_id, member_id FROM completions WHERE date=?', (today_str,)).fetchall()}
            for task in tasks_all:
                if not is_chore_due(task, today_date):
                    continue
                for mid in get_assigned_member_ids(task, all_member_ids, conn):
                    already_done = 1 if (task['id'], mid) in done_set else 0
                    conn.execute('''
                        INSERT OR IGNORE INTO daily_claims
                            (task_id, member_id, date, goal_amount, goal_unit, progress, completed, completed_count)
                        VALUES (?, ?, ?, NULL, NULL, 0, ?, ?)
                    ''', (task['id'], mid, today_str, already_done, already_done))
            conn.execute('''
                UPDATE daily_claims SET completed=1, completed_count=MAX(completed_count,1)
                WHERE date=? AND completed=0
                  AND EXISTS (SELECT 1 FROM completions
                              WHERE completions.chore_id  = daily_claims.task_id
                                AND completions.member_id = daily_claims.member_id
                                AND completions.date      = daily_claims.date)
            ''', (today_str,))
            conn.commit()
        finally:
            conn.close()

    conn = get_db()
    members = [dict(m) for m in conn.execute('SELECT * FROM members ORDER BY sort_order, id')]
    tasks   = [dict(t) for t in conn.execute('SELECT * FROM chores WHERE active=1 ORDER BY sort_order, id').fetchall()]
    raw_claims = conn.execute('''
        SELECT dc.*, c.name as task_name, c.icon as task_icon, c.points as task_points,
               c.assignment_type as task_assignment_type, c.group_id as task_group_id,
               tg.name as task_group_name, tg.icon as task_group_icon
        FROM daily_claims dc
        JOIN chores c ON dc.task_id = c.id
        LEFT JOIN task_groups tg ON c.group_id = tg.id
        WHERE dc.date = ? AND c.active = 1 AND COALESCE(dc.manually_hidden, 0) = 0
        ORDER BY c.sort_order, c.id, dc.created_at
    ''', (today_str,)).fetchall()

    # Unique task rows in display order
    seen_tasks = {}
    task_rows  = []
    for r in raw_claims:
        tid = r['task_id']
        if tid not in seen_tasks:
            seen_tasks[tid] = {'task_id': tid, 'task_name': r['task_name'],
                               'task_icon': r['task_icon'], 'task_points': r['task_points'],
                               'task_assignment_type': r['task_assignment_type'],
                               'task_group_id': r['task_group_id'],
                               'task_group_name': r['task_group_name'],
                               'task_group_icon': r['task_group_icon']}
            task_rows.append(seen_tasks[tid])

    # cells[task_id][member_id] = claim_dict
    cells = {}
    for r in raw_claims:
        tid, mid = r['task_id'], r['member_id']
        cells.setdefault(tid, {})[mid] = dict(r)

    # Earned points per member — multiply by completed_count for multi-count tasks
    member_totals = {m['id']: 0 for m in members}
    for r in raw_claims:
        cnt = r['completed_count'] or 0
        if cnt > 0:
            pts = r['task_points']
            earned = pts + (cnt - 1) * (pts // 2) if cnt > 1 else pts
            member_totals[r['member_id']] = member_totals.get(r['member_id'], 0) + earned

    # Flat list per member for calendar drag panel
    claims_by_member = {}
    for r in raw_claims:
        mid = r['member_id']
        claims_by_member.setdefault(mid, []).append({
            'id':                 r['id'],
            'task_id':            r['task_id'],
            'task_name':          r['task_name'],
            'task_icon':          r['task_icon'],
            'task_pts':           r['task_points'],
            'completed_count':    r['completed_count'] or 0,
            'completed':          bool(r['completed']),
            'scheduled_time':     r['scheduled_time'],
            'scheduled_duration': r['scheduled_duration'],
            'goal_amount':        r['goal_amount'],
            'goal_unit':          r['goal_unit'],
            'goal_comment':       r['goal_comment'],
            'completion_note':    r['completion_note'],
        })

    # Fetch today's ad-hoc extras
    extras_raw = conn.execute('''
        SELECT de.*, tg.name as group_name
        FROM daily_extra de
        LEFT JOIN task_groups tg ON de.group_id = tg.id
        WHERE de.date = ?
        ORDER BY de.created_at
    ''', (today_str,)).fetchall()
    extras_by_member = {}
    for e in extras_raw:
        extras_by_member.setdefault(e['member_id'], []).append(dict(e))
    for mid, elist in extras_by_member.items():
        member_totals[mid] = member_totals.get(mid, 0) + sum(e['points'] for e in elist)

    groups = [dict(g) for g in conn.execute('SELECT * FROM task_groups ORDER BY sort_order, id')]

    # Hidden tasks for this date — one entry per unique task (for the unhide UI)
    hidden_raw = conn.execute('''
        SELECT DISTINCT c.id as task_id, c.name as task_name, c.icon as task_icon,
               tg.name as task_group_name, tg.icon as task_group_icon
        FROM daily_claims dc
        JOIN chores c ON dc.task_id = c.id
        LEFT JOIN task_groups tg ON c.group_id = tg.id
        WHERE dc.date = ? AND COALESCE(dc.manually_hidden, 0) = 1 AND c.active = 1
        ORDER BY c.sort_order, c.id
    ''', (today_str,)).fetchall()
    hidden_tasks = [dict(r) for r in hidden_raw]

    conn.close()

    # Build grouped_task_rows: list of {group, rows} in group sort_order
    tasks_by_group = {}
    for row in task_rows:
        gid = row['task_group_id']
        tasks_by_group.setdefault(gid, []).append(row)
    grouped_task_rows = []
    for g in groups:
        if g['id'] in tasks_by_group:
            grouped_task_rows.append({'group': g, 'rows': tasks_by_group[g['id']]})
    if None in tasks_by_group:
        grouped_task_rows.append({'group': None, 'rows': tasks_by_group[None]})
    # If no groups at all, still pass the flat list as one section
    if not grouped_task_rows and task_rows:
        grouped_task_rows = [{'group': None, 'rows': task_rows}]

    # Penalty groups (icon == '⚠️') go below the Add row in Today view
    normal_groups  = [s for s in grouped_task_rows if not s['group'] or s['group'].get('icon') != '⚠️']
    penalty_groups = [s for s in grouped_task_rows if s['group'] and s['group'].get('icon') == '⚠️']

    return render_template('today.html',
        members=members, tasks=tasks,
        task_rows=task_rows, cells=cells,
        member_totals=member_totals,
        claims_by_member=claims_by_member,
        extras_by_member=extras_by_member,
        groups=groups,
        grouped_task_rows=grouped_task_rows,
        normal_groups=normal_groups,
        penalty_groups=penalty_groups,
        hidden_tasks=hidden_tasks,
        today=today_date, today_str=today_str,
        is_today=is_today, prev_str=prev_str, next_str=next_str, date_label=date_label,
        goal_units=GOAL_UNITS)

@app.route('/chart')
def chart():
    week_offset = int(request.args.get('week', 0))
    group_by    = request.args.get('group', 'profiles')
    conn = get_db()
    members = [dict(m) for m in conn.execute('SELECT * FROM members ORDER BY sort_order, id')]
    all_member_ids = [m['id'] for m in members]
    chore_rows = conn.execute('SELECT * FROM chores WHERE active=1 ORDER BY sort_order, id').fetchall()
    week_dates = get_week_dates(week_offset)
    today = date.today()
    start_str, end_str = week_dates[0].isoformat(), week_dates[-1].isoformat()
    comp_rows = conn.execute(
        'SELECT chore_id, member_id, date FROM completions WHERE date >= ? AND date <= ?',
        (start_str, end_str)).fetchall()
    completions = {(r['chore_id'], r['member_id'], r['date']) for r in comp_rows}
    claim_rows = conn.execute(
        'SELECT task_id, member_id, date FROM daily_claims WHERE date >= ? AND date <= ?',
        (start_str, end_str)).fetchall()
    claims_set = {(r['task_id'], r['member_id'], r['date']) for r in claim_rows}

    def cell_status(chore_id, member_id, d):
        d_str = d.isoformat()
        if (chore_id, member_id, d_str) in completions: return 'completed'
        if d_str == today.isoformat():                   return 'due_today'
        if d_str > today.isoformat():                    return 'upcoming'
        # Past day, not completed: distinguish claimed vs never-signed-up
        if (chore_id, member_id, d_str) in claims_set:  return 'incomplete'
        return 'not_claimed'

    chart_data = []
    def as_needed_cells(chore_id, member_id):
        # as_needed tasks have no fixed schedule — show completed days, not_due otherwise
        return [('completed' if (chore_id, member_id, d.isoformat()) in completions else 'not_due')
                for d in week_dates]

    if group_by == 'profiles':
        for m in members:
            m_chores = []
            for c in chore_rows:
                if m['id'] not in get_assigned_member_ids(c, all_member_ids, conn): continue
                if c['schedule_type'] == 'as_needed':
                    cells = as_needed_cells(c['id'], m['id'])
                else:
                    cells = [cell_status(c['id'], m['id'], d) if is_chore_due(c, d) else 'not_due'
                             for d in week_dates]
                m_chores.append({'chore': dict(c), 'cells': cells})
            m_chores.sort(key=lambda x: 1 if (x['chore'].get('points') or 0) < 0 else 0)
            chart_data.append({'member': m, 'chores': m_chores})
    else:
        for c in chore_rows:
            mids = get_assigned_member_ids(c, all_member_ids, conn)
            member_rows = [{'member': m,
                            'cells': as_needed_cells(c['id'], m['id']) if c['schedule_type'] == 'as_needed' else
                                     [cell_status(c['id'], m['id'], d) if is_chore_due(c, d) else 'not_due'
                                      for d in week_dates]}
                           for m in members if m['id'] in mids]
            chart_data.append({'chore': dict(c), 'members': member_rows})

    chores_map = {c['id']: {'name': c['name'], 'points': c['points']} for c in chore_rows}
    conn.close()
    if week_offset == 0:    week_label = 'This Week'
    elif week_offset == 1:  week_label = 'Next Week'
    elif week_offset == -1: week_label = 'Last Week'
    else: week_label = f"{week_dates[0].strftime('%b %d')} – {week_dates[-1].strftime('%b %d')}"

    return render_template('chart.html', chart_data=chart_data, group_by=group_by,
        week_dates=week_dates, week_offset=week_offset, week_label=week_label, today=today,
        day_names=['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
        chores_map=chores_map)

@app.route('/balances')
def balances():
    conn = get_db()
    members = [dict(m) for m in conn.execute('SELECT * FROM members ORDER BY sort_order, id')]
    rewards = [dict(r) for r in conn.execute('SELECT * FROM rewards ORDER BY points_cost')]
    sixty_ago = (date.today() - timedelta(days=60)).isoformat()
    history = {}
    for m in members:
        m['points'] = calc_points(m['id'], conn)
        adj_rows = conn.execute('''
            SELECT 'adjustment' as type, points_delta, reason,
                   '' as chore_name, '' as chore_icon, created_at,
                   null as completion_note
            FROM balance_history WHERE member_id=? ORDER BY created_at DESC
        ''', (m['id'],)).fetchall()
        comp_rows = conn.execute('''
            SELECT 'completion' as type,
                   CASE WHEN dc.completed_count <= 1 THEN c.points
                        ELSE c.points + (dc.completed_count - 1) * (c.points / 2)
                   END as points_delta,
                   '' as reason,
                   c.name as chore_name, c.icon as chore_icon,
                   dc.date || 'T12:00:00' as created_at,
                   dc.completion_note
            FROM daily_claims dc
            JOIN chores c ON dc.task_id = c.id
            WHERE dc.member_id=? AND dc.date >= ?
              AND dc.completed_count > 0 AND c.active = 1 AND c.points != 0
            ORDER BY dc.date DESC
        ''', (m['id'], sixty_ago)).fetchall()
        extra_rows = conn.execute('''
            SELECT 'extra' as type, de.points as points_delta, de.description as reason,
                   COALESCE(tg.name, '') as chore_name, '📝' as chore_icon,
                   de.date || 'T12:00:00' as created_at, null as completion_note
            FROM daily_extra de
            LEFT JOIN task_groups tg ON de.group_id = tg.id
            WHERE de.member_id=? AND de.date >= ?
            ORDER BY de.date DESC
        ''', (m['id'], sixty_ago)).fetchall()
        combined = sorted(
            [dict(r) for r in adj_rows] + [dict(r) for r in comp_rows] + [dict(r) for r in extra_rows],
            key=lambda x: x['created_at'], reverse=True
        )[:50]
        history[m['id']] = combined
    redemptions = conn.execute('''
        SELECT rr.id, rr.reward_name, rr.points_cost, rr.redeemed_at, rr.taken_at,
               m.name as member_name, m.avatar as member_avatar, m.color as member_color
        FROM reward_redemptions rr
        JOIN members m ON rr.member_id = m.id
        ORDER BY rr.redeemed_at DESC
        LIMIT 50
    ''').fetchall()
    # Per-member pending (not yet taken) redemptions
    pending_rows = conn.execute('''
        SELECT rr.id, rr.reward_name, rr.points_cost, rr.redeemed_at,
               rr.member_id
        FROM reward_redemptions rr
        WHERE rr.taken_at IS NULL
        ORDER BY rr.redeemed_at DESC
    ''').fetchall()
    pending_by_member = {}
    for r in pending_rows:
        pending_by_member.setdefault(r['member_id'], []).append(dict(r))
    conn.close()
    return render_template('balances.html', members=members, rewards=rewards,
                           history=history,
                           redemptions=[dict(r) for r in redemptions],
                           pending_by_member=pending_by_member)

@app.route('/settings')
def settings():
    conn = get_db()
    members = [dict(m) for m in conn.execute('SELECT * FROM members ORDER BY sort_order, id')]
    conn.close()
    return render_template('settings.html', members=members)

@app.route('/admin')
def admin():
    conn = get_db()

    # Row counts per table
    tables = ['members', 'chores', 'completions', 'rewards', 'balance_history', 'app_settings']
    row_counts = {t: conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in tables}
    row_counts['chores_active'] = conn.execute(
        'SELECT COUNT(*) FROM chores WHERE active=1').fetchone()[0]

    # Chore version history — all chores (active + inactive) grouped by lineage
    all_chores_raw = conn.execute('''
        SELECT c.*,
               (SELECT COUNT(*) FROM completions WHERE chore_id = c.id) AS completion_count
        FROM chores c
        ORDER BY COALESCE(c.parent_id, c.id), c.version, c.id
    ''').fetchall()
    all_chores = [dict(r) for r in all_chores_raw]

    # Group into version chains: key = root_id (id where parent_id IS NULL)
    chains_map = {}
    for c in all_chores:
        root = c['parent_id'] if c['parent_id'] else c['id']
        chains_map.setdefault(root, []).append(c)
    chore_chains = sorted(chains_map.values(), key=lambda lst: lst[0]['id'])

    # Recent completions (last 30)
    recent = conn.execute('''
        SELECT m.name AS member_name, m.avatar AS member_avatar,
               c.name AS chore_name, c.icon AS chore_icon, cp.date
        FROM completions cp
        JOIN members m ON cp.member_id = m.id
        JOIN chores  c ON cp.chore_id  = c.id
        ORDER BY cp.date DESC, cp.id DESC
        LIMIT 30
    ''').fetchall()

    # Top members by total completions
    top_members = conn.execute('''
        SELECT m.name, m.avatar, m.color, COUNT(cp.id) AS total
        FROM members m LEFT JOIN completions cp ON m.id = cp.member_id
        GROUP BY m.id ORDER BY total DESC
    ''').fetchall()

    # Top chores by completion count (active + legacy — both credited)
    top_chores = conn.execute('''
        SELECT c.name, c.icon, COUNT(cp.id) AS total
        FROM chores c LEFT JOIN completions cp ON c.id = cp.chore_id
        WHERE c.active = 1
        GROUP BY c.id ORDER BY total DESC LIMIT 8
    ''').fetchall()

    # Date range of data
    date_range = conn.execute(
        'SELECT MIN(date) AS first_date, MAX(date) AS last_date FROM completions'
    ).fetchone()

    # Schema + system info
    schema_v  = conn.execute('SELECT version FROM schema_version').fetchone()
    sqlite_v  = conn.execute('SELECT sqlite_version()').fetchone()[0]
    conn.close()

    db_size    = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    uptime_sec = int(_time.time() - _server_start)
    uptime_str = (f"{uptime_sec // 3600}h {(uptime_sec % 3600) // 60}m"
                  if uptime_sec >= 3600 else f"{uptime_sec // 60}m {uptime_sec % 60}s")

    return render_template('admin.html',
        row_counts=row_counts,
        chore_chains=chore_chains,
        recent=[dict(r) for r in recent],
        top_members=[dict(r) for r in top_members],
        top_chores=[dict(r) for r in top_chores],
        date_range=dict(date_range) if date_range else {},
        schema_version=schema_v['version'] if schema_v else '?',
        sqlite_version=sqlite_v,
        db_size=format_bytes(db_size),
        db_size_raw=db_size,
        uptime=uptime_str,
    )

# ---------------------------------------------------------------------------
# API routes — writes go through _write_lock
# ---------------------------------------------------------------------------

@app.route('/api/claim-task', methods=['POST'])
def claim_task():
    data = request.json
    task_id     = data['task_id']
    member_id   = data['member_id']
    goal_amount = data.get('goal_amount') or None
    goal_unit   = data.get('goal_unit') or None
    date_str    = data.get('date', date.today().isoformat())
    with _write_lock:
        conn = get_db()
        try:
            conn.execute('''
                INSERT OR REPLACE INTO daily_claims
                    (task_id, member_id, date, goal_amount, goal_unit, progress, completed)
                VALUES (?, ?, ?, ?, ?, 0, 0)
            ''', (task_id, member_id, date_str, goal_amount, goal_unit))
            conn.commit()
            claim_id = conn.execute(
                'SELECT id FROM daily_claims WHERE task_id=? AND member_id=? AND date=?',
                (task_id, member_id, date_str)).fetchone()['id']
        finally:
            conn.close()
    return jsonify({'success': True, 'claim_id': claim_id})

@app.route('/api/update-claim', methods=['POST'])
def update_claim():
    data = request.json
    claim_id       = data['claim_id']
    progress       = data.get('progress')
    completed      = data.get('completed')
    scheduled_time = data.get('scheduled_time')
    count_delta    = data.get('count_delta')  # +N or -N for multi-count
    with _write_lock:
        conn = get_db()
        try:
            if progress is not None:
                conn.execute('UPDATE daily_claims SET progress=? WHERE id=?', (progress, claim_id))
            if completed is not None:
                # Fetch before update to know old completed_count
                row = conn.execute(
                    'SELECT task_id, member_id, date, completed_count FROM daily_claims WHERE id=?',
                    (claim_id,)).fetchone()
                conn.execute('UPDATE daily_claims SET completed=? WHERE id=?', (int(completed), claim_id))
                if row:
                    old_count = row['completed_count'] or 0
                    # Keep completed_count in sync with completed flag
                    if completed and old_count == 0:
                        conn.execute('UPDATE daily_claims SET completed_count=1 WHERE id=?', (claim_id,))
                    elif not completed:
                        conn.execute('UPDATE daily_claims SET completed_count=0 WHERE id=?', (claim_id,))
                    if completed:
                        conn.execute('INSERT OR IGNORE INTO completions (chore_id, member_id, date) VALUES (?,?,?)',
                                     (row['task_id'], row['member_id'], row['date']))
                    else:
                        conn.execute('DELETE FROM completions WHERE chore_id=? AND member_id=? AND date=?',
                                     (row['task_id'], row['member_id'], row['date']))
            if count_delta is not None:
                row = conn.execute(
                    'SELECT task_id, member_id, date, completed_count FROM daily_claims WHERE id=?',
                    (claim_id,)).fetchone()
                if row:
                    old_count = row['completed_count'] or 0
                    new_count = max(0, old_count + int(count_delta))
                    conn.execute('UPDATE daily_claims SET completed_count=?, completed=? WHERE id=?',
                                 (new_count, 1 if new_count > 0 else 0, claim_id))
                    if old_count == 0 and new_count > 0:
                        conn.execute('INSERT OR IGNORE INTO completions (chore_id, member_id, date) VALUES (?,?,?)',
                                     (row['task_id'], row['member_id'], row['date']))
                    elif old_count > 0 and new_count == 0:
                        conn.execute('DELETE FROM completions WHERE chore_id=? AND member_id=? AND date=?',
                                     (row['task_id'], row['member_id'], row['date']))
            if scheduled_time is not None:
                conn.execute('UPDATE daily_claims SET scheduled_time=? WHERE id=?',
                             (scheduled_time or None, claim_id))
            if 'scheduled_duration' in data:
                conn.execute('UPDATE daily_claims SET scheduled_duration=? WHERE id=?',
                             (data['scheduled_duration'] or None, claim_id))
            if 'goal_amount' in data or 'goal_unit' in data:
                conn.execute('UPDATE daily_claims SET goal_amount=?, goal_unit=? WHERE id=?',
                             (data.get('goal_amount'), data.get('goal_unit') or None, claim_id))
            completion_note = data.get('completion_note')
            if completion_note is not None:
                conn.execute('UPDATE daily_claims SET completion_note=? WHERE id=?',
                             (completion_note or None, claim_id))
            if 'goal_comment' in data:
                conn.execute('UPDATE daily_claims SET goal_comment=? WHERE id=?',
                             (data.get('goal_comment') or None, claim_id))
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True})

@app.route('/api/unclaim-task', methods=['POST'])
def unclaim_task():
    data = request.json
    with _write_lock:
        conn = get_db()
        try:
            conn.execute('DELETE FROM daily_claims WHERE id=?', (data['claim_id'],))
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True})

@app.route('/api/remove-today-claim', methods=['POST'])
def remove_today_claim():
    """Delete a specific member's daily_claims row + completions row, resetting the card to unclaimed."""
    data = request.json
    claim_id = data.get('claim_id')
    with _write_lock:
        conn = get_db()
        try:
            row = conn.execute('SELECT * FROM daily_claims WHERE id=?', (claim_id,)).fetchone()
            if row:
                conn.execute('DELETE FROM daily_claims WHERE id=?', (claim_id,))
                conn.execute(
                    'DELETE FROM completions WHERE chore_id=? AND member_id=? AND date=?',
                    (row['task_id'], row['member_id'], row['date']))
                conn.commit()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
        finally:
            conn.close()

@app.route('/api/hide-today-task', methods=['POST'])
def hide_today_task():
    """Mark all daily_claims for task+date as manually hidden (hides from Today view)."""
    data = request.json
    task_id  = data['task_id']
    date_str = data['date']
    with _write_lock:
        conn = get_db()
        try:
            conn.execute(
                'UPDATE daily_claims SET manually_hidden=1 WHERE task_id=? AND date=?',
                (task_id, date_str))
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True})

@app.route('/api/unhide-today-task', methods=['POST'])
def unhide_today_task():
    """Clear manually_hidden for task+date (re-shows in Today view)."""
    data = request.json
    task_id  = data['task_id']
    date_str = data['date']
    with _write_lock:
        conn = get_db()
        try:
            conn.execute(
                'UPDATE daily_claims SET manually_hidden=0 WHERE task_id=? AND date=?',
                (task_id, date_str))
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True})

@app.route('/api/toggle-completion', methods=['POST'])
def toggle_completion():
    data = request.json
    chore_id, member_id, date_str = data['chore_id'], data['member_id'], data['date']
    with _write_lock:
        conn = get_db()
        try:
            deleted = conn.execute(
                'DELETE FROM completions WHERE chore_id=? AND member_id=? AND date=?',
                (chore_id, member_id, date_str)).rowcount
            if deleted == 0:
                conn.execute(
                    'INSERT OR IGNORE INTO completions (chore_id, member_id, date) VALUES (?,?,?)',
                    (chore_id, member_id, date_str))
                # Keep daily_claims in sync so Review/Balances see this completion
                conn.execute('''
                    INSERT INTO daily_claims (task_id, member_id, date, completed, completed_count)
                    VALUES (?, ?, ?, 1, 1)
                    ON CONFLICT(task_id, member_id, date) DO UPDATE SET
                        completed=1, completed_count=MAX(completed_count, 1)
                ''', (chore_id, member_id, date_str))
                completed = True
            else:
                conn.execute('''
                    UPDATE daily_claims SET completed=0, completed_count=0
                    WHERE task_id=? AND member_id=? AND date=?
                ''', (chore_id, member_id, date_str))
                completed = False
            conn.commit()
        finally:
            conn.close()
    return jsonify({'completed': completed})

@app.route('/api/save-group', methods=['POST'])
def save_group():
    data     = request.json
    group_id = data.get('id')
    name     = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'Name required'}), 400
    icon = (data.get('icon') or '📁').strip() or '📁'
    with _write_lock:
        conn = get_db()
        try:
            if group_id:
                conn.execute('UPDATE task_groups SET name=?, icon=? WHERE id=?', (name, icon, group_id))
            else:
                cur = conn.execute('INSERT INTO task_groups (name, icon) VALUES (?, ?)', (name, icon))
                group_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True, 'group_id': group_id, 'name': name, 'icon': icon})

@app.route('/api/delete-group', methods=['POST'])
def delete_group():
    group_id = request.json['group_id']
    with _write_lock:
        conn = get_db()
        try:
            # Clear group reference from tasks instead of blocking delete
            conn.execute('UPDATE chores SET group_id=NULL WHERE group_id=?', (group_id,))
            conn.execute('DELETE FROM task_groups WHERE id=?', (group_id,))
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True})

@app.route('/api/reorder-today', methods=['POST'])
def reorder_today():
    task_ids = request.json.get('task_ids', [])
    with _write_lock:
        conn = get_db()
        for i, tid in enumerate(task_ids):
            conn.execute('UPDATE chores SET sort_order=? WHERE id=?', (i * 10, tid))
        conn.commit()
        conn.close()
    return jsonify({'success': True})

@app.route('/api/reorder-tasks', methods=['POST'])
def reorder_tasks():
    task_order = request.json.get('task_order', [])
    with _write_lock:
        conn = get_db()
        for i, entry in enumerate(task_order):
            conn.execute('UPDATE chores SET sort_order=?, group_id=? WHERE id=?',
                         (i * 10, entry.get('group_id'), entry['task_id']))
        conn.commit()
        conn.close()
    return jsonify({'success': True})

@app.route('/api/reorder-groups', methods=['POST'])
def reorder_groups():
    group_ids = request.json.get('group_ids', [])
    with _write_lock:
        conn = get_db()
        for i, gid in enumerate(group_ids):
            if gid:
                conn.execute('UPDATE task_groups SET sort_order=? WHERE id=?', (i * 10, int(gid)))
        conn.commit()
        conn.close()
    return jsonify({'success': True})

@app.route('/api/reorder-members', methods=['POST'])
def reorder_members():
    member_ids = request.json.get('member_ids', [])
    with _write_lock:
        conn = get_db()
        for i, mid in enumerate(member_ids):
            conn.execute('UPDATE members SET sort_order=? WHERE id=?', (i * 10, int(mid)))
        conn.commit()
        conn.close()
    return jsonify({'success': True})

@app.route('/api/batch-restore', methods=['POST'])
def batch_restore():
    ids = request.json.get('chore_ids', [])
    with _write_lock:
        conn = get_db()
        for cid in ids:
            conn.execute('UPDATE chores SET active=1 WHERE id=?', (int(cid),))
        conn.commit()
        conn.close()
    return jsonify({'success': True})

@app.route('/api/batch-purge', methods=['POST'])
def batch_purge():
    ids = request.json.get('chore_ids', [])
    with _write_lock:
        conn = get_db()
        for cid in ids:
            cid = int(cid)
            conn.execute('DELETE FROM chore_members WHERE chore_id=?', (cid,))
            conn.execute('DELETE FROM daily_claims WHERE task_id=?', (cid,))
            conn.execute('DELETE FROM completions WHERE chore_id=?', (cid,))
            conn.execute('DELETE FROM chores WHERE id=? AND active=0', (cid,))
        conn.commit()
        conn.close()
    return jsonify({'success': True})

@app.route('/api/purge-chore', methods=['POST'])
def purge_chore():
    chore_id = request.json['chore_id']
    with _write_lock:
        conn = get_db()
        conn.execute('DELETE FROM chore_members WHERE chore_id=?', (chore_id,))
        conn.execute('DELETE FROM daily_claims WHERE task_id=?', (chore_id,))
        conn.execute('DELETE FROM completions WHERE chore_id=?', (chore_id,))
        conn.execute('DELETE FROM chores WHERE id=? AND active=0', (chore_id,))
        conn.commit()
        conn.close()
    return jsonify({'success': True})

@app.route('/api/add-extra', methods=['POST'])
def add_extra():
    data        = request.json
    date_str    = data.get('date') or date.today().isoformat()
    member_id   = int(data['member_id'])
    group_id    = data.get('group_id') or None
    description = (data.get('description') or '').strip()
    points      = int(data.get('points') or 0)
    if not description:
        return jsonify({'success': False, 'error': 'Description required'}), 400
    with _write_lock:
        conn = get_db()
        try:
            cur = conn.execute('''
                INSERT INTO daily_extra (date, member_id, group_id, description, points)
                VALUES (?,?,?,?,?)
            ''', (date_str, member_id, group_id, description, points))
            extra_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True, 'extra_id': extra_id})

@app.route('/api/delete-extra', methods=['POST'])
def delete_extra():
    extra_id = request.json['extra_id']
    with _write_lock:
        conn = get_db()
        try:
            conn.execute('DELETE FROM daily_extra WHERE id=?', (extra_id,))
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True})

@app.route('/api/save-chore', methods=['POST'])
def save_chore():
    data            = request.json
    chore_id        = data.get('id')
    name            = (data.get('name') or '').strip()
    icon            = data.get('icon', '📋')
    points          = int(data.get('points') or 0)
    assignment_type = data.get('assignment_type', 'everyone')
    schedule_type   = data.get('schedule_type', 'daily')
    schedule_days   = json.dumps(data.get('schedule_days', []))
    member_ids      = data.get('member_ids', [])
    group_id        = data.get('group_id') or None
    one_time        = 1 if data.get('one_time') else 0

    if not name:
        return jsonify({'success': False, 'error': 'Name required'}), 400

    versioned = False
    with _write_lock:
        conn = get_db()
        try:
            if chore_id:
                old = conn.execute('SELECT * FROM chores WHERE id=?', (chore_id,)).fetchone()
                if old and old['active'] == 1:
                    has_completions = conn.execute(
                        'SELECT 1 FROM completions WHERE chore_id=?', (chore_id,)).fetchone()

                    # Only create a new version when structural fields change:
                    # points, schedule, or assignment type. Name/icon/group edits
                    # are safe to apply in-place so existing claim IDs stay valid.
                    structural_changed = has_completions and (
                        points != int(old['points'] or 0) or
                        assignment_type != (old['assignment_type'] or 'everyone') or
                        schedule_type   != (old['schedule_type']   or 'daily') or
                        schedule_days   != (old['schedule_days']   or '[]')
                    )

                    if structural_changed:
                        # ── Immutable versioning ──
                        # Structural fields changed with existing completions. Deactivate
                        # the old version (completions still JOIN to it) and insert a new one.
                        parent      = old['parent_id'] if old['parent_id'] else old['id']
                        new_version = (old['version'] or 1) + 1
                        conn.execute('UPDATE chores SET active=0 WHERE id=?', (chore_id,))
                        cur = conn.execute('''
                            INSERT INTO chores
                                (name, icon, points, assignment_type, schedule_type,
                                 schedule_days, sort_order, parent_id, version, group_id)
                            VALUES (?,?,?,?,?,?,?,?,?,?)
                        ''', (name, icon, points, assignment_type, schedule_type,
                              schedule_days, old['sort_order'], parent, new_version, group_id))
                        chore_id  = cur.lastrowid
                        versioned = True
                    else:
                        # No structural change (or no completions) — safe to update in-place.
                        conn.execute('''
                            UPDATE chores
                            SET name=?, icon=?, points=?, assignment_type=?,
                                schedule_type=?, schedule_days=?, group_id=?
                            WHERE id=?
                        ''', (name, icon, points, assignment_type,
                              schedule_type, schedule_days, group_id, chore_id))
                        conn.execute('DELETE FROM chore_members WHERE chore_id=?', (chore_id,))
                elif not old:
                    chore_id = None  # Not found — fall through to insert

            if not chore_id or (chore_id and not conn.execute(
                    'SELECT 1 FROM chores WHERE id=?', (chore_id,)).fetchone()):
                cur = conn.execute('''
                    INSERT INTO chores
                        (name, icon, points, assignment_type, schedule_type, schedule_days, group_id, one_time)
                    VALUES (?,?,?,?,?,?,?,?)
                ''', (name, icon, points, assignment_type, schedule_type, schedule_days, group_id, one_time))
                chore_id = cur.lastrowid

            if assignment_type in ('specific', 'rotate'):
                for mid in member_ids:
                    conn.execute(
                        'INSERT OR IGNORE INTO chore_members (chore_id, member_id) VALUES (?,?)',
                        (chore_id, mid))
            conn.commit()
        finally:
            conn.close()

    return jsonify({'success': True, 'chore_id': chore_id, 'versioned': versioned})

@app.route('/api/delete-chore', methods=['POST'])
def delete_chore():
    with _write_lock:
        conn = get_db()
        try:
            conn.execute('UPDATE chores SET active=0 WHERE id=?', (request.json['chore_id'],))
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True})

@app.route('/api/hard-delete-chore', methods=['POST'])
def hard_delete_chore():
    chore_id = request.json['chore_id']
    with _write_lock:
        conn = get_db()
        try:
            conn.execute('DELETE FROM chore_members WHERE chore_id=?', (chore_id,))
            conn.execute('DELETE FROM daily_claims  WHERE task_id=?',  (chore_id,))
            conn.execute('DELETE FROM completions   WHERE chore_id=?', (chore_id,))
            conn.execute('DELETE FROM chores        WHERE id=?',       (chore_id,))
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True})

@app.route('/api/restore-chore', methods=['POST'])
def restore_chore():
    with _write_lock:
        conn = get_db()
        try:
            conn.execute('UPDATE chores SET active=1 WHERE id=?', (request.json['chore_id'],))
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True})

@app.route('/api/add-member', methods=['POST'])
def add_member():
    data = request.json
    with _write_lock:
        conn = get_db()
        try:
            count = conn.execute('SELECT COUNT(*) FROM members').fetchone()[0]
            color = data.get('color', MEMBER_COLORS[count % len(MEMBER_COLORS)])
            conn.execute(
                'INSERT INTO members (name, avatar, color, sort_order) VALUES (?,?,?,?)',
                (data['name'], data.get('avatar', '🙂'), color, count))
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True})

@app.route('/api/update-member', methods=['POST'])
def update_member():
    data = request.json
    with _write_lock:
        conn = get_db()
        try:
            conn.execute(
                'UPDATE members SET name=?, avatar=?, color=? WHERE id=?',
                (data['name'], data.get('avatar', '🙂'), data.get('color', '#007AFF'), data['id']))
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True})

@app.route('/api/delete-member', methods=['POST'])
def delete_member():
    member_id = request.json['member_id']
    with _write_lock:
        conn = get_db()
        try:
            conn.execute('DELETE FROM members WHERE id=?', (member_id,))
            conn.execute('DELETE FROM chore_members WHERE member_id=?', (member_id,))
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True})

@app.route('/api/redeem-reward', methods=['POST'])
def redeem_reward():
    data = request.json
    reward_id = data['reward_id']
    member_id = data['member_id']
    with _write_lock:
        conn = get_db()
        try:
            reward = conn.execute('SELECT * FROM rewards WHERE id=?', (reward_id,)).fetchone()
            if not reward:
                return jsonify({'error': 'Reward not found'})
            current_pts = calc_points(member_id, conn)
            if current_pts < reward['points_cost']:
                return jsonify({'error': 'Not enough points',
                                'have': current_pts, 'need': reward['points_cost']})
            conn.execute(
                'INSERT INTO balance_history (member_id, points_delta, reason) VALUES (?,?,?)',
                (member_id, -reward['points_cost'], f'🎁 Redeemed: {reward["name"]}'))
            conn.execute(
                'INSERT INTO reward_redemptions (member_id, reward_name, points_cost) VALUES (?,?,?)',
                (member_id, reward['name'], reward['points_cost']))
            conn.commit()
            return jsonify({'success': True})
        finally:
            conn.close()

@app.route('/api/undo-redeem', methods=['POST'])
def undo_redeem():
    redemption_id = request.json['redemption_id']
    with _write_lock:
        conn = get_db()
        try:
            rr = conn.execute('SELECT * FROM reward_redemptions WHERE id=?', (redemption_id,)).fetchone()
            if not rr:
                return jsonify({'error': 'Not found'})
            conn.execute(
                'INSERT INTO balance_history (member_id, points_delta, reason) VALUES (?,?,?)',
                (rr['member_id'], rr['points_cost'], f'↩ Undo redeem: {rr["reward_name"]}'))
            conn.execute('DELETE FROM reward_redemptions WHERE id=?', (redemption_id,))
            conn.commit()
            return jsonify({'success': True})
        finally:
            conn.close()

@app.route('/api/mark-taken', methods=['POST'])
def mark_taken():
    redemption_id = request.json['redemption_id']
    with _write_lock:
        conn = get_db()
        try:
            conn.execute(
                "UPDATE reward_redemptions SET taken_at=datetime('now') WHERE id=?",
                (redemption_id,))
            conn.commit()
            return jsonify({'success': True})
        finally:
            conn.close()

@app.route('/api/toggle-taken', methods=['POST'])
def toggle_taken():
    data = request.json
    redemption_id = data['redemption_id']
    taken = data.get('taken', True)
    with _write_lock:
        conn = get_db()
        try:
            if taken:
                conn.execute(
                    "UPDATE reward_redemptions SET taken_at=datetime('now') WHERE id=?",
                    (redemption_id,))
            else:
                conn.execute(
                    'UPDATE reward_redemptions SET taken_at=NULL WHERE id=?',
                    (redemption_id,))
            conn.commit()
            return jsonify({'success': True})
        finally:
            conn.close()

@app.route('/api/add-reward', methods=['POST'])
def add_reward():
    data = request.json
    with _write_lock:
        conn = get_db()
        try:
            conn.execute(
                'INSERT INTO rewards (name, points_cost, description) VALUES (?,?,?)',
                (data['name'], int(data['points_cost']), data.get('description', '')))
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True})

@app.route('/api/delete-reward', methods=['POST'])
def delete_reward():
    with _write_lock:
        conn = get_db()
        try:
            conn.execute('DELETE FROM rewards WHERE id=?', (request.json['reward_id'],))
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True})

@app.route('/api/adjust-balance', methods=['POST'])
def adjust_balance():
    data = request.json
    with _write_lock:
        conn = get_db()
        try:
            conn.execute(
                'INSERT INTO balance_history (member_id, points_delta, reason) VALUES (?,?,?)',
                (data['member_id'], int(data['points_delta']), data.get('reason', '')))
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True})

@app.route('/api/advance-rotate', methods=['POST'])
def advance_rotate():
    chore_id = request.json['chore_id']
    with _write_lock:
        conn = get_db()
        try:
            chore = conn.execute('SELECT * FROM chores WHERE id=?', (chore_id,)).fetchone()
            count = conn.execute(
                'SELECT COUNT(*) FROM chore_members WHERE chore_id=?', (chore_id,)).fetchone()[0]
            if count > 0:
                new_idx = (chore['rotate_current_idx'] + 1) % count
                conn.execute('UPDATE chores SET rotate_current_idx=? WHERE id=?',
                             (new_idx, chore_id))
                conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True})

@app.route('/api/weekly-review')
def weekly_review():
    week_offset = int(request.args.get('week', 0))
    conn = get_db()
    members = [dict(m) for m in conn.execute('SELECT * FROM members ORDER BY sort_order, id')]
    all_member_ids = [m['id'] for m in members]
    chore_rows = conn.execute('SELECT * FROM chores WHERE active=1').fetchall()
    week_dates = get_week_dates(week_offset)
    start_str, end_str = week_dates[0].isoformat(), week_dates[-1].isoformat()
    result = []
    for m in members:
        streak    = calc_streak(m['id'], conn)
        # Points from positive-point tasks (rewards, with half-points for 2nd+ counts per day)
        reward_pts = conn.execute('''
            SELECT COALESCE(SUM(
                CASE WHEN dc.completed_count <= 1 THEN c.points
                     ELSE c.points + (dc.completed_count - 1) * (c.points / 2)
                END
            ), 0)
            FROM daily_claims dc
            JOIN chores c ON dc.task_id = c.id
            WHERE dc.member_id=? AND dc.date>=? AND dc.date<=?
              AND dc.completed_count > 0 AND c.active = 1 AND c.points > 0
        ''', (m['id'], start_str, end_str)).fetchone()[0] or 0
        # Points (negative) from penalty tasks, with half-points for 2nd+ counts per day
        penalty_rows = conn.execute('''
            SELECT c.name, c.icon, c.points,
                   SUM(dc.completed_count) AS total_count,
                   SUM(CASE WHEN dc.completed_count <= 1 THEN c.points
                            ELSE c.points + (dc.completed_count - 1) * (c.points / 2)
                       END) AS total_pts
            FROM daily_claims dc
            JOIN chores c ON dc.task_id = c.id
            WHERE dc.member_id=? AND dc.date>=? AND dc.date<=?
              AND dc.completed_count > 0 AND c.active=1 AND c.points < 0
            GROUP BY c.id, c.name, c.icon, c.points
            ORDER BY c.points ASC
        ''', (m['id'], start_str, end_str)).fetchall()
        penalty_pts = sum(r['total_pts'] for r in penalty_rows)
        penalty_items = [{'name': r['name'], 'icon': r['icon'],
                          'points': r['points'], 'count': r['total_count']}
                         for r in penalty_rows]
        extra_pts = conn.execute('''
            SELECT COALESCE(SUM(points),0) FROM daily_extra
            WHERE member_id=? AND date>=? AND date<=?
        ''', (m['id'], start_str, end_str)).fetchone()[0] or 0
        adj_pts   = conn.execute('''
            SELECT COALESCE(SUM(points_delta),0) FROM balance_history
            WHERE member_id=? AND created_at>=? AND created_at<=?
        ''', (m['id'], start_str + 'T00:00:00', end_str + 'T23:59:59')).fetchone()[0] or 0
        pts_week  = reward_pts + penalty_pts + extra_pts + adj_pts
        # comp_count and total_due count only non-penalty tasks
        comp_count = conn.execute('''
            SELECT COUNT(*) FROM daily_claims dc
            JOIN chores c ON dc.task_id = c.id
            WHERE dc.member_id=? AND dc.date>=? AND dc.date<=?
              AND dc.completed_count > 0 AND c.active=1 AND (c.points IS NULL OR c.points >= 0)
        ''', (m['id'], start_str, end_str)).fetchone()[0]
        total_due = sum(
            1 for c in chore_rows for d in week_dates
            if (c['points'] or 0) >= 0
            and m['id'] in get_assigned_member_ids(c, all_member_ids, conn)
            and is_chore_due(c, d)
        )
        best = conn.execute('''
            SELECT c.name, c.icon, SUM(dc.completed_count) AS cnt FROM daily_claims dc
            JOIN chores c ON dc.task_id=c.id
            WHERE dc.member_id=? AND dc.date>=? AND dc.date<=?
              AND dc.completed_count > 0 AND c.active=1 AND (c.points IS NULL OR c.points >= 0)
            GROUP BY dc.task_id ORDER BY cnt DESC LIMIT 1
        ''', (m['id'], start_str, end_str)).fetchone()
        # 84-day heatmap (12 weeks)
        heat_start = week_dates[-1] - timedelta(days=83)
        heat_rows  = conn.execute(
            'SELECT date, COUNT(*) as cnt FROM daily_claims WHERE member_id=? AND date>=? AND completed_count>0 GROUP BY date',
            (m['id'], heat_start.isoformat())).fetchall()
        heat_counts = {r['date']: r['cnt'] for r in heat_rows}
        heatmap = [{'date': (heat_start + timedelta(days=i)).isoformat(),
                    'count': heat_counts.get((heat_start + timedelta(days=i)).isoformat(), 0)}
                   for i in range(84)]
        result.append({
            'id': m['id'], 'name': m['name'], 'avatar': m['avatar'], 'color': m['color'],
            'streak': streak, 'pts_week': pts_week,
            'reward_pts': reward_pts, 'penalty_pts': penalty_pts,
            'penalty_items': penalty_items,
            'comp_count': comp_count, 'total_due': total_due,
            'pct': round(comp_count * 100 / total_due) if total_due else 0,
            'best_chore': {'name': best['name'], 'icon': best['icon']} if best else None,
            'badges': calc_badges(streak),
            'heatmap': heatmap,
        })
    conn.close()
    return jsonify({'members': result})

# ---------------------------------------------------------------------------
# Admin API actions
# ---------------------------------------------------------------------------

@app.route('/api/admin/vacuum', methods=['POST'])
def admin_vacuum():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute('VACUUM')
        conn.close()
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    new_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    return jsonify({'success': True, 'new_size': format_bytes(new_size)})

@app.route('/api/admin/export')
def admin_export():
    conn = get_db()
    export = {}
    for table in ['members', 'chores', 'completions', 'rewards', 'balance_history', 'app_settings']:
        rows = conn.execute(f'SELECT * FROM {table}').fetchall()
        export[table] = [dict(r) for r in rows]
    conn.close()
    return Response(
        json.dumps(export, indent=2, default=str),
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment; filename=taskchart-backup.json'}
    )

@app.route('/api/admin/integrity-check')
def admin_integrity_check():
    conn = get_db()
    issues = []
    orphan_member = conn.execute('''
        SELECT COUNT(*) FROM completions cp
        WHERE NOT EXISTS (SELECT 1 FROM members m WHERE m.id = cp.member_id)
    ''').fetchone()[0]
    if orphan_member:
        issues.append(f'{orphan_member} completion(s) reference deleted members')

    orphan_chore = conn.execute('''
        SELECT COUNT(*) FROM completions cp
        WHERE NOT EXISTS (SELECT 1 FROM chores c WHERE c.id = cp.chore_id)
    ''').fetchone()[0]
    if orphan_chore:
        issues.append(f'{orphan_chore} completion(s) reference non-existent chores')

    orphan_cm_chore = conn.execute('''
        SELECT COUNT(*) FROM chore_members cm
        WHERE NOT EXISTS (SELECT 1 FROM chores c WHERE c.id = cm.chore_id)
    ''').fetchone()[0]
    if orphan_cm_chore:
        issues.append(f'{orphan_cm_chore} chore_members row(s) reference non-existent chores')

    orphan_cm_member = conn.execute('''
        SELECT COUNT(*) FROM chore_members cm
        WHERE NOT EXISTS (SELECT 1 FROM members m WHERE m.id = cm.member_id)
    ''').fetchone()[0]
    if orphan_cm_member:
        issues.append(f'{orphan_cm_member} chore_members row(s) reference deleted members')

    conn.close()
    return jsonify({'issues': issues, 'ok': len(issues) == 0})

@app.route('/api/admin/purge-completions', methods=['POST'])
def admin_purge_completions():
    days = int(request.json.get('days', 365))
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with _write_lock:
        conn = get_db()
        try:
            deleted = conn.execute(
                'DELETE FROM completions WHERE date < ?', (cutoff,)).rowcount
            conn.commit()
        finally:
            conn.close()
    return jsonify({'success': True, 'deleted': deleted})

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5008))
    debug = os.environ.get('FLASK_ENV') != 'production'
    app.run(debug=debug, port=port, host='0.0.0.0')
