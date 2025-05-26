from datetime import datetime
import pandas as pd
import numpy as np
from typing import Any, Dict, List, Union

class JSONSerializer:
    @staticmethod
    def serialize_timestamp(timestamp) -> str:
        """Convert Timestamp to string format"""
        if isinstance(timestamp, pd.Timestamp):
            return timestamp.strftime('%Y-%m-%d %H:%M:%S')
        return str(timestamp)
    
    @staticmethod
    def serialize_value(value: Any) -> Any:
        """Serialize a single value to JSON-compatible format"""
        if isinstance(value, (pd.Series, np.ndarray)):
            return [JSONSerializer.serialize_value(v) for v in value]
        elif isinstance(value, pd.Timestamp):
            return JSONSerializer.serialize_timestamp(value)
        elif isinstance(value, dict):
            return JSONSerializer.serialize_dict(value)
        elif isinstance(value, (list, tuple)):
            return [JSONSerializer.serialize_value(v) for v in value]
        elif isinstance(value, pd.DataFrame):
            return JSONSerializer.serialize_dataframe(value)
        elif isinstance(value, (np.int64, np.int32, np.int16, np.int8)):
            return int(value)
        elif isinstance(value, (np.float64, np.float32, np.float16)):
            return float(value)
        elif isinstance(value, np.bool_):
            return bool(value)
        elif pd.isna(value) or value is None:
            return None
        return value
    
    @staticmethod
    def serialize_dict(data: Dict) -> Dict:
        """Convert dictionary with Pandas objects to JSON-serializable format"""
        if data is None:
            return None
            
        serialized = {}
        for key, value in data.items():
            # Convert key to string if it's not a basic type
            if not isinstance(key, (str, int, float, bool)) or isinstance(key, pd.Timestamp):
                key = str(key)
            
            try:
                serialized[key] = JSONSerializer.serialize_value(value)
            except Exception as e:
                print(f"Warning: Could not serialize value for key {key}: {str(e)}")
                serialized[key] = None
                
        return serialized
    
    @staticmethod
    def serialize_dataframe(df: pd.DataFrame) -> Dict:
        """Convert DataFrame to JSON-serializable format"""
        if df is None or df.empty:
            return None
            
        try:
            return {
                'index': [JSONSerializer.serialize_timestamp(idx) for idx in df.index],
                'columns': list(df.columns),
                'data': [JSONSerializer.serialize_dict(row) for row in df.to_dict(orient='records')]
            }
        except Exception as e:
            print(f"Warning: Could not serialize DataFrame: {str(e)}")
            return None 