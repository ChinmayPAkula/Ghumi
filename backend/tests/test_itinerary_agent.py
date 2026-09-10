"""
Tests for itinerary_agent.

build_itinerary() is pure code — no mocking needed, same style as
allocate_budget()/ranking_agent's scorers. write_day_narrative()'s Groq
call is mocked, same pattern as budget_agent/parse_priority_weights.
"""
from unittest.mock import MagicMock, patch

from app.agents.itinerary_agent import (
    build_itinerary,
    write_day_narrative,
    compose_itinerary,
    HOTELS,
    FOOD,
    ACTIVITIES,
    TRANSPORT,
    MEALS_PER_DAY,
)
from app.schemas.trip_state import ScoredCandidate, DayPlan


def _candidate(id, category, name, price=500.0, score=0.5):
    return ScoredCandidate(id=id, category=category, name=name, price=price, score=score)


def _shortlist(n_hotels=1, n_food=10, n_activities=10):
    return {
        HOTELS: [_candidate(f"h{i}", HOTELS, f"Hotel {i}") for i in range(n_hotels)],
        FOOD: [_candidate(f"f{i}", FOOD, f"Restaurant {i}") for i in range(n_food)],
        ACTIVITIES: [_candidate(f"a{i}", ACTIVITIES, f"Activity {i}") for i in range(n_activities)],
    }


# --- build_itinerary: basic structure ---


def test_build_itinerary_returns_one_day_plan_per_duration_day():
    days = build_itinerary(_shortlist(), {TRANSPORT: 10000}, duration_days=5)
    assert len(days) == 5
    assert [d.day_number for d in days] == [1, 2, 3, 4, 5]


def test_build_itinerary_includes_hotel_every_day():
    days = build_itinerary(_shortlist(), {TRANSPORT: 10000}, duration_days=3)
    for day in days:
        hotel_items = [i for i in day.items if i.category == HOTELS]
        assert len(hotel_items) == 1
        assert hotel_items[0].id == "h0"  # top-ranked hotel, same every day


def test_build_itinerary_three_meals_per_day():
    days = build_itinerary(_shortlist(), {TRANSPORT: 10000}, duration_days=2)
    for day in days:
        meal_items = [i for i in day.items if i.category == FOOD]
        assert len(meal_items) == MEALS_PER_DAY


def test_build_itinerary_one_activity_per_day():
    days = build_itinerary(_shortlist(), {TRANSPORT: 10000}, duration_days=2)
    for day in days:
        activity_items = [i for i in day.items if i.category == ACTIVITIES]
        assert len(activity_items) == 1


def test_build_itinerary_no_repeat_meals_while_shortlist_lasts():
    # 10 food candidates, 2 days * 3 meals/day = 6 meals needed -- fewer
    # than 10, so no repeats should occur yet.
    days = build_itinerary(_shortlist(n_food=10), {TRANSPORT: 10000}, duration_days=2)
    all_meal_ids = [i.id for day in days for i in day.items if i.category == FOOD]
    assert len(all_meal_ids) == len(set(all_meal_ids))


def test_build_itinerary_cycles_when_shortlist_exhausted():
    # Only 2 food candidates but 3 meals/day needed -- must cycle back to
    # the top rather than leaving a day with fewer than 3 meals.
    days = build_itinerary(_shortlist(n_food=2), {TRANSPORT: 10000}, duration_days=1)
    meal_items = [i for i in days[0].items if i.category == FOOD]
    assert len(meal_items) == MEALS_PER_DAY
    assert meal_items[0].id == "f0"
    assert meal_items[1].id == "f1"
    assert meal_items[2].id == "f0"  # wrapped back around


# --- build_itinerary: transport placeholder ---


def test_build_itinerary_transport_split_evenly_across_days():
    days = build_itinerary(_shortlist(), {TRANSPORT: 10000}, duration_days=5)
    for day in days:
        transport_items = [i for i in day.items if i.category == TRANSPORT]
        assert len(transport_items) == 1
        assert transport_items[0].price == 2000.0  # 10000 / 5 days


def test_build_itinerary_missing_transport_allocation_defaults_to_zero():
    days = build_itinerary(_shortlist(), {}, duration_days=2)
    transport_items = [i for i in days[0].items if i.category == TRANSPORT]
    assert transport_items[0].price == 0.0


# --- build_itinerary: missing data doesn't crash ---


def test_build_itinerary_no_hotel_available_skips_it_gracefully():
    shortlist = _shortlist(n_hotels=0)
    days = build_itinerary(shortlist, {TRANSPORT: 5000}, duration_days=2)
    for day in days:
        assert not any(i.category == HOTELS for i in day.items)


def test_build_itinerary_no_food_or_activities_still_produces_days():
    shortlist = {HOTELS: [_candidate("h0", HOTELS, "Hotel")], FOOD: [], ACTIVITIES: []}
    days = build_itinerary(shortlist, {TRANSPORT: 5000}, duration_days=2)
    assert len(days) == 2
    for day in days:
        assert not any(i.category == FOOD for i in day.items)
        assert not any(i.category == ACTIVITIES for i in day.items)


def test_build_itinerary_empty_shortlist_entirely():
    days = build_itinerary({}, {}, duration_days=1)
    assert len(days) == 1
    # only the transport placeholder should exist
    assert len(days[0].items) == 1
    assert days[0].items[0].category == TRANSPORT


# --- write_day_narrative ---


def test_write_day_narrative_returns_llm_text():
    day = DayPlan(day_number=1, items=[_candidate("a0", ACTIVITIES, "Tokyo Tower")])
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="A lovely day exploring Tokyo Tower.")

    with patch("app.agents.itinerary_agent._get_narrative_llm", return_value=mock_llm):
        result = write_day_narrative(day, "Tokyo")

    assert result == "A lovely day exploring Tokyo Tower."
    mock_llm.invoke.assert_called_once()


def test_write_day_narrative_falls_back_on_llm_error():
    day = DayPlan(day_number=1, items=[_candidate("a0", ACTIVITIES, "Tokyo Tower")])

    with patch("app.agents.itinerary_agent._get_narrative_llm", side_effect=RuntimeError("boom")):
        result = write_day_narrative(day, "Tokyo")

    assert "Day 1 in Tokyo" in result
    assert "Tokyo Tower" in result


def test_write_day_narrative_falls_back_on_empty_llm_response():
    day = DayPlan(day_number=1, items=[_candidate("a0", ACTIVITIES, "Tokyo Tower")])
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="")

    with patch("app.agents.itinerary_agent._get_narrative_llm", return_value=mock_llm):
        result = write_day_narrative(day, "Tokyo")

    assert "Tokyo Tower" in result  # fell back to the code-generated sentence


def test_write_day_narrative_excludes_synthetic_transport_from_fallback_text():
    from app.agents.itinerary_agent import _transport_placeholder

    day = DayPlan(
        day_number=1,
        items=[_candidate("a0", ACTIVITIES, "Tokyo Tower"), _transport_placeholder(1, 2000.0)],
    )
    with patch("app.agents.itinerary_agent._get_narrative_llm", side_effect=RuntimeError("boom")):
        result = write_day_narrative(day, "Tokyo")

    assert "Local transport" not in result


# --- compose_itinerary: full pipeline ---


def test_compose_itinerary_writes_summary_for_every_day():
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="A great day.")

    with patch("app.agents.itinerary_agent._get_narrative_llm", return_value=mock_llm):
        days = compose_itinerary(_shortlist(), {TRANSPORT: 10000}, duration_days=3, destination="Tokyo")

    assert len(days) == 3
    for day in days:
        assert day.summary == "A great day."
