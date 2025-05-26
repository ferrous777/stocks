#!/bin/bash

# PythonAnywhere Deployment Script
# This script creates a deployment package for uploading to PythonAnywhere

set -e  # Exit on any error

echo "📦 Creating deployment package for PythonAnywhere..."

# Create deployment directory
DEPLOY_DIR="deploy_temp"
rm -rf $DEPLOY_DIR
mkdir -p $DEPLOY_DIR

echo "📂 Copying application files..."

# Copy core application directories
CORE_DIRS=(
    "analysis"
    "cache" 
    "config"
    "market_calendar"
    "market_data"
    "recommendations"
    "scheduler"
    "static"
    "storage"
    "strategies"
    "templates"
    "utils"
    "docs"
)

for dir in "${CORE_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        cp -r "$dir/" $DEPLOY_DIR/ 2>/dev/null || true
        echo "   ✅ Copied $dir/"
    fi
done

# Copy main application files
CORE_FILES=(
    "app.py"
    "main.py"
    "pythonanywhere_daily_hook.py"
    "pythonanywhere_daily_hook_server.py"
    "requirements.txt"
    "wsgi.py"
    "version.py"
    "__init__.py"
    "README.md"
)

for file in "${CORE_FILES[@]}"; do
    if [ -f "$file" ]; then
        cp "$file" $DEPLOY_DIR/ 2>/dev/null || true
        echo "   ✅ Copied $file"
    fi
done

# Create server deployment script
cat > $DEPLOY_DIR/deploy_server.sh << 'EOF'
#!/bin/bash
echo "🚀 Deploying stocks application on PythonAnywhere server..."

# Define target application directory
APP_DIR="/home/ferrous77/stocks"
echo "📍 Target application directory: $APP_DIR"

# Create backup of existing installation
if [ -d "$APP_DIR" ] && [ "$(ls -A $APP_DIR 2>/dev/null)" ]; then
    echo "📦 Creating backup of existing installation..."
    tar -czf ~/stocks-backup-$(date +%Y%m%d-%H%M).tar.gz "$APP_DIR/" 2>/dev/null
    echo "✅ Backup created: ~/stocks-backup-$(date +%Y%m%d-%H%M).tar.gz"
else
    echo "ℹ️  No existing installation found to backup"
fi

# Ensure target directory exists
echo "📂 Ensuring target directory exists..."
mkdir -p "$APP_DIR"

# Define files and directories to deploy
DEPLOY_DIRS=(
    "analysis"
    "cache" 
    "config"
    "market_calendar"
    "market_data"
    "recommendations"
    "scheduler"
    "static"
    "storage"
    "strategies"
    "templates"
    "utils"
    "docs"
)

DEPLOY_FILES=(
    "app.py"
    "main.py"
    "pythonanywhere_daily_hook.py"
    "pythonanywhere_daily_hook_server.py"
    "requirements.txt"
    "wsgi.py"
    "version.py"
    "__init__.py"
    "README.md"
)

# Deploy directories
echo "📁 Deploying directories..."
for dir in "${DEPLOY_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        echo "   📁 Copying $dir/ -> $APP_DIR/$dir/"
        cp -rf "$dir" "$APP_DIR/"
    else
        echo "   ⚠️  Directory $dir not found in deployment package"
    fi
done

# Deploy files
echo "📄 Deploying files..."
for file in "${DEPLOY_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "   📄 Copying $file -> $APP_DIR/$file"
        cp -f "$file" "$APP_DIR/"
    else
        echo "   ⚠️  File $file not found in deployment package"
    fi
done

# Clear Python bytecode cache
echo "🧹 Clearing Python bytecode cache..."
find "$APP_DIR" -name "*.pyc" -delete 2>/dev/null || true
find "$APP_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
echo "✅ Python cache cleared"

# Find and remove duplicate files in unknown locations
echo "🔍 Scanning for duplicate files..."
DEPLOYED_PYTHON_FILES=(
    "market_data/market_data.py"
    "app.py"
    "pythonanywhere_daily_hook.py"
    "main.py"
    "wsgi.py"
)

for file in "${DEPLOYED_PYTHON_FILES[@]}"; do
    echo "   🔍 Checking for duplicates of $file..."
    # Find all copies of this file
    while IFS= read -r -d '' duplicate; do
        # Skip the correct location
        if [[ "$duplicate" != "$APP_DIR/$file" ]]; then
            echo "   ❌ Removing duplicate: $duplicate"
            rm -f "$duplicate"
        fi
    done < <(find /home/ferrous77 -name "$(basename "$file")" -type f -print0 2>/dev/null)
done

# Remove empty directories
echo "🧹 Removing empty directories..."
# Find empty directories, excluding the target app directory and its subdirectories
while IFS= read -r -d '' empty_dir; do
    # Skip if it's within our target app directory
    if [[ "$empty_dir" != "$APP_DIR"* ]]; then
        echo "   📁 Removing empty directory: $empty_dir"
        rmdir "$empty_dir" 2>/dev/null || true
    fi
done < <(find /home/ferrous77 -type d -empty -print0 2>/dev/null)

# Verify critical files were deployed correctly
echo "🔍 Verifying deployment..."
CRITICAL_FILES=(
    "$APP_DIR/market_data/market_data.py"
    "$APP_DIR/app.py"
    "$APP_DIR/pythonanywhere_daily_hook.py"
)

for file in "${CRITICAL_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "   ✅ $file exists"
        # Check for simplified cache logic in market_data.py
        if [[ "$file" == *"market_data.py" ]]; then
            if grep -q "Merged data:" "$file"; then
                echo "   ✅ Simplified cache logic found in market_data.py"
            else
                echo "   ❌ WARNING: Simplified cache logic NOT found in market_data.py"
                echo "   🔍 Found cache messages:"
                grep -n "CACHE WRITE\|Merged data" "$file" || echo "   No cache messages found"
            fi
        fi
    else
        echo "   ❌ MISSING: $file"
    fi
done

echo "✅ Deployment completed!"
echo ""
echo "📍 Application deployed to: $APP_DIR"
echo "🗂️  All duplicate files removed from other locations"
echo "🧹 Empty directories cleaned up"
echo ""
echo "🌐 NEXT STEPS:"
echo "   1. Go to PythonAnywhere Web Dashboard"
echo "   2. Go to Web tab"
echo "   3. Click 'Reload' button"
echo "   4. Wait for reload to complete"
echo ""
echo "🔗 Test deployment:"
echo "   https://ferrous77.pythonanywhere.com/"
EOF

chmod +x $DEPLOY_DIR/deploy_server.sh

echo "📦 Creating deployment archive..."
tar -czf stocks-app.tar.gz -C $DEPLOY_DIR .

echo "🧹 Cleaning up temporary files..."
rm -rf $DEPLOY_DIR

echo "✅ Deployment package created: stocks-app.tar.gz"
echo "📤 Ready for upload to PythonAnywhere"