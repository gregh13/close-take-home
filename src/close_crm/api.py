"""Thin wrapper around Close REST API with Basic auth and 429 handling."""

from __future__ import annotations

import time
from typing import Any

import requests

from close_crm.config import API_BASE, LOG


class CloseAPI:
    """Thin wrapper around Close REST API with Basic auth and 429 handling."""

    def __init__(self, api_key: str, base_url: str = API_BASE) -> None:
        self._session = requests.Session()
        self._session.auth = (api_key, "")
        self._session.headers.update(
            {"Accept": "application/json", "Content-Type": "application/json"}
        )
        self._base = base_url.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
        max_retries: int = 6,
    ) -> Any:
        url = path if path.startswith("http") else f"{self._base}{path if path.startswith('/') else '/' + path}"
        attempt = 0
        while attempt < max_retries:
            resp = self._session.request(method, url, params=params, json=json_body)
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", "2"))
                LOG.warning("Rate limited (429); sleeping %.1fs", wait)
                time.sleep(min(wait, 60.0))
                attempt += 1
                continue
            if 500 <= resp.status_code < 600:
                time.sleep(1.5**attempt)
                attempt += 1
                continue
            if not resp.ok:
                body = (resp.text or "")[:8000]
                LOG.error("Close API %s %s: %s", resp.status_code, url, body or "(empty body)")
            resp.raise_for_status()
            if resp.content and "application/json" in resp.headers.get("Content-Type", ""):
                return resp.json()
            return None
        raise RuntimeError(f"Request failed after retries: {method} {url}")

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, json_body: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, json_body=json_body)

    def list_lead_custom_fields(self) -> list[dict[str, Any]]:
        """Paginate GET /custom_field/lead/."""
        out: list[dict[str, Any]] = []
        skip = 0
        limit = 200
        while True:
            data = self.get("/custom_field/lead/", params={"_limit": limit, "_skip": skip})
            if not isinstance(data, dict):
                break
            batch = data.get("data") or []
            for row in batch:
                if isinstance(row, dict):
                    out.append(row)
            if not data.get("has_more"):
                break
            if len(batch) < limit:
                break
            skip += limit
        return out

    def create_lead_custom_field(self, name: str, field_type: str) -> dict[str, Any]:
        return self.post("/custom_field/lead/", json_body={"name": name, "type": field_type})

    def create_lead(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.post("/lead/", json_body=payload)
        if not isinstance(result, dict):
            raise RuntimeError("Unexpected response from POST /lead/")
        return result

    def search_data(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST /data/search/ — returns dict with data, cursor, etc."""
        result = self.post("/data/search/", json_body=body)
        if not isinstance(result, dict):
            raise RuntimeError("Unexpected response from POST /data/search/")
        return result
