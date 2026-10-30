"""Pricing guard: re-run both reference pricing runs and compare results.json hashes.

    python tools/qa/pricing_guard.py OUT.json

Runs `agroshield-price run --all --offline`, hashes each new run's results.json
and the config files, and compares them with docs/overnight/pricing_reference.json.
Exits 1 if any hash differs.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "docs" / "overnight" / "pricing_reference.json"
RUNS = ROOT / "runs"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(out: str) -> int:
    ref = json.loads(REF.read_text(encoding="utf-8"))
    before = {p.name for p in RUNS.iterdir() if p.is_dir()}
    exe = Path(sys.executable).with_name("agroshield-price")
    subprocess.run([str(exe), "run", "--all", "--offline"], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL)
    new = sorted(p for p in RUNS.iterdir() if p.is_dir() and p.name not in before)
    result = {"command": "agroshield-price run --all --offline", "reference": REF.relative_to(ROOT).as_posix(),
              "wards": {}, "all_match": True}
    for ward, want in ref["wards"].items():
        runs = [p for p in new if f"_{ward}_" in p.name]
        if not runs:
            result["wards"][ward] = {"error": "no new run"}
            result["all_match"] = False
            continue
        run = runs[-1]
        got = sha(run / "results.json")
        cfg = {name: sha(ROOT / "config" / name) for name in want["config_sha256"]}
        ok = got == want["results_sha256"] and cfg == want["config_sha256"]
        result["wards"][ward] = {"run_id": run.name, "results_sha256": got,
                                 "matches_reference": got == want["results_sha256"],
                                 "config_matches": cfg == want["config_sha256"]}
        result["all_match"] &= ok
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["all_match"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
