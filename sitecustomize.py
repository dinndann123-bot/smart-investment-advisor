"""Alpaca trading-endpoint compatibility layer.

The app historically hard-coded paper-api.alpaca.markets for clock/calendar/assets.
Alpaca paper and live credentials are separate. Until those call sites are fully
centralized, retry only Alpaca Trading API requests against the matching live host
when the paper host rejects authentication. Market Data (data.alpaca.markets) is
never rewritten.
"""
from urllib.parse import urlsplit, urlunsplit

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None


def _live_alpaca_url(url):
    try:
        text = str(url)
        parts = urlsplit(text)
        if parts.hostname != "paper-api.alpaca.markets":
            return None
        return urlunsplit((parts.scheme, "api.alpaca.markets", parts.path, parts.query, parts.fragment))
    except Exception:
        return None


if httpx is not None and not getattr(httpx.AsyncClient, "_alpaca_env_retry_installed", False):
    _original_get = httpx.AsyncClient.get

    async def _alpaca_environment_aware_get(self, url, *args, **kwargs):
        response = await _original_get(self, url, *args, **kwargs)
        retry_url = _live_alpaca_url(url)
        if retry_url and response.status_code in (401, 403):
            return await _original_get(self, retry_url, *args, **kwargs)
        return response

    httpx.AsyncClient.get = _alpaca_environment_aware_get
    httpx.AsyncClient._alpaca_env_retry_installed = True
