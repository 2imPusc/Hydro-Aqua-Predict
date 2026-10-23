import pandas as pd
import json
import sys
import hashlib
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.fetch import _read_csv
from core.greenlab_api import load_cached_history
from core.config import MONGODB_URI, MONGODB_DB_NAME, MONGODB_COLLECTION
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

def check_mongo(station):
    if not MONGODB_URI:
        return {'status': 'not_configured'}
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=3000)
        client.admin.command('ping')
        db = client[MONGODB_DB_NAME]
        col = db[MONGODB_COLLECTION]
        count = col.count_documents({"device": station})
        if count == 0:
            return {'status': 'query_empty', 'count': 0}
        
        # Actually fetch
        cursor = col.find({"device": station}).sort("fetchedAt", 1)
        df = pd.DataFrame(list(cursor))
        return {'status': 'success', 'count': len(df), 'df': df}
    except ConnectionFailure:
        return {'status': 'timeout'}
    except OperationFailure as e:
        return {'status': 'auth_error', 'reason': str(e)}
    except Exception as e:
        return {'status': 'error', 'reason': str(e)}

def parse_and_audit(df, source_name):
    if df is None or df.empty:
        return pd.DataFrame(), {'total': 0}
    
    total = len(df)
    # convert fetchedAt explicitly
    parsed = pd.to_datetime(df['fetchedAt'], utc=True, errors='coerce')
    unparseable = parsed.isna()
    
    unparseable_examples = df.loc[unparseable, 'fetchedAt'].head(5).tolist()
    
    df_clean = df[~unparseable].copy()
    df_clean['fetchedAt'] = parsed[~unparseable]
    
    return df_clean, {
        'total_rows': total,
        'unparseable_count': int(unparseable.sum()),
        'unparseable_examples': unparseable_examples
    }

def normalize_dataframe(df, source_name):
    if df is None or df.empty:
        return pd.DataFrame()
    
    rows = []
    for _, r in df.iterrows():
        t = r['fetchedAt']
        for param in ['COD', 'NH4', 'pH', 'Temperature', 'TSS']:
            if param in r and pd.notna(r[param]):
                unit = 'mg/L' if param in ['COD', 'TSS'] else ('C' if param == 'Temperature' else ('unit_unconfirmed' if param == 'NH4' else ''))
                rows.append({
                    'observed_at_utc': t,
                    'parameter': param,
                    'value': r[param],
                    'original_unit': unit,
                    'source': source_name,
                    'source_record_id': hashlib.md5(f"{source_name}_{t.isoformat()}_{param}".encode()).hexdigest(),
                })
    return pd.DataFrame(rows)

def main():
    STATION = "06M26042804"
    RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    OUT_DIR = Path(f"artifacts/experiments/weather-risk-pilot/round3/{RUN_ID}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"Starting A inventory. Run ID: {RUN_ID}")
    
    dfs = []
    sources_info = {}
    audit_info = {}
    
    # 1. MongoDB
    mongo_res = check_mongo(STATION)
    sources_info['mongodb'] = {k: v for k, v in mongo_res.items() if k != 'df'}
    if mongo_res['status'] == 'success':
        df_m, audit_m = parse_and_audit(mongo_res['df'], 'mongodb')
        audit_info['mongodb'] = audit_m
        dfs.append(normalize_dataframe(df_m, 'mongodb'))
        
    # 2. CSV fallback
    try:
        df_csv = _read_csv(STATION)
        df_c, audit_c = parse_and_audit(df_csv, 'local_csv')
        audit_info['local_csv'] = audit_c
        df_csv_norm = normalize_dataframe(df_c, 'local_csv')
        dfs.append(df_csv_norm)
        sources_info['local_csv'] = {'status': 'success', 'count': len(df_csv_norm)}
    except Exception as e:
        sources_info['local_csv'] = {'status': 'error', 'reason': str(e)}

    # 3. Cached History
    try:
        df_cache = load_cached_history(STATION)
        df_h, audit_h = parse_and_audit(df_cache, 'cached_history')
        audit_info['cached_history'] = audit_h
        df_cache_norm = normalize_dataframe(df_h, 'cached_history')
        dfs.append(df_cache_norm)
        sources_info['cached_history'] = {'status': 'success', 'count': len(df_cache_norm)}
    except Exception as e:
        sources_info['cached_history'] = {'status': 'error', 'reason': str(e)}
        
    if not dfs:
        print("No data found.")
        return
        
    df_all = pd.concat(dfs, ignore_index=True)
    df_all['station_id'] = STATION
    
    # Audit unique timestamps vs rows
    n_sensor_timestamps = df_all['observed_at_utc'].nunique()
    n_parameter_rows = len(df_all)
    
    # Duplicate logic: exact (station, observed_at, parameter)
    duplicates = df_all[df_all.duplicated(subset=['station_id', 'observed_at_utc', 'parameter'], keep=False)]
    if not duplicates.empty:
        duplicates.to_csv(OUT_DIR / "duplicates.csv", index=False)
        
    # Keep first by source priority
    source_priority = {'cached_history': 1, 'local_csv': 2, 'mongodb': 3}
    df_all['priority'] = df_all['source'].map(source_priority)
    df_clean = df_all.sort_values(['observed_at_utc', 'priority']).drop_duplicates(subset=['station_id', 'observed_at_utc', 'parameter'], keep='first').copy()
    df_clean.drop(columns=['priority'], inplace=True)
    
    n_source_records = len(df_clean)
    
    with open(OUT_DIR / "sensor_parse_audit.json", "w") as f:
        json.dump({
            "n_sensor_timestamps": n_sensor_timestamps,
            "n_parameter_rows": n_parameter_rows,
            "n_source_records_after_dedup": n_source_records,
            "source_audits": audit_info
        }, f, indent=2)
    
    # Generate source_inventory.json
    inv = {
        "run_started_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources_info,
        "combined_records": n_source_records,
    }
    with open(OUT_DIR / "source_inventory.json", "w") as f:
        json.dump(inv, f, indent=2)
        
    # Gaps
    sensor_times = pd.Series(df_clean['observed_at_utc'].unique()).sort_values()
    gaps_diff = sensor_times.diff().dt.total_seconds()
    gaps_df = pd.DataFrame({'end': sensor_times, 'duration_seconds': gaps_diff})
    gaps_df['start'] = gaps_df['end'] - pd.to_timedelta(gaps_df['duration_seconds'], unit='s')
    gaps_df[gaps_df['duration_seconds'] > 300].to_csv(OUT_DIR / "gaps.csv", index=False)
    
    # Output to flat CSV structure expected by downstream models
    df_pivot = df_clean.pivot(index='observed_at_utc', columns='parameter', values='value').reset_index()
    df_pivot = df_pivot.rename(columns={'observed_at_utc': 'fetchedAt'})
    
    # Format exactly as ISO-8601 with Z
    df_pivot['fetchedAt'] = df_pivot['fetchedAt'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    df_pivot.to_csv(OUT_DIR / "standardized_sensor_data.csv", index=False)
    
    print(f"R1 complete. Output in {OUT_DIR}")
    with open("artifacts/experiments/weather-risk-pilot/round3/dir.txt", "w") as f:
        f.write(str(OUT_DIR))

if __name__ == "__main__":
    main()
