# lab/realtime_greenlab/tests/test_monitor.py
from core.monitor import check_params, ParamStatus

def test_nh3_ok_low():
    r = check_params({"NH3": 0.05, "pH": 7.5, "Temperature": 28.0, "TSS": 30.0})
    assert r["NH3"].status == "OK"

def test_nh3_exceed():
    r = check_params({"NH3": 0.15, "pH": 7.5, "Temperature": 28.0, "TSS": 30.0})
    assert r["NH3"].status == "EXCEED"

def test_ph_below_min_exceed():
    r = check_params({"pH": 6.0, "Temperature": 28.0, "TSS": 30.0})
    assert r["pH"].status == "EXCEED"

def test_ph_ok():
    r = check_params({"pH": 7.5, "Temperature": 28.0, "TSS": 30.0})
    assert r["pH"].status == "OK"

def test_temp_exceed():
    r = check_params({"pH": 7.5, "Temperature": 32.0, "TSS": 30.0})
    assert r["Temperature"].status == "EXCEED"

def test_cod_skipped_when_none():
    # COD không truyền vào (sensor chết) → không xuất hiện trong kết quả
    r = check_params({"pH": 7.5, "Temperature": 28.0, "TSS": 30.0})
    assert "COD" not in r

def test_cod_checked_when_present():
    r = check_params({"COD": 9.0, "pH": 7.5, "Temperature": 28.0, "TSS": 30.0})
    assert r["COD"].status == "OK"

def test_non_qcvn_param_ignored():
    r = check_params({"DO": 6.5, "pH": 7.5})
    assert "DO" not in r
