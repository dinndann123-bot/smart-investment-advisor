"""Alpaca trading-endpoint compatibility layer.

Retries Alpaca Trading API calls against the live host when paper credentials are
not accepted. It also prints safe configuration diagnostics at process startup so
Render logs can confirm that required environment variables are actually present.
Secret values are never printed.
"""
import os
from urllib.parse import urlsplit, urlunsplit

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None


def _configured(name):
    return bool((os.getenv(name) or "").strip())


# Safe startup diagnostics: presence only, never values.
print(
    "ALPACA_RUNTIME_CONFIG "
    f"api_key={'set' if _configured('ALPACA_API_KEY') else 'missing'} "
    f"secret_key={'set' if _configured('ALPACA_SECRET_KEY') else 'missing'} "
    f"feed={(os.getenv('ALPACA_FEED') or 'iex').strip().lower()}"
)


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
