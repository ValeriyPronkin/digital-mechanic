"""Скользящее окно: квота на клиента и на экземпляр, отказ не расходует квоту, окно освобождается."""

from service.rate_limit import RateLimiter


def test_window() -> None:
    now = [0.0]
    lim = RateLimiter(per_client=2, total=3, clock=lambda: now[0])
    assert lim.check("a") == 0 and lim.check("a") == 0
    assert lim.check("a") > 0  # третий от того же клиента
    assert lim.check("b") == 0
    assert lim.check("c") > 0  # общий потолок 3
    now[0] = 61.0
    assert lim.check("a") == 0 and lim.check("c") == 0
