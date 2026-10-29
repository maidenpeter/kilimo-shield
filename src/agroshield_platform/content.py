"""Public Learn articles: plain-language explainers, each with its sources (see templates/public/article.html).

Every factual claim in an article carries a numbered source. The articles were drafted only from facts checked
against their source pages (docs/overnight/phase_c_facts.json), then checked again sentence by sentence by an
independent reviewer; what could not be supported was cut (docs/overnight/phase_c_article_checks.json).
Citations of "How AgroShield works" point at /how-it-works, which states the product terms from config/product.yaml.
"""
from __future__ import annotations

import json
from pathlib import Path

ARTICLES: list[dict] = json.loads((Path(__file__).parent / "articles.json").read_text(encoding="utf-8"))


def article(slug: str) -> dict | None:
    return next((a for a in ARTICLES if a["slug"] == slug), None)
