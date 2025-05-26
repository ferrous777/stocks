#!/usr/bin/env python3
"""
Flask Application Dependency Analyzer

Analyzes imports and determines which files are actually used by the Flask application.
Creates a mapping of all required files for clean deployment.
"""

import ast
import os
import sys
from pathlib import Path
from typing import Set, Dict, List, Tuple
import json
import importlib.util
from datetime import datetime

class FlaskDependencyAnalyzer:
    def __init__(self, app_root: str = "."):
        self.app_root = Path(app_root).resolve()
        self.python_files: Set[Path] = set()
        self.imports: Dict[str, Set[str]] = {}
        self.file_mapping: Dict[str, str] = {}
        self.used_files: Set[Path] = set()
        self.entry_points = ['app.py', 'main.py', 'wsgi.py']
        
    def discover_python_files(self) -> None:
        """Discover all Python files in the project."""
        print("🔍 Discovering Python files...")
        
        for pattern in ['**/*.py']:
            for file_path in self.app_root.glob(pattern):
                # Skip certain directories
                if any(part in str(file_path) for part in ['.git', '__pycache__', '.venv', 'venv', '.pytest_cache']):
                    continue
                self.python_files.add(file_path)
        
        print(f"   Found {len(self.python_files)} Python files")
    
    def extract_imports_from_file(self, file_path: Path) -> Set[str]:
        """Extract import statements from a Python file."""
        imports = set()
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        imports.add(name.name.split('.')[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module.split('.')[0])
                        
        except Exception as e:
            print(f"   ⚠️  Could not parse {file_path}: {e}")
            
        return imports
    
    def analyze_imports(self) -> None:
        """Analyze imports in all Python files."""
        print("📊 Analyzing imports...")
        
        for file_path in self.python_files:
            relative_path = file_path.relative_to(self.app_root)
            imports = self.extract_imports_from_file(file_path)
            self.imports[str(relative_path)] = imports
            
        print(f"   Analyzed imports in {len(self.imports)} files")
    
    def resolve_local_imports(self, import_name: str) -> List[Path]:
        """Resolve local import to actual file paths."""
        candidates = []
        
        # Try direct module file
        module_file = self.app_root / f"{import_name}.py"
        if module_file.exists():
            candidates.append(module_file)
        
        # Try package directory
        package_dir = self.app_root / import_name
        if package_dir.is_dir():
            init_file = package_dir / "__init__.py"
            if init_file.exists():
                candidates.append(init_file)
            
            # Add all Python files in the package
            for py_file in package_dir.glob("*.py"):
                candidates.append(py_file)
        
        return candidates
    
    def trace_dependencies(self, start_files: List[str]) -> None:
        """Trace dependencies starting from entry points."""
        print("🕸️  Tracing dependencies...")
        
        to_process = []
        for start_file in start_files:
            file_path = self.app_root / start_file
            if file_path.exists():
                to_process.append(file_path)
                self.used_files.add(file_path)
        
        processed = set()
        
        while to_process:
            current_file = to_process.pop(0)
            
            if current_file in processed:
                continue
            processed.add(current_file)
            
            relative_path = str(current_file.relative_to(self.app_root))
            
            if relative_path in self.imports:
                for import_name in self.imports[relative_path]:
                    # Only process local imports (not external libraries)
                    if not self.is_external_library(import_name):
                        candidates = self.resolve_local_imports(import_name)
                        for candidate in candidates:
                            if candidate not in self.used_files:
                                self.used_files.add(candidate)
                                to_process.append(candidate)
        
        print(f"   Traced {len(self.used_files)} used Python files")
    
    def is_external_library(self, import_name: str) -> bool:
        """Check if import is an external library."""
        external_libs = {
            'flask', 'numpy', 'pandas', 'requests', 'yfinance', 'yaml', 'json', 
            'os', 'sys', 'datetime', 'time', 'logging', 'pathlib', 'typing',
            'collections', 'itertools', 'functools', 'operator', 'math', 'random',
            'urllib', 'http', 'socket', 'threading', 'subprocess', 'shutil',
            'glob', 're', 'csv', 'sqlite3', 'pickle', 'base64', 'hashlib',
            'flask_cors', 'scipy', 'tabulate', 'pytz'
        }
        return import_name in external_libs
    
    def analyze_flask_routes(self) -> Set[str]:
        """Analyze Flask routes to find template and static file dependencies."""
        template_files = set()
        static_files = set()
        
        # Find all template references
        for file_path in self.used_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Look for render_template calls
                import re
                template_matches = re.findall(r"render_template\s*\(\s*['\"]([^'\"]+)['\"]", content)
                for template in template_matches:
                    template_files.add(template)
                
                # Look for url_for static calls
                static_matches = re.findall(r"url_for\s*\(\s*['\"]static['\"],\s*filename\s*=\s*['\"]([^'\"]+)['\"]", content)
                for static_file in static_matches:
                    static_files.add(static_file)
                    
            except Exception:
                pass
        
        return template_files, static_files
    
    def create_deployment_mapping(self) -> Dict[str, str]:
        """Create a mapping of source files to deployment locations."""
        mapping = {}
        
        # Python files - maintain directory structure
        for file_path in self.used_files:
            relative_path = file_path.relative_to(self.app_root)
            mapping[str(relative_path)] = str(relative_path)
        
        # Add Flask entry points
        for entry_point in self.entry_points:
            if (self.app_root / entry_point).exists():
                mapping[entry_point] = entry_point
        
        # Add configuration files
        config_files = [
            'requirements.txt',
            'config/system_config.yaml',
            '.env'
        ]
        
        for config_file in config_files:
            if (self.app_root / config_file).exists():
                mapping[config_file] = config_file
        
        # Add templates and static files
        template_files, static_files = self.analyze_flask_routes()
        
        for template in template_files:
            template_path = f"templates/{template}"
            if (self.app_root / template_path).exists():
                mapping[template_path] = template_path
        
        for static_file in static_files:
            static_path = f"static/{static_file}"
            if (self.app_root / static_path).exists():
                mapping[static_path] = static_path
        
        # Add entire directories that should be included
        required_dirs = ['templates', 'static', 'config', 'cache', 'results']
        for dir_name in required_dirs:
            dir_path = self.app_root / dir_name
            if dir_path.exists():
                for file_path in dir_path.rglob('*'):
                    if file_path.is_file():
                        relative_path = file_path.relative_to(self.app_root)
                        mapping[str(relative_path)] = str(relative_path)
        
        return mapping
    
    def generate_clean_deployment_script(self, mapping: Dict[str, str]) -> str:
        """Generate a deployment script that only copies required files."""
        script = '''#!/bin/bash

# Clean Flask Deployment Script
# Generated automatically based on dependency analysis

set -e  # Exit on any error

echo "🧹 Creating clean deployment package..."

# Create deployment directory
DEPLOY_DIR="deploy_temp"
rm -rf $DEPLOY_DIR
mkdir -p $DEPLOY_DIR

echo "📂 Copying only required files..."

# File mapping (source -> destination)
declare -A FILE_MAP
'''
        
        for source, dest in sorted(mapping.items()):
            script += f'FILE_MAP["{source}"]="{dest}"\n'
        
        script += '''
# Copy files according to mapping
for source in "${!FILE_MAP[@]}"; do
    dest="${FILE_MAP[$source]}"
    
    if [ -f "$source" ]; then
        # Create destination directory if needed
        dest_dir=$(dirname "$DEPLOY_DIR/$dest")
        mkdir -p "$dest_dir"
        
        # Copy file
        cp "$source" "$DEPLOY_DIR/$dest"
        echo "   ✅ $source -> $dest"
    elif [ -d "$source" ]; then
        # Copy directory
        mkdir -p "$DEPLOY_DIR/$dest"
        cp -r "$source/"* "$DEPLOY_DIR/$dest/" 2>/dev/null || true
        echo "   📁 $source/ -> $dest/"
    else
        echo "   ⚠️  Not found: $source"
    fi
done

# Create server deployment script
cat > $DEPLOY_DIR/deploy_server.sh << 'EOF'
#!/bin/bash
echo "🚀 Deploying clean Flask application..."

APP_DIR="/home/ferrous77/stocks"
echo "📍 Target: $APP_DIR"

# Backup existing installation
if [ -d "$APP_DIR" ]; then
    echo "📦 Creating backup..."
    tar -czf ~/stocks-backup-$(date +%Y%m%d-%H%M%S).tar.gz "$APP_DIR/"
fi

# Clean target directory
echo "🧹 Cleaning target directory..."
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"

# Copy all files maintaining structure
echo "📂 Copying files..."
cp -r ./* "$APP_DIR/"

# Remove any duplicate files from other locations
echo "🔍 Removing duplicates..."
CRITICAL_FILES=("app.py" "main.py" "wsgi.py" "market_data.py")

for file in "${CRITICAL_FILES[@]}"; do
    echo "  Checking for duplicates of $file..."
    find /home/ferrous77 -name "$file" -not -path "$APP_DIR/*" -delete 2>/dev/null || true
done

# Clean Python cache
find "$APP_DIR" -name "*.pyc" -delete 2>/dev/null || true
find "$APP_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo "✅ Clean deployment completed!"
echo "🔄 Reload your web app in PythonAnywhere dashboard"
EOF

chmod +x $DEPLOY_DIR/deploy_server.sh

# Create deployment package
tar -czf stocks-app-clean.tar.gz -C $DEPLOY_DIR .
rm -rf $DEPLOY_DIR

echo "✅ Clean deployment package created: stocks-app-clean.tar.gz"
echo "📋 Package contains only required files based on dependency analysis"
'''
        
        return script
    
    def analyze(self) -> None:
        """Run complete dependency analysis."""
        print("🎯 Flask Application Dependency Analysis")
        print("=" * 50)
        
        self.discover_python_files()
        self.analyze_imports()
        self.trace_dependencies(self.entry_points)
        
        # Create deployment mapping
        mapping = self.create_deployment_mapping()
        
        print(f"\n📋 Analysis Results:")
        print(f"   Total Python files found: {len(self.python_files)}")
        print(f"   Actually used Python files: {len(self.used_files)}")
        print(f"   Total files for deployment: {len(mapping)}")
        
        # Save results
        results = {
            'used_python_files': [str(f.relative_to(self.app_root)) for f in self.used_files],
            'deployment_mapping': mapping,
            'entry_points': self.entry_points,
            'analysis_timestamp': str(datetime.now())
        }
        
        with open('dependency_analysis.json', 'w') as f:
            json.dump(results, f, indent=2)
        
        # Generate clean deployment script
        script_content = self.generate_clean_deployment_script(mapping)
        with open('deploy_clean.sh', 'w') as f:
            f.write(script_content)
        os.chmod('deploy_clean.sh', 0o755)
        
        print("\n📄 Files created:")
        print("   dependency_analysis.json - Detailed analysis results")
        print("   deploy_clean.sh - Clean deployment script")
        
        # Show unused files
        unused_files = self.python_files - self.used_files
        if unused_files:
            print(f"\n⚠️  Found {len(unused_files)} unused Python files:")
            for unused in sorted(unused_files)[:10]:  # Show first 10
                print(f"   - {unused.relative_to(self.app_root)}")
            if len(unused_files) > 10:
                print(f"   ... and {len(unused_files) - 10} more")

def main():
    if len(sys.argv) > 1:
        app_root = sys.argv[1]
    else:
        app_root = "."
    
    analyzer = FlaskDependencyAnalyzer(app_root)
    analyzer.analyze()

if __name__ == "__main__":
    main()
