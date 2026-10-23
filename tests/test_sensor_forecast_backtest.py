import numpy as np
import pandas as pd
from experiments.sensor_forecast_backtest import backtest_series
def test_backtest_compares_persistence_and_xgboost():
    s=pd.Series(np.sin(np.arange(150)/6)+20,index=pd.date_range("2026-01-01",periods=150,freq="3min",tz="UTC"))
    result=backtest_series(s,15)
    assert result["n_test"] > 5 and "rmse" in result["persistence"] and "rmse" in result["xgboost"]
