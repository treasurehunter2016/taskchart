# ── Detect OS ────────────────────────────────────────────────────────────────
OS      := $(shell uname -s)
PYTHON  := python3
VENV    := .venv
PIP     := $(VENV)/bin/pip
VENV_PY := $(VENV)/bin/python3
APP_DIR := $(abspath .)
LOG_DIR := $(APP_DIR)/logs

# macOS — launchd
PLIST_LABEL := com.taskchart
PLIST_PATH  := $(HOME)/Library/LaunchAgents/$(PLIST_LABEL).plist

# Linux — systemd user session
SYSTEMD_DIR  := $(HOME)/.config/systemd/user
SYSTEMD_UNIT := taskchart.service

# ── Plist template (macOS) ───────────────────────────────────────────────────
define PLIST_CONTENT
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>             <string>$(PLIST_LABEL)</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(APP_DIR)/$(VENV_PY)</string>
    <string>$(APP_DIR)/app.py</string>
  </array>
  <key>WorkingDirectory</key>  <string>$(APP_DIR)</string>
  <key>RunAtLoad</key>         <true/>
  <key>KeepAlive</key>         <true/>
  <key>StandardOutPath</key>   <string>$(LOG_DIR)/taskchart.log</string>
  <key>StandardErrorPath</key> <string>$(LOG_DIR)/taskchart.err</string>
</dict>
</plist>
endef
export PLIST_CONTENT

# ── Systemd unit template (Linux) ────────────────────────────────────────────
define SYSTEMD_CONTENT
[Unit]
Description=TaskChart Family Chore Tracker
After=network.target

[Service]
Type=simple
WorkingDirectory=$(APP_DIR)
ExecStart=$(APP_DIR)/$(VENV_PY) $(APP_DIR)/app.py
Restart=on-failure
RestartSec=5
StandardOutput=append:$(LOG_DIR)/taskchart.log
StandardError=append:$(LOG_DIR)/taskchart.err

[Install]
WantedBy=default.target
endef
export SYSTEMD_CONTENT

# ─────────────────────────────────────────────────────────────────────────────
.PHONY: build init install uninstall help

.DEFAULT_GOAL := help

help:
	@printf '\033[1mTaskChart — available targets\033[0m\n\n'
	@printf '  \033[36m%-12s\033[0m %s\n' build     'Create .venv and install Python dependencies'
	@printf '  \033[36m%-12s\033[0m %s\n' init      'Initialize an empty chores.db (safe: skips if file exists)'
	@printf '  \033[36m%-12s\033[0m %s\n' install   'Deploy TaskChart as a managed background service'
	@printf '  \033[36m%-12s\033[0m %s\n' uninstall 'Stop and remove the background service'
	@echo ''

# ── build ─────────────────────────────────────────────────────────────────────
build:
	@echo "→ Creating virtual environment in $(VENV)/ ..."
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip --quiet
	$(PIP) install -r requirements.txt
	@echo "✓ Build complete."
	@echo "  Run manually: $(VENV_PY) app.py"

# ── init ──────────────────────────────────────────────────────────────────────
init: _ensure_venv
	@if [ -f chores.db ]; then \
		echo "✓ chores.db already exists — skipping init."; \
		echo "  Delete chores.db first if you want a fresh database."; \
	else \
		echo "→ Initializing empty database..."; \
		$(VENV_PY) -c "from app import init_db; init_db()"; \
		echo "✓ chores.db created with schema v$$($(VENV_PY) -c \
		  'import sqlite3; c=sqlite3.connect("chores.db"); \
		   print(c.execute("SELECT version FROM schema_version").fetchone()[0])')"; \
	fi

# ── install ───────────────────────────────────────────────────────────────────
install: _ensure_venv _ensure_db
	@mkdir -p $(LOG_DIR)
ifeq ($(OS),Darwin)
	@echo "→ Installing launchd service: $(PLIST_LABEL)"
	@echo "$$PLIST_CONTENT" > $(PLIST_PATH)
	@launchctl unload $(PLIST_PATH) 2>/dev/null || true
	@launchctl load -w $(PLIST_PATH)
	@echo "✓ Service installed and started on port 5008."
	@echo "  Logs:      tail -f $(LOG_DIR)/taskchart.log"
	@echo "  Stop:      launchctl unload $(PLIST_PATH)"
	@echo "  Uninstall: make uninstall"
else
	@echo "→ Installing systemd user service: $(SYSTEMD_UNIT)"
	@mkdir -p $(SYSTEMD_DIR) $(LOG_DIR)
	@echo "$$SYSTEMD_CONTENT" > $(SYSTEMD_DIR)/$(SYSTEMD_UNIT)
	@systemctl --user daemon-reload
	@systemctl --user enable --now $(SYSTEMD_UNIT)
	@echo "✓ Service enabled and started on port 5008."
	@echo "  Logs:      journalctl --user -u $(SYSTEMD_UNIT) -f"
	@echo "  Status:    systemctl --user status $(SYSTEMD_UNIT)"
	@echo "  Uninstall: make uninstall"
endif

# ── uninstall ─────────────────────────────────────────────────────────────────
uninstall:
ifeq ($(OS),Darwin)
	@launchctl unload $(PLIST_PATH) 2>/dev/null && echo "✓ Service stopped." || echo "  (service was not running)"
	@rm -f $(PLIST_PATH) && echo "✓ Plist removed: $(PLIST_PATH)"
else
	@systemctl --user disable --now $(SYSTEMD_UNIT) 2>/dev/null \
	  && echo "✓ Service stopped and disabled." || true
	@rm -f $(SYSTEMD_DIR)/$(SYSTEMD_UNIT)
	@systemctl --user daemon-reload
	@echo "✓ Unit file removed: $(SYSTEMD_DIR)/$(SYSTEMD_UNIT)"
endif

# ── internal helpers ──────────────────────────────────────────────────────────
_ensure_venv:
	@if [ ! -f "$(VENV_PY)" ]; then \
		echo "Error: virtualenv not found. Run 'make build' first."; \
		exit 1; \
	fi

_ensure_db:
	@if [ ! -f chores.db ]; then \
		echo "→ No chores.db found — initializing empty database first..."; \
		$(VENV_PY) -c "from app import init_db; init_db()"; \
	fi
