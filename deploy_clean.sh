#!/bin/bash

# Clean Deployment Script for PythonAnywhere
# This script ensures only the correct files exist in their correct locations

set -e  # Exit on any error

echo "🧹 Creating clean deployment package for PythonAnywhere..."

# Load deployment manifest
MANIFEST_FILE="deployment_manifest.json"
if [ ! -f "$MANIFEST_FILE" ]; then
    echo "❌ Error: deployment_manifest.json not found"
    exit 1
fi

# Create deployment directory
DEPLOY_DIR="deploy_temp"
rm -rf $DEPLOY_DIR
mkdir -p $DEPLOY_DIR

echo "📋 Using deployment manifest to copy files..."

# Copy root files
echo "📄 Copying root files..."
ROOT_FILES=(
    "app.py"
    "main.py"
    "wsgi.py"
    "requirements.txt"
    "pythonanywhere_daily_hook.py"
    "pythonanywhere_daily_hook_server.py"
    "version.py"
    "__init__.py"
    "README.md"
)

for file in "${ROOT_FILES[@]}"; do
    if [ -f "$file" ]; then
        cp "$file" "$DEPLOY_DIR/"
        echo "   ✅ $file"
    else
        echo "   ❌ MISSING: $file"
    fi
done

# Copy directories with their expected files
echo "📁 Copying application directories..."
DIRECTORIES=(
    "analysis"
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
)

for dir in "${DIRECTORIES[@]}"; do
    if [ -d "$dir" ]; then
        echo "   📁 Copying $dir/"
        mkdir -p "$DEPLOY_DIR/$dir"
        cp -r "$dir"/* "$DEPLOY_DIR/$dir/" 2>/dev/null || true
        
        # Verify critical files exist
        case "$dir" in
            "market_data")
                if [ -f "$DEPLOY_DIR/$dir/market_data.py" ]; then
                    if grep -q "Merged data:" "$DEPLOY_DIR/$dir/market_data.py"; then
                        echo "      ✅ Verified simplified cache logic in market_data.py"
                    else
                        echo "      ❌ WARNING: Simplified cache logic NOT found in market_data.py"
                    fi
                else
                    echo "      ❌ MISSING: market_data.py"
                fi
                ;;
            "templates")
                if [ -f "$DEPLOY_DIR/$dir/index.html" ]; then
                    echo "      ✅ Templates directory complete"
                else
                    echo "      ❌ MISSING: index.html in templates"
                fi
                ;;
        esac
    else
        echo "   ❌ MISSING DIRECTORY: $dir"
    fi
done

# Create comprehensive server deployment script
cat > "$DEPLOY_DIR/deploy_server.sh" << 'EOF'
#!/bin/bash
echo "🚀 Deploying stocks application on PythonAnywhere server..."
echo "🧹 This script ensures ONLY the correct files exist in their correct locations"

# Define target application directory
APP_DIR="/home/ferrous77/stocks"
echo "📍 Target application directory: $APP_DIR"

# Create backup of existing installation
if [ -d "$APP_DIR" ] && [ "$(ls -A $APP_DIR 2>/dev/null)" ]; then
    echo "📦 Creating backup of existing installation..."
    BACKUP_FILE="~/stocks-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
    tar -czf "$BACKUP_FILE" "$APP_DIR/" 2>/dev/null
    echo "✅ Backup created: $BACKUP_FILE"
else
    echo "ℹ️  No existing installation found to backup"
fi

# Ensure target directory exists and is clean
echo "🧹 Preparing clean target directory..."
mkdir -p "$APP_DIR"

# Define expected file structure
declare -A EXPECTED_FILES
EXPECTED_FILES["app.py"]="$APP_DIR/app.py"
EXPECTED_FILES["main.py"]="$APP_DIR/main.py"
EXPECTED_FILES["wsgi.py"]="$APP_DIR/wsgi.py"
EXPECTED_FILES["requirements.txt"]="$APP_DIR/requirements.txt"
EXPECTED_FILES["pythonanywhere_daily_hook.py"]="$APP_DIR/pythonanywhere_daily_hook.py"
EXPECTED_FILES["pythonanywhere_daily_hook_server.py"]="$APP_DIR/pythonanywhere_daily_hook_server.py"
EXPECTED_FILES["version.py"]="$APP_DIR/version.py"
EXPECTED_FILES["__init__.py"]="$APP_DIR/__init__.py"
EXPECTED_FILES["README.md"]="$APP_DIR/README.md"

EXPECTED_DIRS=(
    "analysis"
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
)

# Step 1: Deploy new files to correct locations
echo "📂 Deploying files to correct locations..."
for file in "${!EXPECTED_FILES[@]}"; do
    if [ -f "$file" ]; then
        cp -f "$file" "${EXPECTED_FILES[$file]}"
        echo "   ✅ Deployed $file"
    else
        echo "   ❌ MISSING: $file"
    fi
done

# Deploy directories
for dir in "${EXPECTED_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        echo "   📁 Deploying $dir/"
        rm -rf "$APP_DIR/$dir"  # Remove old version completely
        cp -r "$dir" "$APP_DIR/"
        echo "   ✅ Deployed $dir/"
    else
        echo "   ❌ MISSING DIRECTORY: $dir"
    fi
done

# Step 2: Scan for and remove duplicate files
echo "🔍 Scanning for duplicate files that shouldn't exist..."

# Critical files that should only exist in one location
CRITICAL_FILES=(
    "market_data.py"
    "app.py"
    "main.py"
    "wsgi.py"
    "pythonanywhere_daily_hook.py"
)

for critical_file in "${CRITICAL_FILES[@]}"; do
    echo "   🔍 Checking for duplicates of $critical_file..."
    
    # Find all instances of this file
    duplicates_found=false
    while IFS= read -r -d '' file_path; do
        # Determine the expected location for this file
        case "$critical_file" in
            "market_data.py")
                expected_path="$APP_DIR/market_data/market_data.py"
                ;;
            *)
                expected_path="$APP_DIR/$critical_file"
                ;;
        esac
        
        # If this file is not in the expected location, remove it
        if [[ "$file_path" != "$expected_path" ]]; then
            echo "   ❌ Removing duplicate: $file_path"
            rm -f "$file_path"
            duplicates_found=true
        fi
    done < <(find /home/ferrous77 -name "$critical_file" -type f -print0 2>/dev/null)
    
    if [ "$duplicates_found" = false ]; then
        echo "   ✅ No duplicates found for $critical_file"
    fi
done

# Step 3: Remove empty directories
echo "🧹 Removing empty directories..."
find /home/ferrous77 -type d -empty -not -path "$APP_DIR*" -print0 2>/dev/null | while IFS= read -r -d '' empty_dir; do
    echo "   📁 Removing empty directory: $empty_dir"
    rmdir "$empty_dir" 2>/dev/null || true
done

# Step 4: Clear Python bytecode cache
echo "🧹 Clearing Python bytecode cache..."
find "$APP_DIR" -name "*.pyc" -delete 2>/dev/null || true
find "$APP_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Step 5: Verify critical files are in place and correct
echo "🔍 Verifying deployment..."
VERIFICATION_FAILED=false

# Check that expected files exist
for file in "${!EXPECTED_FILES[@]}"; do
    expected_path="${EXPECTED_FILES[$file]}"
    if [ -f "$expected_path" ]; then
        echo "   ✅ $expected_path exists"
    else
        echo "   ❌ MISSING: $expected_path"
        VERIFICATION_FAILED=true
    fi
done

# Special verification for market_data.py
MARKET_DATA_FILE="$APP_DIR/market_data/market_data.py"
if [ -f "$MARKET_DATA_FILE" ]; then
    if grep -q "Merged data:" "$MARKET_DATA_FILE"; then
        echo "   ✅ Simplified cache logic verified in market_data.py"
    else
        echo "   ❌ WARNING: Simplified cache logic NOT found in market_data.py"
        echo "   🔍 Cache messages found:"
        grep -n "CACHE WRITE\|Merged data\|FULL CACHE" "$MARKET_DATA_FILE" || echo "   No cache messages found"
        VERIFICATION_FAILED=true
    fi
else
    echo "   ❌ CRITICAL: market_data.py missing from $APP_DIR/market_data/"
    VERIFICATION_FAILED=true
fi

# Final status
if [ "$VERIFICATION_FAILED" = true ]; then
    echo "❌ DEPLOYMENT VERIFICATION FAILED"
    echo "   Please check the errors above before proceeding"
    exit 1
else
    echo "✅ DEPLOYMENT SUCCESSFUL"
    echo ""
    echo "📍 Application deployed to: $APP_DIR"
    echo "🗂️  All duplicate files removed"
    echo "🧹 Empty directories cleaned up"
    echo "🐍 Python cache cleared"
    echo ""
    echo "🌐 NEXT STEPS:"
    echo "   1. Go to PythonAnywhere Web Dashboard"
    echo "   2. Go to Web tab"
    echo "   3. Click 'Reload' button"
    echo "   4. Test deployment: https://ferrous77.pythonanywhere.com/"
fi
EOF

chmod +x "$DEPLOY_DIR/deploy_server.sh"

# Create deployment package
echo "📦 Creating deployment archive..."
tar -czf stocks-app-clean.tar.gz -C "$DEPLOY_DIR" .

# Cleanup
echo "🧹 Cleaning up temporary files..."
rm -rf "$DEPLOY_DIR"

echo "✅ Clean deployment package created: stocks-app-clean.tar.gz"
echo ""
echo "📋 DEPLOYMENT SUMMARY:"
echo "   📦 Package: stocks-app-clean.tar.gz"
echo "   🧹 Only correct files included"
echo "   🔍 Duplicate detection enabled"
echo "   📍 Target location: /home/ferrous77/stocks"
echo ""
echo "📤 UPLOAD INSTRUCTIONS:"
echo "   1. Upload stocks-app-clean.tar.gz to PythonAnywhere"
echo "   2. Extract: tar -xzf stocks-app-clean.tar.gz"
echo "   3. Run: ./deploy_server.sh"
echo "   4. Reload web app in dashboard"
