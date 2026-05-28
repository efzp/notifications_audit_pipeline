import logging
from time import perf_counter
from typing import Callable, TypeVar


T = TypeVar("T")


def timed_step(
    timings: dict[str, float],
    step_name: str,
    callback: Callable[[], T],
) -> T:
    start = perf_counter()
    try:
        return callback()
    finally:
        elapsed = round(perf_counter() - start, 4)
        timings[step_name] = elapsed
        logging.info("%s completado en %.4f segundos", step_name, elapsed)
