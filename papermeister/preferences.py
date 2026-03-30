import json
import os

PREFS_PATH = os.path.join(os.path.expanduser('~'), '.papermeister', 'preferences.json')

_cache = None


def _load():
    global _cache
    if _cache is not None:
        return _cache
    if os.path.exists(PREFS_PATH):
        with open(PREFS_PATH, encoding='utf-8') as f:
            _cache = json.load(f)
    else:
        _cache = {}
    return _cache


def _save(data):
    global _cache
    os.makedirs(os.path.dirname(PREFS_PATH), exist_ok=True)
    with open(PREFS_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _cache = data


def get_pref(key, default=None):
    return _load().get(key, default)


def set_pref(key, value):
    data = _load().copy()
    data[key] = value
    _save(data)
