import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

def check_health(station: str, path: Path):
    if not path.exists():
        return {"status": "missing", "reason": "file_not_found"}
        
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            doc = json.loads(line)
            if doc.get("station") == station:
                records.append(doc)
                
    if not records:
        return {"status": "missing", "reason": "no_records_for_station"}
        
    # extract distinct captures by retrieved_at
    captures = {}
    for r in records:
        rat = r.get("retrieved_at")
        if rat:
            captures[rat] = r
            
    sorted_caps = sorted(captures.keys())
    last_cap_time = datetime.fromisoformat(sorted_caps[-1].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    
    age_hours = (now - last_cap_time).total_seconds() / 3600
    
    status = "healthy"
    if age_hours > 2:
        status = "stale"
        
    # count last 24h, 7d
    cap_24h = sum(1 for c in sorted_caps if (now - datetime.fromisoformat(c.replace("Z", "+00:00"))).total_seconds() <= 86400)
    cap_7d = sum(1 for c in sorted_caps if (now - datetime.fromisoformat(c.replace("Z", "+00:00"))).total_seconds() <= 7*86400)
    
    # gaps > 2h
    gaps = []
    times = [datetime.fromisoformat(c.replace("Z", "+00:00")) for c in sorted_caps]
    for i in range(1, len(times)):
        diff = (times[i] - times[i-1]).total_seconds() / 3600
        if diff > 2:
            gaps.append({"start": times[i-1].isoformat(), "end": times[i].isoformat(), "hours": round(diff, 1)})
            
    last_record = captures[sorted_caps[-1]]
    
    return {
        "status": status,
        "last_capture_at": last_cap_time.isoformat(),
        "age_hours": round(age_hours, 1),
        "captures_24h": cap_24h,
        "captures_7d": cap_7d,
        "gaps_gt_2h": gaps,
        "location_id": last_record.get("location_id", "unknown"),
        "missing_forecast_hours": 0 # simplified
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--station", required=True)
    parser.add_argument("--snapshots", type=Path, default=Path("artifacts/experiments/forecast-v2/weather-snapshots.jsonl"))
    args = parser.parse_args()
    
    result = check_health(args.station, args.snapshots)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
