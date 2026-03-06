"""Token and linked computers managers for Flow"""

import json
import time
import uuid
from typing import Optional, Dict

from .constants import DATA_DIR, TOKENS_FILE, LINKED_COMPUTERS_FILE


class FlowTokenManager:
    """Manages authentication tokens for Flow connections"""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.tokens: Dict[str, str] = {}
        self._load_tokens()

    def _load_tokens(self):
        if TOKENS_FILE.exists():
            try:
                with open(TOKENS_FILE, 'r', encoding='utf-8') as f:
                    self.tokens = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.tokens = {}

    def _save_tokens(self):
        with open(TOKENS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.tokens, f)

    def create_token(self, name: str) -> str:
        token = str(uuid.uuid4())
        self.tokens[name] = token
        self._save_tokens()
        return token

    def verify_token(self, token: str) -> Optional[str]:
        for name, stored_token in self.tokens.items():
            if stored_token == token:
                return name
        return None

    def revoke_token(self, name: str) -> bool:
        if name in self.tokens:
            del self.tokens[name]
            self._save_tokens()
            return True
        return False


class LinkedComputersManager:
    """Manages linked computers for Flow"""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.computers: Dict[str, dict] = {}
        self._load()

    def _load(self):
        if LINKED_COMPUTERS_FILE.exists():
            try:
                with open(LINKED_COMPUTERS_FILE, 'r', encoding='utf-8') as f:
                    self.computers = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.computers = {}

    def _save(self):
        with open(LINKED_COMPUTERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.computers, f, indent=2)

    def add_computer(self, name: str, ip: str, port: int, token: str,
                     public_key: str = "") -> None:
        self.computers[name] = {
            'ip': ip,
            'port': port,
            'token': token,
            'public_key': public_key,
            'linked_at': time.time()
        }
        self._save()

    def remove_computer(self, name: str) -> bool:
        if name in self.computers:
            del self.computers[name]
            self._save()
            return True
        return False

    def get_all(self) -> Dict[str, dict]:
        return self.computers.copy()
