import logging
import requests

logger = logging.getLogger("waha_client")

class WAHAClient:
    def __init__(self, api_url: str = "http://localhost:3000", session: str = "default", api_key: str = ""):
        self.api_url = api_url.rstrip("/")
        self.session = session
        self.api_key = api_key

    def send_text(self, chat_id: str, message: str, reply_to: str = None) -> bool:
        url = f"{self.api_url}/api/sendText"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key

        payload = {
            "session": self.session,
            "chatId": chat_id,
            "text": message
        }
        if reply_to:
            payload["reply_to"] = reply_to

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code in [200, 201]:
                return True
            # Fallback tanpa reply_to jika engine WAHA menolak parameter reply_to
            if reply_to:
                payload.pop("reply_to", None)
                resp = requests.post(url, json=payload, headers=headers, timeout=10)
                if resp.status_code in [200, 201]:
                    return True
            logger.error(f"WAHA send error: HTTP {resp.status_code} - {resp.text}")
            return False
        except Exception as e:
            logger.error(f"WAHA request failed: {e}")
            return False

    def get_groups(self) -> list[dict]:
        """Ambil daftar grup WhatsApp dari WAHA untuk memudahkan pencarian Group ID."""
        url = f"{self.api_url}/api/{self.session}/groups"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data
            logger.error(f"WAHA get_groups error: HTTP {resp.status_code} - {resp.text}")
            return []
        except Exception as e:
            logger.error(f"WAHA get_groups request failed: {e}")
            return []
