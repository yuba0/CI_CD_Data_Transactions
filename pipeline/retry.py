"""Mécanisme de retry générique avec backoff exponentiel (Niveau 1.7 et 2.4)."""
from __future__ import annotations

import functools
import logging
import time
from typing import Callable, Tuple, Type

log = logging.getLogger(__name__)


def retry(
    exceptions: Tuple[Type[BaseException], ...],
    attempts: int = 5,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
):
    """Réessaie la fonction décorée si elle lève une des `exceptions`.

    Délai entre les tentatives : base_delay * 2^(n-1), plafonné à max_delay.
    Après `attempts` échecs, la dernière exception est relevée.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt == attempts:
                        log.error("%s : échec définitif après %d tentatives (%s)",
                                  func.__name__, attempts, exc)
                        raise
                    delay = min(base_delay * 2 ** (attempt - 1), max_delay)
                    log.warning("%s : tentative %d/%d échouée (%s) -> retry dans %.1fs",
                                func.__name__, attempt, attempts, exc, delay)
                    sleep(delay)

        return wrapper

    return decorator
