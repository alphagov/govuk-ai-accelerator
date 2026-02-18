import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.results.backends import RedisBackend
from dramatiq.results import Results



redis_broker = RedisBroker(host="redis", port=6379) # setup dramatiq broker
dramatiq.set_broker(redis_broker)
result_backend = RedisBackend(host="redis", port=6379)
redis_broker.add_middleware(Results(backend=result_backend))




@dramatiq.actor(store_results=True)
def run_counter(count_value: int)-> bool:
    if isinstance(count_value, int): 

        for i in range(count_value): return i
    else:
        raise Exception(f'Value {count_value} must be an int')

    return True

