"""Command line: `agroshield-price run --ward ward-a` prices a ward and writes its report.

Subcommands
  run              price and backtest one ward (or all pilot wards) -> runs/<run_id>/
  fetch-rainfall   download and cache CHIRPS for one or all pilot wards
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
from .rainfall import make_source
from .report import render_html, write_json


def _repo_root(config_dir: Path) -> Path:
    return config_dir.resolve().parent


def cmd_run(args) -> int:
    cfg = load_config(args.config)
    repo = _repo_root(Path(args.config))
    runs_dir = Path(args.out) if args.out else repo / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    source_name = args.source or cfg.rainfall.source
    source = make_source(cfg, source_name, allow_download=not args.offline)
    wards = cfg.pilot.wards if args.all else [args.ward or cfg.pilot.default_ward]
    command = "agroshield-price " + " ".join(shlex.quote(a) for a in sys.argv[1:])

    for ward_id in wards:
        result = price_ward(cfg, ward_id, source)
        run_id = new_run_id(ward_id)
        out = runs_dir / run_id
        out.mkdir()
        results_path = out / "results.json"
        write_json(results_path, result.summary)
        manifest = {
            **base_manifest(run_id, command, repo),
            "ward_id": ward_id,
            "rainfall_source": source_name,
            "rainfall": result.summary["rainfall_provenance"],
            "index_version": cfg.product.layer_b.version,
            "pilot": cfg.pilot.model_dump(),
            "history": cfg.rainfall.history.model_dump(),
            "backtest_settings": cfg.product.backtest.model_dump(),
            "config_sha256": cfg.file_hashes,
            "results_sha256": sha256_file(results_path),
        }
        write_json(out / "manifest.json", manifest)
        (out / "report.html").write_text(render_html(result, manifest), encoding="utf-8")
        append_audit_log(runs_dir, manifest)

        print(f"\n{result.summary['ward']['name']}  [{run_id}]")
        for s, sr in result.seasons.items():
            b, p = sr.summary["burn_cost"], sr.summary["premium"]
            print(f"  {s}: {b['seasons']} seasons, pays in {b['payout_frequency']:.0%}, "
                  f"expected loss {b['expected_loss']:.2%}, 1-in-10 {b['loss_1_in_10']:.1%}, "
                  f"gross rate {p['gross_rate']:.2%} of sum insured")
        labels = sorted({p["label"] for p in result.summary["provenance"]})
        print(f"  inputs: {', '.join(labels)} (see report)")
        print(f"  report: {out / 'report.html'}")
    return 0


def cmd_fetch(args) -> int:
    cfg = load_config(args.config)
    src = make_source(cfg, "chirps")
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
                print(f"{ward_id}: cached, skipping (use --refresh to re-download)")
                continue
        print(f"{ward_id}: saved {src.fetch(ward, h.start_year, h.end_year)}")
    return 0


def cmd_validate(args) -> int:
    cfg = load_config(args.config)
    print(f"config OK: {len(cfg.wards)} wards, index {cfg.product.layer_b.version}, "
          f"rainfall source {cfg.rainfall.source}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agroshield-price", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config", help="config directory (default: ./config)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="price and backtest a ward, write the HTML report")
    r.add_argument("--ward", help="ward id from wards.yaml (default: pilot.default_ward)")
    r.add_argument("--all", action="store_true", help="every pilot ward")
    r.add_argument("--source", choices=["chirps", "synthetic"], help="override rainfall.source")
    r.add_argument("--offline", action="store_true", help="never download; fail if not cached")
    r.add_argument("--out", help="output directory (default: ./runs)")
    r.set_defaults(fn=cmd_run)

    f = sub.add_parser("fetch-rainfall", help="download CHIRPS for pilot wards")
    f.add_argument("--ward")
    f.add_argument("--all", action="store_true")
    f.add_argument("--refresh", action="store_true", help="re-download even if cached")
    f.set_defaults(fn=cmd_fetch)

    v = sub.add_parser("validate", help="validate config only")
    v.set_defaults(fn=cmd_validate)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
