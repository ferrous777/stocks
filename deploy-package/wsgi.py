#!/var/www/yourusername_pythonanywhere_com_wsgi.py

"""
WSGI config for PythonAnywhere deployment
Update 'yourusername' with your actual PythonAnywhere username
"""

import sys
import os

# Add your project directory to the Python path
# Replace 'yourusername' with your actual PythonAnywhere username
project_home = '/home/yourusername/stocks'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Set environment variables
os.environ['FLASK_ENV'] = 'production'

# Import your Flask application
from app import app as application

if __name__ == "__main__":
    application.run()
