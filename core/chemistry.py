# lab/realtime_greenlab/chemistry.py
"""Ammonia quantities derived from the GreenLab NH4 channel.

Two DIFFERENT quantities come out of the same raw NH4 reading:

* ``TAN`` — total ammonium as N (NH4+ + NH3, mg/L N), ``tan_mg_l``.  This is the
  basis of the provincial monitoring data (HP Excel header "Amôni (NH4+ tính theo
  N) (mg/l)", QN "Amoni" under QCVN 10:2023/BTNMT) whose column is *named* ``NH3``
  in ``data/*/clean_data.csv``.  Everything trained or defined on that data uses
  TAN: the QCVN 10 B1 ammonium limit (0.1 mg/L), the imputers, the contextual
  models, the HSI breakpoints and the spatial anchors.
* un-ionised ``NH3`` — the toxic fraction, ``emerson_nh3`` (Emerson et al. 1975,
  depends on pH and temperature; 13–25× smaller than TAN at Cát Bà).  Only the
  fish-toxicity alerts use it (alerts.py, forecast_advisory.py, model_alerts.py).

``provincial_basis_row`` is the single, explicit mapping between the two: models
and thresholds built on provincial data name their ammonium feature ``NH3``, so
that slot is filled from ``TAN`` — never from the un-ionised value.

The sensor's basis (NH4+ ion mass vs NH4-N) and unit (µg/L) are unconfirmed by the
vendor; see ``NH4_UNIT_SCALE`` / ``NH4_TO_N_FACTOR`` in core/config.py.
"""
import math

from core.config import AMMONIA_FEATURE_SOURCE, NH4_TO_N_FACTOR, NH4_UNIT_SCALE


def nh3_fraction(pH: float, temp_c: float) -> float:
    """Tỉ lệ NH3 / tổng amoni theo Emerson (freshwater approximation).

    pKa = 0.09018 + 2729.92 / T(Kelvin)
    f   = 1 / (1 + 10^(pKa − pH))
    """
    t_kelvin = temp_c + 273.15
    pka = 0.09018 + 2729.92 / t_kelvin
    return 1.0 / (1.0 + 10 ** (pka - pH))


def tan_mg_l(nh4_raw: float, scale: float = None, n_factor: float = None) -> float:
    """Raw sensor NH4 → TAN, total ammonium as N (mg/L).

    TAN = max(0, raw) × NH4_UNIT_SCALE (µg/L → mg/L) × NH4_TO_N_FACTOR (ion → N).
    Same basis as the provincial ``NH3`` column and the QCVN 10 B1 ammonium limit.
    """
    if scale is None:
        scale = NH4_UNIT_SCALE
    if n_factor is None:
        n_factor = NH4_TO_N_FACTOR
    return max(0.0, nh4_raw) * scale * n_factor


def emerson_nh3(nh4_raw: float, pH: float, temp_c: float, scale: float = None) -> float:
    """Raw sensor NH4 → un-ionised NH3 (mg/L, as N), the fish-toxicity quantity.

    NH3 = TAN × Emerson fraction(pH, T); it shares ``tan_mg_l``'s unit scale and
    N factor.  Not comparable with QCVN 10 B1 ammonium or the provincial data.
    """
    return tan_mg_l(nh4_raw, scale=scale) * nh3_fraction(pH, temp_c)


def _present(value) -> bool:
    if value is None:
        return False
    try:
        return not math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def provincial_basis_row(values: dict) -> dict:
    """Copy of ``values`` ready for a provincial-trained model/threshold.

    For each feature in ``AMMONIA_FEATURE_SOURCE`` (``{"NH3": "TAN"}``) the feature
    slot is filled from the source key.  If the source is absent the slot is
    removed — the un-ionised ``NH3`` value is never passed through, so a caller
    without ``TAN`` sees the feature as missing instead of a value 13–25× too small.
    """
    row = dict(values)
    for feature, source in AMMONIA_FEATURE_SOURCE.items():
        if _present(row.get(source)):
            row[feature] = float(row[source])
        else:
            row.pop(feature, None)
    return row
