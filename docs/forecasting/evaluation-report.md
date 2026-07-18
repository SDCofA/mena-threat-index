# Governed forecast pilot evaluation report

## Frozen evaluation

The benchmark manifest was frozen before this final backtest with status
`frozen-before-evaluation`. It fixes the target, resolution rule, ordered
rolling-origin method, source hashes, missing-data policy, baselines, metrics,
bootstrap settings, and required report fields.

- **Manifest:** [`forecasting/benchmark-manifest.json`](../../forecasting/benchmark-manifest.json)
- **Manifest hash:** `sha256:b18ed7fbc4b4832ca008b62263c99c1a55e7de647d369b2632a145d40b61dcac`
- **Governance schema commit:** `86b1c12`
- **Evaluation period:** 2026-06-27 20:00 UTC through 2026-07-18 10:00 UTC
- **Sample:** 178 timestamped model-vs-naïve observations
- **Horizon:** one recorded pipeline step
- **Domain:** MENA composite threat-index series
- **Missing data:** no imputation or timestamp interpolation

## Results

| Forecast or baseline | MAE | RMSE |
| --- | ---: | ---: |
| Recorded model | 0.008764 | 0.014221 |
| Naïve | 0.008315 | 0.011708 |
| Persistence | 0.008315 | 0.011708 |
| Expanding-mean reference | 0.044126 | 0.062783 |

On this frozen sample, the recorded model has **5.4% higher MAE than the naïve
baseline** (absolute MAE difference `+0.000449` index points). The deterministic
paired-bootstrap 95% interval for that difference is `[-0.000618, +0.001854]`
using 10,000 paired resamples and seed `20260718`. The interval includes zero,
so this sample does not establish a directional difference.

## Rolling-origin and calibration checks

Rows were evaluated in timestamp order. The expanding-mean reference and each
migration envelope use only outcomes resolved before the forecast origin.
Leakage tests reject any feature or retrieval timestamp after the cutoff.

Of the 178 evaluation rows, 175 have exact forecast-to-history lineage and are
represented in the governed ledger. Their migration-envelope empirical
coverage was:

| Nominal level | Empirical coverage |
| ---: | ---: |
| 50% | 80.6% |
| 80% | 88.0% |
| 95% | 97.1% |

These envelopes are backfilled governance diagnostics, not historically issued
prediction intervals. Their coverage cannot be used as evidence about the
uncertainty shown to users during the evaluation period.

## Traceability and exclusions

Every record in [`forecasting/records.jsonl`](../../forecasting/records.jsonl)
has a stable ID, issue time, cutoff, horizon, unchanged point, resolution,
absolute-error score, method/data/code versions, benchmark hash, hash-linked
source snapshot, and complete feature timestamps. Attempts to rewrite an
existing ledger with changed bytes fail.

Three evaluation rows—`2026-06-29T18Z`, `2026-07-04T14Z`, and
`2026-07-15T10Z`—do not exactly match the immediately preceding retained
history points. They remain in the 178-row aggregate comparison and are
explicitly excluded from governed record migration. Their values were not
silently corrected.

The blind audit starts only with
`mti-composite-2026-07-18t08z-v1` and reconstructs its issue-time input
snapshot, method/version, point `1.98`, outcome `1.98`, and MAE score `0.0`.
The committed reconstruction is
[`forecasting/blind-audit.json`](../../forecasting/blind-audit.json).

## Reproduction

```shell
python -m scripts.forecast_governance --check
python -m pytest -q tests/test_forecast_governance.py
```

Identical source files, manifest, and code version produce byte-identical
evaluation, ledger, provenance, and audit artifacts. Machine-readable evidence
is in [`forecasting/evaluation-results.json`](../../forecasting/evaluation-results.json)
and [`forecasting/provenance-manifest.json`](../../forecasting/provenance-manifest.json).

## Limitations and claim boundary

The period is short, operational, and not a randomized sample. Three legacy
rows lack exact retained lineage. Backfilled calibration envelopes were not
issued historically. The model result is currently worse on MAE than the naïve
baseline, while the paired interval includes zero. No public
comparative-performance claim is supported.
