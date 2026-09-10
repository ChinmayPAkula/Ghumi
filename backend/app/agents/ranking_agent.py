"""
Ranking Agent — Ghumi_Agent_Architecture_Spec.docx §3.3 / §5.1, PRD §6.3

Pure code, weighted-sum scoring per category. Per the LLM/code split
(PRD §5.2), an LLM re-ranks/explains only the top-N shortlist afterward
(rerank_shortlist(), not yet built) — this module never calls an LLM,
it only produces the ScoredCandidate list the LLM step will read from.

Formula, adapted from the original PRD's five-factor spec once real
providers were wired in search_agent (decided collaboratively, not
unilaterally — see conversation history):
  - rating_norm, review_count_norm, proximity_norm, style_match — used
    for hotels/food/activities.
  - recency_norm DROPPED ENTIRELY: no provider we use exposes a
    listing-freshness/review-recency signal without a separate, far more
    expensive per-candidate "details" call. Faking it with a constant
    would add formula complexity with zero real signal, which is worse
    than being honest that it's unavailable — revisit only if a future
    provider swap makes it cheaply available.
  - Flights have no rating/review data from Duffel at all, so they're
    scored separately: price + a static airline-rating lookup table
    (deliberately NOT an LLM call per search — that would add latency/
    cost per request for data that barely changes; a small curated table
    is zero-latency and matches "ranking is code, not LLM" anyway).
"""
from __future__ import annotations

import math
from typing import Optional

from app.schemas.trip_state import Candidate, ScoredCandidate

HOTELS = "hotels"
FOOD = "food"
ACTIVITIES = "activities"
FLIGHTS = "flights"

# Rating scales differ per provider: LiteAPI hotels are out of 10,
# Google Places food/activities are out of 5.
RATING_SCALE = {HOTELS: 10.0, FOOD: 5.0, ACTIVITIES: 5.0}

# Equal weighting across the four available factors — a documented,
# adjustable default, not a claim that these are the objectively correct
# proportions. Revisit once real user feedback exists to tune against.
PLACE_WEIGHTS = {
    "rating_norm": 0.25,
    "review_count_norm": 0.25,
    "proximity_norm": 0.25,
    "style_match": 0.25,
}

# Flights: price dominates (it's the one number every traveler actually
# compares), airline reputation is a secondary tiebreaker.
FLIGHT_WEIGHTS = {"price_norm": 0.7, "airline_rating_norm": 0.3}

# Static, curated, zero-latency airline reputation proxy (out of 5) —
# deliberately NOT an LLM call per search. Extend as needed; unknown
# airlines fall back to a neutral default rather than being penalized.
AIRLINE_RATING_PROXY: dict[str, float] = {
    "SQ": 4.8,  # Singapore Airlines
    "QR": 4.7,  # Qatar Airways
    "EK": 4.6,  # Emirates
    "NH": 4.5,  # ANA
    "JL": 4.5,  # Japan Airlines
    "CX": 4.4,  # Cathay Pacific
    "LH": 4.2,  # Lufthansa
    "AF": 4.0,  # Air France
    "BA": 4.0,  # British Airways
    "UA": 3.7,  # United
    "AA": 3.6,  # American Airlines
    "DL": 3.9,  # Delta
    "AI": 3.4,  # Air India
    "6E": 3.8,  # IndiGo
    "SG": 3.3,  # SpiceJet
    "UK": 3.9,  # Vistara
}
DEFAULT_AIRLINE_RATING = 3.5

# Keyword hints for style_match — an approximate heuristic (documented as
# such, same pattern as search_agent's PRICE_LEVEL_PROXY), not a claim of
# precise style classification. Refine in Phase 2 with richer place-type
# data if this proves too coarse.
STYLE_KEYWORDS: dict[str, list[str]] = {
    "cultural": ["temple", "shrine", "museum", "heritage", "historic", "palace", "fort", "gallery"],
    "adventurous": ["adventure", "hike", "trek", "extreme", "climbing", "rafting", "safari"],
    "relaxed": ["spa", "resort", "onsen", "garden", "park", "beach", "retreat"],
}


def _normalize(values: list[float]) -> list[float]:
    """Min-max normalize within this candidate list. Flat/singleton lists
    map to a neutral 1.0 for everyone rather than dividing by zero."""
    if not values:
        return []
    low, high = min(values), max(values)
    if high == low:
        return [1.0 for _ in values]
    return [(v - low) / (high - low) for v in values]


def _extract_coordinates(candidate: Candidate) -> Optional[tuple[float, float]]:
    """
    Pulls lat/lng out of whichever raw provider payload search_agent
    stashed in metadata — LiteAPI hotels and Google Places both include
    real coordinates in what's already fetched, no extra API call needed.
    """
    raw = candidate.metadata.get("raw")
    if not isinstance(raw, dict):
        return None

    # Google Places shape: {"location": {"latitude": .., "longitude": ..}}
    location = raw.get("location")
    if isinstance(location, dict) and "latitude" in location and "longitude" in location:
        return (location["latitude"], location["longitude"])

    # LiteAPI hotel shape: {"hotel": {"latitude": .., "longitude": ..}, ...}
    hotel = raw.get("hotel")
    if isinstance(hotel, dict) and "latitude" in hotel and "longitude" in hotel:
        return (hotel["latitude"], hotel["longitude"])

    return None


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))  # Earth radius 6371 km


def _style_match_score(candidate: Candidate, category: str, style: Optional[str]) -> float:
    """Neutral 0.5 with no style set, or no keyword rule defined for it."""
    if style is None:
        return 0.5

    if style == "popular":
        # Reward high review counts directly — handled by the caller via
        # review_count_norm reuse, since that's exactly what "popular" means.
        return None  # sentinel: caller substitutes review_count_norm
    if style == "hidden_gems":
        return None  # sentinel: caller substitutes 1 - review_count_norm
    if style == "food_focused":
        return 1.0 if category == FOOD else 0.4

    keywords = STYLE_KEYWORDS.get(style)
    if not keywords:
        return 0.5

    name = candidate.name.lower()
    return 1.0 if any(kw in name for kw in keywords) else 0.3


def score_places(
    candidates: list[Candidate],
    category: str,
    style: Optional[str] = None,
    reference_location: Optional[tuple[float, float]] = None,
) -> list[ScoredCandidate]:
    """
    Weighted-sum scoring for hotels/food/activities. Returns
    ScoredCandidates sorted highest-score-first. Every normalization is
    computed within this candidate list (there's no universal "good"
    rating/distance threshold across different searches).
    """
    if not candidates:
        return []

    scale = RATING_SCALE.get(category, 5.0)
    ratings = [c.rating / scale if c.rating is not None else 0.0 for c in candidates]
    rating_norms = _normalize(ratings)

    review_logs = [
        math.log1p(c.review_count) if c.review_count is not None else 0.0 for c in candidates
    ]
    review_count_norms = _normalize(review_logs)

    coords = [_extract_coordinates(c) for c in candidates]
    weights = dict(PLACE_WEIGHTS)
    if reference_location is None or all(c is None for c in coords):
        # No usable location data at all for this search — drop proximity
        # entirely and redistribute its weight, rather than silently
        # scoring everyone as "equally close."
        del weights["proximity_norm"]
        total = sum(weights.values())
        weights = {k: v / total for k, v in weights.items()}
        proximity_norms = [0.0] * len(candidates)
    else:
        distances = [
            _haversine_km(reference_location, c) if c is not None else None for c in coords
        ]
        known = [d for d in distances if d is not None]
        max_known = max(known) if known else 0.0
        # Missing coordinates for an individual candidate -> treat as
        # worst-case distance rather than penalizing the whole search.
        filled = [d if d is not None else max_known for d in distances]
        proximity_norms = [1.0 - n for n in _normalize(filled)]

    scored = []
    for i, candidate in enumerate(candidates):
        style_score = _style_match_score(candidate, category, style)
        if style_score is None:  # popular/hidden_gems sentinel
            style_score = (
                review_count_norms[i] if style == "popular" else 1.0 - review_count_norms[i]
            )

        score = (
            weights.get("rating_norm", 0.0) * rating_norms[i]
            + weights.get("review_count_norm", 0.0) * review_count_norms[i]
            + weights.get("proximity_norm", 0.0) * proximity_norms[i]
            + weights.get("style_match", 0.0) * style_score
        )
        scored.append(ScoredCandidate(**candidate.model_dump(), score=score))

    return sorted(scored, key=lambda c: c.score, reverse=True)


def _extract_airline_code(candidate: Candidate) -> Optional[str]:
    """
    Duffel's offer.owner.iata_code is the offer's overall owning
    airline — confirmed live against a real offer (owner: {"iata_code":
    "BA", "name": "British Airways", ...}) rather than guessed.
    """
    raw = candidate.metadata.get("raw")
    if not isinstance(raw, dict):
        return None
    owner = raw.get("owner")
    if isinstance(owner, dict):
        return owner.get("iata_code")
    return None


def score_flights(candidates: list[Candidate]) -> list[ScoredCandidate]:
    """Weighted-sum scoring for flights: price (cheaper is better) + a
    static airline-rating lookup, since Duffel gives no rating/review data."""
    if not candidates:
        return []

    prices = [c.price for c in candidates]
    # Cheaper = better, so invert the normalized price.
    price_norms = [1.0 - n for n in _normalize(prices)]

    airline_ratings = [
        AIRLINE_RATING_PROXY.get(_extract_airline_code(c) or "", DEFAULT_AIRLINE_RATING) / 5.0
        for c in candidates
    ]
    airline_norms = _normalize(airline_ratings)

    scored = [
        ScoredCandidate(
            **candidate.model_dump(),
            score=(
                FLIGHT_WEIGHTS["price_norm"] * price_norms[i]
                + FLIGHT_WEIGHTS["airline_rating_norm"] * airline_norms[i]
            ),
        )
        for i, candidate in enumerate(candidates)
    ]
    return sorted(scored, key=lambda c: c.score, reverse=True)


def rank_search_results(
    search_results: dict[str, list[Candidate]],
    style: Optional[str] = None,
    reference_location: Optional[tuple[float, float]] = None,
) -> dict[str, list[ScoredCandidate]]:
    """Applies the right scorer per category. Flights never use style/
    location (Duffel gives neither), places do."""
    ranked: dict[str, list[ScoredCandidate]] = {}
    for category, candidates in search_results.items():
        if category == FLIGHTS:
            ranked[category] = score_flights(candidates)
        else:
            ranked[category] = score_places(candidates, category, style, reference_location)
    return ranked
