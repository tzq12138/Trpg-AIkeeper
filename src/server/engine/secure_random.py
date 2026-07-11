import os
import random
import secrets


_system_rng = secrets.SystemRandom()


def secure_randint(low: int, high: int, *, test_rng=None) -> int:
    if os.getenv("AIKEEPER_DEV_MODE", "").strip() == "1" and test_rng is not None:
        return test_rng.randint(low, high)
    return _system_rng.randint(low, high)
