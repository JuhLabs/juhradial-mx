"""Flow client for connecting to another JuhRadialMX computer"""

from typing import Optional

from flow.constants import FLOW_PORT
from flow.clipboard import get_clipboard


class FlowClient:
    """Client for connecting to another JuhRadialMX computer"""

    def __init__(self, server_ip: str, server_port: int = FLOW_PORT):
        self.server_ip = server_ip
        self.server_port = server_port
        self.token: Optional[str] = None

    def pair(self, pairing_code: str, my_name: str) -> bool:
        import requests

        try:
            url = f"http://{self.server_ip}:{self.server_port}/pair"
            response = requests.post(
                url,
                json={'pairing_code': pairing_code, 'name': my_name},
                timeout=5
            )
            if response.ok:
                data = response.json()
                self.token = data.get('token')
                return True
        except Exception as e:
            print(f"[Flow Client] Pairing failed: {e}")
        return False

    def get_server_info(self) -> Optional[dict]:
        import requests

        try:
            url = f"http://{self.server_ip}:{self.server_port}/info"
            response = requests.get(url, timeout=2)
            if response.ok:
                return response.json()
        except Exception as e:
            print(f"[Flow Client] Error getting server info: {e}")
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
            print(f"[Flow Client] Error notifying host change: {e}")
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
            print(f"[Flow Client] Error syncing clipboard: {e}")
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
            print(f"[Flow Client] Error getting clipboard: {e}")
        return None
