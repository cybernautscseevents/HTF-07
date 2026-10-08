from decimal import Decimal

from backend.app.evaluation.metrics import efficiency


def test_exact_decimal_metrics_and_zero_collateral():
    assert efficiency(10, 4) == Decimal("2.5")
    assert efficiency(10, 0) == Decimal("10")
    assert efficiency(0, 0) is None


def test_negative_metrics_are_rejected():
    try:
        efficiency(-1, 1)
    except ValueError:
        pass
    else:
        raise AssertionError("negative capital must be rejected")
