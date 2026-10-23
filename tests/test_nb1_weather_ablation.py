import pandas as pd

from experiments.nb1_weather_ablation import evaluate_pair, paired_frame


def _row(station, quarter, offset):
    return {"Station": station, "Quarter": quarter, "pH": 7.5 + offset, "Temperature": 25 + offset, "TSS": 10 + offset, "NH3": .02 + offset / 100, "Rain_median": 1 + offset, "Wind_median": 3 + offset, "Wave_median": .5 + offset / 10, "DO": 6 + offset, "Salinity": 30 + offset}


def test_pairing_and_temporal_gate():
    data = pd.DataFrame([_row("NB1", f"202{i // 4}-0{(i % 4) + 1}-01", i) for i in range(12)] + [_row("NB2", f"202{i // 4}-0{(i % 4) + 1}-01", i + .1) for i in range(12)])
    frame = paired_frame(data, "NB2")
    result = evaluate_pair(frame, "DO", include_weather=True)
    assert len(frame) == 12
    assert result["status"] == "evaluated"
    assert result["evidence"] == "exploratory_only"
