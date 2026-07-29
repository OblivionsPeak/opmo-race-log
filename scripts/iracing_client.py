"""
Minimal iRacing Data API client — OAuth2 "password_limited" grant.

Vendored deliberately: this repo is a static site and should not import from
operation-motorsport-dashboard. The masking algorithm below is iRacing's:
base64(sha256(value + identifier.trim().lower())), STANDARD base64 — the token
endpoint explicitly rejects URL-safe base64.

Requires an OAuth client registered at
https://oauth.iracing.com/accountmanagement that is authorised for the
password_limited grant (iRacing must enable that grant for the client).
"""
import base64
import hashlib
import json
import os
import pathlib
import time

try:
    from curl_cffi import requests as http
    _IMPERSONATE = {'impersonate': 'chrome124'}
except ImportError:                      # plain requests works too, just likelier to be filtered
    import requests as http              # type: ignore
    _IMPERSONATE = {}

OAUTH_TOKEN_URL = 'https://oauth.iracing.com/oauth2/token'
DATA_BASE = 'https://members-ng.iracing.com'


def _mask(value: str, identifier: str) -> str:
    return base64.b64encode(
        hashlib.sha256((value + identifier.strip().lower()).encode('utf-8')).digest()
    ).decode('utf-8')


def load_env(*candidates: pathlib.Path) -> None:
    """Populate os.environ from the first .env found. Existing vars win."""
    for path in candidates:
        if not path or not path.is_file():
            continue
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, val = line.split('=', 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
        return


class IRacingError(RuntimeError):
    pass


class IRacingClient:
    def __init__(self):
        self._s = http.Session(**_IMPERSONATE)
        self._token = None
        self._expires_at = 0.0

    def login(self) -> None:
        try:
            email = os.environ['IRACING_EMAIL'].strip()
            password = os.environ['IRACING_PASSWORD']
            client_id = os.environ['IRACING_CLIENT_ID'].strip()
            client_secret = os.environ['IRACING_CLIENT_SECRET']
        except KeyError as e:
            raise IRacingError(
                f'Missing {e.args[0]} — put it in .env (see .env.example).'
            ) from None

        r = self._s.post(OAUTH_TOKEN_URL, data={
            'grant_type': 'password_limited',
            'client_id': client_id,
            'client_secret': _mask(client_secret, client_id),
            'username': email,
            'password': _mask(password, email),
            'scope': 'iracing.auth',
        })

        if r.status_code != 200:
            detail = ''
            try:
                j = r.json()
                detail = f" — {j.get('error')}: {j.get('error_description')}"
            except Exception:
                detail = ' — ' + r.text[:200]
            hint = ''
            if 'invalid_client' in detail:
                hint = (
                    '\n\nThe request format is correct, so this is the registration, not the code:'
                    '\n  1. Open https://oauth.iracing.com/accountmanagement and confirm the'
                    '\n     OAuth client still exists and is enabled.'
                    '\n  2. Confirm it is authorised for the "password_limited" grant — iRacing'
                    '\n     must enable that grant per-client; it is not on by default.'
                    '\n  3. Regenerate the client secret and paste it into .env.'
                )
            raise IRacingError(f'iRacing OAuth login failed [{r.status_code}]{detail}{hint}')

        tok = r.json()
        if 'access_token' not in tok:
            raise IRacingError(f'Token response had no access_token: {tok}')
        self._token = tok['access_token']
        self._expires_at = time.time() + tok.get('expires_in', 600) - 30

    def get(self, path: str, **params):
        """GET a /data endpoint, following the S3 link the API returns."""
        if not self._token or time.time() > self._expires_at:
            self.login()
        r = self._s.get(DATA_BASE + path, params=params,
                        headers={'Authorization': 'Bearer ' + self._token})
        if r.status_code != 200:
            raise IRacingError(f'GET {path} failed [{r.status_code}]: {r.text[:200]}')
        data = r.json()
        # most endpoints hand back a signed link to the real payload
        if isinstance(data, dict) and 'link' in data and len(data) <= 3:
            data = self._s.get(data['link']).json()
        return data

    def chunked(self, payload: dict) -> list:
        """Expand a chunked result payload into a flat list."""
        info = (payload or {}).get('chunk_info') or {}
        base = info.get('base_download_url')
        files = info.get('chunk_file_names') or []
        if not base or not files:
            return []
        out = []
        for name in files:
            out.extend(self._s.get(base + name).json())
        return out

    def download(self, url: str, dest: pathlib.Path) -> bool:
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = self._s.get(url)
        if r.status_code != 200 or not r.content:
            return False
        dest.write_bytes(r.content)
        return True


def write_json(path: pathlib.Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n', encoding='utf-8')
