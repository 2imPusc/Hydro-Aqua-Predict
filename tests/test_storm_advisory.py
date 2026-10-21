import math

import pytest

from core.storm_advisory import beaufort, qd18_risk_level, site_action, storm_class_vi, to_ms


@pytest.mark.parametrize("speed, level", [(0.0, 0), (10.79, 5), (10.8, 6), (17.1, 7), (17.2, 8),
                                          (24.5, 10), (32.7, 12), (56.1, 17), (80.0, 17)])
def test_beaufort_bounds(speed, level):
    assert beaufort(speed) == level


def test_beaufort_missing():
    assert beaufort(None) is None
    assert beaufort(float("nan")) is None


def test_to_ms_units():
    assert to_ms(36, "km/h") == pytest.approx(10.0)
    assert to_ms(10, "kn") == pytest.approx(5.14444)
    assert to_ms(5, "m/s") == 5.0
    with pytest.raises(ValueError):
        to_ms(1, "furlong/h")


@pytest.mark.parametrize("level, cls", [(5, None), (6, "áp thấp nhiệt đới"), (9, "bão"),
                                        (11, "bão mạnh"), (15, "bão rất mạnh"), (16, "siêu bão")])
def test_storm_class(level, cls):
    assert storm_class_vi(level) == cls


@pytest.mark.parametrize("level, risk", [(None, None), (5, None), (6, 3), (11, 3), (12, 4), (15, 4), (16, 5)])
def test_qd18_level(level, risk):
    assert qd18_risk_level(level) == risk


def test_site_action_tiers():
    assert site_action(5)["tier"] == 0
    assert site_action(7)["tier"] == 1
    assert site_action(9)["tier"] == 2
    assert site_action(11)["tier"] == 3
    assert site_action(13)["tier"] == 4
    assert site_action(13)["basis"] == "proposal_needs_expert_review"
    assert site_action(None)["tier"] is None
