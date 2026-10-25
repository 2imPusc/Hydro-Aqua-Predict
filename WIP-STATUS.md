# WIP — H1.7 transfer learning (foreign pretrain + NB1 fine-tune) — checkpoint 2026-10-25 ~14:25

Stopped early at the owner's request (machine shutdown). No results have been looked at yet:
no evaluate stage has run, so the pre-registered design is still clean.

## Done
- `experiments/transfer_forecast.py`: stages `prepare | features | fit | evaluate`. The whole design is
  pre-registered in the module docstring: representation, families, inner-validation rule, Eval A/B,
  site-similarity rule, regime threshold and best-NB1-only rule.
- `tests/test_transfer_forecast.py`: 10 tests pass in the main `.venv`. They cover causality against
  truncated and tampered data, the delta target, fold purge, inner split, Eval-B boundaries, Prep
  statistics fitted on train only, and shrunk-ridge limits. `scripts/check_isolation.py` passes.
  The full core suite has not been re-run yet.
- The worktree branch was fast-forwarded to `h1-ph-drift-followup` (e35144b) to get `foundation_zero_shot.py`.

## Run dir `artifacts/experiments/transfer-forecast-20261025/` (main checkout)
Complete:
- `foreign-15min.parquet`, `foreign_site_stats.csv`, `manifest-prepare.json`: 33 NERRS stations,
  2007–2011, per-file sha256. The similar set (fixed rule, OISST p5 18.76 / p95 30.34) is
  rkbmb rkbfu rkbfb rkblh marsc gtmpi gtmss gtmfm.
- `features-Temperature/` (h15/60/180/360/720) and `features-pH/` (h60/180), each with `manifest.json`.
  The look-ahead assert passed on 20 origins per horizon.
- `pred-Temperature-ridge.*`, `hyper-Temperature-ridge.csv`, `pred-pH-ridge.*`, `hyper-pH-ridge.csv`.

Partial or missing:
- `pred-Temperature-xgb.*` is missing. The run started at 13:26 and finished foreign pretraining for
  h15 (all 70 s, sim 44 s). It then appeared stalled in the first NB1 fold split for ~55 min (low CPU
  time). The process (PID 5408) could not be killed from the session. It writes only at the end, so
  nothing partial was written. If a `pred-Temperature-xgb.parquet` appears anyway, treat it as
  suspect and check its `.json`.
- Not run yet: `pred-pH-xgb`, `pred-*-mlp` (an MLP smoke test on a small sample passed in `.venv-fm`),
  and every `evaluate` stage.

## Next steps
1. Debug the xgb stall before rerunning. Time one split by hand: `XGBFamily().nb1(...)` and
   `.finetune(...)` on `features-Temperature/nb1-train-h15.parquet`. Suspects:
   - the `FT`/`NB1` params lack `tree_method: "hist"`;
   - continued boosting on a copied foreign booster;
   - CPU contention with another python process (PID 13912, started 12:57, not from this task).
   Likely fixes: add `"tree_method": "hist"` to `NB1`/`FT`, and evaluate the fine-tune rounds with one
   `evals_result` pass instead of 61 `predict` calls. These are implementation fixes, not design changes.
2. The run dir already holds ridge predictions. Either:
   - keep the run dir and only add the missing `pred-*` files (each stage refuses to overwrite); or
   - if the xgb code changes, keep the run dir (the ridge and features stay valid) and note the
     change in NOTES.
   A new run name is needed only if `prepare` or `features` must change.
3. Commands (bash, from the worktree root):
   ```
   export HAP_DATA_DIR=/d/2impusc/Hydro-Aqua-Predict/data HAP_ARTIFACTS_DIR=/d/2impusc/Hydro-Aqua-Predict/artifacts
   PY=/d/2impusc/Hydro-Aqua-Predict/.venv/Scripts/python; FM=/d/2impusc/Hydro-Aqua-Predict/.venv-fm/Scripts/python
   $PY experiments/transfer_forecast.py fit --target Temperature --family xgb
   $PY experiments/transfer_forecast.py fit --target pH --family xgb
   $FM experiments/transfer_forecast.py fit --target Temperature --family mlp
   $FM experiments/transfer_forecast.py fit --target pH --family mlp
   $PY experiments/transfer_forecast.py evaluate --target Temperature --eval A   # A first, freeze it
   $PY experiments/transfer_forecast.py evaluate --target pH --eval A
   $PY experiments/transfer_forecast.py evaluate --target Temperature --eval B
   ```
4. Then:
   - write `NOTES.md` in Vietnamese, RL style, with a top-level `manifest.json` (input sha256s are in
     `manifest-prepare.json` and `features-*/manifest.json`, package versions in each `pred-*.json`);
   - run the full core pytest and the isolation check;
   - make one commit;
   - put the proposed RESULTS row and RL entry in the final report (do not edit RESULTS.md, the
     research log or decisions.md).

## Fixed (pre-registered) choices, already in the docstring
- Step: 15 min.
- Target: delta from p[T].
- Features: 25.
- Hour of day: local standard time.
- Foreign data:
  - NERRS only;
  - thinned to 1/8 per horizon;
  - holdout year 2011 used only for foreign early stopping.
- Inner validation: the last 7 days of each split's NB1 training rows, MAE criterion, then refit.
- Eval B:
  - training rows valid before 01/09 local; test origins issued 15/09–24/10;
  - weekly blocks; the gate analogue needs ≥ 5/6 blocks plus DM p < 0.05;
  - Temperature only.
- Large-diurnal regime: amp24 > 3.0 °C.
- Best NB1-only model: chosen on rolling-fold mean MAE only.
- Chronos fine-tuning: skipped.
- TSS and NH4: skipped.
