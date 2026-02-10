import requests
import re
import time
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional

from app.engine.utils import extract_token_from_json
from app.config import BASE_URL
from app.redis import update_session

class ECourtsClient:
    """
    Stateless client.
    All state (cookies, token) must be injected on creation
    and persisted back to Redis after each request.
    """

    def __init__(
        self,
        session_id: str,
        app_token: Optional[str] = None,
        cookies: Optional[Dict[str, str]] = None,
    ):
        self.session_id = session_id
        self.session = requests.Session()
        self.current_token = app_token

        if cookies:
            self.session.cookies.update(cookies)

        self.session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": "https://services.ecourts.gov.in/",
            "Origin": "https://services.ecourts.gov.in",
        })

    def _persist_state(self):
        update_session(self.session_id, {
            "app_token": self.current_token,
            "cookies": self.session.cookies.get_dict()
        })

    def _update_token(self, response):
        token = extract_token_from_json(response)
        if token:
            self.current_token = token

    def _post(self, endpoint: str, data: Dict[str, Any]):
        url = f"{BASE_URL}/?p={endpoint}"

        if self.current_token and "app_token" not in data:
            data["app_token"] = self.current_token

        data.setdefault("ajax_req", "true")

        resp = self.session.post(url, data=data)
        self._update_token(resp)
        self._persist_state()

        return resp

    def bootstrap(self):
        url = f"{BASE_URL}/?p=casestatus/index"

        headers = self.session.headers.copy()
        headers.pop("X-Requested-With", None)
        headers.pop("Content-Type", None)

        resp = self.session.get(url, headers=headers)

        soup = BeautifulSoup(resp.text, "html.parser")
        token_input = soup.find("input", {"name": "app_token"})

        if token_input:
            self.current_token = token_input["value"]
        else:
            match = re.search(r'app_token\s*=\s*["\']([^"\']+)["\']', resp.text)
            if match:
                self.current_token = match.group(1)

        self._persist_state()
        return self.current_token

    def get_captcha(self) -> bytes:
        self._post("casestatus/getCaptcha", {})

        ts = int(time.time() * 1000)
        img_url = f"{BASE_URL}/vendor/securimage/securimage_show.php?{ts}"

        headers = self.session.headers.copy()
        headers.pop("X-Requested-With", None)
        headers.pop("Content-Type", None)

        resp = self.session.get(img_url, headers=headers)
        self._persist_state()
        return resp.content