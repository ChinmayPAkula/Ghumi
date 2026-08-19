# Ghumi

AI-powered multi-agent travel planner. See `/docs` for the full PRD, design spec, tech stack, and agent architecture doc — this README is just setup + status.

## Repo structure

```
/backend    FastAPI app, LangGraph agents, Pydantic schemas, Pytest suite
/frontend   React + Vite + TypeScript + Tailwind
/docs       PRD, design spec, tech stack, agent architecture, HTML prototypes
```

Plain folder split, no monorepo tooling — see `docs/Ghumi_TechStack.docx` §5 for why.

## Setup

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env             # fill in real keys
uvicorn app.main:app --reload    # http://localhost:8000
```

Check it's alive: `curl http://localhost:8000/health`

### Frontend

```bash
cd frontend
npm install
cp .env.example .env             # usually fine to leave blank in dev
npm run dev                      # http://localhost:5173
```

Vite proxies `/api/*` to the backend on `:8000` in dev (see `vite.config.ts`) — no CORS headaches locally.

## Build status

Building in phases, not all at once — see the decision log below for why things are ordered this way.

- [x] Repo scaffolding, env templates, CI skeleton
- [x] Landing page (hero, transition, how-it-works) — ported from validated HTML prototype
- [ ] `input_handler` — GUI form → validated `UserInput` (next up)
- [ ] `TripState` schema wired end-to-end through one full LangGraph run (P1, no interrupts)
- [ ] Checkpointed clarification interrupts (per-node, not just infeasibility-triggered)
- [ ] Phase 2 additions (pacing, price comparison, seasonal rules, conflict resolution)
- [ ] Phase 3 additions (booking, group mode, explainability)

## Decisions worth remembering

Kept short and blunt — full reasoning lives in conversation history, not repeated here.

- **GUI before chatbot.** Chat's whole job is producing the same structured `UserInput` the GUI form produces, just from messier text. Building GUI first means the agent pipeline gets tested with clean input before ambiguity gets added on top.
- **Checkpointed interrupts, not true anytime-interrupts, for v1.** Pausing between nodes (LangGraph `interrupt()` + checkpointer) is what's actually planned — not canceling a node mid-flight. True live interruption is a real but separate scope, deferred.
- **`TripState` schema is the contract.** Every agent reads what it needs, writes only its own fields. Don't reach into another agent's fields — if two agents need to share something, it goes through state, not a side channel.
