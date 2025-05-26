#!/bin/bash

# PythonAnywhere Deployment Script
# This script creates a clean deployment package excluding development files

DEPLOY_DIR="deploy-package"
EXCLUDE_FILE=".deployignore"

echo "Creating deployment package for PythonAnywhere..."

# Clean up previous deployment package
if [ -d "$DEPLOY_DIR" ]; then
    rm -rf "$DEPLOY_DIR"
fi

# Create deployment directory
mkdir "$DEPLOY_DIR"

# Copy essential files while respecting .deployignore
rsync -av --exclude-from="$EXCLUDE_FILE" . "$DEPLOY_DIR/" --exclude="$DEPLOY_DIR"

echo "Deployment package created in $DEPLOY_DIR/"
echo ""
echo "Essential files for PythonAnywhere:"
find "$DEPLOY_DIR" -type f -name "*.py" -o -name "*.html" -o -name "*.txt" -o -name "*.yaml" -o -name "*.yml" -o -name "*.json" | sort

echo ""
echo "Creating deployment archive..."

# Create the deployment archive with macOS-compatible options
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS - use options to avoid extended attribute warnings
    tar --disable-copyfile --exclude='._*' -czf stocks-app.tar.gz -C "$DEPLOY_DIR" .
    echo "✅ Created stocks-app.tar.gz (macOS optimized)"
else
    # Linux/other systems - use standard options
    tar -czf stocks-app.tar.gz -C "$DEPLOY_DIR" .
    echo "✅ Created stocks-app.tar.gz"
fi

# Show archive size
if [ -f "stocks-app.tar.gz" ]; then
    SIZE=$(ls -lh stocks-app.tar.gz | awk '{print $5}')
    echo "📦 Archive size: $SIZE"
fi

echo ""
echo "🚀 Ready for PythonAnywhere deployment:"
echo "1. Upload stocks-app.tar.gz to PythonAnywhere Files tab"
echo "2. In PythonAnywhere console, navigate to your web app directory"
echo "3. Extract with: tar -xzf stocks-app.tar.gz"
echo "4. Install dependencies: pip3.10 install --user -r requirements.txt"
echo "5. Test: python3.10 pythonanywhere_daily_hook.py --force"
