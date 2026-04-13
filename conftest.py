import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# Ensure required env vars exist so config.py can be imported in tests
# that do not care about these values (they monkeypatch what they need)
_REQUIRED_DEFAULTS = {
    "TELEGRAM_BOT_TOKEN": "test_token",
    "ADMIN_TELEGRAM_ID": "0",
    "ASANA_PAT": "test_pat",
    "ASANA_WORKSPACE_GID": "ws_test",
}
for _key, _val in _REQUIRED_DEFAULTS.items():
    os.environ.setdefault(_key, _val)
