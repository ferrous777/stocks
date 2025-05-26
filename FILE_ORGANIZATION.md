# File Organization Summary

This document provides a complete categorization of all files in the project after reorganization for optimal PythonAnywhere deployment.

## 📁 **PRODUCTION FILES (Root Directory)**

### **Core Application Files:**
- `app.py` - Main Flask web application
- `wsgi.py` - WSGI entry point for PythonAnywhere
- `requirements.txt` - Python package dependencies

### **Production Scripts:**
- `pythonanywhere_daily_hook.py` - **ESSENTIAL** Daily scheduler for PythonAnywhere automation

### **Configuration & Data:**
- `config/` - System configuration files
- `data/` - SQLite databases and data files
- `src/` - Core application source code

### **Web Assets:**
- `templates/` - Jinja2 HTML templates
- `static/` - CSS, JavaScript, images

### **Documentation:**
- `README.md` - Primary project documentation
- `DEPLOYMENT_GUIDE.md` - PythonAnywhere deployment instructions

### **Configuration Files:**
- `.env` - Environment variables (production)
- `.deployignore` - Deployment exclusion rules
- `.gitignore` - Git exclusion rules

---

## 🔧 **DEVELOPMENT FILES (dev-tools/ Directory)**

### **Analysis & CLI Tools:**
- `analysis_cli.py` - Command-line analysis tools
- `config_cli.py` - Configuration management CLI
- `scheduler_cli.py` - Scheduler management
- `update_symbols.py` - Symbol configuration updates

### **Data Management:**
- `add_ticker.py` - Add new stock symbols
- `detect_gaps.py` - Data gap detection
- `generate_missing_recommendations.py` - Backfill recommendations
- `migrate_data.py` - Database migration utilities
- `run_daily.py` - Manual daily operations

### **Development Tools:**
- `start_server.py` - Local development server
- `run_performance_analysis.py` - Performance analysis
- `browser_debug.js` / `debug_browser.js` - Debug utilities

### **Test Files:**
- `test_aggregation.py`
- `test_api.py`
- `test_database.py`
- `test_migrated_db.py`
- `test_prediction_tracker.py`
- `test_ticker_management.py`

### **Deployment & Setup Scripts:**
- `create-deployment-package.sh` - Creates clean deployment package
- `deploy_to_pythonanywhere.sh` - Deployment automation
- `setup_cron.sh` - Cron setup utilities
- `setup_pythonanywhere.sh` - PythonAnywhere setup
- `fix_data_gaps_20250524_1854.sh` - One-time data fixes

### **Documentation:**
- `DEPLOYMENT.md` - Detailed deployment docs
- `PYTHONANYWHERE_SETUP.md` - Setup guide
- `README_COMPLETE.md` - Complete technical documentation
- `REMOTE_DEPLOYMENT.md` - Remote deployment guide
- `TODO.md` - Development task list
- `docs/` - Complete technical documentation (11 files)
- `reports/` - Generated analysis reports (4 files)

### **Configuration Examples:**
- `.ssh_config_example` - SSH configuration template
- `config.py` - Standalone config (legacy)

---

## 🚀 **DEPLOYMENT STRATEGY**

### **PythonAnywhere Upload:**
**Include:** Root directory files only
**Exclude:** `dev-tools/` directory (via `.deployignore`)

### **File Count Comparison:**
- **Production:** ~15 essential files + directories
- **Development:** ~30+ development tools and documentation
- **Total Reduction:** 50%+ fewer files in production

### **Key Benefits:**
1. **Faster Uploads** - Only essential files transferred
2. **Security** - No development tools in production
3. **Clean Environment** - Production-focused file structure
4. **Easy Maintenance** - Clear separation of concerns

---

## 📋 **DEPLOYMENT CHECKLIST**

### **Essential Production Files:**
- ✅ `app.py` (Flask application)
- ✅ `wsgi.py` (WSGI entry point)
- ✅ `pythonanywhere_daily_hook.py` (Daily automation)
- ✅ `requirements.txt` (Dependencies)
- ✅ `src/` (Core code)
- ✅ `templates/` (HTML templates)
- ✅ `static/` (Web assets)
- ✅ `config/` (Configuration)
- ✅ `data/` (Databases)

### **PythonAnywhere Configuration:**
- ✅ Web app points to `wsgi.py`
- ✅ Daily task runs `pythonanywhere_daily_hook.py`
- ✅ Dependencies installed from `requirements.txt`

### **Development Environment:**
- ✅ All tools available in `dev-tools/`
- ✅ Documentation complete and organized
- ✅ Test suite comprehensive
- ✅ Deployment automation ready

---

## 🎯 **CRITICAL INSIGHT**

**`pythonanywhere_daily_hook.py` MUST be in root directory** because:
1. Referenced in all PythonAnywhere documentation
2. Scheduled tasks expect root-level access
3. Production automation depends on it
4. Simplifies deployment configuration

All other scripts can remain in `dev-tools/` as they are development/operational utilities not needed in production.
