"""Flow client for connecting to another JuhRadialMX computer"""

import logging
from typing import Optional

logger = logging.getLogger("juhradial.flow.client")

from .constants import FLOW_PORT
from .clipboard import get_clipboard
from .keys import get_public_key_hex, derive_and_store_peer_key


class FlowClient:
    """Client for connecting to another JuhRadialMX computer"""

    def __init__(self, server_ip: str, server_port: int = FLOW_PORT):
        self.server_ip = server_ip
        self.server_port = server_port
        self.token: Optional[str] = None
        self.peer_public_key: Optional[str] = None
        self.peer_aes_key: Optional[bytes] = None

    def pair(self, pairing_code: str, my_name: str) -> bool:
        import requests

        try:
            url = f"http://{self.server_ip}:{self.server_port}/pair"
            pair_data = {
                'pairing_code': pairing_code,
                'name': my_name,
                'public_key': get_public_key_hex(),
            }
            response = requests.post(url, json=pair_data, timeout=5)
            if response.ok:
                data = response.json()
                self.token = data.get('token')
                self.peer_public_key = data.get('public_key', '')

                # Derive and store peer AES key if server sent a public key
                if self.peer_public_key:
                    peer_name = data.get('hostname', self.server_ip)
                    self.peer_aes_key = derive_and_store_peer_key(
                        peer_name, self.peer_public_key,
                        self.server_ip, self.server_port
                    )
                    logger.info("Crypto key exchange complete with %s", peer_name)

                return True
        except Exception as e:
            logger.warning("Pairing failed: %s", e)
        return False

    def get_server_info(self) -> Optional[dict]:
        import requests

        try:
            url = f"http://{self.server_ip}:{self.server_port}/info"
            response = requests.get(url, timeout=2)
            if response.ok:
                return response.json()
        except Exception as e:
            logger.debug("Error getting server info: %s", e)
        return None

    def notify_host_change(self, new_host: int) -> bool:
        import requests

        if not self.token:
            return False

        try:
            url = f"http://{self.server_ip}:{self.server_port}/host_changed"
            response = requests.post(
                url,
                json={'host': new_host},
                headers={'Authorization': f'Bearer {self.token}'},
                timeout=2
            )
            return response.ok
        except Exception as e:
            logger.debug("Error notifying host change: %s", e)
        return False

    def sync_clipboard(self) -> bool:
        import requests

        if not self.token:
            return False

        clipboard_content = get_clipboard()
        if not clipboard_content:
            return True

        try:
            url = f"http://{self.server_ip}:{self.server_port}/clipboard"
            response = requests.post(
                url,
                data=clipboard_content,
                headers={'Authorization': f'Bearer {self.token}'},
                timeout=2
            )
            return response.ok
        except Exception as e:
            logger.debug("Error syncing clipboard: %s", e)
        return False

    def get_clipboard(self) -> Optional[str]:
        import requests

        if not self.token:
            return None

        try:
            url = f"http://{self.server_ip}:{self.server_port}/clipboard"
            response = requests.get(
                url,
                headers={'Authorization': f'Bearer {self.token}'},
                timeout=2
            )
            if response.ok:
                return response.text
        except Exception as e:
            logger.debug("Error getting clipboard: %s", e)
        return None
