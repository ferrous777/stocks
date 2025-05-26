# PythonAnywhere Deployment Guide

## Prerequisites
- PythonAnywhere account (free or paid)
- Basic familiarity with PythonAnywhere console

## Step 1: Upload Your Code

### Option A: Using Git (Recommended)
1. Log into PythonAnywhere console
2. Clone your repository:
```bash
git clone https://github.com/yourusername/stocks.git
cd stocks
```

### Option B: Upload Files
1. Use PythonAnywhere's Files tab
2. Upload your entire project to `/home/yourusername/stocks/`

## Step 2: Install Dependencies

1. Open a Bash console in PythonAnywhere
2. Navigate to your project directory:
```bash
cd ~/stocks
```

3. Create a virtual environment (recommended):
```bash
python3.11 -m venv venv
source venv/bin/activate
```

4. Install dependencies:
```bash
pip install -r requirements.txt
```

## Step 3: Configure Web App

1. Go to PythonAnywhere Dashboard → Web tab
2. Click "Add a new web app"
3. Choose "Manual configuration" → Python 3.11
4. Set the following configuration:

### Source code directory:
```
/home/yourusername/stocks
```

### Working directory:
```
/home/yourusername/stocks
```

### WSGI configuration file:
```
/var/www/yourusername_pythonanywhere_com_wsgi.py
```

### Virtual environment (if using):
```
/home/yourusername/stocks/venv
```

## Step 4: Update WSGI File

1. Edit the WSGI file in PythonAnywhere:
```python
import sys
import os

# Add your project directory to the Python path
project_home = '/home/yourusername/stocks'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Set environment variables
os.environ['FLASK_ENV'] = 'production'

# Import your Flask application
from app import app as application
```

## Step 5: Static Files Configuration

In the Web tab, set up static files mapping:

### URL: `/static/`
### Directory: `/home/yourusername/stocks/static/`

## Step 6: Environment Variables (Optional)

If you have any API keys or sensitive data:
1. Go to Files tab
2. Create a `.env` file in your project root
3. Add environment variables:
```
API_KEY=your_api_key_here
DEBUG=False
```

## Step 7: Initialize Data (First Time)

1. Open a console and navigate to your project:
```bash
cd ~/stocks
source venv/bin/activate  # if using virtual environment
```

2. Run initial data collection (if needed):
```bash
python src/main.py --symbols AAPL MSFT GOOGL --days 30
```

## Step 8: Test Your Application

1. Click "Reload" in the Web tab
2. Visit your app at: `https://yourusername.pythonanywhere.com`

## Important Notes

### File Permissions
Make sure all files are readable:
```bash
chmod -R 755 ~/stocks
```

### Daily Tasks (Optional)
To automatically update stock data:
1. Go to Tasks tab in PythonAnywhere
2. Create a scheduled task:
```bash
cd /home/yourusername/stocks && source venv/bin/activate && python src/main.py --symbols AAPL MSFT GOOGL --days 30
```

### Debugging
- Check error logs in Web tab → Log files
- Use PythonAnywhere error console for debugging
- Check `pip list` to verify all packages are installed

### Free Account Limitations
- Limited CPU seconds per day
- One web app
- No scheduled tasks on free accounts
- Limited file storage

## Common Issues

### Import Errors
- Verify all dependencies are installed
- Check virtual environment is activated
- Ensure project directory is in Python path

### Static Files Not Loading
- Verify static files mapping in Web tab
- Check file permissions
- Ensure static directory exists

### Data Not Updating
- Check if data files are present in results/ and cache/ directories
- Verify file permissions
- Run data collection manually first

## Security Considerations

1. Never commit API keys to version control
2. Use environment variables for sensitive data
3. Set `DEBUG=False` in production
4. Consider using HTTPS (automatic on PythonAnywhere)

## Support
- PythonAnywhere Help Pages: https://help.pythonanywhere.com/
- PythonAnywhere Forums: https://www.pythonanywhere.com/forums/
