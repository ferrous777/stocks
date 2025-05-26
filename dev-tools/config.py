# Production configuration
DEBUG = False
TESTING = False

# Security
SECRET_KEY = 'your-secret-key-here-change-in-production'

# Application settings
RESULTS_DIR = 'results'
CACHE_DIR = 'cache'
STATIC_DIR = 'static'

# Flask settings
SEND_FILE_MAX_AGE_DEFAULT = 31536000  # 1 year for static files
