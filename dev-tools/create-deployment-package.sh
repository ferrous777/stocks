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
echo "To deploy to PythonAnywhere:"
echo "1. Compress the deploy-package folder: tar -czf stocks-app.tar.gz -C deploy-package ."
echo "2. Upload stocks-app.tar.gz to PythonAnywhere"
echo "3. Extract in your web app directory"
