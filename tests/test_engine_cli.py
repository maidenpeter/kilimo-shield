import json

from agroshield_pricing.cli import main
from agroshield_pricing.engine import price_ward
from agroshield_pricing.rainfall import SyntheticRainfallSource


def test_engine_prices_each_season_separately(cfg):
    r = price_ward(cfg, "ward-a", SyntheticRainfallSource(seed=5))
    assert set(r.seasons) == {"LR", "SR"}
    lr, sr = r.summary["seasons"]["LR"], r.summary["seasons"]["SR"]
    assert lr["terms"] != sr["terms"]  # resolved from each season's own history
    for s in (lr, sr):
        assert 0 <= s["burn_cost"]["expected_loss"] <= 1
        assert s["premium"]["gross_rate"] > s["burn_cost"]["expected_loss"]


def test_every_input_carries_a_provenance_label(cfg):
    r = price_ward(cfg, "ward-a", SyntheticRainfallSource(seed=5))
    labels = {p["input"]: p["label"] for p in r.summary["provenance"]}
    assert labels["Rainfall"] == "SYNTHETIC"
    assert labels["Yields"] == "SYNTHETIC"
    assert labels["Ward location"] == "ILLUSTRATIVE"


def test_same_inputs_give_identical_results(cfg):
    a = price_ward(cfg, "ward-b", SyntheticRainfallSource(seed=9)).summary
    b = price_ward(cfg, "ward-b", SyntheticRainfallSource(seed=9)).summary
    assert json.dumps(a, default=str) == json.dumps(b, default=str)


def test_cli_run_writes_report_manifest_and_audit_log(cfg, tmp_path):
    rc = main(["--config", str(cfg.root), "run", "--ward", "ward-a", "--source", "synthetic", "--out", str(tmp_path)])
    assert rc == 0
    run_dir = next(p for p in tmp_path.iterdir() if p.is_dir())
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "SYNTHETIC" in html and "ILLUSTRATIVE" in html and "Not a filed product" in html
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["index_version"] == cfg.product.layer_b.version
    assert manifest["config_sha256"] == cfg.file_hashes
    log = (tmp_path / "audit_log.jsonl").read_text().strip().splitlines()
    assert json.loads(log[-1])["run_id"] == manifest["run_id"]
    # Hashed outputs must be byte-identical on every OS: LF only.
    for name in ("results.json", "manifest.json", "report.html"):
        assert b"\r\n" not in (run_dir / name).read_bytes(), name
    assert b"\r\n" not in (tmp_path / "audit_log.jsonl").read_bytes()
