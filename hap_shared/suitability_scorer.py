"""One interface for site-suitability scoring (roadmap H4.2, decisions #31).

Inputs: a table of layer values (one row per cell / point / time step, one column per
criterion) plus a :class:`SuitabilityConfig` (criteria, weights, thresholds, missing-value
policy, class cuts). Output: :class:`SuitabilityResult` with score, class, per-criterion
membership and contribution, and missing / out-of-domain (OOD) flags.

Two configs reproduce the scorers that existed before the split, bit for bit
(``tests/test_suitability_golden.py``):

* :func:`rule_config` / :func:`species_rule_config` — breakpoints from
  ``hap_shared/thresholds/<species>_thresholds.json``, weights from ``importance_rank``
  renormalised over the criteria present, missing value = neutral 0.5, 3 classes from
  ``SPECIES[...]['label_thresholds']`` (was ``classification._classify_by_scoring``).
* :data:`LEGACY_COBIA_HSI` — the old aqua-forecast cobia HSI (range / min / max rules,
  equal-weight mean over the criteria present, 4 classes at 0.5 / 0.75 / 0.85) used by the
  research-map HSI layer (was ``core.spatial_overlay._legacy_hsi``).

Only numpy / pandas: the module is imported from the root venv and from the research-map
backend venv (via ``core``), and must stay inside ``hap_shared`` (no ``core`` import).
The fuzzy Ghaderi integration (``hap_shared.fuzzy_suitability``) is a later implementation
(roadmap H3.4); its outputs are frozen experiment runs today.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
import pandas as pd

from hap_shared.scoring import score_param

KINDS = ("breakpoints", "range", "min", "max")
AGGREGATIONS = ("weighted_sum", "mean")
MISSING_POLICIES = ("neutral", "skip")
WEIGHTINGS = ("rank", "fixed")


@dataclass(frozen=True)
class Criterion:
    """One layer and how a value maps to membership in [0, 1].

    kind ``breakpoints``: ``params`` = ((x, y), ...) piecewise linear, clamped at the ends
      (``hap_shared.scoring.score_param``); its domain is [min x, max x].
    kind ``range``: ``params`` = (low, high); 1 inside, value/low below, (2 high - value)/high above.
    kind ``min``: ``params`` = (threshold,); min(1, value/threshold).
    kind ``max``: ``params`` = (threshold,); 1 - value/threshold.
    Non-breakpoint memberships are clipped to [0, 1]. ``valid_range`` overrides the OOD domain.
    """

    name: str
    kind: str
    params: tuple
    rank: int | None = None
    weight: float = 1.0
    valid_range: tuple[float, float] | None = None

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"unknown criterion kind {self.kind!r}")

    def domain(self) -> tuple[float, float] | None:
        if self.valid_range is not None:
            return self.valid_range
        if self.kind == "breakpoints":
            xs = [float(x) for x, _ in self.params]
            return min(xs), max(xs)
        return None

    def numeric(self, values) -> np.ndarray:
        return pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)

    def membership(self, values) -> np.ndarray:
        """Membership of raw layer values; NaN in → 0.5 for breakpoints, NaN for the other kinds."""
        if self.kind == "breakpoints":
            # Raw values straight into score_param, element by element, as the original scorer did.
            return np.array([score_param(v, self.params) for v in np.asarray(values)], dtype=float)
        x = self.numeric(values)
        if self.kind == "range":
            low, high = self.params
            score = np.where(x < low, x / low, np.where(x > high, (2 * high - x) / high, 1.0))
        elif self.kind == "min":
            score = np.minimum(1.0, x / self.params[0])
        else:
            score = 1.0 - x / self.params[0]
        return np.where(np.isnan(x), np.nan, np.clip(score, 0.0, 1.0))


@dataclass(frozen=True)
class ClassScheme:
    """Class = number of ``cuts`` (ascending) the score reaches; NaN → lowest class."""

    cuts: tuple[float, ...]
    labels: tuple
    names: dict | None = None

    def __post_init__(self):
        if len(self.labels) != len(self.cuts) + 1 or list(self.cuts) != sorted(self.cuts):
            raise ValueError("labels must be len(cuts)+1 and cuts ascending")

    def index(self, scores: np.ndarray) -> np.ndarray:
        s = np.asarray(scores, dtype=float)
        idx = np.zeros(s.shape, dtype=int)
        for cut in self.cuts:
            idx += s >= cut
        return idx

    def label(self, score: float):
        return self.labels[int(self.index(np.array([score]))[0])]


@dataclass(frozen=True)
class SuitabilityConfig:
    """Criteria + how to combine them.

    aggregation ``weighted_sum``: score = sum(w_c * m_c), weights normalised over the criteria used;
      with ``missing='neutral'`` a missing value counts as ``neutral_value``.
    aggregation ``mean`` (with ``missing='skip'``): equal-weight mean over the criteria present in
      each row; no criterion present → NaN.
    weighting ``rank``: raw weight = max_rank(used) + 1 - rank; ``fixed``: ``Criterion.weight``.
    ``empty_score`` / ``empty_class`` apply when no configured criterion is usable at all.
    """

    name: str
    criteria: tuple[Criterion, ...]
    classes: ClassScheme
    aggregation: str = "weighted_sum"
    weighting: str = "rank"
    missing: str = "neutral"
    neutral_value: float = 0.5
    empty_score: float = float("nan")
    empty_class: Any = None
    method: str = "scoring"
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.aggregation not in AGGREGATIONS or self.missing not in MISSING_POLICIES or self.weighting not in WEIGHTINGS:
            raise ValueError("bad aggregation / missing / weighting")
        if self.aggregation == "mean" and self.missing != "skip":
            raise ValueError("aggregation 'mean' needs missing='skip'")

    def criterion(self, name: str) -> Criterion:
        for c in self.criteria:
            if c.name == name:
                return c
        raise KeyError(name)

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.criteria]


@dataclass
class SuitabilityResult:
    score: pd.Series
    class_index: pd.Series
    label: pd.Series
    label_name: pd.Series | None
    membership: pd.DataFrame
    contributions: pd.DataFrame
    weights: dict[str, float]
    missing: pd.DataFrame
    ood: pd.DataFrame
    used: list[str]
    method: str

    def to_frame(self) -> pd.DataFrame:
        out = pd.DataFrame({"suitability_score": self.score, "suitability_class": self.class_index,
                            "suitability_label": self.label}, index=self.score.index)
        if self.label_name is not None:
            out["suitability_name"] = self.label_name
        for c in self.contributions:
            out[f"contrib_{c}"] = self.contributions[c]
        for c in self.missing:
            out[f"missing_{c}"] = self.missing[c]
        for c in self.ood:
            out[f"ood_{c}"] = self.ood[c]
        out["n_missing"] = self.missing.sum(axis=1).astype(int)
        out["n_ood"] = self.ood.sum(axis=1).astype(int)
        return out


class SuitabilityScorer:
    """Score layer tables with one :class:`SuitabilityConfig`."""

    def __init__(self, config: SuitabilityConfig):
        self.config = config

    def _weights(self, used: list[Criterion]) -> dict[str, float]:
        if self.config.weighting == "rank":
            max_rank = max(c.rank for c in used)
            raw = {c.name: max_rank + 1 - c.rank for c in used}
        else:
            raw = {c.name: c.weight for c in used}
        total = sum(raw.values())
        return {name: w / total for name, w in raw.items()}

    def score(self, layers: pd.DataFrame, criteria: Sequence[str] | None = None) -> SuitabilityResult:
        """Score every row of ``layers``.

        ``criteria`` (optional) names the criteria to use, in this order; names the config does not
        know are ignored, names it knows must be columns of ``layers``. Without it every configured
        criterion that is a column is used, in config order. Configured criteria that are not
        columns are reported as missing in every row.
        """
        cfg, index = self.config, layers.index
        known = set(cfg.names)
        if criteria is None:
            used = [c for c in cfg.criteria if c.name in layers.columns]
            considered = cfg.names
        else:
            used = [cfg.criterion(n) for n in criteria if n in known]
            for c in used:
                if c.name not in layers.columns:
                    raise KeyError(c.name)
            considered = [c.name for c in used]
        n = len(layers)
        missing = pd.DataFrame({name: np.ones(n, dtype=bool) for name in considered}, index=index)
        ood = pd.DataFrame({name: np.zeros(n, dtype=bool) for name in considered}, index=index)
        membership = pd.DataFrame(index=index)
        for c in used:
            raw = layers[c.name].to_numpy()
            numeric = c.numeric(raw)
            missing[c.name] = np.isnan(numeric)
            domain = c.domain()
            if domain is not None:
                with np.errstate(invalid="ignore"):
                    ood[c.name] = ~np.isnan(numeric) & ((numeric < domain[0]) | (numeric > domain[1]))
            membership[c.name] = c.membership(raw)

        if not used:
            scores = np.full(n, cfg.empty_score, dtype=float)
            weights: dict[str, float] = {}
            contributions = pd.DataFrame(index=index)
        elif cfg.aggregation == "weighted_sum":
            weights = self._weights(used)
            scores = np.zeros(n)
            contributions = pd.DataFrame(index=index)
            for c in used:
                m = membership[c.name].to_numpy()
                if cfg.missing == "neutral":
                    m = np.where(missing[c.name].to_numpy(), cfg.neutral_value, m)
                part = m * weights[c.name]
                scores += part          # same accumulation order as the original rule scorer
                contributions[c.name] = part
        else:  # mean over present criteria
            weights = {c.name: 1.0 / len(used) for c in used}
            total, count = np.zeros(n), np.zeros(n)
            for c in used:
                m = membership[c.name].to_numpy()
                present = ~np.isnan(m)
                total += np.where(present, m, 0.0)
                count += present
            with np.errstate(invalid="ignore", divide="ignore"):
                scores = np.where(count > 0, total / count, np.nan)
                contributions = pd.DataFrame({c.name: np.where(count > 0, np.nan_to_num(membership[c.name].to_numpy()) / count, np.nan)
                                              for c in used}, index=index)

        class_index = cfg.classes.index(scores)
        if not used and cfg.empty_class is not None:
            class_index = np.full(n, cfg.classes.labels.index(cfg.empty_class), dtype=int)
        labels = [cfg.classes.labels[i] for i in class_index]
        names = None if cfg.classes.names is None else pd.Series([cfg.classes.names[l] for l in labels], index=index)
        return SuitabilityResult(score=pd.Series(scores, index=index), class_index=pd.Series(class_index, index=index),
                                 label=pd.Series(labels, index=index), label_name=names, membership=membership,
                                 contributions=contributions, weights=weights, missing=missing, ood=ood,
                                 used=[c.name for c in used], method=cfg.method)


# ---------------------------------------------------------------- configs

RULE_LABEL_NAMES = {0: "Chưa phù hợp", 1: "Phù hợp", 2: "Rất phù hợp"}
DEFAULT_RULE_LABEL_THRESHOLDS = (0.60, 0.72)


def rule_config(thresholds: dict, label_thresholds: Sequence[float] | None = None, *, name: str = "rule") -> SuitabilityConfig:
    """Breakpoint rule scorer from a ``<species>_thresholds.json`` dict (importance_rank + breakpoints)."""
    lo, hi = label_thresholds if label_thresholds else DEFAULT_RULE_LABEL_THRESHOLDS
    criteria = tuple(Criterion(p, "breakpoints", tuple(tuple(bp) for bp in spec["breakpoints"]), rank=spec["importance_rank"])
                     for p, spec in thresholds.items())
    return SuitabilityConfig(name=name, criteria=criteria, classes=ClassScheme((lo, hi), (0, 1, 2), RULE_LABEL_NAMES),
                             aggregation="weighted_sum", weighting="rank", missing="neutral", neutral_value=0.5,
                             empty_score=0.5, empty_class=1, method="scoring")


def species_rule_config(species: str) -> SuitabilityConfig:
    from hap_shared.classification import _load_thresholds  # shared JSON cache
    from hap_shared.species import SPECIES

    return rule_config(_load_thresholds(species), SPECIES[species].get("label_thresholds"), name=f"rule:{species}")


LEGACY_COBIA_HSI = SuitabilityConfig(
    name="legacy_cobia_hsi",
    criteria=(Criterion("DO", "min", (6.0,)), Criterion("Temperature", "range", (24.0, 28.0)),
              Criterion("pH", "range", (8.0, 8.5)), Criterion("Salinity", "range", (27.0, 33.0)),
              Criterion("NH3", "max", (0.1,)), Criterion("TSS", "max", (50.0,))),
    classes=ClassScheme((0.5, 0.75, 0.85), ("not_suitable", "less_suitable", "suitable", "very_suitable")),
    aggregation="mean", weighting="fixed", missing="skip", empty_score=float("nan"), method="legacy_hsi",
    meta={"source": "aqua-forecast radius demo; NH3 slot carries TAN (decisions #28)"},
)


def legacy_cobia_hsi(layers: pd.DataFrame) -> pd.Series:
    """Vectorised legacy cobia HSI per row (NaN where no criterion is present)."""
    return SuitabilityScorer(LEGACY_COBIA_HSI).score(layers).score


def legacy_hsi_label(value: float) -> str:
    return LEGACY_COBIA_HSI.classes.label(value)
