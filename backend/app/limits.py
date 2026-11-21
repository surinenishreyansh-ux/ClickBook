"""Best-effort abuse protection for the single-worker ClickBook pilot.

This counter is process-local and resets on restart. It limits common
automated guessing but does not replace edge/WAF protections or a durable
shared limiter for a multi-worker production deployment.
"""
from collections import defaultdict, deque
import threading
import time
from fastapi import HTTPException

_LOCK = threading.Lock()
_REQUESTS = defaultdict(deque)
_MAX_BUCKETS = 5000


def check_rate(action: str, identity: str, *, limit: int, period: int) -> None:
    """Record a request and return 429 if the bucket is over limit."""
    now = time.monotonic()
    key = (action, identity)
    with _LOCK:
        if len(_REQUESTS) >= _MAX_BUCKETS and key not in _REQUESTS:
            # Prune stale buckets (including any with different time windows).
            for bucket, samples in list(_REQUESTS.items()):
                while samples and samples[0] <= now - 3600:
                    samples.popleft()
                if not samples:
                    _REQUESTS.pop(bucket, None)
            if len(_REQUESTS) >= _MAX_BUCKETS:
                raise HTTPException(429, 'Too many requests. Try again later.')
        hits = _REQUESTS[key]
        while hits and hits[0] <= now - period:
            hits.popleft()
        if len(hits) >= limit:
            raise HTTPException(
                status_code=429,
                detail='Too many requests. Try again later.',
                headers={'Retry-After': str(period)}
            )
        hits.append(now)


def clear_for_tests() -> None:
    with _LOCK:
        _REQUESTS.clear()
