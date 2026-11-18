"""Shared HTTP session and retry behavior."""

import logging
import os
import time

import requests

LOGGER = logging.getLogger(__name__)
RETRY_STATUS = {429, 500, 502, 503, 504}


def create_session() -> requests.Session:
    """Create the shared session used by all API requests."""
    session = requests.Session()
    session.headers.update({"User-Agent": "charles-river-flood-ml/0.1 (+data collection)"})
    key = os.getenv("USGS_API_KEY")
    if key:
        session.headers.update({"X-Api-Key": key})
    return session


def retry_request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    params: dict | None = None,
    timeout: float = 180,
    tries: int = 6,
) -> requests.Response:
    """Request a URL with exponential backoff and Retry-After support."""
    delay = 1.0
    last_error: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            response = session.request(method, url, params=params, timeout=timeout)
            if response.status_code not in RETRY_STATUS:
                response.raise_for_status()
                remaining = response.headers.get("X-RateLimit-Remaining")
                if remaining is not None:
                    try:
                        if int(remaining) < 50:
                            LOGGER.warning("USGS API rate limit remaining: %s", remaining)
                    except ValueError:
                        pass
                return response
            if attempt == tries:
                response.raise_for_status()
        except requests.RequestException as exc:
            last_error = exc
            if attempt == tries:
                raise
        if attempt < tries:
            retry_after = locals().get("response")
            seconds: float = delay
            if retry_after is not None:
                value = getattr(retry_after, "headers", {}).get("Retry-After")
                if value:
                    try:
                        seconds = float(value)
                    except ValueError:
                        pass
            LOGGER.warning("HTTP retry %d/%d in %.1f seconds", attempt, tries, seconds)
            time.sleep(seconds)
            delay *= 2
    if last_error is not None:
        raise last_error
    raise requests.HTTPError("request failed")
