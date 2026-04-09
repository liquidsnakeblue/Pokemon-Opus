# Pokemon-Opus

AI agent that plays Pokemon Blue autonomously, powered by Claude Opus.

Built by combining three projects:
- **[PokemonOpenClaude](https://github.com/NousResearch/pokemon-agent)** — Headless Game Boy emulator with REST API and full Gen 1 RAM reading
- **[Zork-Opus](https://github.com/liquidsnakeblue/Zork-Opus)** — Proven AI game-playing architecture (memory, objectives, multi-model orchestration)
- **[Archon](https://github.com/coleam00/archon)** — Infrastructure patterns for streaming, events, and React dashboards

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  PokemonOpenClaude (game server, port 8765)                 │
│  Headless PyBoy emulator + RAM reader + REST API            │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP (GET /state, POST /action,
                           │       GET /screenshot)
┌──────────────────────────▼──────────────────────────────────┐
│  Pokemon-Opus Backend (Python, port 3000)                   │
│                                                             │
│  ┌─────────────┐  ┌────────────┐  ┌──────────────────────┐ │
│  │ Orchestrator │  │ LLM Client │  │ Streaming Server     │ │
│  │ (state      │  │ (Anthropic,│  │ (FastAPI + WebSocket) │ │
│  │  machine)   │  │  OpenAI,   │  └──────────┬───────────┘ │
│  │             │  │  local)    │              │             │
│  │ ┌─────────┐ │  └────────────┘              │             │
│  │ │ Explore │ │                              │             │
│  │ │ Battle  │ │  ┌────────────┐              │             │
│  │ │ Menu    │ │  │ Memory     │              │             │
│  │ │ Strategy│ │  │ Objectives │              │             │
│  │ └─────────┘ │  │ Map Graph  │              │             │
│  └─────────────┘  │ Context    │              │             │
│                   └────────────┘              │             │
└───────────────────────────────────────────────┼─────────────┘
                                                │ WebSocket
┌───────────────────────────────────────────────▼─────────────┐
│  React Viewer (TypeScript, port 5173)                       │
│  Live game screen, AI reasoning, team, map, objectives      │
└─────────────────────────────────────────────────────────────┘
```

## Features

**AI Brain (adapted from Zork-Opus)**
- Game mode state machine: explore → battle → dialog → menu
- Mode-specific agents with tailored prompts and heuristics
- Battle agent with Gen 1 type chart, STAB awareness, heuristic fast-path
- Dual-cache memory system (persistent cross-episode + ephemeral)
- Strategic objective generation with gym progression planning
- Map graph with BFS pathfinding and exploration frontier tracking
- Stuck detection, oscillation warnings, auto-save

**Game Interface**
- Talks to PokemonOpenClaude via REST API
- Full Gen 1 RAM state: party, bag, battle, dialog, map, badges, Pokedex
- Frame-accurate button input (respects Game Boy timing)
- Screenshot capture for viewer and vision analysis

**LLM Integration**
- Configurable per-role models (agent, battle, strategist, memory)
- Anthropic, OpenRouter, and local LLM support
- Circuit breaker with exponential backoff retry
- Token and cost tracking

**Viewer**
- React + TypeScript + Tailwind v4
- Live game screen with pixel-perfect rendering
- Streaming AI reasoning panel
- Team display with Pokemon sprites and HP bars
- Badge timeline, objectives, inventory, milestones
- WebSocket with auto-reconnection

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for viewer)
- A Pokemon Blue ROM (`Pokemon - Blue Version (USA, Europe).gb`)
- An Anthropic API key (or any OpenAI-compatible endpoint)

### 1. Start the game server

```bash
# Clone and install PokemonOpenClaude
cd /path/to/PokemonOpenClaude/pokemon-agent
pip install -e ".[all]"

# Start with your ROM
pokemon-agent serve --rom "path/to/Pokemon - Blue Version (USA, Europe).gb" --port 8765
```

### 2. Configure Pokemon-Opus

```bash
cd Pokemon-Opus

# Create .env from example
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Install Python dependencies
pip install -e .
```

### 3. Start the agent

```bash
python -m pokemon_opus.main
```

### 4. Start the viewer (optional)

```bash
cd viewer
npm install
npm run dev
# Open http://localhost:5173
```

## Configuration

All settings live in `pyproject.toml` under `[tool.pokemon-opus]`:

```toml
[tool.pokemon-opus.game]
server_url = "http://localhost:8765"
max_turns_per_episode = 10000
save_interval = 50

[tool.pokemon-opus.llm]
client_base_url = "https://api.anthropic.com/v1"
agent_model = "claude-opus-4-20250514"
battle_model = "claude-opus-4-20250514"       # Can use a faster/cheaper model
strategist_model = "claude-opus-4-20250514"
memory_model = "claude-opus-4-20250514"

# Use local models for fast tactical decisions:
# battle_base_url = "http://192.168.4.245:8082/v1"
# battle_model = "qwen3.5-27b"

[tool.pokemon-opus.llm.battle_sampling]
temperature = 0.3
max_tokens = 2048
```

### Per-role model configuration

| Role | Purpose | Recommended |
|------|---------|-------------|
| `agent` | Exploration decisions | Opus (needs reasoning) |
| `battle` | Battle tactics | Opus or fast local model |
| `strategist` | Long-term planning, objectives | Opus |
| `memory` | Memory synthesis | Opus or Sonnet |

Each role can have its own `base_url`, `model`, and `sampling` parameters.

## Project Structure

```
Pokemon-Opus/
├── pokemon_opus/
│   ├── main.py              # Entry point
│   ├── config.py            # Pydantic config from TOML + env
│   ├── game_client.py       # HTTP client for PokemonOpenClaude
│   ├── orchestrator.py      # Game mode state machine + turn loop
│   ├── state.py             # GameState, Pokemon, Objective models
│   ├── agents/
│   │   ├── explore.py       # Overworld navigation
│   │   ├── battle.py        # Battle decisions (type-aware)
│   │   ├── menu.py          # Dialog/menu handling (mechanical)
│   │   └── strategist.py    # Long-term planning + objectives
│   ├── memory/
│   │   └── manager.py       # Dual-cache memory system
│   ├── objectives/
│   │   └── manager.py       # Objective lifecycle tracking
│   ├── map/
│   │   └── graph.py         # Room connectivity + BFS pathfinding
│   ├── context/
│   │   └── builder.py       # Per-mode prompt assembly
│   ├── llm/
│   │   └── client.py        # Multi-provider LLM client
│   ├── streaming/
│   │   └── server.py        # FastAPI + WebSocket for viewer
│   └── data/
│       ├── type_chart.py    # Gen 1 type effectiveness (all quirks)
│       └── map_data.py      # Gym order, HMs, progression milestones
├── viewer/                  # React + TypeScript frontend
│   └── src/
│       ├── components/      # GameScreen, TeamPanel, MapView, etc.
│       ├── hooks/           # useWebSocket
│       └── lib/             # Types, sprite URLs, colors
├── pyproject.toml           # Config + dependencies
└── .env.example             # API keys template
```

## How It Works

### Turn Loop (11 phases)

1. **Read state** — GET /state from emulator RAM
2. **Detect mode** — battle? dialog? menu? → explore
3. **Route to agent** — mode-specific decision-making
4. **Execute actions** — POST /action (button presses)
5. **Read post-state** — capture what changed
6. **Compute deltas** — location, badges, party, items, battles
7. **Record history** — action log with reasoning
8. **Track milestones** — badges, catches, level-ups
9. **Memory synthesis** — create/update location memories
10. **Map update** — record visits and connections
11. **Stream to viewer** — broadcast state + screenshot via WebSocket

### Memory Categories

| Category | Persistence | Example |
|----------|-------------|---------|
| ROUTE | Core | "Route 3 connects Pewter City to Mt. Moon" |
| TRAINER | Permanent | "Bug Catcher on Route 3 has Caterpie Lv9" |
| ITEM | Permanent | "Found Potion at Viridian Forest (12, 8)" |
| POKEMON | Permanent | "Pikachu spawns in Viridian Forest" |
| BATTLE | Permanent | "Brock's Onix is Lv14, Water Gun was super effective" |
| STRATEGY | Permanent | "Need Lv16 before Misty" |
| LANDMARK | Core | "Pokemon Center in Cerulean City at map ID 3" |

### Gen 1 Battle Intelligence

- Full type effectiveness chart with Gen 1 bugs (Ghost doesn't hit Psychic, Psychic is OP)
- STAB (Same Type Attack Bonus) awareness
- Move type guessing from name keywords
- Heuristic fast-path for simple wild encounters (skip LLM)
- LLM fallback for complex trainer battles and switching decisions

## Credits

- **PokemonOpenClaude** by [NousResearch](https://github.com/NousResearch) — emulator + RAM reading
- **Zork-Opus** — AI agent architecture patterns (memory, objectives, orchestration)
- **Archon** by [Cole Medin](https://github.com/coleam00) — infrastructure patterns
- Pokemon sprites from [PokeAPI](https://pokeapi.co/)
- Built with [Claude Opus](https://anthropic.com)
