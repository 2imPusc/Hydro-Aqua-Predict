"""Create reviewed Hai Phong contextual ExtraTrees bundles."""
from __future__ import annotations
import json
import joblib
from sklearn.ensemble import ExtraTreesRegressor
from core.config import IMPUTER_DIR
from core.impute import build_training_data

SPECS = {"DO": ["NH3", "pH", "Temperature", "TSS"], "Salinity": ["NH3", "pH", "Temperature", "TSS", "month"]}
def train() -> dict:
    df = build_training_data("haiphong")
    targets = {}
    for target, features in SPECS.items():
        clean = df.dropna(subset=features + [target])
        model = ExtraTreesRegressor(n_estimators=200, min_samples_leaf=2, random_state=42, n_jobs=-1).fit(clean[features], clean[target])
        artifact = f"contextual_hp_{target.lower()}_extratrees_v1.pkl"
        joblib.dump(model, IMPUTER_DIR / artifact)
        targets[target] = {"artifact": artifact, "features": features, "feature_bounds": {f: [float(clean[f].min()), float(clean[f].max())] for f in features}}
    manifest = {"version": "hp-contextual-v1-shadow", "mode": "shadow", "targets": targets}
    (IMPUTER_DIR / "haiphong_contextual_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
if __name__ == "__main__":
    print(json.dumps(train(), indent=2))
