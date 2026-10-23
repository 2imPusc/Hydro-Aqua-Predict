"""Temporal backtest for direct sensor forecasts against persistence."""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from xgboost import XGBRegressor
from core.quality import is_in_range

DIRECT_PARAMS = ("Temperature", "pH", "NH4", "TSS")
HORIZONS = {15: 5, 30: 10, 60: 20}  # 3-minute aggregation steps

def backtest_series(series: pd.Series, horizon_minutes: int) -> dict:
    s = series.dropna().astype(float)
    steps = HORIZONS[horizon_minutes]
    frame = pd.DataFrame({"value": s})
    for lag in (1, 2, 3, 5, 10): frame[f"lag_{lag}"] = frame.value.shift(lag)
    frame["target"] = frame.value.shift(-steps)
    frame = frame.dropna()
    cut = int(len(frame) * .8)
    train, test = frame.iloc[:cut], frame.iloc[cut:]
    if len(train) < 20 or len(test) < 5: raise ValueError("insufficient temporal samples")
    cols = [c for c in frame if c.startswith("lag_")]
    model = XGBRegressor(n_estimators=80, max_depth=3, learning_rate=.05, random_state=42, verbosity=0).fit(train[cols], train.target)
    actual, xgb, persistence = test.target, model.predict(test[cols]), test.value
    def metrics(pred):
        return {"mae": float(mean_absolute_error(actual, pred)), "rmse": float(np.sqrt(mean_squared_error(actual, pred))), "r2": float(r2_score(actual, pred))}
    return {"n_train": len(train), "n_test": len(test), "persistence": metrics(persistence), "xgboost": metrics(xgb)}

def run(csv_path: Path, station: str) -> pd.DataFrame:
    raw = pd.read_csv(csv_path)
    if "device" in raw: raw = raw[raw.device.astype(str) == station]
    raw["fetchedAt"] = pd.to_datetime(raw["fetchedAt"], utc=True)
    rows=[]
    for param in DIRECT_PARAMS:
        if param not in raw: continue
        valid = raw.loc[raw[param].map(lambda x: is_in_range(param, x)), ["fetchedAt", param]].set_index("fetchedAt")[param]
        # Median aggregation avoids inventing values by interpolation.
        series = valid.resample("3min").median().dropna()
        for minutes in HORIZONS:
            try:
                result=backtest_series(series, minutes)
                for model in ("persistence", "xgboost"):
                    rows.append({"station":station,"param":param,"horizon_minutes":minutes,"model":model,**result[model],"n_train":result["n_train"],"n_test":result["n_test"]})
            except ValueError as exc: rows.append({"station":station,"param":param,"horizon_minutes":minutes,"model":"not_evaluated","reason":str(exc)})
    return pd.DataFrame(rows)

if __name__ == "__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("csv",type=Path); ap.add_argument("--station",required=True); ap.add_argument("--output",type=Path,required=True); args=ap.parse_args()
    out=run(args.csv,args.station); args.output.parent.mkdir(parents=True,exist_ok=True); out.to_csv(args.output,index=False); print(out.to_string(index=False))
