#!/bin/bash
# Deploy script for PythonAnywhere
# Uploads app code to /home/ferrous77/ via rsync.
# Preserves runtime data; only Python source is uploaded from performance/.
set -euo pipefail
cd "$(dirname "$0")"

REMOTE="ferrous77@ssh.pythonanywhere.com"
WSGI_FILE="/var/www/ferrous77_pythonanywhere_com_wsgi.py"

echo "Deploying to PythonAnywhere..."

echo "Uploading root files..."
rsync -az app.py main.py wsgi.py requirements.txt version.py __init__.py "$REMOTE:~/"

echo "Uploading hook scripts..."
rsync -az scripts/pythonanywhere_daily_hook.py scripts/pythonanywhere_daily_hook_server.py "$REMOTE:~/"

echo "Uploading application directories..."
rsync -az --exclude="__pycache__" --exclude="*.pyc" \
  alerts analysis config market_calendar market_data plaid_integration recommendations \
  scheduler static storage strategies templates time_estimation utils \
  "$REMOTE:~/"

echo "Uploading performance modules (preserving runtime data)..."
rsync -az --include="*/" --include="*.py" --exclude="*" performance "$REMOTE:~/"

echo "Verifying WSGI config..."
ssh "$REMOTE" 'bash -s' <<'REMOTE_SCRIPT'
set -euo pipefail
wsgi_file=/var/www/ferrous77_pythonanywhere_com_wsgi.py
if [ -f "$wsgi_file" ]; then
    cp -p "$wsgi_file" "$wsgi_file.backup.$(date +%Y%m%d%H%M%S)"
fi
cat > "$wsgi_file" <<'WSGI'
import sys
import os
project_home = "/home/ferrous77"
if project_home not in sys.path:
    sys.path.insert(0, project_home)
os.chdir(project_home)
os.environ["FLASK_ENV"] = "production"
from app import app as application
WSGI
REMOTE_SCRIPT

echo "Reloading web app..."
ssh "$REMOTE" "touch $WSGI_FILE"

echo ""
echo "Deploy complete: https://ferrous77.pythonanywhere.com/"
