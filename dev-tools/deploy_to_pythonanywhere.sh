#!/bin/bash

# Remote deployment script for PythonAnywhere
# Run this script when connected via Remote-SSH to PythonAnywhere

echo "🚀 Deploying Stock Analysis App to PythonAnywhere..."

# Check if we're on PythonAnywhere
if [[ ! "$HOSTNAME" == *"pythonanywhere"* ]]; then
    echo "❌ This script should be run on PythonAnywhere servers"
    echo "Connect via Remote-SSH first: Remote-SSH: Connect to Host... → pythonanywhere"
    exit 1
fi

# Set up directory
PROJECT_DIR="/home/$USER/stocks"
cd "$PROJECT_DIR" || {
    echo "❌ Project directory not found: $PROJECT_DIR"
    echo "Please ensure your code is uploaded to $PROJECT_DIR"
    exit 1
}

echo "📁 Working in: $PROJECT_DIR"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "🐍 Creating virtual environment..."
    python3.11 -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "⬆️  Upgrading pip..."
pip install --upgrade pip

# Install/update requirements
echo "📦 Installing requirements..."
pip install -r requirements.txt

# Create necessary directories
echo "📂 Creating directories..."
mkdir -p results cache static/css static/js templates

# Set proper permissions
echo "🔒 Setting permissions..."
chmod -R 755 .

# Check if sample data exists, create if not
if [ ! -f "results/AAPL_recommendations_$(date +%Y%m%d).json" ]; then
    echo "📊 Creating sample data..."
    python3 -c "
import os
import json
from datetime import datetime

# Create sample recommendation data
sample_rec = {
    'symbol': 'AAPL',
    'analysis_date': datetime.now().strftime('%Y-%m-%d'),
    'current_price': 195.27,
    'recommendations': {
        'action': 'BUY',
        'confidence': 0.85,
        'entry_price': 185.5,
        'reasoning': 'Strong earnings growth and technical breakout pattern indicate bullish momentum.',
        'stop_loss': 176.25,
        'take_profit': 205.75
    }
}

filename = f'results/AAPL_recommendations_{datetime.now().strftime(\"%Y%m%d\")}.json'
with open(filename, 'w') as f:
    json.dump(sample_rec, f, indent=2)

print(f'Created sample data: {filename}')
"
fi

# Test the application
echo "🧪 Testing application..."
python3 -c "
import sys
sys.path.insert(0, '.')
try:
    from app import app
    print('✅ Application imports successfully')
    
    # Test a simple route
    with app.test_client() as client:
        response = client.get('/')
        if response.status_code == 200:
            print('✅ Application responds to requests')
        else:
            print(f'⚠️  Application returned status code: {response.status_code}')
except Exception as e:
    print(f'❌ Application test failed: {e}')
    sys.exit(1)
"

# Update WSGI file
WSGI_FILE="/var/www/${USER}_pythonanywhere_com_wsgi.py"
if [ -f "$WSGI_FILE" ]; then
    echo "🔧 Updating WSGI configuration..."
    cat > "$WSGI_FILE" << EOF
import sys
import os

# Add your project directory to the Python path
project_home = '/home/$USER/stocks'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Set environment variables
os.environ['FLASK_ENV'] = 'production'

# Import your Flask application
from app import app as application

if __name__ == "__main__":
    application.run()
EOF
    echo "✅ WSGI file updated: $WSGI_FILE"
else
    echo "⚠️  WSGI file not found: $WSGI_FILE"
    echo "Please create your web app first in the PythonAnywhere dashboard"
fi

echo ""
echo "🎉 Deployment complete!"
echo ""
echo "Next steps:"
echo "1. Go to PythonAnywhere Web tab: https://www.pythonanywhere.com/user/$USER/webapps/"
echo "2. Click 'Reload' button for your web app"
echo "3. Visit your app: https://$USER.pythonanywhere.com"
echo ""
echo "💡 To make changes:"
echo "   - Edit files directly in VS Code (Remote-SSH connected)"
echo "   - Test locally: python app.py"
echo "   - Deploy: Run this script again or reload in dashboard"
echo ""
echo "📝 View logs: https://www.pythonanywhere.com/user/$USER/webapps/#tab_id_$USER_pythonanywhere_com_logs"
