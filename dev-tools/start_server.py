#!/usr/bin/env python3
"""
Start the Flask web server for Stock Analysis Dashboard.
"""

import sys
import os
import subprocess
import argparse

def check_dependencies():
    """Check if required dependencies are installed."""
    required_packages = ['Flask', 'flask_cors']
    missing = []
    
    for package in required_packages:
        try:
            __import__(package.lower().replace('-', '_'))
        except ImportError:
            missing.append(package)
    
    if missing:
        print(f"Missing required packages: {', '.join(missing)}")
        print("Installing packages...")
        try:
            subprocess.run([sys.executable, '-m', 'pip', 'install'] + missing, check=True)
            print("Packages installed successfully!")
        except subprocess.CalledProcessError:
            print("Failed to install packages. Please install manually:")
            print(f"pip install {' '.join(missing)}")
            return False
    
    return True

def main():
    parser = argparse.ArgumentParser(description='Start Stock Analysis Dashboard')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind to (default: 5000)')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--no-browser', action='store_true', help='Don\'t open browser automatically')
    
    args = parser.parse_args()
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Set environment variables
    os.environ['FLASK_APP'] = 'app.py'
    if args.debug:
        os.environ['FLASK_ENV'] = 'development'
        os.environ['FLASK_DEBUG'] = '1'
    
    # Print startup information
    print("=" * 60)
    print("🚀 Starting Stock Analysis Dashboard")
    print("=" * 60)
    print(f"📊 Server URL: http://{args.host}:{args.port}")
    print(f"🔧 Debug mode: {'ON' if args.debug else 'OFF'}")
    print(f"📁 Working directory: {os.getcwd()}")
    print("=" * 60)
    print("\n📋 Available endpoints:")
    print(f"   • Dashboard:  http://{args.host}:{args.port}/")
    print(f"   • Compare:    http://{args.host}:{args.port}/compare")
    print(f"   • API Health: http://{args.host}:{args.port}/health")
    print(f"   • Symbol API: http://{args.host}:{args.port}/api/symbols")
    print("\n💡 Tips:")
    print("   • Press Ctrl+C to stop the server")
    print("   • Use --debug for development mode")
    print("   • Access from other devices using your IP address")
    print("=" * 60)
    
    # Open browser if not disabled
    if not args.no_browser:
        try:
            import webbrowser
            import threading
            import time
            
            def open_browser():
                time.sleep(1.5)  # Wait for server to start
                url = f"http://localhost:{args.port}" if args.host == '0.0.0.0' else f"http://{args.host}:{args.port}"
                webbrowser.open(url)
            
            threading.Thread(target=open_browser, daemon=True).start()
        except Exception as e:
            print(f"Could not open browser automatically: {e}")
    
    # Import and run the Flask app
    try:
        from app import app
        app.run(host=args.host, port=args.port, debug=args.debug)
    except ImportError:
        print("❌ Error: app.py not found. Make sure you're in the correct directory.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n👋 Server stopped by user")
    except Exception as e:
        print(f"❌ Error starting server: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
