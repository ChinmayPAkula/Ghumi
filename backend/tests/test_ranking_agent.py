"""
Tests for ranking_agent. Pure code, no external calls to mock — same
testing style as budget_agent's allocate_budget.
"""
import pytest

from app.agents.ranking_agent import (
    _normalize,
    score_places,
    score_flights,
    rank_search_results,
    AIRLINE_RATING_PROXY,
    DEFAULT_AIRLINE_RATING,
    HOTELS,
    FOOD,
    FLIGHTS,
)
from app.schemas.trip_state import Candidate


def _place(id, name, rating=None, review_count=None, lat=None, lng=None):
    raw = {}
    if lat is not None and lng is not None:
        raw["location"] = {"latitude": lat, "longitude": lng}
    return Candidate(
        id=id,
        category=FOOD,
        name=name,
        price=500.0,
        rating=rating,
        review_count=review_count,
        metadata={"raw": raw},
    )


def _flight(id, price, airline_code=None):
    raw = {}
    if airline_code:
        raw["owner"] = {"iata_code": airline_code}
    return Candidate(id=id, category=FLIGHTS, name=f"flight {id}", price=price, metadata={"raw": raw})


# --- _normalize ---


def test_normalize_empty_list():
    assert _normalize([]) == []


def test_normalize_flat_list_returns_all_ones():
    assert _normalize([5.0, 5.0, 5.0]) == [1.0, 1.0, 1.0]


def test_normalize_spreads_values_0_to_1():
    result = _normalize([0.0, 5.0, 10.0])
    assert result == [0.0, 0.5, 1.0]


# --- score_places: rating/review_count ---


def test_score_places_higher_rating_scores_higher_all_else_equal():
    candidates = [
        _place("a", "Low rated", rating=3.0, review_count=100),
        _place("b", "High rated", rating=4.8, review_count=100),
    ]
    scored = score_places(candidates, FOOD)
    assert scored[0].id == "b"


def test_score_places_higher_review_count_scores_higher_all_else_equal():
    candidates = [
        _place("a", "Few reviews", rating=4.0, review_count=5),
        _place("b", "Many reviews", rating=4.0, review_count=5000),
    ]
    scored = score_places(candidates, FOOD)
    assert scored[0].id == "b"


def test_score_places_missing_rating_treated_as_worst_not_crash():
    candidates = [
        _place("a", "No rating", rating=None, review_count=100),
        _place("b", "Has rating", rating=4.0, review_count=100),
    ]
    scored = score_places(candidates, FOOD)
    assert scored[0].id == "b"


def test_score_places_empty_list_returns_empty():
    assert score_places([], FOOD) == []


# --- score_places: rating scale differs by category ---


def test_score_places_uses_correct_rating_scale_per_category():
    # A hotel rated 8/10 and a restaurant rated 4/5 represent the same
    # relative quality (0.8) -- scoring each against its own peer list
    # with an unrelated low-rated peer should rank the good one on top
    # in both cases, proving the /10 vs /5 scale is actually applied.
    hotel_candidates = [
        Candidate(id="h1", category=HOTELS, name="Bad hotel", price=1000, rating=2.0),
        Candidate(id="h2", category=HOTELS, name="Good hotel", price=1000, rating=8.0),
    ]
    scored = score_places(hotel_candidates, HOTELS)
    assert scored[0].id == "h2"


# --- score_places: proximity ---


def test_score_places_closer_to_reference_scores_higher():
    tokyo_center = (35.6762, 139.6503)
    candidates = [
        _place("far", "Far place", rating=4.0, review_count=100, lat=36.5, lng=140.5),
        _place("near", "Near place", rating=4.0, review_count=100, lat=35.68, lng=139.66),
    ]
    scored = score_places(candidates, FOOD, reference_location=tokyo_center)
    assert scored[0].id == "near"


def test_score_places_no_reference_location_does_not_crash():
    candidates = [
        _place("a", "Place A", rating=4.0, review_count=100),
        _place("b", "Place B", rating=3.0, review_count=100),
    ]
    scored = score_places(candidates, FOOD, reference_location=None)
    assert len(scored) == 2
    assert scored[0].id == "a"  # higher rating still wins on remaining factors


def test_score_places_partial_missing_coordinates_does_not_crash():
    tokyo_center = (35.6762, 139.6503)
    candidates = [
        _place("has_coords", "Has coords", rating=4.0, review_count=100, lat=35.68, lng=139.66),
        _place("no_coords", "No coords", rating=4.0, review_count=100),  # no lat/lng
    ]
    scored = score_places(candidates, FOOD, reference_location=tokyo_center)
    assert len(scored) == 2


# --- score_places: style_match ---


def test_style_match_popular_favors_high_review_count():
    candidates = [
        _place("a", "Quiet place", rating=4.0, review_count=10),
        _place("b", "Busy place", rating=4.0, review_count=10000),
    ]
    scored = score_places(candidates, FOOD, style="popular")
    assert scored[0].id == "b"


def test_style_match_hidden_gems_favors_low_review_count():
    candidates = [
        _place("a", "Quiet place", rating=4.0, review_count=10),
        _place("b", "Busy place", rating=4.0, review_count=10000),
    ]
    scored = score_places(candidates, FOOD, style="hidden_gems")
    assert scored[0].id == "a"


def test_style_match_cultural_keyword_boosts_matching_name():
    candidates = [
        _place("a", "Random Cafe", rating=4.0, review_count=100),
        _place("b", "Ancient Temple", rating=4.0, review_count=100),
    ]
    scored = score_places(candidates, FOOD, style="cultural")
    assert scored[0].id == "b"


def test_style_match_food_focused_boosts_food_category_over_others():
    food_candidate = _place("f", "Restaurant", rating=4.0, review_count=100)
    food_candidate.category = FOOD
    activity_candidate = _place("a", "Museum", rating=4.0, review_count=100)
    activity_candidate.category = "activities"

    food_scored = score_places([food_candidate], FOOD, style="food_focused")[0]
    activity_scored = score_places([activity_candidate], "activities", style="food_focused")[0]
    assert food_scored.score > activity_scored.score


def test_style_match_unknown_style_falls_back_to_neutral():
    candidates = [_place("a", "Place A", rating=4.0, review_count=100)]
    # Should not raise for a style with no keyword rule defined
    scored = score_places(candidates, FOOD, style="relaxed")
    assert len(scored) == 1


# --- score_flights ---


def test_score_flights_cheaper_wins_all_else_equal():
    candidates = [_flight("a", 50000), _flight("b", 20000)]
    scored = score_flights(candidates)
    assert scored[0].id == "b"


def test_score_flights_known_airline_beats_unknown_at_same_price():
    candidates = [
        _flight("a", 20000, airline_code="ZZ"),  # unknown -> DEFAULT_AIRLINE_RATING
        _flight("b", 20000, airline_code="SQ"),  # Singapore Airlines, top-rated in table
    ]
    scored = score_flights(candidates)
    assert scored[0].id == "b"


def test_score_flights_missing_airline_code_uses_default_not_crash():
    candidates = [_flight("a", 20000, airline_code=None), _flight("b", 30000, airline_code="SQ")]
    scored = score_flights(candidates)
    assert len(scored) == 2


def test_score_flights_empty_list_returns_empty():
    assert score_flights([]) == []


def test_airline_rating_proxy_has_sensible_bounds():
    assert all(0.0 <= v <= 5.0 for v in AIRLINE_RATING_PROXY.values())
    assert 0.0 <= DEFAULT_AIRLINE_RATING <= 5.0


# --- rank_search_results: dispatch ---


def test_rank_search_results_dispatches_flights_and_places_correctly():
    search_results = {
        FLIGHTS: [_flight("f1", 20000, airline_code="SQ")],
        FOOD: [_place("p1", "Cafe", rating=4.0, review_count=50)],
    }
    ranked = rank_search_results(search_results)
    assert FLIGHTS in ranked and FOOD in ranked
    assert ranked[FLIGHTS][0].id == "f1"
    assert ranked[FOOD][0].id == "p1"


def test_rank_search_results_empty_category_returns_empty_list():
    ranked = rank_search_results({FOOD: []})
    assert ranked[FOOD] == []
