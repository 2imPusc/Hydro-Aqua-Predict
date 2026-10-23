# lab/realtime_greenlab/experiments/exp_tabpfn_debug.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from tabpfn import TabPFNRegressor

def test_tabpfn():
    X_train = np.random.rand(50, 6)
    y_train = np.random.rand(50)
    X_test = np.random.rand(10, 6)
    
    try:
        model = TabPFNRegressor()
        model.fit(X_train, y_train)
        preds = model.predict(X_test)
        print("Success! Predictions:", preds[:5])
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_tabpfn()
