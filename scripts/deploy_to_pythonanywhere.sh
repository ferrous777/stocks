#!/bin/bash
# Build an offline code-only package for the home-directory deployment.
set -euo pipefail
cd "$(dirname "$0")/.."

DEPLOY_DIR=$(mktemp -d)
trap 'rm -rf "$DEPLOY_DIR"' EXIT

rsync -a app.py main.py wsgi.py requirements.txt version.py __init__.py "$DEPLOY_DIR/"
rsync -a scripts/pythonanywhere_daily_hook.py scripts/pythonanywhere_daily_hook_server.py "$DEPLOY_DIR/"
rsync -a --exclude="__pycache__" --exclude="*.pyc" \
    alerts analysis config market_calendar market_data plaid_integration recommendations \
    scheduler storage strategies templates time_estimation utils "$DEPLOY_DIR/"
if [ -d static ]; then
    rsync -a static "$DEPLOY_DIR/"
fi
rsync -a --include="*/" --include="*.py" --exclude="*" performance "$DEPLOY_DIR/"

cat > "$DEPLOY_DIR/deploy_server.sh" <<'SERVER_SCRIPT'
#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
APP_DIR="/home/ferrous77"

# Extract into a separate staging directory, then copy only packaged code.
if [ "$PWD" = "$APP_DIR" ]; then
    echo "Extract the package into a separate staging directory before deploying." >&2
    exit 1
fi
mkdir -p "$APP_DIR"
rsync -a app.py main.py wsgi.py requirements.txt version.py __init__.py \
    pythonanywhere_daily_hook.py pythonanywhere_daily_hook_server.py "$APP_DIR/"
rsync -a --exclude="__pycache__" --exclude="*.pyc" \
    alerts analysis config market_calendar market_data plaid_integration recommendations \
    scheduler storage strategies templates time_estimation utils "$APP_DIR/"
if [ -d static ]; then
    rsync -a static "$APP_DIR/"
fi
rsync -a --include="*/" --include="*.py" --exclude="*" performance "$APP_DIR/"

echo "Code deployed to $APP_DIR. Install requirements and reload the web app in the Web tab."
SERVER_SCRIPT

chmod +x "$DEPLOY_DIR/deploy_server.sh"
tar -czf stocks-app.tar.gz -C "$DEPLOY_DIR" .
echo "Created stocks-app.tar.gz. Extract into a staging directory, then run bash deploy_server.sh."
