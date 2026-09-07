"""
Run this manually to sanity-check parse_priority_weights against the REAL
Groq API — this is NOT part of the pytest suite (pytest tests mock the LLM
call on purpose, see tests/test_budget_agent.py).

Requires GROQ_API_KEY set in your .env.

Run from backend/:
    python scripts/verify_budget_agent_live.py
"""
from app.agents.budget_agent import parse_priority_weights

SAMPLES = [
    "I care a lot about food, don't really mind cheap flights",
    "Just want a comfortable hotel, everything else is flexible",
    "",  # should skip the LLM and return equal weights
    "Budget flights and budget hotels, save everything for activities",
]

if __name__ == "__main__":
    for text in SAMPLES:
        result = parse_priority_weights(text)
        label = text if text else "(empty string)"
        print(f"\nInput: {label}")
        print(f"Weights: {result}")
        print(f"Sum: {sum(result.values()):.3f}")