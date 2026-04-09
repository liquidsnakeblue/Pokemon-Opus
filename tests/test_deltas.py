"""Test state delta computation — badges, catches, level ups, items, position changes."""

from pokemon_opus.orchestrator import Orchestrator
from pokemon_opus.streaming.server import StreamServer
from tests.conftest import make_test_config


def _make_orch():
    config = make_test_config()
    stream = StreamServer(port=3098, enable_cors=False)
    return Orchestrator(config=config, game_client=None, stream=stream)


def _base_snapshot(**overrides):
    base = {
        "map_id": 1,
        "map_name": "Pallet Town",
        "position": (5, 3),
        "badges": [],
        "badge_count": 0,
        "money": 3000,
        "party": [],
        "bag": [],
        "in_battle": False,
        "pokedex_owned": 0,
    }
    base.update(overrides)
    return base


def test_no_change():
    """No deltas when nothing changed."""
    orch = _make_orch()
    pre = _base_snapshot()
    post = _base_snapshot()
    delta = orch._compute_deltas(pre, post)
    assert not delta.is_meaningful()


def test_location_change():
    """Detects map transition."""
    orch = _make_orch()
    pre = _base_snapshot(map_id=1, map_name="Pallet Town")
    post = _base_snapshot(map_id=2, map_name="Route 1")
    delta = orch._compute_deltas(pre, post)
    assert delta.location_changed is True
    assert delta.new_map_name == "Route 1"
    assert delta.is_meaningful()


def test_badge_gained():
    """Detects a new badge."""
    orch = _make_orch()
    pre = _base_snapshot(badges=[])
    post = _base_snapshot(badges=["Boulder"])
    delta = orch._compute_deltas(pre, post)
    assert delta.badge_gained == "Boulder"
    assert delta.is_meaningful()


def test_pokemon_caught():
    """Detects a new Pokemon in the party."""
    orch = _make_orch()
    pre = _base_snapshot(party=[{"species": "Squirtle", "hp": 20}])
    post = _base_snapshot(party=[
        {"species": "Squirtle", "hp": 20},
        {"species": "Pidgey", "hp": 15},
    ])
    delta = orch._compute_deltas(pre, post)
    assert delta.pokemon_caught == "Pidgey"
    assert delta.is_meaningful()


def test_level_up():
    """Detects a level up."""
    orch = _make_orch()
    pre = _base_snapshot(party=[{"species": "Squirtle", "level": 5, "hp": 20}])
    post = _base_snapshot(party=[{"species": "Squirtle", "level": 6, "hp": 22}])
    delta = orch._compute_deltas(pre, post)
    assert delta.pokemon_leveled == "Squirtle"
    assert delta.new_level == 6


def test_money_change():
    """Detects money changes."""
    orch = _make_orch()
    pre = _base_snapshot(money=3000)
    post = _base_snapshot(money=2700)
    delta = orch._compute_deltas(pre, post)
    assert delta.money_delta == -300


def test_battle_started():
    """Detects battle start."""
    orch = _make_orch()
    pre = _base_snapshot(in_battle=False)
    post = _base_snapshot(in_battle=True)
    delta = orch._compute_deltas(pre, post)
    assert delta.battle_started is True


def test_battle_ended():
    """Detects battle end."""
    orch = _make_orch()
    pre = _base_snapshot(in_battle=True)
    post = _base_snapshot(in_battle=False)
    delta = orch._compute_deltas(pre, post)
    assert delta.battle_ended is True


def test_item_gained():
    """Detects new item in bag."""
    orch = _make_orch()
    pre = _base_snapshot(bag=[])
    post = _base_snapshot(bag=[{"item": "Potion", "quantity": 1}])
    delta = orch._compute_deltas(pre, post)
    assert delta.item_gained == "Potion"
