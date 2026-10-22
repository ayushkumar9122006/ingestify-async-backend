import logging
from typing import Optional
import redis
from fastapi import Request, HTTPException, status
from app.core.config import settings

logger = logging.getLogger(__name__)

# Reusable Redis connection pool for rate limiting
_redis_pool: Optional[redis.ConnectionPool] = None


def get_redis_client() -> Optional[redis.Redis]:
    """Get or initialize thread-safe Redis connection pool."""
    global _redis_pool
    try:
        if _redis_pool is None:
            _redis_pool = redis.ConnectionPool.from_url(
                settings.CELERY_BROKER_URL,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
            )
        return redis.Redis(connection_pool=_redis_pool)
    except Exception as e:
        logger.warning(f"Could not initialize Redis connection for rate limiter: {e}")
        return None


class RateLimiter:
    """
    Redis-backed atomic sliding window / fixed window rate limiter.
    Defaults to 5 upload requests per 60 seconds per client IP.
    """
    def __init__(
        self,
        requests_limit: int = 5,
        window_seconds: int = 60,
        prefix: str = "rate_limit:upload",
    ):
        self.requests_limit = requests_limit
        self.window_seconds = window_seconds
        self.prefix = prefix

    def get_client_ip(self, request: Request) -> str:
        """Extract client IP, inspecting X-Forwarded-For if behind a proxy."""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # First IP in comma-separated chain is the original client
            return forwarded_for.split(",")[0].strip()
        if request.client and request.client.host:
            return request.client.host
        return "127.0.0.1"

    async def __call__(self, request: Request) -> None:
        client_ip = self.get_client_ip(request)
        key = f"{self.prefix}:{client_ip}"

        client = get_redis_client()
        if client is None:
            # If Redis is unavailable, log and fail-open gracefully to prevent service outage
            logger.warning("Redis client unavailable; bypassing rate limiting.")
            return

        try:
            # Atomic pipeline to increment and retrieve remaining TTL
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.ttl(key)
            current_count, ttl = pipe.execute()

            # Set expiration on the first hit or if expired
            if current_count == 1 or ttl < 0:
                client.expire(key, self.window_seconds)
                ttl = self.window_seconds

            # Check threshold
            if current_count > self.requests_limit:
                retry_after = max(ttl, 1)
                logger.warning(
                    f"Rate limit exceeded for IP {client_ip} ({current_count}/{self.requests_limit} reqs)."
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        f"Rate limit exceeded: Maximum {self.requests_limit} upload requests allowed "
                        f"per {self.window_seconds} seconds. Please retry in {retry_after} seconds."
                    ),
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(self.requests_limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(retry_after),
                    },
                )

            # Attach headers to request state for inspection
            request.state.rate_limit_remaining = max(0, self.requests_limit - current_count)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error checking rate limit in Redis: {e}")
            # Fail-open on transient Redis errors
            return


# Standard 5 uploads per 60-second window dependency for upload endpoint
upload_rate_limiter = RateLimiter(requests_limit=5, window_seconds=60, prefix="rate_limit:upload")
