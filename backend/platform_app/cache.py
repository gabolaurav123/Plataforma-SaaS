"""Only public bot configuration and catalog data; never tokens or customer data."""

import copy
import json
import threading
import time
from collections import OrderedDict
from redis.exceptions import RedisError


class PublicConfigCache:
    def __init__(self, redis=None, ttl=60, capacity=2000):
        self.redis, self.ttl, self.capacity = redis, ttl, capacity
        self.memory, self.lock = OrderedDict(), threading.Lock()

    def read(self, bot, category, loader):
        key = f"public-config:{bot.tenant_id}:{bot.id}:{bot.config_version}:{category}"
        if self.redis is not None:
            try:
                encoded = self.redis.get(key)
                if encoded is not None:
                    return json.loads(encoded)
            except (RedisError, ValueError):
                pass
            value = loader()
            try:
                self.redis.setex(key, self.ttl, json.dumps(value))
            except RedisError:
                pass
            return value
        with self.lock:
            entry = self.memory.get(key)
            if entry and entry[0] > time.monotonic():
                self.memory.move_to_end(key)
                return copy.deepcopy(entry[1])
        value = loader()
        with self.lock:
            self.memory[key] = (time.monotonic() + self.ttl, copy.deepcopy(value))
            self.memory.move_to_end(key)
            while len(self.memory) > self.capacity:
                self.memory.popitem(last=False)
        return value
