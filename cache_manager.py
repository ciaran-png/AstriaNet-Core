import json
import os
import time
from datetime import datetime

class JSONDateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder for datetime objects."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

class SimpleCache:
    def __init__(self, filename: str = 'cache.json', expiration_time: int = 3600):
        self.filename = filename
        self.expiration_time = expiration_time
        self.cache = self.load_cache()

    def load_cache(self) -> dict:
        """Load the cache from a file."""
        if os.path.exists(self.filename):
            with open(self.filename, 'r') as file:
                return json.load(file, object_hook=self.json_datetime_hook)
        return {}

    def save_cache(self):
        """Save the cache to a file."""
        with open(self.filename, 'w') as file:
            json.dump(self.cache, file, cls=JSONDateTimeEncoder)

    def set(self, key: str, value: dict):
        """Store an item in the cache."""
        self.cache[key] = {'data': value, 'time': time.time()}
        self.save_cache()

    def get(self, key: str) -> dict:
        """Retrieve an item from the cache if it hasn't expired."""
        if key in self.cache:
            if time.time() - self.cache[key]['time'] < self.expiration_time:
                return self.cache[key]['data']
        return None

    @staticmethod
    def json_datetime_hook(json_dict):
        """Converts string in ISO format back into datetime object."""
        for (key, value) in json_dict.items():
            try:
                json_dict[key] = datetime.fromisoformat(value)
            except (TypeError, ValueError):
                pass
        return json_dict