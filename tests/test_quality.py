# lab/realtime_greenlab/tests/test_quality.py
import pandas as pd
from core.quality import is_in_range, check_series, filter_valid_rows

def test_in_range_ok():
    assert is_in_range("pH", 7.5) is True

def test_in_range_cod_rail_rejected():
    assert is_in_range("COD", 558.8) is False   # ngoài (0,100)

def test_in_range_cod_healthy():
    assert is_in_range("COD", 9.8) is True

def test_unknown_param_passes():
    assert is_in_range("Unknown", 12345) is True   # không có range → bỏ qua

def test_check_series_flatline_rail():
    # 100 readings dính cứng 558.8 → INVALID
    s = pd.Series([558.8] * 100)
    status = check_series("COD", s)
    assert status == "INVALID"

def test_check_series_healthy():
    s = pd.Series([8.5, 9.0, 10.2, 9.8, 11.0])
    status = check_series("COD", s)
    assert status == "VALID"

def test_check_series_stuck_at_zero_is_flatline():
    # Sensor dính cứng đúng 0.0 (mean == 0 nên CV không xét được) → INVALID
    s = pd.Series([0.0] * 10)
    assert check_series("COD", s) == "INVALID"

def test_check_series_varying_with_zeros_valid():
    # Có số 0 nhưng chuỗi vẫn dao động → không phải flatline
    s = pd.Series([0, 0.5, 1.2, 0, 2.0, 0.3])
    assert check_series("COD", s) == "VALID"

def test_check_series_few_zeros_keeps_valid():
    # < 5 điểm: quá ít để kết luận flatline → giữ hành vi cũ (VALID)
    s = pd.Series([0.0, 0.0, 0.0])
    assert check_series("COD", s) == "VALID"

def test_check_series_empty():
    assert check_series("COD", pd.Series([], dtype=float)) == "INVALID"

def test_filter_valid_rows_drops_out_of_range():
    df = pd.DataFrame({
        "COD": [9.0, 558.8, 10.0],
        "pH":  [7.5, 7.6, 20.0],     # 20 ngoài dải pH
    })
    out = filter_valid_rows(df, ["COD", "pH"])
    # Row 0 hợp lệ; row 1 COD rail; row 2 pH out → chỉ row 0 còn
    assert len(out) == 1
    assert out.iloc[0]["COD"] == 9.0
