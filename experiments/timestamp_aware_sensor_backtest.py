"""Direct sensor backtest that respects real 1/3/5-minute timestamps."""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from xgboost import XGBRegressor
from core.quality import is_in_range
from core.fetch import fetch_raw

PARAMS=("Temperature","pH","NH4","TSS")
HORIZONS=(15,30,60)
LAGS=(1,2,3,5,10)

def frame_for(series, horizon):
    base=pd.DataFrame({"issued_at":series.index,"value":series.to_numpy()})
    base["cadence_minutes"]=base["issued_at"].diff().dt.total_seconds().div(60).round()
    for lag in LAGS: base[f"lag_{lag}"]=base.value.shift(lag)
    base["valid_at"]=base.issued_at+pd.Timedelta(minutes=horizon)
    actual=pd.DataFrame({"actual_at":series.index,"target":series.to_numpy()})
    out=pd.merge_asof(base.sort_values("valid_at"),actual.sort_values("actual_at"),left_on="valid_at",right_on="actual_at",direction="nearest",tolerance=pd.Timedelta(minutes=2))
    return out.dropna()

def run(path,station):
    raw=fetch_raw(station) if str(path)=="mongodb" else pd.read_csv(path)
    if "device" in raw: raw=raw[raw.device.astype(str).eq(station)].copy()
    raw.fetchedAt=pd.to_datetime(raw.fetchedAt,utc=True)
    rows=[]
    for param in PARAMS:
        s=raw.loc[raw[param].map(lambda x:is_in_range(param,x)),["fetchedAt",param]].set_index("fetchedAt")[param].sort_index()
        for h in HORIZONS:
            f=frame_for(s,h); cut=int(len(f)*.8); train,test=f.iloc[:cut],f.iloc[cut:]
            if len(train)<30 or len(test)<10: continue
            cols=[f"lag_{x}" for x in LAGS]; model=XGBRegressor(n_estimators=120,max_depth=3,learning_rate=.05,random_state=42,verbosity=0).fit(train[cols],train.target)
            for name,pred in (("persistence",test.value),("xgboost",model.predict(test[cols]))):
                rows.append({"param":param,"horizon_minutes":h,"model":name,"cadence":"all","n":len(test),"mae":mean_absolute_error(test.target,pred),"rmse":np.sqrt(mean_squared_error(test.target,pred))})
                scored=pd.DataFrame({"pred":np.asarray(pred),"actual":test.target.to_numpy(),"cadence":test.cadence_minutes.to_numpy()})
                for cadence,mask in (("1m",scored.cadence.between(.5,1.5)),("3m",scored.cadence.between(1.5,3.5)),("5m",scored.cadence.between(3.5,5.5)),("gap",scored.cadence>5.5)):
                    grp=scored[mask]
                    if len(grp)>=3: rows.append({"param":param,"horizon_minutes":h,"model":name,"cadence":cadence,"n":len(grp),"mae":mean_absolute_error(grp.actual,grp.pred),"rmse":np.sqrt(mean_squared_error(grp.actual,grp.pred))})
    return pd.DataFrame(rows)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('csv',type=Path);p.add_argument('--station',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();o=run(a.csv,a.station);a.output.parent.mkdir(parents=True,exist_ok=True);o.to_csv(a.output,index=False);print(o.to_string(index=False))
