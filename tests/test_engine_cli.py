import json

import pytest

from agroshield_pricing.cli import main
from agroshield_pricing.engine import price_ward
from agroshield_pricing.pet import SyntheticPetSource, make_pet_source
from agroshield_pricing.rainfall import SyntheticRainfallSource, make_source


def _synthetic(cfg, ward="ward-a", seed=5):
    return price_ward(cfg, ward, SyntheticRainfallSource(seed=seed), SyntheticPetSource())


def test_engine_prices_long_rains_with_v0_alongside(cfg):
    r = _synthetic(cfg)
    assert set(r.seasons) == {"LR"}
    s = r.summary["seasons"]["LR"]
    assert s["terms"]["version"] == cfg.product.layer_b.version
    assert s["v0"]["version"] == cfg.product.layer_b_v0.version
    assert 0 <= s["burn_cost"]["expected_loss"] <= 1
    assert s["premium"]["gross_rate"] > s["burn_cost"]["expected_loss"]
    assert len(s["worst_seasons"]) == 10
    assert [w["rank"] for w in s["worst_seasons"]] == list(range(1, 11))


def test_trigger_sensitivity_is_monotone(cfg):
    rows = _synthetic(cfg).summary["seasons"]["LR"]["trigger_sensitivity"]
    freqs = [r["payout_frequency"] for r in rows]
    assert freqs == sorted(freqs)                         # higher trigger never pays less often
    assert sum(r["is_current"] for r in rows) == 1


def test_every_input_carries_a_provenance_label(cfg):
    r = _synthetic(cfg)
    labels = {p["input"]: p["label"] for p in r.summary["provenance"]}
    assert labels["Rainfall"] == "SYNTHETIC" and labels["PET"] == "SYNTHETIC"
    assert labels["Ward location"] == "ILLUSTRATIVE"
    # Soil is REAL since Phase 7 (SoilGrids 2.0), and its note names the source.
    soil_row = next(p for p in r.summary["provenance"] if p["input"] == "Soil water holding capacity")
    assert soil_row["label"] == "REAL" and "SoilGrids" in soil_row["note"]
    assert labels["Yields (basis risk)"] == "PENDING"
    assert r.summary["seasons"]["LR"]["basis_risk"]["available"] is False


def test_same_inputs_give_identical_results(cfg):
    a = _synthetic(cfg, "ward-b", 9).summary
    b = _synthetic(cfg, "ward-b", 9).summary
    assert json.dumps(a, default=str) == json.dumps(b, default=str)


def test_cli_run_writes_report_manifest_and_audit_log(cfg, tmp_path):
    rc = main(["--config", str(cfg.root), "run", "--ward", "ward-a", "--source", "synthetic", "--out", str(tmp_path)])
    assert rc == 0
    run_dir = next(p for p in tmp_path.iterdir() if p.is_dir())
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "SYNTHETIC" in html and "ILLUSTRATIVE" in html and "Not a filed product" in html
    assert "v0 per-phase" in html and "NOT MEASURABLE YET" in html
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["index_version"] == cfg.product.layer_b.version
    assert manifest["pet_source"] == "synthetic"
    assert manifest["config_sha256"] == cfg.file_hashes
    results = json.loads((run_dir / "results.json").read_text())   # strict JSON: no NaN
    assert results["index_version"] == cfg.product.layer_b.version
    log = (tmp_path / "audit_log.jsonl").read_text().strip().splitlines()
    assert json.loads(log[-1])["run_id"] == manifest["run_id"]
    # Hashed outputs must be byte-identical on every OS: LF only.
    for name in ("results.json", "manifest.json", "report.html"):
        assert b"\r\n" not in (run_dir / name).read_bytes(), name
    assert b"\r\n" not in (tmp_path / "audit_log.jsonl").read_bytes()


# ------------------------------------------------------------------ regression on committed real inputs
def test_regression_ward_a_1984_from_committed_inputs(cfg):
    """Pins the 1984 event on the committed CHIRPS and NASA POWER inputs.

    If this moves, the index, its terms or its inputs changed: bump layer_b.version
    and update the expected value deliberately, never to hit a target.
    """
    r = price_ward(cfg, "ward-a", make_source(cfg, allow_download=False), make_pet_source(cfg, allow_download=False))
    e = r.summary["seasons"]["LR"]["event_tests"][0]
    assert e["year"] == 1984 and e["sos"] == "Apr d1 1984"
    # B-1.2.1: 54.96 with SoilGrids soil (130 mm). Was 55.56 at B-1.2.0 with the 100 mm placeholder.
    assert e["wrsi"] == pytest.approx(54.96, abs=0.01)
    assert e["passed"]


def test_product_payout_adds_replanting_and_caps_at_sum_insured():
    import pandas as pd
    from agroshield_pricing.engine import product_kes
    t = pd.DataFrame({"failed_onset_share": [0.0, 0.25, 0.0], "wrsi_share": [0.5, 0.0, 1.0],
                      "replant_kes": [2500.0, 0.0, 2500.0], "flowering_share": [0.3, 0.0, 0.0]},
                     index=[2000, 2001, 2002])
    off = product_kes(t, 10000, with_flowering=False)
    assert off.tolist() == [7500.0, 2500.0, 10000.0]          # 5000 + 2500; failed onset; capped
    on = product_kes(t, 10000, with_flowering=True)
    assert on.loc[2000] == 10000.0                            # 5000 + 3000 + 2500, capped at SI


def test_reported_event_has_no_pass_fail_at_other_wards(cfg):
    r = price_ward(cfg, "ward-b", SyntheticRainfallSource(seed=5), SyntheticPetSource())
    e = r.summary["seasons"]["LR"]["event_tests"][0]
    assert e["required"] is False and e["passed"] is None


def test_frequencies_split_main_replanting_and_combined():
    import pandas as pd
    from agroshield_pricing.engine import frequencies
    t = pd.DataFrame({"wrsi_share": [0.4, 0.0, 0.0, 0.0], "failed_onset": [False, True, False, False],
                      "germination_failed": [False, False, True, False]}, index=[1, 2, 3, 4])
    share = pd.Series([0.4, 0.25, 0.25, 0.0], index=[1, 2, 3, 4])
    assert frequencies(t, share) == {"main": 0.5, "replanting": 0.25, "combined": 0.75}


def test_layer_a_not_offered_at_ward_b_and_flowering_hidden(cfg):
    r = price_ward(cfg, "ward-b", SyntheticRainfallSource(seed=5), SyntheticPetSource())
    s = r.summary["seasons"]["LR"]
    assert s["layer_a"]["available"] is False and s["layer_a"]["offered"] is False
    assert s["flowering"] is None
    assert all("Flowering" not in c["component"] for c in s["components"])
    assert set(s["target"]) == {"main", "replanting", "combined"}
