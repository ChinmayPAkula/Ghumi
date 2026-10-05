"""
Tests for orchestrator.py.

Two layers, matching how the underlying agents were each tested:
  1. Direct node-function unit tests -- call e.g. budget_agent_node(state)
     with a plain TripState, mocking only the one real agent function it
     calls. Fast, no graph machinery.
  2. Full graph integration tests -- compile_graph() + ainvoke(), with
     every external-touching function mocked at the orchestrator module
     boundary (same pattern as mocking _duffel_post etc. in
     test_search_agent.py). These prove the wiring (conditional edges,
     interrupt/resume) actually works, not just that each node's logic is
     correct in isolation (already covered by each agent's own test file).
"""
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.orchestrator import (
    input_handler_node,
    budget_agent_node,
    search_agent_node,
    route_after_search,
    ranking_agent_node,
    itinerary_agent_node,
    route_after_itinerary,
    build_graph,
    compile_graph,
    suggest_surprise_destination,
)
from app.schemas.trip_state import TripState, UserInput, Candidate, Conflict, DayPlan

FUTURE_DATE = date.today() + timedelta(days=30)


def _user_input(**overrides):
    payload = dict(
        destination="Tokyo",
        origin="Bangalore",
        start_date=FUTURE_DATE,
        budget_total=100000,
        duration_days=3,
        priorities_raw="",
        style=None,
    )
    payload.update(overrides)
    return UserInput(**payload)


def _state(**overrides):
    payload = dict(run_id="test-run", user_input=_user_input())
    payload.update(overrides)
    return TripState(**payload)


# --- suggest_surprise_destination ---


def test_suggest_surprise_destination_returns_llm_choice():
    user_input = _user_input(destination=None, surprise_me=True, budget_total=80000)
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="Lisbon")

    with patch("app.agents.orchestrator._get_destination_llm", return_value=mock_llm):
        result = suggest_surprise_destination(user_input)

    assert result == "Lisbon"
    mock_llm.invoke.assert_called_once()
    sent_prompt = mock_llm.invoke.call_args[0][0]
    assert "80000" in sent_prompt


def test_suggest_surprise_destination_returns_none_on_llm_error():
    user_input = _user_input(destination=None, surprise_me=True)

    with patch(
        "app.agents.orchestrator._get_destination_llm", side_effect=RuntimeError("boom")
    ):
        result = suggest_surprise_destination(user_input)

    assert result is None


def test_suggest_surprise_destination_returns_none_on_empty_response():
    user_input = _user_input(destination=None, surprise_me=True)
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="")

    with patch("app.agents.orchestrator._get_destination_llm", return_value=mock_llm):
        result = suggest_surprise_destination(user_input)

    assert result is None


def test_suggest_surprise_destination_strips_whitespace_and_punctuation():
    user_input = _user_input(destination=None, surprise_me=True)
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content='  "Lisbon."  ')

    with patch("app.agents.orchestrator._get_destination_llm", return_value=mock_llm):
        result = suggest_surprise_destination(user_input)

    assert result == "Lisbon"


# --- input_handler_node ---


def test_input_handler_node_passes_when_user_input_set():
    result = input_handler_node(_state())
    assert result == {}


def test_input_handler_node_raises_when_user_input_missing():
    with pytest.raises(ValueError):
        input_handler_node(TripState(run_id="test-run"))


# --- budget_agent_node ---


def test_budget_agent_node_writes_weights_and_allocation():
    state = _state()
    with patch(
        "app.agents.orchestrator.parse_priority_weights",
        return_value={"flights": 0.2, "hotels": 0.2, "food": 0.2, "activities": 0.2, "transport": 0.2},
    ) as mock_parse, patch(
        "app.agents.orchestrator.allocate_budget",
        return_value={"flights": 20000, "hotels": 20000, "food": 20000, "activities": 20000, "transport": 20000},
    ) as mock_allocate:
        result = budget_agent_node(state)

    mock_parse.assert_called_once_with(state.user_input.priorities_raw)
    mock_allocate.assert_called_once_with(state.user_input.budget_total, mock_parse.return_value)
    assert result["priority_weights"] == mock_parse.return_value
    assert result["budget_allocation"] == mock_allocate.return_value


# --- search_agent_node ---


@pytest.mark.asyncio
async def test_search_agent_node_unresolvable_origin_sets_clarification():
    state = _state()
    with patch(
        "app.agents.orchestrator.resolve_iata_code", new=AsyncMock(return_value=None)
    ):
        result = await search_agent_node(state)

    assert "clarification_needed" in result
    assert "Bangalore" in result["clarification_needed"]


@pytest.mark.asyncio
async def test_search_agent_node_unresolvable_destination_sets_clarification():
    state = _state()

    async def fake_resolve(city):
        return "BLR" if city == "Bangalore" else None

    with patch("app.agents.orchestrator.resolve_iata_code", side_effect=fake_resolve):
        result = await search_agent_node(state)

    assert "clarification_needed" in result
    assert "Tokyo" in result["clarification_needed"]


@pytest.mark.asyncio
async def test_search_agent_node_surprise_me_suggests_and_uses_destination():
    state = _state(user_input=_user_input(destination=None, surprise_me=True))

    with patch(
        "app.agents.orchestrator.resolve_iata_code", new=AsyncMock(return_value="HND")
    ), patch(
        "app.agents.orchestrator.suggest_surprise_destination", return_value="Tokyo"
    ) as mock_suggest, patch(
        "app.agents.orchestrator.run_search_agent",
        new=AsyncMock(return_value=({"flights": []}, [], [])),
    ) as mock_search:
        result = await search_agent_node(state)

    mock_suggest.assert_called_once_with(state.user_input)
    assert result["chosen_destination"] == "Tokyo"
    assert "clarification_needed" not in result
    assert mock_search.call_args.kwargs["destination_city"] == "Tokyo"


@pytest.mark.asyncio
async def test_search_agent_node_surprise_me_suggestion_fails_sets_clarification():
    state = _state(user_input=_user_input(destination=None, surprise_me=True))

    with patch(
        "app.agents.orchestrator.resolve_iata_code", new=AsyncMock(return_value="BLR")
    ), patch("app.agents.orchestrator.suggest_surprise_destination", return_value=None):
        result = await search_agent_node(state)

    assert "clarification_needed" in result


@pytest.mark.asyncio
async def test_search_agent_node_real_destination_never_calls_suggest():
    state = _state(user_input=_user_input(destination="Tokyo", surprise_me=False))

    with patch(
        "app.agents.orchestrator.resolve_iata_code", new=AsyncMock(return_value="HND")
    ), patch(
        "app.agents.orchestrator.suggest_surprise_destination"
    ) as mock_suggest, patch(
        "app.agents.orchestrator.run_search_agent",
        new=AsyncMock(return_value=({"flights": []}, [], [])),
    ):
        result = await search_agent_node(state)

    mock_suggest.assert_not_called()
    assert result["chosen_destination"] is None


@pytest.mark.asyncio
async def test_search_agent_node_success_merges_conflicts_onto_existing():
    state = _state(conflicts=[Conflict(description="pre-existing", category="hotels")])
    search_conflict = Conflict(description="flight overspend", category="flights")

    with patch(
        "app.agents.orchestrator.resolve_iata_code", new=AsyncMock(return_value="HND")
    ), patch(
        "app.agents.orchestrator.run_search_agent",
        new=AsyncMock(return_value=({"flights": []}, [], [search_conflict])),
    ):
        result = await search_agent_node(state)

    assert len(result["conflicts"]) == 2
    assert result["conflicts"][0].description == "pre-existing"
    assert result["conflicts"][1].description == "flight overspend"


# --- route_after_search ---


def test_route_after_search_goes_to_ranking_when_clean():
    assert route_after_search(_state()) == "ranking_agent"


def test_route_after_search_goes_to_clarify_on_clarification_needed():
    state = _state(clarification_needed="something unresolved")
    assert route_after_search(state) == "clarify_after_search"


def test_route_after_search_ignores_stale_conflicts_without_clarification_needed():
    """
    Regression test: routing must key off clarification_needed, NOT the
    raw conflicts list -- otherwise an already-acknowledged conflict
    carried over in state.conflicts would spuriously re-trigger this
    checkpoint on every subsequent run.
    """
    state = _state(conflicts=[Conflict(description="already acknowledged")])
    assert route_after_search(state) == "ranking_agent"


# --- ranking_agent_node ---


@pytest.mark.asyncio
async def test_ranking_agent_node_passes_style_and_star_preference():
    state = _state(
        user_input=_user_input(style="cultural", hotel_star_preference=4),
        search_results={"flights": [Candidate(id="f1", category="flights", name="f", price=100)]},
    )
    with patch(
        "app.agents.orchestrator.resolve_city_center", new=AsyncMock(return_value=(1.0, 2.0))
    ), patch(
        "app.agents.orchestrator.rank_search_results", return_value={"flights": []}
    ) as mock_rank:
        result = await ranking_agent_node(state)

    mock_rank.assert_called_once_with(
        state.search_results,
        style="cultural",
        reference_location=(1.0, 2.0),
        hotel_star_preference=4,
    )
    assert result["ranked_shortlist"] == {"flights": []}


# --- itinerary_agent_node ---


def test_itinerary_agent_node_merges_conflicts_onto_existing():
    state = _state(conflicts=[Conflict(description="pre-existing")])
    hotel_conflict = Conflict(description="hotel overspend", category="hotels")

    with patch(
        "app.agents.orchestrator.compose_itinerary",
        return_value=([DayPlan(day_number=1)], [hotel_conflict]),
    ):
        result = itinerary_agent_node(state)

    assert len(result["itinerary"]) == 1
    assert len(result["conflicts"]) == 2
    assert result["conflicts"][1].description == "hotel overspend"


# --- route_after_itinerary ---


def test_route_after_itinerary_ends_when_clean():
    from langgraph.graph import END

    assert route_after_itinerary(_state()) == END


def test_route_after_itinerary_ignores_stale_conflicts_without_clarification_needed():
    state = _state(conflicts=[Conflict(description="already acknowledged at search stage")])
    from langgraph.graph import END

    assert route_after_itinerary(state) == END


def test_route_after_itinerary_clarifies_on_fresh_clarification_needed():
    state = _state(
        conflicts=[Conflict(description="x")], clarification_needed="1 conflict(s) found"
    )
    assert route_after_itinerary(state) == "clarify_after_itinerary"


# --- build_graph structure ---


def test_build_graph_has_all_expected_nodes():
    graph = build_graph()
    compiled = graph.compile()
    node_names = set(compiled.get_graph().nodes.keys())
    expected = {
        "__start__",
        "__end__",
        "input_handler",
        "budget_agent",
        "search_agent",
        "clarify_after_search",
        "ranking_agent",
        "itinerary_agent",
        "clarify_after_itinerary",
    }
    assert expected.issubset(node_names)


# --- full graph integration: happy path + both interrupt checkpoints ---


def _patch_all_agents(
    priority_weights=None,
    budget_allocation=None,
    iata_result="HND",
    search_result=None,
    city_center=None,
    ranked=None,
    itinerary_result=None,
):
    priority_weights = priority_weights or {
        "flights": 0.2, "hotels": 0.2, "food": 0.2, "activities": 0.2, "transport": 0.2
    }
    budget_allocation = budget_allocation or {
        "flights": 20000, "hotels": 20000, "food": 20000, "activities": 20000, "transport": 20000
    }
    search_result = search_result or ({"flights": []}, [], [])
    ranked = ranked if ranked is not None else {"flights": []}
    itinerary_result = itinerary_result or ([], [])

    return (
        patch("app.agents.orchestrator.parse_priority_weights", return_value=priority_weights),
        patch("app.agents.orchestrator.allocate_budget", return_value=budget_allocation),
        patch("app.agents.orchestrator.resolve_iata_code", new=AsyncMock(return_value=iata_result)),
        patch("app.agents.orchestrator.run_search_agent", new=AsyncMock(return_value=search_result)),
        patch("app.agents.orchestrator.resolve_city_center", new=AsyncMock(return_value=city_center)),
        patch("app.agents.orchestrator.rank_search_results", return_value=ranked),
        patch("app.agents.orchestrator.compose_itinerary", return_value=itinerary_result),
    )


@pytest.mark.asyncio
async def test_full_graph_happy_path_completes_without_interrupt():
    app = compile_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "happy-path"}}
    patches = _patch_all_agents(
        itinerary_result=([DayPlan(day_number=1)], [])
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        result = await app.ainvoke(_state(), config=config)

    assert result.get("__interrupt__") is None
    assert len(result["itinerary"]) == 1
    assert result["budget_allocation"]["flights"] == 20000


@pytest.mark.asyncio
async def test_full_graph_pauses_after_search_on_conflict_then_resumes():
    app = compile_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "search-conflict"}}
    flight_conflict = Conflict(description="flight overspend", category="flights")
    patches = _patch_all_agents(search_result=({"flights": []}, [], [flight_conflict]))

    with patches[0], patches[1], patches[2], patches[3]:
        first = await app.ainvoke(_state(), config=config)

    assert first.get("__interrupt__") is not None
    assert first["itinerary"] == []  # never reached itinerary_agent yet

    patches2 = _patch_all_agents(itinerary_result=([DayPlan(day_number=1)], []))
    with patches2[4], patches2[5], patches2[6]:
        resumed = await app.ainvoke(Command(resume="acknowledged"), config=config)

    assert resumed.get("__interrupt__") is None
    assert len(resumed["itinerary"]) == 1


@pytest.mark.asyncio
async def test_full_graph_pauses_after_itinerary_on_hotel_conflict_then_resumes():
    app = compile_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "itinerary-conflict"}}
    hotel_conflict = Conflict(description="hotel overspend", category="hotels")
    patches = _patch_all_agents(
        itinerary_result=([DayPlan(day_number=1)], [hotel_conflict])
    )

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        first = await app.ainvoke(_state(), config=config)

    assert first.get("__interrupt__") is not None
    assert len(first["itinerary"]) == 1  # itinerary WAS built, just flagged

    with patches[0]:  # no more real work happens after resume, just routes to END
        resumed = await app.ainvoke(Command(resume="acknowledged"), config=config)

    assert resumed.get("__interrupt__") is None
