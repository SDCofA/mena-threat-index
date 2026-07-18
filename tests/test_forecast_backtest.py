import copy
import hashlib
import json

from scripts import forecast_backtest


def test_evaluation_report_adds_task3_fields_without_changing_scores(tmp_path):
    series = [("composite", [1.0, 1.2, 1.1, 1.4, 1.3, 1.5])]
    rows, evaluations = forecast_backtest.backtest(series)
    original_rows = copy.deepcopy(rows)
    manifest = tmp_path / "benchmark-manifest.json"
    manifest.write_text(
        json.dumps({"id": "mti-test", "status": "template-not-evaluated"}),
        encoding="utf-8",
    )

    report = forecast_backtest.build_evaluation_report(
        series,
        rows,
        evaluations,
        period={"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T10:00:00Z"},
        code_commit="abc123",
        manifest_path=str(manifest),
    )

    assert rows == original_rows
    evaluation = report["evaluation"]
    for field in (
        "sampleCount",
        "period",
        "horizon",
        "domain",
        "exclusions",
        "missingDataHandling",
        "segmentResults",
        "limitations",
        "sourceResolutionRule",
        "codeCommit",
        "manifestHash",
    ):
        assert field in evaluation
    assert evaluation["sampleCount"] == evaluations
    assert report["provenance"]["dataSnapshotHash"].startswith("sha256:")
    expected_manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert report["provenance"]["benchmarkManifestHash"] == f"sha256:{expected_manifest_hash}"
    assert report["claimGate"]["comparativeClaimEligible"] is False
