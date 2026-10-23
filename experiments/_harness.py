# lab/realtime_greenlab/experiments/_harness.py
import numpy as np
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.metrics import r2_score
from xgboost import XGBRegressor

def loo_cv_r2(df, feat_cols, target, group_col="Station",
              n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42, estimator=None):
    """LOO-CV-theo-trạm cho 1 target. Trả về (r2, n_used) hoặc (None, n_used) nếu không đủ data.
    Cùng cấu hình XGBoost với impute.py để số liệu so sánh được. Nếu estimator được truyền, nó sẽ dùng estimator đó."""
    required_cols = feat_cols + [target, group_col]
    df_valid = df.dropna(subset=required_cols).copy()
    
    n_used = len(df_valid)
    if n_used < 20 or df_valid[group_col].nunique() < 3:
        return None, n_used
        
    y = df_valid[target].values
    if np.std(y) == 0:
        return 1.0, n_used
        
    X = df_valid[feat_cols].values
    groups = df_valid[group_col].values
    
    logo = LeaveOneGroupOut()
    preds, trues = [], []
    
    from sklearn.base import clone
    
    for tr, te in logo.split(X, y, groups):
        if len(np.unique(groups[tr])) < 2:
            continue
        if len(tr) < 5 or len(te) == 0:
            continue
            
        if estimator is None:
            m = XGBRegressor(n_estimators=n_estimators, max_depth=max_depth, 
                             learning_rate=learning_rate, random_state=random_state, verbosity=0)
        else:
            m = clone(estimator)
            
        m.fit(X[tr], y[tr])
        preds.extend(m.predict(X[te]))
        trues.extend(y[te])
        
    if len(trues) < 5:
        return None, n_used
        
    r2 = round(float(r2_score(trues, preds)), 4)
    return r2, n_used

