"""Which JuhFlow computers may use Flow with this one.

The bridge's key exchange is anonymous, so any computer on the network could
connect. A computer's public key fingerprint is pinned when the user approves
it in Settings (trust on first use); until then it gets nothing from this
computer (no clipboard, no cursor) and its messages are ignored. A denied key
is disconnected.

~/.config/juhradial/flow_trusted.json:
    {"trusted": {"<fingerprint>": {"hostname", "platform", "at"}},
     "denied":  {"<fingerprint>": {"hostname", "platform", "at"}}}
The settings app writes the same file (settings-qt/bridge/backend.py).
"""

import hashlib
import json
import os
import time
from pathlib import Path

TRUST_FILE = Path.home() / ".config" / "juhradial" / "flow_trusted.json"

TRUSTED = "trusted"
DENIED = "denied"
PENDING = "pending"


def fingerprint(public_key: bytes) -> str:
    """First 16 hex digits of the key's SHA-256, in groups of four."""
    digest = hashlib.sha256(public_key).hexdigest()[:16].upper()
    return " ".join(digest[i:i + 4] for i in range(0, 16, 4))


class TrustStore:
    """The trust file, re-read when it changes (Settings edits it)."""

    def __init__(self, path=None):
        self.path = Path(path) if path else TRUST_FILE
        self._mtime = None
        self._data = {TRUSTED: {}, DENIED: {}}

    def _load(self):
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self._mtime, self._data = None, {TRUSTED: {}, DENIED: {}}
            return self._data
        if mtime != self._mtime:
            try:
                data = json.loads(self.path.read_text())
            except (OSError, ValueError):
                data = {}
            self._data = {TRUSTED: dict(data.get(TRUSTED) or {}),
                          DENIED: dict(data.get(DENIED) or {})}
            self._mtime = mtime
        return self._data

    def state(self, fp: str) -> str:
        data = self._load()
        if fp in data[DENIED]:
            return DENIED
        return TRUSTED if fp in data[TRUSTED] else PENDING

    def set_state(self, fp: str, state: str, hostname: str = "", platform: str = ""):
        """Approve (trusted), deny (denied) or forget (pending) a computer."""
        data = self._load()
        for key in (TRUSTED, DENIED):
            data[key].pop(fp, None)
        if state in (TRUSTED, DENIED):
            data[state][fp] = {"hostname": hostname, "platform": platform, "at": int(time.time())}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        self._mtime = None
