"""Injection de pannes contrôlée par variables d'environnement.

Sert uniquement à démontrer les mécanismes de retry (Niveau 1.7 / 2.4) :
  FAIL_INSERT_TIMES=2   -> les 2 premières insertions en base échouent
  FAIL_S3_GET_TIMES=2   -> les 2 premiers téléchargements S3 échouent
"""
from __future__ import annotations

import os
from collections import Counter

_calls: Counter = Counter()


class SimulatedFailure(ConnectionError):
    """Panne transitoire simulée (traitée comme une erreur réseau)."""


def maybe_fail(name: str) -> None:
    limit = int(os.getenv(f"FAIL_{name}_TIMES", "0"))
    _calls[name] += 1
    if _calls[name] <= limit:
        raise SimulatedFailure(f"panne simulée {name} n°{_calls[name]}/{limit}")


def reset() -> None:
    _calls.clear()
