# Forecast-risk advisory

`core/forecast_advisory.py` converts the 15/30/60-minute sensor-first shadow timeline into an early advisory, separate from direct-sensor alerts.

- Forecast DO <= 5 mg/L creates WATCH; forecast DO <= 4 or forecast Temperature >= 33 C creates WARNING advisory.
- A forecast DO <= 3 is still capped at WARNING, never Emergency.
- `notification_eligible=false` and `used_by_emergency=false` are mandatory.
- Salinity is retained as contextual output only because no operational cobia salinity threshold has been approved.

The advisory is dashboard-only and is not sent, acknowledged or used to control equipment.
# Forecast-risk advisory timeline

The Hai Phong sensor-first forecast now produces one explainable risk point at
each +15/+30/+60-minute horizon. Each point stores forecast Temperature and
derived NH3, inferred DO/Salinity, model/source provenance, drivers and a
`NORMAL`/`WATCH`/`WARNING` advisory severity.

The advisory is appended to the shadow forecast ledger at issue time, so later
sensor outcomes can be evaluated against the exact forecast and risk context
that were available then. The dashboard renders this timeline as a table.

Safety boundary: inferred DO and Salinity are never treated as direct sensor
measurements. Forecast advisory has `notification_eligible=false` and
`used_by_emergency=false`; it cannot trigger an Emergency. Direct sensor alert
policy remains separate.

## Operational inferred-DO policy

Inferred DO is a valid early-warning driver because direct DO hardware is not
available. It is labelled as inferred and must pass the contextual model's
accepted/in-domain gate. The policy is deliberately confirmation-based:

| Condition | Result |
| --- | --- |
| inferred DO <= 5 mg/L | WATCH on dashboard |
| inferred DO <= 4 mg/L, repeated for two cycles or accompanied by Temperature >= 31C / NH3 >= 0.05 mg/L | WARNING, `notification_eligible=true` |
| inferred DO <= 3 mg/L, repeated for two cycles and compound stress | CRITICAL_ADVISORY, `notification_eligible=true` |
| rejected/OOD inference or stale source data | BLOCKED; no notification |

`CRITICAL_ADVISORY` is an operational call to inspect the cage and prepare
aeration; it is not an `EMERGENCY`. The runner stores the risk count and
notification decision in the append-only ledger, so persistence continues after
a process restart.
