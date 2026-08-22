import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import (
    IllegalTransition,
    PermanentError,
    RetriableError,
    TaskTimeout,
    WorkerLost,
)
from app.core.retry import ErrorClassification, RetryPolicy, classify_error, next_backoff


class TestNextBackoff:
    def test_exact_geometric_sequence_with_midpoint_jitter(self) -> None:
        """rand() == 0.5 is the exact midpoint of the jitter range, so the
        jitter term evaluates to zero deviation even with jitter > 0 —
        this is what makes the sequence exactly reproducible rather than
        merely bounded."""
        policy = RetryPolicy(
            max_attempts=6, backoff_seconds=2, backoff_factor=2, max_backoff_seconds=30, jitter=0.2
        )
        expected = [2, 4, 8, 16, 30, 30]

        for attempt, exp in enumerate(expected, start=1):
            assert next_backoff(attempt, policy, rand=lambda: 0.5) == pytest.approx(exp)

    def test_zero_jitter_returns_capped_value_without_calling_rand(self) -> None:
        policy = RetryPolicy(
            max_attempts=5, backoff_seconds=1, backoff_factor=2, max_backoff_seconds=100, jitter=0.0
        )

        def boom() -> float:
            raise AssertionError("rand() must not be called when jitter is 0")

        assert next_backoff(3, policy, rand=boom) == pytest.approx(4.0)  # 1 * 2^2

    def test_cap_enforcement(self) -> None:
        policy = RetryPolicy(
            max_attempts=5, backoff_seconds=10, backoff_factor=3, max_backoff_seconds=20, jitter=0.0
        )
        # raw = 10 * 3^2 = 90, capped to 20
        assert next_backoff(3, policy, rand=lambda: 0.5) == pytest.approx(20.0)

    def test_lower_and_upper_jitter_bounds(self) -> None:
        policy = RetryPolicy(
            max_attempts=2,
            backoff_seconds=10,
            backoff_factor=1,
            max_backoff_seconds=100,
            jitter=0.5,
        )
        # raw = capped = 10; jitter range is capped * (1 +/- 0.5)
        assert next_backoff(1, policy, rand=lambda: 0.0) == pytest.approx(5.0)
        assert next_backoff(1, policy, rand=lambda: 1.0) == pytest.approx(15.0)

    def test_jitter_stays_within_bounds_across_many_samples(self) -> None:
        import random

        rng = random.Random(1234)
        policy = RetryPolicy(
            max_attempts=2,
            backoff_seconds=10,
            backoff_factor=1,
            max_backoff_seconds=100,
            jitter=0.3,
        )
        lower, upper = 10 * (1 - 0.3), 10 * (1 + 0.3)

        for _ in range(1000):
            value = next_backoff(1, policy, rand=rng.random)
            assert lower <= value <= upper

    def test_attempt_must_be_at_least_one(self) -> None:
        policy = RetryPolicy()
        with pytest.raises(ValueError, match="attempt must be >= 1"):
            next_backoff(0, policy, rand=lambda: 0.5)


class TestRetryPolicyValidation:
    def test_max_attempts_one_is_valid(self) -> None:
        policy = RetryPolicy(max_attempts=1)
        assert policy.max_attempts == 1

    def test_max_attempts_must_be_at_least_one(self) -> None:
        with pytest.raises(PydanticValidationError):
            RetryPolicy(max_attempts=0)

    def test_backoff_factor_must_be_at_least_one(self) -> None:
        with pytest.raises(PydanticValidationError):
            RetryPolicy(backoff_factor=0.5)

    def test_jitter_must_be_within_zero_and_one(self) -> None:
        with pytest.raises(PydanticValidationError):
            RetryPolicy(jitter=1.5)
        with pytest.raises(PydanticValidationError):
            RetryPolicy(jitter=-0.1)

    def test_negative_backoff_seconds_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            RetryPolicy(backoff_seconds=-1)

    def test_negative_max_backoff_seconds_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            RetryPolicy(max_backoff_seconds=-1)

    def test_policy_is_immutable(self) -> None:
        policy = RetryPolicy()
        with pytest.raises(PydanticValidationError):
            policy.max_attempts = 5  # type: ignore[misc]


class TestClassifyError:
    @pytest.mark.parametrize(
        "exc,expected",
        [
            (RetriableError("flaky"), ErrorClassification.RETRIABLE),
            (WorkerLost("lease expired"), ErrorClassification.RETRIABLE),
            (TaskTimeout("too slow"), ErrorClassification.RETRIABLE),
            (PermanentError("bad input"), ErrorClassification.PERMANENT),
            (IllegalTransition("bad state change"), ErrorClassification.PERMANENT),
            (ValueError("some unrelated bug"), ErrorClassification.RETRIABLE),
            (KeyError("missing"), ErrorClassification.RETRIABLE),
        ],
    )
    def test_classification(self, exc: Exception, expected: ErrorClassification) -> None:
        assert classify_error(exc) == expected

    def test_pydantic_validation_error_is_permanent(self) -> None:
        try:
            RetryPolicy(max_attempts=0)
        except PydanticValidationError as exc:
            assert classify_error(exc) == ErrorClassification.PERMANENT
        else:
            pytest.fail("expected RetryPolicy(max_attempts=0) to raise")
