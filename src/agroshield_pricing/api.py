"""Quote API (FastAPI).

    GET  /health          liveness
    GET  /v1/products     wards, seasons, layers offered, sum-insured options, Resilience items
    POST /v1/quotes       a quote: gross premium from the engine, subsidy split, Resilience discount

Quotes are computed by agroshield_pricing.quote against a rate book built by the
pricing engine at startup, so the API never duplicates pricing logic. Requests
travel in the POST body; nothing (personal or otherwise) goes in a URL query.
Every quote is appended to var/audit/quotes.jsonl.

Run:  agroshield-api   (http://127.0.0.1:8770, interactive docs at /docs)
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import Config, load_config
from .pet import make_pet_source
from .quote import QuoteError, RateBook, audit_quote, quote
from .rainfall import make_source


class QuoteRequest(BaseModel):
    ward_id: str = Field(examples=["ward-a"])
    season: Literal["LR", "SR"] = "LR"
    acres: float = Field(gt=0, le=1000, examples=[2.0])
    layers: list[Literal["A", "B"]] = Field(default=["B"], examples=[["A", "B"]])
    sum_insured_kes_per_acre: float | None = Field(default=None, examples=[10000])
    resilience: dict[str, bool] = Field(default_factory=dict,
                                        examples=[{"certified_seed_verified": True, "sacco_good_standing": True}])


def create_app(config_dir: str | Path = "config", book: RateBook | None = None,
               audit_path: Path | None = None) -> FastAPI:
    cfg: Config = load_config(config_dir)
    repo = Path(cfg.root).parent
    audit = audit_path or repo / "var" / "audit" / "quotes.jsonl"
    state = {"book": book}

    def rate_book() -> RateBook:
        if state["book"] is None:   # built once, from committed inputs only
            state["book"] = RateBook.build(cfg, make_source(cfg, allow_download=False),
                                           make_pet_source(cfg, allow_download=False))
        return state["book"]

    app = FastAPI(title="AgroShield quote API",
                  description="Illustrative pricing: not a filed product and not for sale.", version="0.4.0")

    @app.get("/health")
    def health():
        return {"ok": True, "index_version": cfg.product.layer_b.version}

    @app.get("/v1/products")
    def products():
        b = rate_book()
        return {
            "illustrative": True,
            "wards": [{"ward_id": w.ward_id, "name": w.ward_name, "season": w.season,
                       "layers": ["A", "B"] if w.layer_a_gross_per_acre is not None else ["B"],
                       "layer_b_gross_per_acre_kes": {str(int(k)): v for k, v in w.layer_b_gross_per_acre.items()},
                       "layer_a_gross_per_acre_kes": w.layer_a_gross_per_acre,
                       "index_versions": w.index_versions} for w in b.rates.values()],
            "sum_insured_options_kes_per_acre": cfg.product.sum_insured.options_kes_per_acre,
            "subsidy": cfg.product.subsidy.model_dump(),
            "resilience": cfg.product.resilience.model_dump(),
            "rate_book_built_at": b.built_at,
        }

    @app.post("/v1/quotes")
    def create_quote(req: QuoteRequest):
        try:
            q = quote(cfg, rate_book(), **req.model_dump())
        except QuoteError as e:
            raise HTTPException(status_code=422, detail=str(e))
        audit_quote(audit, req.model_dump(), q)
        return q

    return app


def main(argv: list[str] | None = None) -> int:
    import uvicorn
    ap = argparse.ArgumentParser(prog="agroshield-api")
    ap.add_argument("--config", default="config")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8770)
    args = ap.parse_args(argv)
    uvicorn.run(create_app(args.config), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
