import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.results.backends import RedisBackend
from dramatiq.results import Results
from taxonomy_ontology_accelerator.commons.utils.logger import get_logger
from typing import cast


redis_broker = RedisBroker(host="redis", port=6379) # setup dramatiq broker
dramatiq.set_broker(redis_broker)
result_backend = RedisBackend(host="redis", port=6379)
redis_broker.add_middleware(Results(backend=result_backend))

logger = cast('Richlogger', get_logger())


@dramatiq.actor(store_results=True)
def run_counter(count_value: int)-> bool:
    if isinstance(count_value, int): 

        for i in range(count_value): 
            logger.info(f'current count {i}')
            pass
        return True
    else:
        raise Exception(f'Value {count_value} must be an int')

    

