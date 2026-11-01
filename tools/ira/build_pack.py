"""IRA documentation pack: DRAFT and ILLUSTRATIVE. One PDF plus its HTML source, the figures as CSV and JSON, and a
manifest with the SHA-256 of every file.

    .venv/Scripts/python tools/ira/build_pack.py              # -> docs/ira/
    .venv/Scripts/python tools/ira/build_pack.py --out some/folder
    .venv/Scripts/python tools/ira/build_pack.py --no-pdf     # HTML, CSV and JSON only

IRA is the Insurance Regulatory Authority of Kenya. This pack has not been submitted to it, carries no IRA logo and
implies no review or approval. The insurer is "Partner insurer (to be named)".

Where every number comes from (nothing is typed in by hand):
  * the pricing engine, run by this command: `agroshield-price run --all --offline --out var/ira-engine-run`
    (results.json and manifest.json per ward; the run's id, command and SHA-256 are recorded in the pack);
  * config/*.yaml (product terms, loadings, consent wording, monitoring and weather rules);
  * data/raw/*/*.meta.json (retrieval dates and checksums of every committed input);
  * docs/remaining/season-2008/season.json, if present (the simulated season: tools/sim/season.py).

The PDF is printed by Chromium through Playwright (the bundled browser, or the installed Chrome or Edge). Every page
carries "DRAFT" and "ILLUSTRATIVE" in its header and footer.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))          # this checkout's code, even if another copy is installed

import yaml  # noqa: E402
from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402

MARK = "DRAFT / ILLUSTRATIVE"
CSV_HEAD = ("# DRAFT / ILLUSTRATIVE. AgroShield IRA documentation pack. Not submitted to or approved by the Insurance "
            "Regulatory Authority. Source: {source}")
PDF_NAME = "AgroShield-IRA-pack-DRAFT-ILLUSTRATIVE.pdf"
ENGINE_OUT = "var/ira-engine-run"
ENGINE_CMD = ["run", "--all", "--offline", "--out", ENGINE_OUT]
INSURER = "Partner insurer (to be named)"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ------------------------------------------------------------------ inputs
def run_engine(repo: Path = REPO) -> dict:
    """Price every pilot ward with the engine's own CLI (offline) and return its outputs per ward."""
    from agroshield_pricing import cli
    out = repo / ENGINE_OUT
    if out.exists():                        # git-ignored scratch for this pack only; keep just the latest run
        shutil.rmtree(out)
    cwd, argv = Path.cwd(), sys.argv
    try:
        os.chdir(repo)                      # so the run records a repo-relative command and output folder
        sys.argv = ["agroshield-price", *ENGINE_CMD]
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            if cli.main(ENGINE_CMD) != 0:
                raise SystemExit("the pricing engine run failed")
    finally:
        os.chdir(cwd)
        sys.argv = argv
    runs = {}
    for m in sorted(out.glob("*/manifest.json")):
        man = json.loads(m.read_text(encoding="utf-8"))
        res_path = m.parent / "results.json"
        if sha256(res_path) != man["results_sha256"]:
            raise SystemExit(f"results.json of run {man['run_id']} does not match its manifest")
        runs[man["ward_id"]] = {"manifest": man, "results": json.loads(res_path.read_text(encoding="utf-8")),
                                "results_sha256": man["results_sha256"], "stdout": log.getvalue()}
    return runs


def data_sources(repo: Path = REPO) -> list[dict]:
    """Every committed input with its metadata: what it is, where from, when retrieved, and whether it still matches."""
    rows = []
    for meta in sorted((repo / "data" / "raw").glob("*/*.meta.json")):
        d = json.loads(meta.read_text(encoding="utf-8"))
        name = meta.name[: -len(".meta.json")]
        data = meta.parent / (name if "." in name else name + ".csv")
        folder = meta.parent.name
        rows.append({
            "file": data.relative_to(repo).as_posix(),
            "folder": folder,
            "use": {"chirps": "pricing and monitoring (rainfall)", "nasapower": "pricing and monitoring (PET)",
                    "ndvi": "research only (livestock feasibility)"}.get(folder, "research only (forecast skill)"),
            "dataset": d.get("dataset") or d.get("product") or d.get("label") or name,
            "provider": d.get("provider") or (d.get("url", "").split("/")[2] if d.get("url") else ""),
            "retrieved_at": d.get("retrieved_at", ""),
            "sha256_recorded": d.get("sha256", ""),
            "sha256_now": sha256(data) if data.exists() else "",
            "status": ("matches" if data.exists() and sha256(data) == d.get("sha256") else
                       "not committed (re-fetchable)" if not data.exists() else "DIFFERS"),
        })
    return rows


def config_view(repo: Path = REPO) -> dict:
    from agroshield_pricing.config import load_config
    from agroshield_platform.services import load_consent_wording
    cfg = load_config(repo / "config")
    product = yaml.safe_load((repo / "config" / "product.yaml").read_text(encoding="utf-8"))
    weather = yaml.safe_load((repo / "config" / "weather.yaml").read_text(encoding="utf-8"))
    consent = load_consent_wording(cfg)
    wards = []
    for wid in cfg.pilot.wards:
        w, cal = cfg.ward(wid), cfg.calendar(wid, "LR")
        wards.append({"id": wid, "display_name": w.label, "name": w.name, "illustrative": w.illustrative,
                      "lat": w.centroid.lat, "lon": w.centroid.lon, "elevation_m": w.elevation_m,
                      "soil_whc_mm": w.soil_whc_mm, "box_deg": w.extraction_box_deg,
                      "sales_window": cal.sales_window.model_dump() if cal.sales_window else None,
                      "planting_window": cal.planting_window.model_dump(), "lgp_days": cal.lgp_days,
                      "variety": cal.variety})
    return {
        "file_sha256": dict(cfg.file_hashes),
        "wards": wards,
        "layer_b": product["layer_b"], "premium": product["premium"], "sum_insured": product["sum_insured"],
        "subsidy": product["subsidy"], "resilience": product["resilience"], "target": product["target"],
        "layer_a": {"enabled": product["layer_a"]["enabled"], "reason": product["layer_a"].get("disabled_reason")},
        "monitoring": cfg.monitoring.model_dump(),
        "history": cfg.rainfall.history.model_dump(),
        "pet": {"source": cfg.pet.source, "fewsnet_status": cfg.pet.fewsnet_status,
                "lapse_rate_c_per_km": cfg.pet.lapse_rate_c_per_km},
        "validation": {"fewsnet_status": cfg.validation.fewsnet_status},
        "consent": {"version": consent["version"], "reviewed": consent["reviewed"],
                    "status": (consent.get("review") or {}).get("status"),
                    "purposes": [{"id": k, "required": v.get("required", False), "en": v["en"], "sw": v["sw"],
                                  "sha256": v["sha256"]} for k, v in consent["purposes"].items()]},
        # The user_agent line is left out: it carries a contact address.
        "weather": [{k: s.get(k) for k in ("name", "enabled", "display_allowed", "sms_distribution_allowed",
                                           "terms_checked_on", "note")} for s in weather["sources"]],
    }


def season_view(repo: Path = REPO) -> dict | None:
    p = repo / "docs" / "remaining" / "season-2008" / "season.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    S = d["steps"]
    return {"file": p.relative_to(repo).as_posix(), "sha256": sha256(p), "year": d["year"], "ward": d["ward"]["display_name"],
            "confirmed_on": S["trigger"]["date"], "final_wrsi": S["trigger"].get("final_wrsi"),
            "share": S["trigger"].get("share"), "approved_on": S["approval"]["date"], "paid_on": S["payout"]["date"],
            "due_by": S["payout"]["events"][0]["due_by"], "max_days": d["checks"]["max_days_to_pay"],
            "payouts": d["checks"]["payouts"], "window": d["payout_within_days"], "generated_at": d["generated_at"]}


def figures(runs: dict) -> dict:
    """The numbers the pack prints, per ward, straight from the engine's results.json."""
    out = {}
    for wid, r in sorted(runs.items()):
        res, man = r["results"], r["manifest"]
        L = res["seasons"]["LR"]
        out[wid] = {
            "ward": res["ward"], "index_version": res["index_version"],
            "run": {"run_id": man["run_id"], "created_at": man["created_at"], "command": man["command"],
                    "git": man.get("git"), "results_sha256": r["results_sha256"],
                    "config_sha256": man.get("config_sha256")},
            "rainfall": res["rainfall_provenance"], "pet": res["pet_provenance"],
            "rainfall_annual_mean_mm": res["rainfall_annual_mean_mm"], "pet_annual_mean_mm": res["pet_annual_mean_mm"],
            "provenance": res["provenance"],
            "terms": L["terms"], "calendar": L["calendar"], "burn_cost": L["burn_cost"], "premium": L["premium"],
            "target": L["target"], "onset_stats": L["onset_stats"], "wrsi_stats": L["wrsi_stats"],
            "components": L["components"], "early_season_triggers": L["early_season_triggers"],
            "event_tests": L["event_tests"], "worst_seasons": L["worst_seasons"],
            "trigger_sensitivity": L["trigger_sensitivity"], "whc_sensitivity": L["whc_sensitivity"],
            "v0": {k: L["v0"][k] for k in ("version", "payout_frequency", "expected_loss", "loss_1_in_10", "gross_rate")},
            "comparison": L["comparison"], "fewsnet_validation": L["fewsnet_validation"],
            "basis_risk": L["basis_risk"], "layer_a": {k: L["layer_a"].get(k) for k in ("available", "dropped", "reason")},
            "combined_gross_per_acre": L["combined_gross_per_acre"], "history": L["history"],
        }
    return out


# ------------------------------------------------------------------ outputs
def _csv(path: Path, source: str, header: list[str], rows: list[list]) -> None:
    buf = io.StringIO()
    buf.write(CSV_HEAD.format(source=source) + "\n")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8", newline="\n")


def _json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def write_data(out: Path, figs: dict, runs: dict, sources: list[dict], conf: dict, season: dict | None,
               generated_at: str) -> None:
    d = out / "data"
    d.mkdir(parents=True, exist_ok=True)
    for wid, f in figs.items():
        src = f"pricing engine run {f['run']['run_id']} (results.json SHA-256 {f['run']['results_sha256']})"
        si = f["premium"]["default_sum_insured_kes_per_acre"]
        _csv(d / f"backtest_{wid}.csv", src,
             ["year", "start_of_season", "start_rule", "planting_window_rain_mm", "failed_onset", "germination_dry_spell",
              "wrsi", "season_rain_mm", "water_requirement_mm", "payout_share_of_sum_insured",
              f"payout_kes_per_acre_at_{si:.0f}", "v0_payout_share"],
             [[h["year"], h["sos"], h["sos_rule"], h["window_rain_mm"], h["failed_onset"], h["germination_failed"],
               h["wrsi"], h["season_rain_mm"], h["water_requirement_mm"], h["payout"], h["payout_kes"], h["v0_payout"]]
              for h in f["history"]])
        _csv(d / f"trigger_sensitivity_{wid}.csv", src,
             ["trigger_wrsi", "is_current", "main_payout_frequency", "any_payout_frequency", "expected_loss_share",
              "loss_1_in_10_share", "gross_rate", "in_target_band"],
             [[t["trigger_wrsi"], t["is_current"], t["main_frequency"], t["payout_frequency"], t["expected_loss"],
               t["loss_1_in_10"], t["gross_rate"], t["in_target_band"]] for t in f["trigger_sensitivity"]])
        _csv(d / f"soil_sensitivity_{wid}.csv", src,
             ["soil_water_capacity_mm", "is_current", "median_wrsi", "payout_frequency", "expected_loss_share", "gross_rate"],
             [[t["whc_mm"], t["is_current"], t["median_wrsi"], t["payout_frequency"], t["expected_loss"], t["gross_rate"]]
              for t in f["whc_sensitivity"]])
        wrapped = {"marking": MARK, "note": "The pricing engine's own output, unchanged, wrapped with its run manifest.",
                   "results_sha256": runs[wid]["results_sha256"], "manifest": runs[wid]["manifest"],
                   "results": runs[wid]["results"]}
        _json(d / f"engine_{wid}.json", wrapped)
    rows = []
    for wid, f in figs.items():
        b, p = f["burn_cost"], f["premium"]
        for o in p["per_acre"]:
            rows.append([wid, f["ward"]["display_name"], f["index_version"], f["run"]["run_id"], b["seasons"],
                         b["first_year"], b["last_year"], b["payout_seasons"], b["payout_frequency"], b["expected_loss"],
                         b["std_dev"], b["loss_1_in_10"], b["loss_1_in_20"], b["max_loss"], p["risk_margin_rate"],
                         p["pure_premium_rate"], p["gross_rate"], p["loss_ratio_at_gross"], o["sum_insured_kes_per_acre"],
                         o["expected_loss_kes"], o["risk_margin_kes"], sum(o["loadings_kes"].values()),
                         o["gross_premium_kes"]])
    _csv(d / "pricing_summary.csv", "pricing engine runs " + ", ".join(f["run"]["run_id"] for f in figs.values()),
         ["ward_id", "ward", "index_version", "run_id", "seasons", "first_year", "last_year", "payout_seasons",
          "payout_frequency", "expected_loss_share", "std_dev_share", "loss_1_in_10_share", "loss_1_in_20_share",
          "max_loss_share", "risk_margin_rate", "pure_premium_rate", "gross_rate", "loss_ratio_at_gross",
          "sum_insured_kes_per_acre", "expected_loss_kes_per_acre", "risk_margin_kes_per_acre", "loadings_kes_per_acre",
          "gross_premium_kes_per_acre"], rows)
    _csv(d / "data_sources.csv", "data/raw/*/*.meta.json, checksums recomputed at build time",
         ["file", "use", "dataset", "provider", "retrieved_at", "sha256_recorded", "sha256_now", "status"],
         [[r["file"], r["use"], r["dataset"], r["provider"], r["retrieved_at"], r["sha256_recorded"], r["sha256_now"],
           r["status"]] for r in sources])
    _json(d / "figures.json", {"marking": MARK, "generated_at": generated_at, "insurer": INSURER,
                               "sources": {"engine_runs": {w: f["run"] for w, f in figs.items()},
                                           "config_sha256": conf["file_sha256"],
                                           "season_simulation": season and {k: season[k] for k in ("file", "sha256")}},
                               "wards": {w: {k: v for k, v in f.items() if k != "history"} for w, f in figs.items()},
                               "config": conf, "data_sources": sources, "season_simulation": season})


def render(out: Path, ctx: dict) -> list[Path]:
    from agroshield_platform.docstyle import css
    env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=select_autoescape(["html"]))
    env.filters["pct"] = lambda v, n=0: "" if v is None else f"{v * 100:.{n}f}%"
    env.filters["kes"] = lambda v: "" if v is None else "KES " + (f"{v:,.2f}" if round(v % 1, 2) else f"{v:,.0f}")
    env.filters["num"] = lambda v, n=1: "" if v is None else f"{v:,.{n}f}"
    env.filters["short"] = lambda v, n=12: (v or "")[:n]
    written = []
    for name in ("pack.html", "disclosure.html"):
        p = out / name
        p.write_text(env.get_template(name).render(css=css(), **ctx), encoding="utf-8", newline="\n")
        written.append(p)
    return written


HEADER = ('<div style="width:100%;font-size:8px;color:#8A5600;text-align:center;font-family:Arial,sans-serif;">'
          'DRAFT &middot; ILLUSTRATIVE &middot; not submitted to or approved by the Insurance Regulatory Authority</div>')
FOOTER = ('<div style="width:100%;font-size:8px;color:#5E574B;font-family:Arial,sans-serif;padding:0 14mm;'
          'display:flex;justify-content:space-between;"><span>AgroShield IRA documentation pack &middot; DRAFT &middot; '
          'ILLUSTRATIVE</span><span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>')


def make_pdf(html: Path, pdf: Path) -> str:
    """Print the pack with Chromium. Returns which browser printed it."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, used = None, None
        for channel in (None, "chrome", "msedge"):
            try:
                browser = p.chromium.launch(channel=channel) if channel else p.chromium.launch()
                used = channel or "chromium"
                break
            except Exception:
                continue
        if browser is None:
            raise RuntimeError("no Chromium found: run `playwright install chromium`, or install Chrome or Edge")
        page = browser.new_page()
        page.emulate_media(media="print", color_scheme="light")
        page.goto(html.resolve().as_uri())
        page.wait_for_load_state("load")
        page.pdf(path=str(pdf), format="A4", print_background=True, display_header_footer=True,
                 header_template=HEADER, footer_template=FOOTER,
                 margin={"top": "18mm", "bottom": "18mm", "left": "14mm", "right": "14mm"})
        browser.close()
    return used


def write_manifest(out: Path, generated_at: str, extra: dict) -> dict:
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "manifest.json")
    man = {"marking": MARK, "title": "AgroShield parametric maize cover: IRA documentation pack",
           "status": "DRAFT. ILLUSTRATIVE. Not submitted to, reviewed or approved by the Insurance Regulatory Authority.",
           "insurer": INSURER, "generated_at": generated_at,
           "rebuild": "python tools/ira/build_pack.py", **extra,
           "files": [{"path": p.relative_to(out).as_posix(), "bytes": p.stat().st_size, "sha256": sha256(p)} for p in files]}
    _json(out / "manifest.json", man)
    return man


def build(out: Path = REPO / "docs" / "ira", pdf: bool = True, runs: dict | None = None) -> dict:
    out = Path(out)
    runs = runs or run_engine()             # first, so the run records a clean tree when the pack is committed
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    figs, sources, conf, season = figures(runs), data_sources(), config_view(), season_view()
    write_data(out, figs, runs, sources, conf, season, generated_at)
    ctx = {"mark": MARK, "insurer": INSURER, "generated_at": generated_at, "figs": figs, "sources": sources,
           "conf": conf, "season": season, "pdf_name": PDF_NAME, "engine_cmd": "agroshield-price " + " ".join(ENGINE_CMD),
           "git": next(iter(figs.values()))["run"]["git"]}
    html = render(out, ctx)
    printer = make_pdf(html[0], out / PDF_NAME) if pdf else None
    return write_manifest(out, generated_at, {"pdf_printed_by": printer,
                                              "engine_runs": {w: f["run"]["run_id"] for w, f in figs.items()}})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="build_pack", description="IRA documentation pack (DRAFT, ILLUSTRATIVE)")
    ap.add_argument("--out", default=str(REPO / "docs" / "ira"))
    ap.add_argument("--no-pdf", action="store_true", help="skip the PDF (HTML, CSV and JSON only)")
    a = ap.parse_args(argv)
    man = build(Path(a.out), pdf=not a.no_pdf)
    print(f"IRA pack ({MARK}): {len(man['files'])} files in {a.out}")
    for f in man["files"]:
        print(f"  {f['sha256'][:16]}  {f['bytes']:>9,}  {f['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
