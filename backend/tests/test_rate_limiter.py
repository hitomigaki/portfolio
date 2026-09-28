"""core/rate_limiter.py の単体テスト。"""

from datetime import datetime, timedelta

from app.core.rate_limiter import RateLimiter

NOW = datetime(2026, 1, 1, 12, 0, 0)


class TestRateLimiter:
    def test_allows_up_to_max_attempts(self) -> None:
        limiter = RateLimiter(max_attempts=3, window_sec=60)
        assert limiter.check_and_record("1.2.3.4", NOW) is True
        assert limiter.check_and_record("1.2.3.4", NOW) is True
        assert limiter.check_and_record("1.2.3.4", NOW) is True

    def test_blocks_after_max_attempts(self) -> None:
        limiter = RateLimiter(max_attempts=3, window_sec=60)
        for _ in range(3):
            limiter.check_and_record("1.2.3.4", NOW)
        assert limiter.check_and_record("1.2.3.4", NOW) is False

    def test_keys_are_independent(self) -> None:
        limiter = RateLimiter(max_attempts=1, window_sec=60)
        assert limiter.check_and_record("1.2.3.4", NOW) is True
        assert limiter.check_and_record("5.6.7.8", NOW) is True
        assert limiter.check_and_record("1.2.3.4", NOW) is False

    def test_old_attempts_expire_outside_window(self) -> None:
        limiter = RateLimiter(max_attempts=2, window_sec=60)
        limiter.check_and_record("1.2.3.4", NOW)
        limiter.check_and_record("1.2.3.4", NOW)
        assert limiter.check_and_record("1.2.3.4", NOW + timedelta(seconds=61)) is True

    def test_still_blocked_within_window(self) -> None:
        limiter = RateLimiter(max_attempts=2, window_sec=60)
        limiter.check_and_record("1.2.3.4", NOW)
        limiter.check_and_record("1.2.3.4", NOW)
        assert limiter.check_and_record("1.2.3.4", NOW + timedelta(seconds=30)) is False
