import json
import os
from copy import deepcopy


CONFIG_PATH = "viewer_config.json"

DEFAULT_CONFIG = {
    "cassy": {
        "dll_path": r"C:\Users\grego\OneDrive\Studium\MA\Software\Cassy SDK\CASSYSDK\Api\LD.Api.dll"
    },
    "hardware": {
        "measurement_window": {
            "width_mm": 1.0,
            "height_mm": 1.0
        }
    }
}


class AppConfig:
    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self.data = self._load()

    def get(self, *keys, default=None):
        value = self.data
        for key in keys:
            if not isinstance(value, dict) or key not in value:
                return default
            value = value[key]
        return value

    def set(self, *keys, value):
        if not keys:
            raise ValueError("Mindestens ein Schluessel ist erforderlich.")

        target = self.data
        for key in keys[:-1]:
            target = target.setdefault(key, {})
        target[keys[-1]] = value

    def save(self):
        with open(self.path, "w", encoding="utf-8") as file:
            json.dump(self.data, file, indent=2, ensure_ascii=False)

    def _load(self):
        if not os.path.exists(self.path):
            data = deepcopy(DEFAULT_CONFIG)
            self.data = data
            self.save()
            return data

        try:
            with open(self.path, "r", encoding="utf-8") as file:
                loaded = json.load(file)
        except (OSError, json.JSONDecodeError):
            loaded = {}

        data = deepcopy(DEFAULT_CONFIG)
        self._merge(data, loaded)
        return data

    def _merge(self, target, source):
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                self._merge(target[key], value)
            else:
                target[key] = value
