# TaskChart — Configuration Template
# Copy this file to config.py and adjust for your environment.
# config.py is gitignored and never committed.

import os

# ── Server ──────────────────────────────────────────────────────────────────
HOST = '0.0.0.0'       # Bind to all interfaces (LAN-accessible)
PORT = 5008
DEBUG = False          # Set True only in local dev

# ── Database ─────────────────────────────────────────────────────────────────
# Default: chores.db next to app.py
# Override with an absolute path for production (e.g. a dedicated data volume):
# DB_PATH = '/var/data/taskchart/chores.db'
DB_PATH = os.path.join(os.path.dirname(__file__), 'chores.db')

# ── Secret key (used by Flask session signing if sessions are added later) ──
SECRET_KEY = 'change-me-before-production'

# ── Production deployment example (gunicorn) ─────────────────────────────────
# gunicorn -w 1 -b 0.0.0.0:5008 --timeout 30 app:app
#
# NOTE: use 1 worker only — the in-process threading.Lock requires a single
# process. If you need multiple workers in future, replace threading.Lock with
# a Redis-backed lock or switch to PostgreSQL + row-level locking.
