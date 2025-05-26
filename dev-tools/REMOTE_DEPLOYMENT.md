# Remote Development Setup for PythonAnywhere

## Prerequisites
1. PythonAnywhere account (free or paid)
2. VS Code with Remote-SSH extension installed ✅
3. SSH access enabled on your PythonAnywhere account

## Step 1: Enable SSH on PythonAnywhere

### For Paid Accounts:
SSH is enabled by default.

### For Free Accounts:
Unfortunately, free PythonAnywhere accounts don't support SSH access. You'll need to:
1. Upgrade to a paid account ($5/month minimum), OR
2. Use the manual upload method described in DEPLOYMENT.md

## Step 2: Configure SSH Connection

1. **Get your SSH details from PythonAnywhere:**
   - Go to PythonAnywhere Dashboard → Account → SSH Keys
   - Note your SSH hostname: `ssh.pythonanywhere.com`
   - Note your username: `yourusername`

2. **Generate SSH key pair (if you don't have one):**
   ```bash
   ssh-keygen -t rsa -b 4096 -C "your_email@example.com"
   ```

3. **Add your public key to PythonAnywhere:**
   - Copy your public key: `cat ~/.ssh/id_rsa.pub`
   - Go to PythonAnywhere → Account → SSH Keys
   - Click "Upload a new SSH key"
   - Paste your public key

## Step 3: Configure VS Code SSH

1. **Open VS Code Command Palette** (`Cmd+Shift+P` on Mac, `Ctrl+Shift+P` on Windows/Linux)

2. **Type: "Remote-SSH: Open SSH Configuration File"**

3. **Add your PythonAnywhere configuration:**
   ```
   Host pythonanywhere
       HostName ssh.pythonanywhere.com
       User yourusername
       Port 22
       IdentityFile ~/.ssh/id_rsa
       ServerAliveInterval 60
       ServerAliveCountMax 120
   ```

## Step 4: Connect to PythonAnywhere

1. **Open Command Palette** (`Cmd+Shift+P`)
2. **Type: "Remote-SSH: Connect to Host..."**
3. **Select "pythonanywhere"**
4. **Enter your password when prompted**

## Step 5: Set Up Your Project on PythonAnywhere

Once connected via Remote-SSH:

1. **Open Terminal in VS Code** (will be connected to PythonAnywhere)

2. **Clone or upload your project:**
   ```bash
   cd ~
   git clone https://github.com/yourusername/stocks.git
   # OR upload files using VS Code's file explorer
   ```

3. **Navigate to project directory:**
   ```bash
   cd ~/stocks
   ```

4. **Create virtual environment:**
   ```bash
   python3.11 -m venv venv
   source venv/bin/activate
   ```

5. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Step 6: Configure Web App via PythonAnywhere Dashboard

1. **Go to PythonAnywhere Dashboard → Web tab**
2. **Click "Add a new web app"**
3. **Choose "Manual configuration" → Python 3.11**
4. **Configure the following:**

   - **Source code:** `/home/yourusername/stocks`
   - **Working directory:** `/home/yourusername/stocks`
   - **WSGI file:** `/var/www/yourusername_pythonanywhere_com_wsgi.py`
   - **Virtualenv:** `/home/yourusername/stocks/venv`

5. **Static files mapping:**
   - **URL:** `/static/`
   - **Directory:** `/home/yourusername/stocks/static/`

## Step 7: Update WSGI Configuration

1. **In VS Code (connected to PythonAnywhere), open the WSGI file:**
   ```bash
   code /var/www/yourusername_pythonanywhere_com_wsgi.py
   ```

2. **Replace content with:**
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

   if __name__ == "__main__":
       application.run()
   ```

## Step 8: Deploy and Test

1. **Create necessary directories:**
   ```bash
   mkdir -p results cache static/css static/js templates
   chmod -R 755 ~/stocks
   ```

2. **Test your application locally (on PythonAnywhere):**
   ```bash
   cd ~/stocks
   source venv/bin/activate
   python app.py
   ```

3. **Reload your web app:**
   - Go to PythonAnywhere Web tab
   - Click "Reload"

4. **Visit your app:**
   `https://yourusername.pythonanywhere.com`

## Step 9: Development Workflow

With Remote-SSH, you can now:

1. **Edit files directly on PythonAnywhere** using VS Code
2. **Use VS Code terminal** connected to PythonAnywhere
3. **Debug and test** in real-time
4. **Auto-sync changes** without manual upload

### Quick deployment commands:
```bash
# Connect to PythonAnywhere via VS Code
# Make your changes
# Test locally
python app.py

# Deploy (reload web app)
# Go to PythonAnywhere dashboard and click Reload
# OR use their API:
curl -X POST https://www.pythonanywhere.com/api/v0/user/yourusername/webapps/yourusername.pythonanywhere.com/reload/ \
     -H "Authorization: Token your-api-token"
```

## Troubleshooting

### SSH Connection Issues:
- Verify SSH keys are correctly uploaded
- Check username and hostname
- Ensure you have a paid PythonAnywhere account

### Permission Errors:
```bash
chmod -R 755 ~/stocks
```

### Import Errors:
- Verify virtual environment is activated
- Check all dependencies are installed
- Verify Python path in WSGI file

### Web App Not Loading:
- Check error logs in PythonAnywhere Web tab
- Verify WSGI configuration
- Ensure all files have correct permissions

## Benefits of Remote-SSH Development

✅ **Direct editing** on PythonAnywhere servers
✅ **Real-time testing** in production environment  
✅ **Integrated terminal** connected to PythonAnywhere
✅ **Version control** with git directly on server
✅ **No manual file uploads** required
✅ **Full VS Code features** (IntelliSense, debugging, extensions)

## Alternative: VS Code Web Interface

If SSH isn't available, PythonAnywhere also provides a web-based VS Code interface:
1. Go to PythonAnywhere Dashboard → Files
2. Click on any Python file
3. Choose "Open in VS Code" (web interface)

This provides a similar experience but with some limitations compared to the full Remote-SSH setup.
