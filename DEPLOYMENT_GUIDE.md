# PythonAnywhere Deployment Guide

## Project Structure After Reorganization

The project has been reorganized for clean PythonAnywhere deployment:

### Essential Files (included in deployment):
```
/
├── app.py                 # Main Flask application
├── wsgi.py               # WSGI entry point for PythonAnywhere
├── pythonanywhere_daily_hook.py  # Production scheduler
├── requirements.txt      # Python dependencies
├── README.md            # Basic project documentation
├── config/              # Configuration files
├── data/                # Database files
├── src/                 # Core application source code
├── static/              # Static assets (CSS, JS, images)
└── templates/           # Jinja2 HTML templates
```

### Development Files (excluded from deployment):
```
dev-tools/
├── analysis_cli.py           # CLI analysis tools
├── add_ticker.py            # Ticker management
├── config_cli.py            # Configuration CLI
├── docs/                    # Documentation
├── reports/                 # Generated reports
├── test_*.py               # All test files
├── *.sh                    # Shell scripts
├── start_server.py         # Development server
└── deployment tools        # Various deployment utilities
```

## Deployment Process

### Option 1: Using the Deployment Script
```bash
# Create deployment package
./dev-tools/create-deployment-package.sh

# Create compressed archive
tar -czf stocks-app.tar.gz -C deploy-package .

# Upload to PythonAnywhere and extract
```

### Option 2: Manual Upload
Upload only these essential directories and files:
- `app.py`
- `wsgi.py` 
- `pythonanywhere_daily_hook.py`
- `requirements.txt`
- `src/`
- `templates/`
- `static/`
- `config/`
- `data/`

### PythonAnywhere Configuration

1. **Web App Setup:**
   - Source code: `/home/yourusername/mysite/`
   - WSGI configuration file: `/home/yourusername/mysite/wsgi.py`

2. **Dependencies:**
   ```bash
   pip3.10 install --user -r requirements.txt
   ```

3. **Environment Variables:**
   - Set any required environment variables in the PythonAnywhere web app configuration

## File Size Comparison

- **Before reorganization:** ~150 files including all dev tools
- **After reorganization:** ~70 essential files for production
- **Excluded from deployment:** 80+ development files

This reduces upload time and keeps the production environment clean and focused.

## Development Workflow

- **Local development:** All tools available in `dev-tools/`
- **Testing:** Run tests from `dev-tools/test_*.py`
- **Analysis:** Use CLI tools in `dev-tools/`
- **Deployment:** Use deployment script or manual upload of essential files only

## Benefits

1. **Faster deployments** - Only essential files uploaded
2. **Cleaner production environment** - No development clutter
3. **Better security** - No test files or development scripts in production
4. **Organized development** - All development tools in one place
5. **Easy maintenance** - Clear separation of concerns
