"""
Version information for the stock analysis system
"""

VERSION = "1.3.0"
BUILD_DATE = "2025-05-28"
BUILD_NUMBER = "20250528002"

# Version history:
# 1.3.0 - Enhanced deployment process with comprehensive version checking and testing
# 1.2.0 - Enhanced data fetching, fixed yfinance imports, organized file structure
# 1.1.0 - Added YAML configuration management, improved add/remove ticker functionality
# 1.0.0 - Initial release with basic functionality

# Key features in this version:
# - Comprehensive server deployment with backup and verification
# - Enhanced version checking for dependencies  
# - Robust import testing to catch yfinance issues
# - Automated deployment process with cleanup and validation
# - File organization with docs/ and dev-tools/ structure
# 1.1.0 - Added admin CLI, improved deployment
# 1.0.0 - Initial release

def get_version_info():
    """Get comprehensive version information"""
    return {
        "version": VERSION,
        "build_date": BUILD_DATE,
        "build_number": BUILD_NUMBER,
        "python_requirements": {
            "yfinance": "0.2.36",
            "pandas": ">=2.1.1",
            "flask": ">=2.3.3"
        }
    }

def get_version_string():
    """Get a simple version string"""
    return f"{VERSION} (build {BUILD_NUMBER})"
