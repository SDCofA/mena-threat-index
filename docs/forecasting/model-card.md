# MENA one-step composite forecast model card

## Status and scope

- **Evaluation contract:** `forecast-standard-pilot/v1`
- **Historical model version:** `legacy-pre-governance`
- **Governance source:** `MonarchCastleTech/company-governance` commit `86b1c12`
- **Source snapshot commit:** `02da23265a6420a272ce2aa3134b4d72fa4d6f75`
- **Target:** next recorded MENA composite threat-index level
- **Target type and unit:** continuous, index points
- **Horizon:** one recorded pipeline step (normally two hours; the exact elapsed horizon is stored per forecast)

This card describes a governed migration and evaluation contract. It does not
state or imply achieved forecast accuracy.

## Data and cutoff controls

The frozen inputs are [`data/forecast_eval.jsonl`](../../data/forecast_eval.jsonl)
and [`data/history.jsonl`](../../data/history.jsonl). Their hashes and counts are
fixed in [`forecasting/benchmark-manifest.json`](../../forecasting/benchmark-manifest.json).
Forecast records include the complete ordered feature-timestamp set used at
their origin. Validation rejects a source retrieval or feature timestamp after
`dataCutoff`.

Of 178 timestamped evaluation rows, 175 stored model and naïve points match the
immediately preceding retained history row exactly and are migrated to the
append-only ledger. Three rows remain in aggregate evaluation but are excluded
from forecast-record migration; their mismatches are listed in
[`evaluation-results.json`](../../forecasting/evaluation-results.json). No
historical point, outcome, or score is rewritten.

## Method and uncertainty

The retained point is the historical one-step composite forecast. For migrated
records, 50%, 80%, and 95% coverage envelopes are generated from absolute
errors resolved before each issue-time cutoff. These envelopes exercise the
governance calibration contract but were not part of the historically issued
point forecasts; they must not be described as contemporaneous uncertainty.

The model assumes that the next recorded composite index is the resolution
target and that the operational history is ordered correctly. Missing rows are
not imputed, time series are never shuffled, and future outcomes are not model
inputs.

## Baselines and scoring

The frozen baselines are:

- recorded naïve point;
- persistence, which is numerically identical to the recorded naïve point for
  this one-step target; and
- an expanding-mean reference using only previously resolved outcomes, with the
  first origin initialized from its recorded naïve point.

Primary scoring is MAE. Secondary reporting includes RMSE, empirical 50%, 80%,
and 95% coverage, and a paired-bootstrap 95% interval for the model-minus-naïve
MAE difference. The bootstrap uses 10,000 resamples and fixed seed `20260718`.

## Reproduction and audit

```shell
python -m scripts.forecast_governance --check
python -m pytest -q tests/test_forecast_governance.py
```

The benchmark manifest hash is
`sha256:b18ed7fbc4b4832ca008b62263c99c1a55e7de647d369b2632a145d40b61dcac`.
The machine-readable results are in
[`forecasting/evaluation-results.json`](../../forecasting/evaluation-results.json),
and the human-readable interpretation is in
[`evaluation-report.md`](evaluation-report.md).

The blind-audit seed is forecast ID
`mti-composite-2026-07-18t08z-v1`. Supplying only that ID to
`reconstruct_forecast` recovers and verifies the input snapshot, method and
versions, point, outcome, and score recorded in
[`forecasting/blind-audit.json`](../../forecasting/blind-audit.json).

## Limitations

The evaluation period is short and operational. The migration intervals were
not issued historically. Three legacy rows cannot be promoted to governed
records. The observed model-minus-naïve confidence interval crosses zero.
These facts preclude a public comparative-performance claim.
