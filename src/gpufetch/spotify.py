"""Spotify integration: PKCE OAuth flow + background currently-playing polling."""

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from typing import Optional

REDIRECT_URI       = "http://127.0.0.1:8888/callback"
SCOPES             = "user-read-currently-playing user-read-playback-state"
TOKEN_FILE         = os.path.expanduser("~/.config/lsgpu/spotify.json")
POLL_INTERVAL      = 5   # seconds between /currently-playing API calls
_DEFAULT_CLIENT_ID = "493c84a2c4bc420e944a19112158402c"


class SpotifyClient:
    def __init__(self):
        self.access_token:  Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.expires_at:    float         = 0.0
        self.client_id:     str           = os.getenv("SPOTIFY_CLIENT_ID", _DEFAULT_CLIENT_ID)
        self._load()

    # ── status ────────────────────────────────────────────────────────────────

    def is_connected(self) -> bool:
        return bool(self.refresh_token or
                    (self.access_token and time.time() < self.expires_at))

    # ── OAuth PKCE ────────────────────────────────────────────────────────────

    def connect(self) -> tuple[bool, str]:
        """
        Run the Authorization Code + PKCE flow.
        Blocks until the user authorises in browser (or 120 s timeout).
        Returns (success, message).
        """
        verifier  = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()
            ).rstrip(b"=").decode()
        )
        auth_url = (
            "https://accounts.spotify.com/authorize?"
            + urllib.parse.urlencode({
                "client_id":             self.client_id,
                "response_type":         "code",
                "redirect_uri":          REDIRECT_URI,
                "scope":                 SCOPES,
                "code_challenge_method": "S256",
                "code_challenge":        challenge,
            })
        )

        code_holder: dict = {}

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                params = urllib.parse.parse_qs(
                    urllib.parse.urlparse(self.path).query
                )
                if "code" in params:
                    code_holder["code"] = params["code"][0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>Authorized! Return to lsgpu.</h2></body></html>"
                )
            def log_message(self, *_):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 8888), _Handler)
        t   = threading.Thread(target=srv.handle_request, daemon=True)
        t.start()

        print(f"\nOpening browser for Spotify authorization…")
        print(f"If it doesn't open, visit:\n  {auth_url}\n")
        webbrowser.open(auth_url)
        t.join(timeout=120)
        srv.server_close()

        if "code" not in code_holder:
            return False, "Authorization timed out or was denied."

        data = urllib.parse.urlencode({
            "grant_type":    "authorization_code",
            "code":          code_holder["code"],
            "redirect_uri":  REDIRECT_URI,
            "client_id":     self.client_id,
            "code_verifier": verifier,
        }).encode()
        try:
            with urllib.request.urlopen(
                urllib.request.Request(
                    "https://accounts.spotify.com/api/token",
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                ),
                timeout=10,
            ) as resp:
                tok = json.loads(resp.read())
        except Exception as exc:
            return False, f"Token exchange failed: {exc}"

        self.access_token  = tok["access_token"]
        self.refresh_token = tok.get("refresh_token", self.refresh_token)
        self.expires_at    = time.time() + tok.get("expires_in", 3600)
        self._save()
        return True, "Connected to Spotify!"

    # ── token refresh ─────────────────────────────────────────────────────────

    def _refresh(self) -> bool:
        if not self.refresh_token:
            return False
        data = urllib.parse.urlencode({
            "grant_type":    "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id":     self.client_id,
        }).encode()
        try:
            with urllib.request.urlopen(
                urllib.request.Request(
                    "https://accounts.spotify.com/api/token",
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                ),
                timeout=10,
            ) as resp:
                tok = json.loads(resp.read())
            self.access_token = tok["access_token"]
            if "refresh_token" in tok:
                self.refresh_token = tok["refresh_token"]
            self.expires_at = time.time() + tok.get("expires_in", 3600)
            self._save()
            return True
        except Exception:
            return False

    # ── currently playing ─────────────────────────────────────────────────────

    def get_current_track(self) -> Optional[dict]:
        """Return track dict or None (nothing playing / not connected / error)."""
        if time.time() >= self.expires_at - 60:
            if not self._refresh():
                return None
        if not self.access_token:
            return None
        try:
            req = urllib.request.Request(
                "https://api.spotify.com/v1/me/player/currently-playing",
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 204:   # 204 = nothing playing
                    return None
                data = json.loads(resp.read())
        except Exception:
            return None

        if not data or not data.get("is_playing"):
            return None
        item = data.get("item") or {}
        return {
            "title":       item.get("name", "Unknown"),
            "artist":      ", ".join(a["name"] for a in item.get("artists", [])),
            "album":       item.get("album", {}).get("name", ""),
            "progress_ms": data.get("progress_ms", 0),
            "duration_ms": max(1, item.get("duration_ms", 1)),
            "is_playing":  data.get("is_playing", False),
        }

    # ── persistence ───────────────────────────────────────────────────────────

    def _save(self):
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with open(TOKEN_FILE, "w") as f:
            json.dump({
                "access_token":  self.access_token,
                "refresh_token": self.refresh_token,
                "expires_at":    self.expires_at,
                "client_id":     self.client_id,
            }, f)

    def _load(self):
        try:
            with open(TOKEN_FILE) as f:
                d = json.load(f)
            self.access_token  = d.get("access_token")
            self.refresh_token = d.get("refresh_token")
            self.expires_at    = float(d.get("expires_at", 0))
            if d.get("client_id"):
                self.client_id = d["client_id"]
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            pass


class SpotifyPoller:
    """Daemon thread — polls Spotify every POLL_INTERVAL seconds."""

    def __init__(self, client: SpotifyClient):
        self._client = client
        self._track:  Optional[dict] = None
        self._lock    = threading.Lock()
        self._stop    = threading.Event()
        self._thread  = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.wait(POLL_INTERVAL):
            try:
                track = self._client.get_current_track()
                with self._lock:
                    self._track = track
            except Exception:
                pass

    def get(self) -> Optional[dict]:
        with self._lock:
            return self._track

    def stop(self):
        self._stop.set()
