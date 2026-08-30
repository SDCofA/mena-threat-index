import hashlib
import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PILOT_MODULE = ROOT / "scripts" / "forecast_governance.py"
FORECAST_SCHEMA = ROOT / "forecasting" / "schemas" / "forecast-event.schema.json"
PROVENANCE_SCHEMA = ROOT / "forecasting" / "schemas" / "provenance.schema.json"
SCHEMA_LOCK = ROOT / "forecasting" / "governance-schema-lock.json"
BENCHMARK_MANIFEST = ROOT / "forecasting" / "benchmark-manifest.json"
LEDGER = ROOT / "forecasting" / "records.jsonl"
PROVENANCE_MANIFEST = ROOT / "forecasting" / "provenance-manifest.json"
EVALUATION = ROOT / "forecasting" / "evaluation-results.json"
BLIND_AUDIT = ROOT / "forecasting" / "blind-audit.json"


def load_pilot():
    assert PILOT_MODULE.exists(), "forecast governance pilot module must exist"
    spec = importlib.util.spec_from_file_location("forecast_governance", PILOT_MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalized_sha256(path):
    content = path.read_bytes().replace(b"\r\n", b"\n")
    return "sha256:" + hashlib.sha256(content).hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def source_rows():
    module = load_pilot()
    manifest = json.loads(BENCHMARK_MANIFEST.read_text(encoding="utf-8"))
    return module.load_source_snapshot_rows(ROOT, manifest)


def test_governance_schemas_are_locked_to_approved_commit():
    lock = json.loads(SCHEMA_LOCK.read_text(encoding="utf-8"))
    assert lock["governanceCommit"] == "e26de16"
    assert normalized_sha256(FORECAST_SCHEMA) == (
        "sha256:feec0d8c022dd7422029bf0e6c716af7dc3133fe7e9906e161ade655541e666c"
    )
    assert normalized_sha256(PROVENANCE_SCHEMA) == (
        "sha256:4b2e3e7a742147db20fe79fbc68f5658a929f5ba72504bc8a01c1306e941a492"
    )
    assert lock["schemas"]["forecastEvent"]["sha256"] == normalized_sha256(FORECAST_SCHEMA)
    assert lock["schemas"]["provenance"]["sha256"] == normalized_sha256(PROVENANCE_SCHEMA)


def test_records_preserve_recorded_points_and_are_append_only(tmp_path):
    module = load_pilot()
    history, evaluations = source_rows()
    records, exclusions = module.build_forecast_records(
        history,
        evaluations,
        module.sha256_file(BENCHMARK_MANIFEST),
    )

    assert len(evaluations) == 178
    assert len(records) == 175
    assert len(exclusions) == 3
    by_resolution_id = {row["run_id"]: row for row in evaluations}
    for record in records:
        source = by_resolution_id[record["resolutionCriteria"]["source"].rsplit("/", 1)[-1]]
        assert record["distribution"]["point"] == source["model_pred"]
        assert record["resolutionCriteria"]["outcome"] == source["actual"]
        assert record["resolutionCriteria"]["score"] == source["err_model"]
        module.validate_forecast_record(record)

    ledger = tmp_path / "records.jsonl"
    module.write_immutable_ledger(ledger, records)
    original = ledger.read_bytes()
    module.write_immutable_ledger(ledger, records)
    assert ledger.read_bytes() == original
    changed = json.loads(json.dumps(records))
    changed[0]["distribution"]["point"] += 0.01
    with pytest.raises(module.ImmutableForecastError):
        module.write_immutable_ledger(ledger, changed)


def test_frozen_sources_survive_append_only_operational_updates(tmp_path):
    module = load_pilot()
    history, evaluations = source_rows()

    assert len(history) == 204
    assert len(evaluations) == 178
    assert len(module.load_jsonl(ROOT / "data" / "history.jsonl")) >= len(history)
    assert len(module.load_jsonl(ROOT / "data" / "forecast_eval.jsonl")) >= len(evaluations)

    manifest = json.loads(BENCHMARK_MANIFEST.read_text(encoding="utf-8"))
    linux_copy = tmp_path / "history.jsonl"
    source_lines = (ROOT / "data" / "history.jsonl").read_bytes().replace(b"\r\n", b"\n").splitlines()
    linux_copy.write_bytes(b"\n".join(source_lines) + b"\n")
    recovered = module.load_frozen_jsonl(
        linux_copy,
        manifest["sourceSnapshot"]["history"]["sha256"],
    )
    assert len(recovered) == len(history)


def test_temporal_leakage_is_rejected():
    module = load_pilot()
    history, evaluations = source_rows()
    records, _ = module.build_forecast_records(
        history,
        evaluations,
        module.sha256_file(BENCHMARK_MANIFEST),
    )
    leaked = json.loads(json.dumps(records[0]))
    leaked["provenance"]["featureTimestamps"].append(leaked["horizon"]["endsAt"])
    with pytest.raises(ValueError, match="temporal leakage"):
        module.validate_forecast_record(leaked)


def test_frozen_manifest_drives_rolling_evaluation_and_required_baselines():
    module = load_pilot()
    manifest = json.loads(BENCHMARK_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["status"] == "frozen-before-evaluation"
    history, evaluations = source_rows()
    records, _ = module.build_forecast_records(
        history,
        evaluations,
        module.sha256_file(BENCHMARK_MANIFEST),
    )
    result = module.evaluate(evaluations, records, manifest)

    assert result["sampleCount"] == 178
    assert set(result["baselines"]) == {
        "naive",
        "persistence",
        "expanding-mean-reference",
    }
    assert result["metrics"]["model"]["mae"] == pytest.approx(0.00876404494382023)
    assert result["metrics"]["naive"]["mae"] == pytest.approx(0.00831460674157304)
    assert result["comparisons"]["modelVsNaive"]["relativeMaePercent"] == pytest.approx(
        5.405405405405395
    )
    interval = result["comparisons"]["modelVsNaive"]["pairedBootstrap95"]
    assert interval["lower"] <= interval["upper"]
    assert result["calibration"]["sampleCount"] == 175
    assert set(result["calibration"]["empiricalCoverage"]) == {"50", "80", "95"}
    assert result["rollingOrigin"]["futureInputsUsed"] is False


def test_evaluation_reproduction_is_byte_identical():
    module = load_pilot()
    history, evaluations = source_rows()
    manifest = json.loads(BENCHMARK_MANIFEST.read_text(encoding="utf-8"))
    records, _ = module.build_forecast_records(
        history,
        evaluations,
        module.sha256_file(BENCHMARK_MANIFEST),
    )
    first = module.canonical_json_bytes(module.evaluate(evaluations, records, manifest))
    second = module.canonical_json_bytes(module.evaluate(evaluations, records, manifest))
    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()


def test_reproduction_check_is_read_only_when_artifact_drift_is_detected(tmp_path):
    module = load_pilot()
    paths = (
        "data/history.jsonl",
        "data/forecast_eval.jsonl",
        "forecasting/benchmark-manifest.json",
        "forecasting/governance-schema-lock.json",
        "forecasting/records.jsonl",
        "forecasting/evaluation-results.json",
        "forecasting/blind-audit.json",
        "forecasting/provenance-manifest.json",
    )
    for relative in paths:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    drifted = tmp_path / "forecasting" / "evaluation-results.json"
    drifted.write_bytes(b"{}\n")

    with pytest.raises(ValueError, match="not deterministically reproducible"):
        module.check_artifacts(tmp_path)

    assert drifted.read_bytes() == b"{}\n"


def test_blind_audit_reconstructs_from_forecast_id_only():
    module = load_pilot()
    records = read_jsonl(LEDGER)
    audit_seed = json.loads(BLIND_AUDIT.read_text(encoding="utf-8"))
    reconstruction = module.reconstruct_forecast(
        audit_seed["forecastId"],
        ROOT,
    )
    record = next(record for record in records if record["id"] == audit_seed["forecastId"])

    assert reconstruction["forecastId"] == record["id"]
    assert reconstruction["point"] == record["distribution"]["point"]
    assert reconstruction["method"] == record["method"]
    assert reconstruction["outcome"] == record["resolutionCriteria"]["outcome"]
    assert reconstruction["score"] == record["resolutionCriteria"]["score"]
    assert reconstruction["verified"] is True
    assert reconstruction == audit_seed["reconstruction"]


def test_published_evidence_is_machine_reproducible_and_has_no_marketing_claim():
    module = load_pilot()
    result = json.loads(EVALUATION.read_text(encoding="utf-8"))
    provenance = json.loads(PROVENANCE_MANIFEST.read_text(encoding="utf-8"))
    assert module.sha256_file(LEDGER) == provenance["forecastLedgerHash"]
    assert module.sha256_file(EVALUATION) == provenance["evaluationResultsHash"]
    assert result["comparisons"]["modelVsNaive"]["relativeMaePercent"] == pytest.approx(
        5.405405405405395
    )

    published = "\n".join(
        [
            (ROOT / "README.md").read_text(encoding="utf-8"),
            (ROOT / "index.html").read_text(encoding="utf-8"),
            (ROOT / "docs" / "forecasting" / "model-card.md").read_text(encoding="utf-8"),
            (ROOT / "docs" / "forecasting" / "evaluation-report.md").read_text(
                encoding="utf-8"
            ),
        ]
    )
    assert "5.4% higher MAE than the naïve baseline" in published
    assert not re.search(
        r"\b(outperform(?:s|ed|ing)?|superior|best|most accurate|beats?|better than|"
        r"state[- ]of[- ]the[- ]art|leading)\b",
        published,
        re.I,
    )
    assert "docs/forecasting/evaluation-report.md" in published
