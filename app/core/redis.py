import redis.asyncio as redis
from app.core.config import settings

async def get_redis() -> redis.Redis:
    return redis.from_url(settings.REDIS_URL)
