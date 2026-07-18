"""Governed forecast ledger, evaluation, and blind-audit reproduction.

This module migrates only historically reconstructable point forecasts. It
never changes the recorded point, outcome, or score in ``forecast_eval.jsonl``.
The aggregate benchmark retains all 178 timestamped model-vs-naive outcomes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORECASTING = ROOT / "forecasting"
MANIFEST_PATH = FORECASTING / "benchmark-manifest.json"
LEDGER_PATH = FORECASTING / "records.jsonl"
EVALUATION_PATH = FORECASTING / "evaluation-results.json"
PROVENANCE_PATH = FORECASTING / "provenance-manifest.json"
BLIND_AUDIT_PATH = FORECASTING / "blind-audit.json"
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ImmutableForecastError(RuntimeError):
    """Raised when a caller attempts to rewrite an existing forecast ledger."""


def canonical_json_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def pretty_json_bytes(value):
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()


def load_jsonl(path):
    rows = []
    with Path(path).open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from error
    return rows


def _parse_utc(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"timestamp is not RFC3339 UTC: {value!r}")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"timestamp is not RFC3339 UTC: {value!r}") from error
    return parsed


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _quantile(values, probability):
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    fraction = position - lower_index
    return ordered[lower_index] * (1 - fraction) + ordered[upper_index] * fraction


def _intervals(point, prior_errors):
    intervals = []
    for level in (0.5, 0.8, 0.95):
        width = _quantile(prior_errors, level)
        intervals.append(
            {
                "level": level,
                "lower": round(point - width, 6),
                "upper": round(point + width, 6),
            }
        )
    return intervals


def _record_id(issue_run_id):
    slug = re.sub(r"[^a-z0-9]+", "-", issue_run_id.lower()).strip("-")
    return f"mti-composite-{slug}-v1"


def _history_context(history):
    rows = sorted(
        (row for row in history if not row.get("seed") and row.get("index") is not None),
        key=lambda row: row["ts"],
    )
    return rows, {row["run_id"]: index for index, row in enumerate(rows)}


def build_forecast_records(history, evaluations, manifest_hash, code_version="forecast-standard-pilot/v1"):
    """Return immutable migrations and explicit legacy exclusions.

    A row is migrated only when its stored model and naive points exactly match
    the immediately preceding history record. All evaluations remain in the
    aggregate benchmark whether or not they can be migrated.
    """

    history_rows, history_index = _history_context(history)
    records = []
    exclusions = []
    ordered_evaluations = sorted(evaluations, key=lambda row: row["ts"])

    for evaluation_index, evaluation in enumerate(ordered_evaluations):
        current_index = history_index.get(evaluation.get("run_id"))
        if current_index is None or current_index == 0:
            exclusions.append(
                {
                    "runId": evaluation.get("run_id"),
                    "reason": "No immediately preceding non-seed history row.",
                }
            )
            continue
        issue_row = history_rows[current_index - 1]
        point_matches = float(issue_row.get("forecast_next")) == float(evaluation["model_pred"])
        naive_matches = float(issue_row["index"]) == float(evaluation["naive_pred"])
        if not point_matches or not naive_matches:
            exclusions.append(
                {
                    "runId": evaluation["run_id"],
                    "issueRunId": issue_row["run_id"],
                    "reason": (
                        "Stored evaluation points do not exactly match the immediately "
                        "preceding history row; the legacy result is retained for aggregate "
                        "evaluation but is not rewritten as a governed forecast."
                    ),
                    "recordedModelPoint": evaluation["model_pred"],
                    "historyModelPoint": issue_row.get("forecast_next"),
                    "recordedNaivePoint": evaluation["naive_pred"],
                    "historyNaivePoint": issue_row["index"],
                }
            )
            continue

        issued_at = issue_row["ts"]
        ends_at = evaluation["ts"]
        horizon_hours = (_parse_utc(ends_at) - _parse_utc(issued_at)).total_seconds() / 3600
        if horizon_hours <= 0:
            raise ValueError(f"non-positive forecast horizon for {evaluation['run_id']}")
        prefix = history_rows[:current_index]
        snapshot_hash = sha256_bytes(canonical_json_bytes(prefix))
        prior_errors = [
            float(row["err_model"])
            for row in ordered_evaluations[:evaluation_index]
            if _finite(row.get("err_model"))
        ]
        record_id = _record_id(issue_row["run_id"])
        record = {
            "id": record_id,
            "lineageId": record_id,
            "version": 1,
            "recordType": "forecast",
            "target": {
                "id": "mena-composite-next-index",
                "label": "Next recorded MENA composite threat-index level",
                "type": "continuous",
            },
            "outcomeSpace": {
                "type": "continuous",
                "unit": "index-points",
            },
            "issuedAt": issued_at,
            "dataCutoff": issued_at,
            "horizon": {
                "value": horizon_hours,
                "unit": "hours",
                "endsAt": ends_at,
            },
            "distribution": {
                "point": float(evaluation["model_pred"]),
                "intervals": _intervals(float(evaluation["model_pred"]), prior_errors),
            },
            "uncertainty": {
                "description": (
                    "The point is the unchanged legacy forecast. Coverage intervals are "
                    "a governance-migration diagnostic derived only from absolute errors "
                    "resolved before this issue-time cutoff; they were not issued historically."
                ),
            },
            "assumptions": [
                "The next recorded composite index is the resolution target.",
                "No observation timestamped after the data cutoff is a forecast input.",
                "Legacy point, outcome, and absolute-error score remain unchanged.",
            ],
            "method": {
                "name": "MENA one-step composite forecast (legacy governed migration)",
                "modelVersion": "legacy-pre-governance",
                "dataVersion": manifest_hash,
                "codeVersion": code_version,
            },
            "resolutionCriteria": {
                "source": (
                    "https://github.com/SDCofA/mena-threat-index/forecast-evaluations/"
                    + evaluation["run_id"]
                ),
                "rule": (
                    "Resolve against the next actual recorded composite index and score "
                    "the unchanged point with absolute error."
                ),
                "outcome": float(evaluation["actual"]),
                "score": float(evaluation["err_model"]),
            },
            "provenance": {
                "sourceRecords": [
                    {
                        "source": (
                            "https://github.com/SDCofA/mena-threat-index/history/"
                            + issue_row["run_id"]
                        ),
                        "retrievedAt": issued_at,
                        "hash": snapshot_hash,
                    }
                ],
                "featureTimestamps": [row["ts"] for row in prefix],
                "dataSnapshotHash": snapshot_hash,
                "codeCommit": code_version,
                "benchmarkManifestHash": manifest_hash,
            },
            "supersedes": None,
        }
        validate_forecast_record(record)
        records.append(record)
    return records, exclusions


def validate_forecast_record(record):
    schema = json.loads((FORECASTING / "schemas" / "forecast-event.schema.json").read_text())
    required = set(schema["required"])
    missing = sorted(required - set(record))
    unknown = sorted(set(record) - set(schema["properties"]))
    if missing:
        raise ValueError(f"missing forecast fields: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"unknown forecast fields: {', '.join(unknown)}")
    if record["recordType"] != "forecast":
        raise ValueError("recordType must be forecast")
    if record["version"] != 1 or record["lineageId"] != record["id"] or record["supersedes"] is not None:
        raise ValueError("version 1 must start its own lineage and supersede nothing")
    if record["target"]["type"] != "continuous" or record["outcomeSpace"] != {
        "type": "continuous",
        "unit": "index-points",
    }:
        raise ValueError("pilot records must use the continuous index-points target")

    issued_at = _parse_utc(record["issuedAt"])
    cutoff = _parse_utc(record["dataCutoff"])
    ends_at = _parse_utc(record["horizon"]["endsAt"])
    if cutoff > issued_at:
        raise ValueError("data cutoff is after issue time")
    if ends_at <= issued_at:
        raise ValueError("forecast horizon must end after issue time")
    if not _finite(record["horizon"]["value"]) or record["horizon"]["value"] <= 0:
        raise ValueError("forecast horizon value must be positive")

    distribution = record["distribution"]
    if set(distribution) != {"point", "intervals"} or not _finite(distribution["point"]):
        raise ValueError("continuous distribution requires a finite point and intervals")
    intervals = distribution["intervals"]
    if [item.get("level") for item in intervals] != [0.5, 0.8, 0.95]:
        raise ValueError("coverage intervals must be ordered 50%, 80%, 95%")
    previous_lower = distribution["point"]
    previous_upper = distribution["point"]
    for interval in intervals:
        lower, upper = interval.get("lower"), interval.get("upper")
        if not _finite(lower) or not _finite(upper) or lower > distribution["point"] or upper < distribution["point"]:
            raise ValueError("coverage interval must contain the point")
        if lower > previous_lower or upper < previous_upper:
            raise ValueError("coverage intervals must be noncrossing and nested")
        previous_lower, previous_upper = lower, upper

    provenance = record["provenance"]
    provenance_schema = json.loads((FORECASTING / "schemas" / "provenance.schema.json").read_text())
    provenance_required = set(provenance_schema["required"])
    if provenance_required - set(provenance):
        raise ValueError("provenance is missing required fields")
    for field in ("dataSnapshotHash", "benchmarkManifestHash"):
        if not isinstance(provenance.get(field), str) or not HASH_RE.fullmatch(provenance[field]):
            raise ValueError(f"invalid provenance hash: {field}")
    if not provenance.get("sourceRecords"):
        raise ValueError("provenance requires a source record")
    for source in provenance["sourceRecords"]:
        if not str(source.get("source", "")).startswith(("http://", "https://")):
            raise ValueError("source record URI must use HTTP(S)")
        if not HASH_RE.fullmatch(str(source.get("hash", ""))):
            raise ValueError("source record hash is invalid")
        if _parse_utc(source.get("retrievedAt")) > cutoff:
            raise ValueError("temporal leakage: source was retrieved after data cutoff")
    for feature_timestamp in provenance.get("featureTimestamps", []):
        if _parse_utc(feature_timestamp) > cutoff:
            raise ValueError("temporal leakage: feature timestamp is after data cutoff")

    outcome = record["resolutionCriteria"]["outcome"]
    score = record["resolutionCriteria"]["score"]
    if not _finite(outcome) or not _finite(score):
        raise ValueError("resolved pilot forecast requires finite outcome and score")
    expected_score = round(abs(distribution["point"] - outcome), 3)
    if score != expected_score:
        raise ValueError("stored score does not equal the unchanged point absolute error")
    return True


def _ledger_bytes(records):
    return b"".join(canonical_json_bytes(record) + b"\n" for record in records)


def write_immutable_ledger(path, records):
    path = Path(path)
    expected = _ledger_bytes(records)
    if path.exists():
        if path.read_bytes() != expected:
            raise ImmutableForecastError(
                f"refusing to rewrite immutable forecast ledger: {path}"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as target:
        target.write(expected)


def _point_metrics(predictions, actuals):
    errors = [abs(float(prediction) - float(actual)) for prediction, actual in zip(predictions, actuals)]
    squared = [(float(prediction) - float(actual)) ** 2 for prediction, actual in zip(predictions, actuals)]
    return {
        "mae": sum(errors) / len(errors),
        "rmse": math.sqrt(sum(squared) / len(squared)),
    }


def _paired_bootstrap(differences, seed, resamples):
    rng = random.Random(seed)
    count = len(differences)
    means = []
    for _ in range(resamples):
        means.append(sum(differences[rng.randrange(count)] for _ in range(count)) / count)
    return {
        "lower": _quantile(means, 0.025),
        "upper": _quantile(means, 0.975),
        "seed": seed,
        "resamples": resamples,
    }


def evaluate(evaluations, records, manifest, manifest_hash=None):
    if manifest.get("status") != "frozen-before-evaluation":
        raise ValueError("benchmark manifest must be frozen before evaluation")
    ordered = sorted(evaluations, key=lambda row: row["ts"])
    expected_count = manifest["sourceSnapshot"]["forecastEvaluations"]["observationCount"]
    if len(ordered) != expected_count:
        raise ValueError(f"evaluation count changed after manifest freeze: {len(ordered)}")
    required = ("actual", "model_pred", "naive_pred", "ts", "err_model", "err_naive")
    if any(any(key not in row or (key != "ts" and not _finite(row[key])) for key in required) for row in ordered):
        raise ValueError("frozen evaluation contains a missing or non-finite field")

    actuals = [float(row["actual"]) for row in ordered]
    model = [float(row["model_pred"]) for row in ordered]
    naive = [float(row["naive_pred"]) for row in ordered]
    persistence = list(naive)
    reference = []
    prior_actuals = []
    for row in ordered:
        reference.append(sum(prior_actuals) / len(prior_actuals) if prior_actuals else float(row["naive_pred"]))
        prior_actuals.append(float(row["actual"]))

    metrics = {
        "model": _point_metrics(model, actuals),
        "naive": _point_metrics(naive, actuals),
        "persistence": _point_metrics(persistence, actuals),
        "expanding-mean-reference": _point_metrics(reference, actuals),
    }
    differences = [
        abs(prediction - actual) - abs(baseline - actual)
        for prediction, baseline, actual in zip(model, naive, actuals)
    ]
    bootstrap = _paired_bootstrap(
        differences,
        manifest["scoring"]["bootstrapSeed"],
        manifest["scoring"]["bootstrapResamples"],
    )
    coverages = {}
    for level in (0.5, 0.8, 0.95):
        covered = 0
        for record in records:
            interval = next(item for item in record["distribution"]["intervals"] if item["level"] == level)
            outcome = record["resolutionCriteria"]["outcome"]
            covered += interval["lower"] <= outcome <= interval["upper"]
        coverages[str(int(level * 100))] = covered / len(records)

    model_mae = metrics["model"]["mae"]
    naive_mae = metrics["naive"]["mae"]
    return {
        "schemaVersion": "mti-governed-evaluation/v1",
        "benchmarkId": manifest["id"],
        "benchmarkManifestHash": manifest_hash or sha256_bytes(pretty_json_bytes(manifest)),
        "codeVersion": manifest["codeVersion"],
        "sampleCount": len(ordered),
        "period": {"start": ordered[0]["ts"], "end": ordered[-1]["ts"]},
        "horizon": manifest["preregistration"]["horizon"],
        "domain": manifest["preregistration"]["domain"],
        "baselines": manifest["baselines"],
        "metrics": metrics,
        "comparisons": {
            "modelVsNaive": {
                "maeDifference": model_mae - naive_mae,
                "relativeMaePercent": (model_mae / naive_mae - 1) * 100,
                "direction": "higher-error-than-naive",
                "pairedBootstrap95": bootstrap,
            }
        },
        "calibration": {
            "method": "Rolling absolute-residual coverage envelopes using only previously resolved errors.",
            "sampleCount": len(records),
            "nominalCoverage": {"50": 0.5, "80": 0.8, "95": 0.95},
            "empiricalCoverage": coverages,
            "historicalIssuanceNote": (
                "These intervals are migration diagnostics and were not part of the "
                "historically issued point forecasts."
            ),
        },
        "rollingOrigin": {
            "orderedBy": "ts",
            "futureInputsUsed": False,
            "referenceBaselineWarmStart": "First expanding-mean prediction uses the recorded naive point.",
        },
        "segmentResults": [
            {
                "segment": "full frozen period",
                "sampleCount": len(ordered),
                "modelMae": model_mae,
                "naiveMae": naive_mae,
            }
        ],
        "exclusions": manifest["preregistration"]["exclusions"],
        "missingDataHandling": manifest["preregistration"]["missingDataHandling"],
        "limitations": [
            "The frozen period is short and operational rather than a randomized sample.",
            "Three legacy rows are not eligible for governed record migration because their points do not match the immediately preceding retained history row.",
            "The model MAE is higher than the naive MAE in this frozen sample; no performance claim is supported.",
            "Migration intervals test calibration mechanics but were not issued with the historical point forecasts.",
        ],
        "sourceResolutionRule": manifest["preregistration"]["resolutionRule"],
    }


def reconstruct_forecast(forecast_id, root=ROOT):
    root = Path(root)
    records = load_jsonl(root / "forecasting" / "records.jsonl")
    matches = [record for record in records if record["id"] == forecast_id]
    if len(matches) != 1:
        raise ValueError(f"forecast ID did not resolve uniquely: {forecast_id}")
    record = matches[0]
    validate_forecast_record(record)

    evaluation_run_id = record["resolutionCriteria"]["source"].rsplit("/", 1)[-1]
    evaluations = load_jsonl(root / "data" / "forecast_eval.jsonl")
    evaluation = next((row for row in evaluations if row["run_id"] == evaluation_run_id), None)
    if evaluation is None:
        raise ValueError(f"resolution row missing for {forecast_id}")
    history = load_jsonl(root / "data" / "history.jsonl")
    history_rows, history_index = _history_context(history)
    current_index = history_index[evaluation_run_id]
    issue_row = history_rows[current_index - 1]
    snapshot_hash = sha256_bytes(canonical_json_bytes(history_rows[:current_index]))
    manifest_hash = sha256_bytes((root / "forecasting" / "benchmark-manifest.json").read_bytes())
    verified = all(
        [
            issue_row["ts"] == record["dataCutoff"],
            float(issue_row["forecast_next"]) == record["distribution"]["point"],
            float(issue_row["index"]) == float(evaluation["naive_pred"]),
            float(evaluation["actual"]) == record["resolutionCriteria"]["outcome"],
            float(evaluation["err_model"]) == record["resolutionCriteria"]["score"],
            snapshot_hash == record["provenance"]["dataSnapshotHash"],
            manifest_hash == record["provenance"]["benchmarkManifestHash"],
        ]
    )
    return {
        "forecastId": forecast_id,
        "inputs": {
            "historyRunId": issue_row["run_id"],
            "dataCutoff": issue_row["ts"],
            "dataSnapshotHash": snapshot_hash,
            "recordedNaivePoint": float(evaluation["naive_pred"]),
        },
        "point": record["distribution"]["point"],
        "method": record["method"],
        "outcome": record["resolutionCriteria"]["outcome"],
        "score": record["resolutionCriteria"]["score"],
        "verified": verified,
    }


def _assert_source_snapshot(root, manifest):
    for source in manifest["sourceSnapshot"].values():
        actual = sha256_bytes((root / source["path"]).read_bytes())
        if actual != source["sha256"]:
            raise ValueError(
                f"source snapshot changed after manifest freeze: {source['path']}"
            )


def write_artifacts(root=ROOT):
    root = Path(root)
    manifest_path = root / "forecasting" / "benchmark-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _assert_source_snapshot(root, manifest)
    manifest_hash = sha256_bytes(manifest_path.read_bytes())
    history = load_jsonl(root / "data" / "history.jsonl")
    evaluations = load_jsonl(root / "data" / "forecast_eval.jsonl")
    records, migration_exclusions = build_forecast_records(
        history,
        evaluations,
        manifest_hash,
        manifest["codeVersion"],
    )
    ledger_path = root / "forecasting" / "records.jsonl"
    write_immutable_ledger(ledger_path, records)

    result = evaluate(evaluations, records, manifest, manifest_hash)
    result["migration"] = {
        "eligibleForecastRecords": len(records),
        "excludedLegacyRows": migration_exclusions,
    }
    evaluation_path = root / "forecasting" / "evaluation-results.json"
    evaluation_path.write_bytes(pretty_json_bytes(result))

    audit = {
        "auditProtocol": (
            "Reviewer receives only forecastId and reconstructs inputs, method/version, "
            "outcome, and score from committed artifacts."
        ),
        "forecastId": records[-1]["id"],
    }
    audit["reconstruction"] = reconstruct_forecast(audit["forecastId"], root)
    blind_audit_path = root / "forecasting" / "blind-audit.json"
    blind_audit_path.write_bytes(pretty_json_bytes(audit))

    lock_path = root / "forecasting" / "governance-schema-lock.json"
    provenance = {
        "schemaVersion": "mti-forecast-provenance/v1",
        "governanceCommit": manifest["governanceCommit"],
        "sourceBaseCommit": manifest["sourceBaseCommit"],
        "benchmarkManifestHash": manifest_hash,
        "forecastLedgerHash": sha256_bytes(ledger_path.read_bytes()),
        "evaluationResultsHash": sha256_bytes(evaluation_path.read_bytes()),
        "blindAuditHash": sha256_bytes(blind_audit_path.read_bytes()),
        "schemaLockHash": sha256_bytes(lock_path.read_bytes()),
        "sourceSnapshots": manifest["sourceSnapshot"],
        "recordCount": len(records),
        "legacyEvaluationCount": len(evaluations),
        "migrationExclusionCount": len(migration_exclusions),
    }
    provenance_path = root / "forecasting" / "provenance-manifest.json"
    provenance_path.write_bytes(pretty_json_bytes(provenance))
    return provenance


def check_artifacts(root=ROOT):
    root = Path(root)
    outputs = (
        "forecasting/records.jsonl",
        "forecasting/evaluation-results.json",
        "forecasting/blind-audit.json",
        "forecasting/provenance-manifest.json",
    )
    before = {path: (root / path).read_bytes() for path in outputs}
    inputs = (
        "data/history.jsonl",
        "data/forecast_eval.jsonl",
        "forecasting/benchmark-manifest.json",
        "forecasting/governance-schema-lock.json",
        "forecasting/records.jsonl",
    )
    with tempfile.TemporaryDirectory(prefix="mti-forecast-check-") as temporary:
        check_root = Path(temporary)
        for relative in inputs:
            destination = check_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / relative, destination)
        write_artifacts(check_root)
        for path, expected in before.items():
            if (check_root / path).read_bytes() != expected:
                raise ValueError(f"artifact is not deterministically reproducible: {path}")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true", help="write frozen pilot artifacts")
    action.add_argument("--check", action="store_true", help="verify byte-identical reproduction")
    args = parser.parse_args(argv)
    if args.write:
        provenance = write_artifacts()
        print(
            f"wrote {provenance['recordCount']} governed forecasts from "
            f"{provenance['legacyEvaluationCount']} evaluations; "
            f"{provenance['migrationExclusionCount']} legacy rows remained evaluation-only"
        )
    else:
        check_artifacts()
        print("forecast governance artifacts reproduce byte-identically")


if __name__ == "__main__":
    main()
