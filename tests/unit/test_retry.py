import pytest

from pipeline.retry import retry


def test_retry_succeeds_after_transient_failures():
    calls, sleeps = [], []

    @retry(exceptions=(ConnectionError,), attempts=4, base_delay=1, sleep=sleeps.append)
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("boom")
        return "ok"

    assert flaky() == "ok"
    assert len(calls) == 3
    assert sleeps == [1, 2]  # backoff exponentiel


def test_retry_gives_up_after_max_attempts():
    @retry(exceptions=(ConnectionError,), attempts=3, base_delay=0, sleep=lambda s: None)
    def always_fails():
        raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        always_fails()


def test_retry_does_not_catch_other_errors():
    calls = []

    @retry(exceptions=(ConnectionError,), attempts=3, base_delay=0, sleep=lambda s: None)
    def bug():
        calls.append(1)
        raise ValueError("vrai bug")

    with pytest.raises(ValueError):
        bug()
    assert len(calls) == 1  # un bug n'est pas réessayé
