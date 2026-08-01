from __future__ import annotations

from collections import defaultdict, deque
from ipaddress import ip_address, ip_network
from threading import Lock
from time import monotonic

from fastapi import HTTPException, Request, status

from backend.config import settings


class InMemoryRateLimiter:
    """Small single-process limiter. Put a shared limiter at the proxy for multi-worker deployments."""

    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def enforce(self, key: str, limit: int, window_seconds: int) -> None:
        now = monotonic()
        with self._lock:
            attempts = self._attempts[key]
            while attempts and attempts[0] <= now - window_seconds:
                attempts.popleft()
            if len(attempts) >= limit:
                retry_after = max(1, int(window_seconds - (now - attempts[0])))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Try again later.",
                    headers={"Retry-After": str(retry_after)},
                )
            attempts.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._attempts.clear()


limiter = InMemoryRateLimiter()


def client_ip(request: Request) -> str:
    direct = request.client.host if request.client else "unknown"
    try:
        trusted = any(
            ip_address(direct) in ip_network(network.strip(), strict=False)
            for network in settings.trusted_proxies.split(",")
            if network.strip()
        )
    except ValueError:
        trusted = False
    forwarded = request.headers.get("x-forwarded-for")
    if trusted and forwarded:
        candidate = forwarded.split(",", 1)[0].strip()
        try:
            return str(ip_address(candidate))
        except ValueError:
            pass
    return direct


def enforce_auth_limit(
    request: Request,
    endpoint: str,
    identifier: str,
    *,
    login: bool = False,
) -> tuple[str, str]:
    address = client_ip(request)
    normalized = identifier.strip().casefold()
    attempts = settings.login_rate_limit_attempts if login else settings.auth_rate_limit_attempts
    window = settings.login_rate_limit_window_seconds if login else settings.auth_rate_limit_window_seconds
    ip_key = f"auth:{endpoint}:ip:{address}"
    identity_key = f"auth:{endpoint}:identity:{normalized}"
    limiter.enforce(ip_key, attempts, window)
    limiter.enforce(identity_key, attempts, window)
    return ip_key, identity_key
