"""Test that GameState syncs correctly from raw emulator data."""

import pytest
from pokemon_opus.state import GameState, GameMode, Pokemon, Move
from pokemon_opus.orchestrator import Orchestrator
from tests.conftest import make_test_config
from pokemon_opus.game_client import GameClient
from pokemon_opus.streaming.server import StreamServer
from pokemon_opus.llm.client import LLMClient


@pytest.mark.asyncio
async def test_sync_position(game_client):
    """Position syncs as a (y, x) tuple from the emulator's {y, x} dict."""
    config = make_test_config()
    stream = StreamServer(port=3098, enable_cors=False)
    orch = Orchestrator(config=config, game_client=game_client, stream=stream)

    raw = await game_client.get_state()
    orch._sync_state_from_raw(raw)

    pos = raw["player"]["position"]
    assert orch.gs.position == (pos["y"], pos["x"])


@pytest.mark.asyncio
async def test_sync_map_info(game_client):
    """Map ID and name sync from emulator state."""
    config = make_test_config()
    stream = StreamServer(port=3098, enable_cors=False)
    orch = Orchestrator(config=config, game_client=game_client, stream=stream)

    raw = await game_client.get_state()
    orch._sync_state_from_raw(raw)

    assert orch.gs.map_id == raw["map"]["map_id"]
    assert orch.gs.map_name == raw["map"]["map_name"]


@pytest.mark.asyncio
async def test_sync_badges(game_client):
    """Badges sync as a list."""
    config = make_test_config()
    stream = StreamServer(port=3098, enable_cors=False)
    orch = Orchestrator(config=config, game_client=game_client, stream=stream)

    raw = await game_client.get_state()
    orch._sync_state_from_raw(raw)

    assert isinstance(orch.gs.badges, list)
    assert orch.gs.badge_count == len(raw["player"].get("badges", []))


@pytest.mark.asyncio
async def test_sync_party(game_client):
    """Party syncs Pokemon objects or empty list."""
    config = make_test_config()
    stream = StreamServer(port=3098, enable_cors=False)
    orch = Orchestrator(config=config, game_client=game_client, stream=stream)

    raw = await game_client.get_state()
    orch._sync_state_from_raw(raw)

    assert isinstance(orch.gs.party, list)
    assert len(orch.gs.party) == len(raw.get("party", []))
    for p in orch.gs.party:
        assert isinstance(p, Pokemon)


@pytest.mark.asyncio
async def test_sync_dialog_flag(game_client):
    """Dialog active flag syncs from emulator."""
    config = make_test_config()
    stream = StreamServer(port=3098, enable_cors=False)
    orch = Orchestrator(config=config, game_client=game_client, stream=stream)

    raw = await game_client.get_state()
    orch._sync_state_from_raw(raw)

    assert isinstance(orch.gs.dialog_active, bool)


@pytest.mark.asyncio
async def test_sync_flags(game_client):
    """Game flags (pokedex, etc.) sync."""
    config = make_test_config()
    stream = StreamServer(port=3098, enable_cors=False)
    orch = Orchestrator(config=config, game_client=game_client, stream=stream)

    raw = await game_client.get_state()
    orch._sync_state_from_raw(raw)

    assert isinstance(orch.gs.has_pokedex, bool)
    assert isinstance(orch.gs.pokedex_owned, int)


def test_mode_detection_no_dialog_no_battle():
    """Default mode is EXPLORE when no dialog or battle."""
    config = make_test_config()
    stream = StreamServer(port=3098, enable_cors=False)
    orch = Orchestrator(config=config, game_client=None, stream=stream)

    raw = {"dialog": {"active": False}, "battle": {"in_battle": False}}
    assert orch._detect_mode(raw) == GameMode.EXPLORE


def test_mode_detection_dialog():
    """Dialog mode when dialog.active is True."""
    config = make_test_config()
    stream = StreamServer(port=3098, enable_cors=False)
    orch = Orchestrator(config=config, game_client=None, stream=stream)

    raw = {"dialog": {"active": True}, "battle": {"in_battle": False}}
    assert orch._detect_mode(raw) == GameMode.DIALOG


def test_mode_detection_battle():
    """Battle mode when battle.in_battle is True."""
    config = make_test_config()
    stream = StreamServer(port=3098, enable_cors=False)
    orch = Orchestrator(config=config, game_client=None, stream=stream)

    raw = {"dialog": {"active": False}, "battle": {"in_battle": True}}
    assert orch._detect_mode(raw) == GameMode.BATTLE


def test_serialize_round_trips():
    """GameState.serialize() produces valid JSON-serializable dict."""
    gs = GameState()
    gs.player_name = "RED"
    gs.map_name = "Pallet Town"
    gs.position = (5, 3)
    gs.turn_count = 42

    data = gs.serialize()
    assert data["turn"] == 42
    assert data["player"]["name"] == "RED"
    assert data["player"]["map_name"] == "Pallet Town"
    assert data["player"]["position"] == [5, 3]
