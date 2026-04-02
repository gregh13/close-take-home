"""Thin wrapper around Close REST API with Basic auth and 429 handling."""

from __future__ import annotations

import time
from typing import Any

import requests

from close_crm.config import API_BASE, LOG

# API_BASE: default https://api.close.com/api/v1. LOG: rate-limit and error responses in request().


class CloseAPI:
    """Thin wrapper around Close REST API with Basic auth and 429 handling."""

    # All HTTP traffic goes through request(); get/post are thin wrappers.

    def __init__(self, api_key: str, base_url: str = API_BASE) -> None:
        """Auth as Basic (api_key, empty password); JSON headers; optional alternate base URL."""
        self._session = requests.Session()
        # Close expects HTTP Basic: username = API key, password empty.
        self._session.auth = (api_key, "")
        self._session.headers.update(
            {"Accept": "application/json", "Content-Type": "application/json"}
        )
        # Default https://api.close.com/api/v1 — strip trailing slash for joins in request().
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
        """HTTP request with retries on 429 and 5xx; logs error bodies; returns JSON or None."""
        # --- Absolute URL passthrough; else prefix _base (path may omit leading slash) ---
        url = path if path.startswith("http") else f"{self._base}{path if path.startswith('/') else '/' + path}"
        attempt = 0
        # -------------------------------------------------------------------------
        # Retry loop: 429 and 5xx count as retriable; other errors fail after logging body.
        # -------------------------------------------------------------------------
        while attempt < max_retries:
            resp = self._session.request(method, url, params=params, json=json_body)
            if resp.status_code == 429:
                # Honor Retry-After when present; cap sleep to avoid hanging the job.
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
        """GET relative path or absolute URL."""
        # Query string only; no request body (pagination uses _limit/_skip params).
        return self.request("GET", path, params=params)

    def post(self, path: str, json_body: dict[str, Any] | None = None) -> Any:
        """POST JSON body to path or absolute URL."""
        # Used for /lead/, /custom_field/lead/, /data/search/, etc.
        return self.request("POST", path, json_body=json_body)

    def list_lead_custom_fields(self) -> list[dict[str, Any]]:
        """Paginate GET /custom_field/lead/."""
        # -------------------------------------------------------------------------
        # _skip/_limit until has_more is false or a short page (end of collection).
        # -------------------------------------------------------------------------
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
        """POST /custom_field/lead/ — create a lead-level custom field."""
        # name / type must match Close-supported field types (date, number, text, …).
        return self.post("/custom_field/lead/", json_body={"name": name, "type": field_type})

    def create_lead(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /lead/ — create a lead (nested contacts and custom.* fields allowed)."""
        # Caller builds payload (e.g. CSVImporter.build_lead_payload); we assert JSON object back.
        result = self.post("/lead/", json_body=payload)
        if not isinstance(result, dict):
            raise RuntimeError("Unexpected response from POST /lead/")
        return result

    def search_data(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST /data/search/ — returns dict with data, cursor, etc."""
        # Advanced Search / reporting: body built in reporting.build_search_body.
        result = self.post("/data/search/", json_body=body)
        if not isinstance(result, dict):
            raise RuntimeError("Unexpected response from POST /data/search/")
        return result
