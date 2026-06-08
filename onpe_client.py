"""HTTP client for the ONPE second-round results API."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://resultadosegundavuelta.onpe.gob.pe/presentacion-backend"
ID_ELECCION = 10


class ONPEClientError(RuntimeError):
    """Raised when the ONPE API returns an unexpected or failed response."""


class ONPEClient:
    """Small, throttled client around the public ONPE endpoints."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        id_eleccion: int = ID_ELECCION,
        timeout: float = 20.0,
        sleep_seconds: float = 0.2,
        save_raw_json: bool = False,
        raw_dir: str | Path = "raw",
        retries: int = 3,
        backoff_factor: float = 0.5,
        non_json_retries: int = 4,
        logger: logging.Logger | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.id_eleccion = id_eleccion
        self.timeout = timeout
        self.sleep_seconds = sleep_seconds
        self.save_raw_json = save_raw_json
        self.raw_dir = Path(raw_dir)
        self.non_json_retries = non_json_retries
        self.backoff_factor = backoff_factor
        self.logger = logger or logging.getLogger(__name__)
        self._last_request_at: float | None = None
        parsed_base = urlparse(self.base_url)
        origin = f"{parsed_base.scheme}://{parsed_base.netloc}"

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/148.0.0.0 Safari/537.36"
                ),
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.8",
                "Content-Type": "application/json",
                "Referer": f"{origin}/main/resumen",
                "Sec-CH-UA": (
                    '"Chromium";v="148", "Google Chrome";v="148", '
                    '"Not/A)Brand";v="99"'
                ),
                "Sec-CH-UA-Mobile": "?0",
                "Sec-CH-UA-Platform": '"macOS"',
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            }
        )
        retry = Retry(
            total=retries,
            connect=retries,
            read=retries,
            status=retries,
            backoff_factor=backoff_factor,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        """GET an endpoint and return the endpoint's normalized ``data`` value."""

        clean_path = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{clean_path}"
        request_params = dict(params or {})

        last_error: ONPEClientError | None = None
        for attempt in range(1, self.non_json_retries + 2):
            self._throttle()
            self.logger.debug(
                "GET %s params=%s attempt=%s", clean_path, request_params, attempt
            )
            response = self.session.get(
                url, params=request_params, timeout=self.timeout
            )
            self._last_request_at = time.monotonic()
            response.raise_for_status()

            try:
                payload = response.json()
                break
            except ValueError as exc:
                last_error = self._non_json_error(response, exc)
                if attempt > self.non_json_retries:
                    raise last_error from exc
                wait_seconds = self.backoff_factor * attempt
                self.logger.warning(
                    "ONPE returned non-JSON content for %s; retrying in %.2fs "
                    "(attempt %s/%s)",
                    response.url,
                    wait_seconds,
                    attempt,
                    self.non_json_retries + 1,
                )
                time.sleep(wait_seconds)
        else:
            raise last_error or ONPEClientError(f"Could not fetch JSON: {url}")

        if self.save_raw_json:
            self._save_raw_json(response.url, payload)

        return self._normalize_payload(payload, response.url)

    def get_departamentos(self, id_ambito_geografico: int) -> list[dict[str, Any]]:
        return self.get_json(
            "/ubigeos/departamentos",
            {
                "idEleccion": self.id_eleccion,
                "idAmbitoGeografico": id_ambito_geografico,
            },
        )

    def get_provincias(
        self, id_ambito_geografico: int, id_ubigeo_departamento: str
    ) -> list[dict[str, Any]]:
        return self.get_json(
            "/ubigeos/provincias",
            {
                "idEleccion": self.id_eleccion,
                "idAmbitoGeografico": id_ambito_geografico,
                "idUbigeoDepartamento": id_ubigeo_departamento,
            },
        )

    def get_distritos(
        self, id_ambito_geografico: int, id_ubigeo_provincia: str
    ) -> list[dict[str, Any]]:
        return self.get_json(
            "/ubigeos/distritos",
            {
                "idEleccion": self.id_eleccion,
                "idAmbitoGeografico": id_ambito_geografico,
                "idUbigeoProvincia": id_ubigeo_provincia,
            },
        )

    def get_totales(self, params: Mapping[str, Any]) -> dict[str, Any]:
        return self.get_json("/resumen-general/totales", params)

    def get_participantes(self, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        return self.get_json("/resumen-general/participantes", params)

    def check_api_available(self) -> None:
        """Fail early if the configured base URL is serving non-API content."""

        self.get_json("/proceso/proceso-electoral-activo")

    def _non_json_error(self, response: requests.Response, exc: Exception) -> ONPEClientError:
        content_type = response.headers.get("content-type", "")
        x_cache = response.headers.get("x-cache", "")
        snippet = response.text[:300].replace("\n", "\\n").replace("\r", "\\r")
        hint = ""
        if "<!doctype html" in response.text[:100].lower():
            hint = (
                " The server returned the frontend HTML instead of the API; "
                "this is often an intermittent CloudFront fallback. Try a higher "
                "--sleep value if it persists."
            )
        return ONPEClientError(
            "Response is not JSON "
            f"(status={response.status_code}, content-type={content_type}, "
            f"x-cache={x_cache}) for {response.url}. "
            f"First bytes: {snippet!r}.{hint}"
        )

    def _throttle(self) -> None:
        if self.sleep_seconds <= 0 or self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait_seconds = self.sleep_seconds - elapsed
        if wait_seconds > 0:
            time.sleep(wait_seconds)

    def _save_raw_json(self, url: str, payload: Any) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe = _safe_filename(url)
        path = self.raw_dir / f"{ts}_{safe}.json"
        with path.open("w", encoding="utf-8") as fh:
            json.dump(
                {
                    "url": url,
                    "captured_at": ts,
                    "data": payload,
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )

    def _normalize_payload(self, payload: Any, url: str) -> Any:
        if isinstance(payload, dict) and "success" in payload and "data" in payload:
            if payload.get("success") is not True:
                message = payload.get("message") or "ONPE response success=false"
                raise ONPEClientError(f"{message}: {url}")
            return payload.get("data")
        return payload


def _safe_filename(url: str) -> str:
    url = url.replace("https://", "").replace("http://", "")
    url = url.replace("?", "_").replace("/", "_")
    url = url.replace("&", "_").replace("=", "_")
    encoded = urlencode({"u": url})[2:].replace("%", "")
    return encoded[:180]
