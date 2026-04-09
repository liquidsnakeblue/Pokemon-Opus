"""
Shared fixtures for Pokemon-Opus integration tests.

Uses Sonnet via OpenAI-compatible proxy for fast, reliable testing.
Requires the PokemonOpenClaude game server running on localhost:8765.
"""

import asyncio
import os
import pytest
from pathlib import Path

# Ensure we can import the project
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from pokemon_opus.config import Config
from pokemon_opus.game_client import GameClient
from pokemon_opus.llm.client import LLMClient
from pokemon_opus.state import GameState
from pokemon_opus.map.graph import MapGraph
from pokemon_opus.memory.manager import MemoryManager
from pokemon_opus.objectives.manager import ObjectiveManager
from pokemon_opus.context.builder import ContextBuilder
from pokemon_opus.orchestrator import Orchestrator
from pokemon_opus.streaming.server import StreamServer

# ── Test LLM config (Sonnet via proxy) ─────────────────────────────

TEST_LLM_BASE_URL = "http://192.168.4.245:8317/v1"
TEST_LLM_API_KEY = "sk-zmj9x0jPEvtM3EXIHdam29UMDlPdzCHVDCxTvRHeLgre5"
TEST_LLM_MODEL = "claude-sonnet-4-5-20250929"
TEST_GAME_URL = "http://localhost:8765"


def make_test_config() -> Config:
    """Build a Config pointed at Sonnet for testing."""
    return Config(
        game_server_url=TEST_GAME_URL,
        client_base_url=TEST_LLM_BASE_URL,
        client_api_key=TEST_LLM_API_KEY,
        agent_model=TEST_LLM_MODEL,
        strategist_model=TEST_LLM_MODEL,
        memory_model=TEST_LLM_MODEL,
        battle_model=TEST_LLM_MODEL,
        max_turns_per_episode=100,
        turn_delay_seconds=0.0,
        save_interval=999,
        agent_sampling={"temperature": 0.3, "max_tokens": 2048},
        strategist_sampling={"temperature": 0.3, "max_tokens": 2048},
        battle_sampling={"temperature": 0.2, "max_tokens": 1024},
        memory_sampling={"temperature": 0.3, "max_tokens": 1024},
        streaming_port=3099,  # Different port to avoid conflict with live viewer
    )


@pytest.fixture
def config():
    return make_test_config()


@pytest.fixture
async def game_client(config):
    client = GameClient(base_url=config.game_server_url)
    healthy = await client.health()
    if not healthy:
        pytest.skip("Game server not running at localhost:8765")
    yield client
    await client.close()


@pytest.fixture
def llm_client(config):
    return LLMClient(config)


@pytest.fixture
def game_state():
    return GameState()


@pytest.fixture
def map_graph():
    return MapGraph()


@pytest.fixture
async def full_stack(config):
    """Full orchestrator stack for end-to-end tests."""
    game = GameClient(base_url=config.game_server_url)
    healthy = await game.health()
    if not healthy:
        pytest.skip("Game server not running at localhost:8765")

    llm = LLMClient(config)
    stream = StreamServer(port=config.streaming_port, enable_cors=False)
    memory = MemoryManager(config, llm_client=llm, memory_file="/tmp/test_memories.md")
    objectives = ObjectiveManager(config, llm_client=llm)
    map_graph = MapGraph()
    context = ContextBuilder(memory_manager=memory, map_manager=map_graph)

    orchestrator = Orchestrator(
        config=config,
        game_client=game,
        stream=stream,
        llm_client=llm,
        memory_manager=memory,
        objective_manager=objectives,
        map_manager=map_graph,
        context_builder=context,
    )

    yield {
        "orchestrator": orchestrator,
        "game": game,
        "llm": llm,
        "stream": stream,
        "gs": orchestrator.gs,
        "map": map_graph,
        "config": config,
    }

    await game.close()
