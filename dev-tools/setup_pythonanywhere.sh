#!/bin/bash

# PythonAnywhere Setup Script
# Run this script after uploading your code to PythonAnywhere

echo "Setting up Stock Analysis App on PythonAnywhere..."

# Create virtual environment
echo "Creating virtual environment..."
python3.11 -m venv venv
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install requirements
echo "Installing requirements..."
pip install -r requirements.txt

# Create necessary directories
echo "Creating directories..."
mkdir -p results
mkdir -p cache
mkdir -p static/css
mkdir -p static/js
mkdir -p templates

# Set proper permissions
echo "Setting permissions..."
chmod -R 755 .

# Generate some sample data if needed
echo "Generating sample data..."
python3 -c "
import os
import json
from datetime import datetime

# Create sample data structure
os.makedirs('results', exist_ok=True)
os.makedirs('cache', exist_ok=True)

# Sample recommendation data
sample_rec = {
    'symbol': 'AAPL',
    'analysis_date': datetime.now().strftime('%Y-%m-%d'),
    'recommendations': {
        'action': 'BUY',
        'confidence': 0.85,
        'entry_price': 185.5,
        'reasoning': 'Sample recommendation for demo purposes',
        'stop_loss': 176.25,
        'take_profit': 205.75
    }
}

with open('results/AAPL_recommendations_$(date +%Y%m%d).json', 'w') as f:
    json.dump(sample_rec, f, indent=2)

print('Sample data created successfully!')
"

echo "Setup complete!"
echo ""
echo "Next steps:"
echo "1. Go to PythonAnywhere Web tab"
echo "2. Create a new web app (Manual configuration, Python 3.11)"
echo "3. Set source code directory to: /home/yourusername/stocks"
echo "4. Set working directory to: /home/yourusername/stocks"
echo "5. Update WSGI file with the provided configuration"
echo "6. Set virtual environment to: /home/yourusername/stocks/venv"
echo "7. Add static files mapping: /static/ -> /home/yourusername/stocks/static/"
echo "8. Reload your web app"
echo ""
echo "Your app should be available at: https://yourusername.pythonanywhere.com"
