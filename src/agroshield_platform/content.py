"""Public Learn articles: plain-language explainers, each with its sources (see templates/public/article.html).

Every factual claim in an article must carry a source link. Facts were checked against the source pages when the
articles were written; anything that could not be verified was left out.
"""
from __future__ import annotations

ARTICLES: list[dict] = []        # filled in by the Learn hub content


def article(slug: str) -> dict | None:
    return next((a for a in ARTICLES if a["slug"] == slug), None)
