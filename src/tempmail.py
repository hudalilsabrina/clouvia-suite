"""
Clouvia Suite - Tempik API Client
Disposable temp-mail client. API mengikuti tempik:
https://github.com/hirotomasato/tempik

Endpoints:
  GET  /api/session               → { sessionId }
  POST /api/inboxes                → { address, created_at }
  GET  /api/inboxes/{addr}/messages → [ { subject, body, from_address, received_at } ]
"""

import asyncio
import json
import random
import re
import time
import urllib.request
from typing import List, Optional, Dict, Any

from .config import TEMPIK_BASE

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/132.0.0.0 Safari/537.36"
)


class TempikClient:
    """Tempik disposable email API client."""

    def __init__(self, base_url: str = None):
        self.base_url = (base_url or TEMPIK_BASE).rstrip("/")
        self.session_id: Optional[str] = None
        self._email: Optional[str] = None
        self._domains: List[str] = []

    def init_session(self) -> str:
        """Create a new session. Returns sessionId."""
        if self.session_id:
            return self.session_id

        url = f"{self.base_url}/session"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", _BROWSER_UA)

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            self.session_id = data.get("sessionId")
            if not self.session_id:
                raise ValueError(f"No sessionId in response: {data}")
            return self.session_id

    def _fetch_domains(self) -> List[str]:
        if self._domains:
            return self._domains

        self.init_session()
        # tempik menyediakan domain di /config (bukan /domains)
        for path in ("/config", "/domains"):
            req = urllib.request.Request(f"{self.base_url}{path}", method="GET")
            req.add_header("Accept", "application/json")
            req.add_header("User-Agent", _BROWSER_UA)
            if self.session_id:
                req.add_header("x-session-id", self.session_id)
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode())
            except Exception:
                continue
            raw = []
            if isinstance(data, dict):
                raw = (data.get("mailDomains") or data.get("domains")
                       or ([data["mailDomain"]] if data.get("mailDomain") else []))
            elif isinstance(data, list):
                raw = data
            domains = [d.get("name", d) if isinstance(d, dict) else str(d) for d in raw]
            domains = [d for d in domains if d]
            if domains:
                self._domains = domains
                return domains
        return ["example.com"]

    def create_inbox(self, local_part: str = None, domain: str = None) -> str:
        """Create a new inbox. Returns email address."""
        self.init_session()

        if not domain:
            domains = self._fetch_domains()
            domain = random.choice(domains) if domains else "example.com"

        if not local_part:
            animals = ["kucing", "harimau", "elang", "singa", "serigala", "rajawali", "garuda", "badak"]
            adjectives = ["cepat", "tangkas", "cerdas", "hebat", "sigap", "tenang", "berani", "kuat"]
            local_part = f"{random.choice(animals)}{random.choice(adjectives)}{random.randint(10, 99)}"

        payload = {"name": local_part, "domain": domain}
        url = f"{self.base_url}/inboxes"
        data = json.dumps(payload).encode()

        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", _BROWSER_UA)
        if self.session_id:
            req.add_header("x-session-id", self.session_id)

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            addr = data.get("address") or f"{local_part}@{domain}"
            self._email = addr
            return addr

    def get_messages(self, address: str = None) -> List[Dict[str, Any]]:
        """Get all messages for an inbox address."""
        self.init_session()
        addr = address or self._email
        if not addr:
            raise ValueError("No email address provided")

        url = f"{self.base_url}/inboxes/{addr}/messages"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", _BROWSER_UA)
        if self.session_id:
            req.add_header("x-session-id", self.session_id)

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if isinstance(data, list):
                return data
            return data.get("messages", [])

    def wait_for_verification_link(self, address: str = None, timeout: int = 60, interval: int = 4) -> Optional[str]:
        """Poll inbox until Clouvia verification link arrives."""
        addr = address or self._email
        start = time.time()
        while time.time() - start < timeout:
            try:
                msgs = self.get_messages(addr)
                for m in msgs:
                    body = m.get("body", "") + " " + m.get("text", "") + " " + m.get("html", "")
                    match = re.search(r'https://clouvia\.ai/verify-email\?[^\s"<>]+', body)
                    if match:
                        return match.group(0)
            except Exception:
                pass
            time.sleep(interval)
        return None
