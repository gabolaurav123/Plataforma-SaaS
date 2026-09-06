import threading
from collections import defaultdict
from .errors import RetryLater
from .models.base import now

LUA = """
for i,key in ipairs(KEYS) do
  if tonumber(redis.call('GET', key) or '0') >= tonumber(ARGV[i]) then
    return math.max(1, math.ceil(redis.call('PTTL', key) / 1000))
  end
end
for _,key in ipairs(KEYS) do
  local n = redis.call('INCR', key)
  if n == 1 then redis.call('PEXPIRE', key, 1000) end
end
return 0
"""


class RateLimiter:
    def __init__(self, settings):
        self.settings, self.lock, self.memory = settings, threading.Lock(), defaultdict(lambda: [0, 0])
        self.redis = None
        if settings.redis_url:
            from redis import Redis

            self.redis = Redis.from_url(settings.redis_url.get_secret_value(), socket_timeout=2)

    def check(self, buckets):
        if self.redis:
            delay = self.redis.eval(LUA, len(buckets), *["rate:" + k for k in buckets], *buckets.values())
            if delay:
                raise RetryLater(delay)
            return
        with self.lock:
            current = now()
            for key, limit in buckets.items():
                window, count = self.memory[key]
                if window == current and count >= limit:
                    raise RetryLater(1)
            for key in buckets:
                window, count = self.memory[key]
                self.memory[key] = [current, count + 1 if window == current else 1]
            if len(self.memory) > 10000:
                self.memory = defaultdict(
                    lambda: [0, 0], {k: v for k, v in self.memory.items() if v[0] >= current - 2}
                )

    def outbound(self, bot_id, tenant_id, user_id):
        s = self.settings
        self.check(
            {
                "global": s.global_rps,
                f"bot:{bot_id}": s.bot_rps,
                f"tenant:{tenant_id}": s.tenant_rps,
                f"user:{bot_id}:{user_id}": s.user_rps,
            }
        )
