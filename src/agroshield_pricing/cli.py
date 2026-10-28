"""Command line: `agroshield-price run --ward ward-a` prices a ward and writes its report.

Subcommands
  run              price one ward (or all pilot wards) -> runs/<run_id>/
  fetch-rainfall   download and cache CHIRPS for one or all pilot wards
  fetch-climate    download and cache NASA POWER temperature (for Hargreaves PET)
  validate         load and validate config/ without pricing anything
"""
from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from .audit import append_audit_log, base_manifest, new_run_id, sha256_file
from .config import load_config
from .engine import price_ward
from .pet import make_pet_source
from .rainfall import make_source
from .report import render_html, write_json


def _repo_root(config_dir: Path) -> Path:
    return config_dir.resolve().parent


def cmd_run(args) -> int:
    cfg = load_config(args.config)
    repo = _repo_root(Path(args.config))
    runs_dir = Path(args.out) if args.out else repo / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    # --source synthetic switches both inputs, so a fully synthetic run is one flag.
    rain_name = args.source or cfg.rainfall.source
    pet_name = args.pet or ("synthetic" if args.source == "synthetic" else cfg.pet.source)
    rain_source = make_source(cfg, rain_name, allow_download=not args.offline)
    pet_source = make_pet_source(cfg, pet_name, allow_download=not args.offline)
    wards = cfg.pilot.wards if args.all else [args.ward or cfg.pilot.default_ward]
    command = "agroshield-price " + " ".join(shlex.quote(a) for a in sys.argv[1:])

    for ward_id in wards:
        result = price_ward(cfg, ward_id, rain_source, pet_source)
        run_id = new_run_id(ward_id)
        out = runs_dir / run_id
        out.mkdir()
        results_path = out / "results.json"
        write_json(results_path, result.summary)
        manifest = {
            **base_manifest(run_id, command, repo),
            "ward_id": ward_id,
            "rainfall_source": rain_name,
            "pet_source": pet_name,
            "rainfall": result.summary["rainfall_provenance"],
            "pet": result.summary["pet_provenance"],
            "index_version": cfg.product.layer_b.version,
            "index_v0_version": cfg.product.layer_b_v0.version,
            "pilot": cfg.pilot.model_dump(),
            "history": cfg.rainfall.history.model_dump(),
            "config_sha256": cfg.file_hashes,
            "results_sha256": sha256_file(results_path),
        }
        write_json(out / "manifest.json", manifest)
        (out / "report.html").write_text(render_html(result, manifest), encoding="utf-8", newline="\n")
        append_audit_log(runs_dir, manifest)

        print(f"\n{result.summary['ward']['name']}  [{run_id}]")
        for s, sr in result.seasons.items():
            b, p, tg = sr.summary["burn_cost"], sr.summary["premium"], sr.summary["target"]
            print(f"  {s}: {b['seasons']} seasons, pays in {b['payout_frequency']:.0%} "
                  f"({'in' if tg['in_band'] else 'outside'} target band), expected loss {b['expected_loss']:.2%}, "
                  f"gross rate {p['gross_rate']:.2%} of sum insured")
            for e in sr.summary["event_tests"]:
                verdict = ("PASS" if e["passed"] else "FAIL") + f" (needs >= {e['min_payout']:.0%})" \
                    if e["required"] else "reported only"
                print(f"     event {e['year']}: WRSI {e['wrsi']}, payout {e['payout']:.0%} -> {verdict}")
            for e in sr.summary["early_season_triggers"]:
                print(f"     {e['year']} {e['trigger']}: KES {e['payout_kes']:,.0f}/acre - {e['cause']}")
            la = sr.summary["layer_a"]
            if la.get("available"):
                hb = la["scores"]["layer_b_payout"]
                print(f"  Layer A (SYNTHETIC forecast, skill {la['forecast']['skill_correlation']}): voucher in "
                      f"{la['trigger_frequency_mean']:.0%} of seasons, KES {la['expected_cost_kes']:,.0f} expected, "
                      f"KES {la['gross_kes']:,.0f} gross per acre; catches {hb['hit_rate']['median']:.0%} of Layer B "
                      f"payout seasons, {hb['false_alarm_ratio']['median']:.0%} of vouchers to seasons Layer B did not pay")
        labels = sorted({p["label"] for p in result.summary["provenance"]})
        print(f"  inputs: {', '.join(labels)} (see report)")
        print(f"  report: {out / 'report.html'}")
    return 0


def _fetch(args, src, what: str) -> int:
    cfg = load_config(args.config)
    wards = cfg.pilot.wards if args.all or not args.ward else [args.ward]
    h = cfg.rainfall.history
    for ward_id in wards:
        ward = cfg.ward(ward_id)
        if not args.refresh:
            try:
                cached = src.is_cached(ward, h.start_year, h.end_year)
            except ValueError as e:  # cache exists but no longer matches config or its checksum
                print(f"{ward_id}: {e}")
                return 1
            if cached:
                print(f"{ward_id}: {what} cached, skipping (use --refresh to re-download)")
                continue
        print(f"{ward_id}: saved {src.fetch(ward, h.start_year, h.end_year)}")
    return 0


def cmd_fetch_rain(args) -> int:
    cfg = load_config(args.config)
    return _fetch(args, make_source(cfg, "chirps"), "CHIRPS")


def cmd_fetch_climate(args) -> int:
    cfg = load_config(args.config)
    return _fetch(args, make_pet_source(cfg, "hargreaves_nasapower").base, "NASA POWER")


def cmd_validate(args) -> int:
    cfg = load_config(args.config)
    print(f"config OK: {len(cfg.wards)} wards, index {cfg.product.layer_b.version}, "
          f"rainfall {cfg.rainfall.source}, PET {cfg.pet.source}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agroshield-price", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config", help="config directory (default: ./config)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="price a ward, write the HTML report")
    r.add_argument("--ward", help="ward id from wards.yaml (default: pilot.default_ward)")
    r.add_argument("--all", action="store_true", help="every pilot ward")
    r.add_argument("--source", choices=["chirps", "synthetic"], help="override rainfall.source")
    r.add_argument("--pet", choices=["hargreaves_nasapower", "synthetic"], help="override pet.source")
    r.add_argument("--offline", action="store_true", help="never download; fail if not cached")
    r.add_argument("--out", help="output directory (default: ./runs)")
    r.set_defaults(fn=cmd_run)

    for name, fn, helptext in (("fetch-rainfall", cmd_fetch_rain, "download CHIRPS for pilot wards"),
                               ("fetch-climate", cmd_fetch_climate, "download NASA POWER temperature")):
        f = sub.add_parser(name, help=helptext)
        f.add_argument("--ward")
        f.add_argument("--all", action="store_true")
        f.add_argument("--refresh", action="store_true", help="re-download even if cached")
        f.set_defaults(fn=fn)

    v = sub.add_parser("validate", help="validate config only")
    v.set_defaults(fn=cmd_validate)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
