from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from typing import Callable
import time
import os
import logging

logger = logging.getLogger("mission_planner.middleware")


class SimpleRateLimiterMiddleware(BaseHTTPMiddleware):
    """A tiny in-memory rate limiter per key (IP or API key). Not distributed.

    Config via env:
      ENABLE_RATE_LIMIT (true/1 to enable)
      RATE_LIMIT_RPS (requests per second, default 5)
    """

    def __init__(self, app, rate_limit_rps: int = 5):
        super().__init__(app)
        self.rate = float(rate_limit_rps)
        self.state = {}  # key -> (tokens, last_ts)

    async def dispatch(self, request: Request, call_next: Callable):
        if not os.environ.get("ENABLE_RATE_LIMIT"):
            return await call_next(request)

        key = request.headers.get("x-api-key") or request.client.host
        now = time.time()
        tokens, last = self.state.get(key, (self.rate, now))
        # refill
        elapsed = max(0.0, now - last)
        tokens = min(self.rate, tokens + elapsed * self.rate)
        if tokens < 1.0:
            # rate limited
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
        tokens -= 1.0
        self.state[key] = (tokens, now)
        return await call_next(request)


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Optional simple API-key auth. Enable by setting ENABLE_AUTH=1 and API_KEY env var.
    Exempts GET public endpoints if needed (keeps minimal surface).
    """

    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable):
        if not os.environ.get("ENABLE_AUTH"):
            return await call_next(request)

        # Allow safe methods to be optionally public (configurable later). For now require key for non-GET.
        if request.method == "GET" and os.environ.get("AUTH_REQUIRED_FOR_GET") != "1":
            return await call_next(request)

        api_key = os.environ.get("API_KEY")
        if not api_key:
            return JSONResponse({"detail": "server misconfigured: API_KEY not set"}, status_code=500)
        provided = request.headers.get("x-api-key")
        if provided != api_key:
            return JSONResponse({"detail": "invalid or missing API key"}, status_code=401)
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        start = time.time()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception as e:
            status = 500
            raise
        finally:
            duration = time.time() - start
            try:
                client = request.client.host
            except Exception:
                client = "-"
            logger.info({
                "method": request.method,
                "path": request.url.path,
                "status": status,
                "duration_s": round(duration, 4),
                "client": client,
            })
        return response


def init_sentry_if_configured():
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return None
    try:
        import sentry_sdk
        sentry_sdk.init(dsn, traces_sample_rate=0.1)
        logger.info("Sentry initialized")
        return sentry_sdk
    except Exception:
        logger.exception("Failed to initialize Sentry SDK")
        return None
