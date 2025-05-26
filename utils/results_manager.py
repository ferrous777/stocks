from datetime import datetime
import os
import json
import shutil

class ResultsManager:
    def __init__(self, results_dir: str = "results"):
        self.results_dir = results_dir
        os.makedirs(results_dir, exist_ok=True)
    
    def archive_old_results(self, days_old: int = 30):
        """Archive results older than specified days"""
        archive_dir = os.path.join(self.results_dir, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        
        today = datetime.now()
        for filename in os.listdir(self.results_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self.results_dir, filename)
                file_date = datetime.strptime(filename[-12:-5], '%Y%m%d')
                if (today - file_date).days > days_old:
                    archive_path = os.path.join(archive_dir, filename)
                    shutil.move(filepath, archive_path)
    
    def get_latest_results(self, symbol: str, result_type: str = None):
        """Get most recent results for a symbol"""
        files = [f for f in os.listdir(self.results_dir) 
                if f.startswith(symbol) 
                and (result_type is None or result_type in f)
                and f.endswith('.json')]
        
        if not files:
            return None
            
        latest_file = max(files, key=lambda x: x[-12:-5])  # Sort by date in filename
        with open(os.path.join(self.results_dir, latest_file), 'r') as f:
            return json.load(f) 