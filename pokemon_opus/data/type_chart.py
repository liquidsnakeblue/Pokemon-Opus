"""
Gen 1 Type Effectiveness Chart.
Includes all Gen 1 quirks: no Steel/Dark/Fairy, Ghost doesn't hit Psychic (bugged),
Psychic is immune to Ghost, etc.
"""

from typing import Dict, List, Tuple

# All Gen 1 types
TYPES = [
    "Normal", "Fighting", "Flying", "Poison", "Ground",
    "Rock", "Bug", "Ghost", "Fire", "Water",
    "Grass", "Electric", "Ice", "Psychic", "Dragon",
]

# Type effectiveness: (attacker, defender) -> multiplier
# Only store non-1.0 matchups for efficiency
_SUPER_EFFECTIVE: List[Tuple[str, str]] = [
    # Fighting
    ("Fighting", "Normal"), ("Fighting", "Rock"), ("Fighting", "Ice"),
    # Flying
    ("Flying", "Fighting"), ("Flying", "Bug"), ("Flying", "Grass"),
    # Poison
    ("Poison", "Grass"), ("Poison", "Bug"),
    # Ground
    ("Ground", "Fire"), ("Ground", "Electric"), ("Ground", "Poison"), ("Ground", "Rock"),
    # Rock
    ("Rock", "Fire"), ("Rock", "Ice"), ("Rock", "Flying"), ("Rock", "Bug"),
    # Bug — Gen 1: Bug is super effective vs Poison (changed in Gen 2)
    ("Bug", "Grass"), ("Bug", "Psychic"), ("Bug", "Poison"),
    # Ghost — Gen 1 BUG: Ghost moves do 0x to Psychic (should be 2x)
    ("Ghost", "Ghost"),
    # Fire
    ("Fire", "Grass"), ("Fire", "Ice"), ("Fire", "Bug"),
    # Water
    ("Water", "Fire"), ("Water", "Ground"), ("Water", "Rock"),
    # Grass
    ("Grass", "Water"), ("Grass", "Ground"), ("Grass", "Rock"),
    # Electric
    ("Electric", "Water"), ("Electric", "Flying"),
    # Ice
    ("Ice", "Grass"), ("Ice", "Ground"), ("Ice", "Flying"), ("Ice", "Dragon"),
    # Psychic
    ("Psychic", "Fighting"), ("Psychic", "Poison"),
    # Dragon
    ("Dragon", "Dragon"),
]

_NOT_VERY_EFFECTIVE: List[Tuple[str, str]] = [
    # Normal
    ("Normal", "Rock"),
    # Fighting
    ("Fighting", "Flying"), ("Fighting", "Poison"), ("Fighting", "Bug"),
    ("Fighting", "Psychic"),
    # Flying
    ("Flying", "Rock"), ("Flying", "Electric"),
    # Poison
    ("Poison", "Poison"), ("Poison", "Ground"), ("Poison", "Rock"), ("Poison", "Ghost"),
    # Ground
    ("Ground", "Grass"), ("Ground", "Bug"),
    # Rock
    ("Rock", "Fighting"), ("Rock", "Ground"),
    # Bug
    ("Bug", "Fighting"), ("Bug", "Flying"), ("Bug", "Ghost"), ("Bug", "Fire"),
    # Ghost
    ("Ghost", "Normal"),  # Listed in immune below, but including for clarity
    # Fire
    ("Fire", "Fire"), ("Fire", "Water"), ("Fire", "Rock"), ("Fire", "Dragon"),
    # Water
    ("Water", "Water"), ("Water", "Grass"), ("Water", "Dragon"),
    # Grass
    ("Grass", "Fire"), ("Grass", "Grass"), ("Grass", "Poison"),
    ("Grass", "Flying"), ("Grass", "Bug"), ("Grass", "Dragon"),
    # Electric
    ("Electric", "Electric"), ("Electric", "Grass"), ("Electric", "Dragon"),
    # Ice
    ("Ice", "Fire"), ("Ice", "Water"), ("Ice", "Ice"),
    # Psychic — no resistances in Gen 1 (Psychic resists Fighting, but that's defender side)
    # Dragon — nothing resists Dragon except... well, no Steel in Gen 1
]

_IMMUNE: List[Tuple[str, str]] = [
    ("Normal", "Ghost"),
    ("Fighting", "Ghost"),
    ("Ghost", "Normal"),
    # Gen 1 BUG: Ghost is immune to Psychic (supposed to be super effective)
    ("Ghost", "Psychic"),
    ("Ground", "Flying"),
    ("Electric", "Ground"),
]

# Build lookup table
_CHART: Dict[Tuple[str, str], float] = {}
for atk, dfn in _SUPER_EFFECTIVE:
    _CHART[(atk, dfn)] = 2.0
for atk, dfn in _NOT_VERY_EFFECTIVE:
    _CHART[(atk, dfn)] = 0.5
for atk, dfn in _IMMUNE:
    _CHART[(atk, dfn)] = 0.0


def effectiveness(attack_type: str, defend_type: str) -> float:
    """Get type effectiveness multiplier (Gen 1 rules).

    Returns: 2.0 (super effective), 1.0 (normal), 0.5 (not very), 0.0 (immune)
    """
    return _CHART.get((attack_type, defend_type), 1.0)


def matchup(attack_type: str, defender_types: List[str]) -> float:
    """Calculate total effectiveness against a Pokemon with 1-2 types.

    For dual types, multiply the individual effectiveness values.
    Example: Electric vs Water/Flying = 2.0 * 2.0 = 4.0
    """
    result = 1.0
    for dtype in defender_types:
        result *= effectiveness(attack_type, dtype)
    return result


def best_type_against(defender_types: List[str]) -> List[Tuple[str, float]]:
    """Find the most effective attack types against a defender.

    Returns: List of (type, multiplier) sorted by effectiveness descending.
    Only includes types with multiplier > 1.0.
    """
    results = []
    for attack_type in TYPES:
        mult = matchup(attack_type, defender_types)
        if mult > 1.0:
            results.append((attack_type, mult))
    return sorted(results, key=lambda x: x[1], reverse=True)


def weak_types_against(defender_types: List[str]) -> List[Tuple[str, float]]:
    """Find types that are ineffective against a defender.

    Returns: List of (type, multiplier) sorted by effectiveness ascending.
    Only includes types with multiplier < 1.0.
    """
    results = []
    for attack_type in TYPES:
        mult = matchup(attack_type, defender_types)
        if mult < 1.0:
            results.append((attack_type, mult))
    return sorted(results, key=lambda x: x[1])


def describe_matchup(attack_type: str, defender_types: List[str]) -> str:
    """Human-readable description of a type matchup."""
    mult = matchup(attack_type, defender_types)
    def_str = "/".join(defender_types)
    if mult == 0.0:
        return f"{attack_type} has no effect on {def_str}"
    elif mult >= 4.0:
        return f"{attack_type} is 4x effective vs {def_str}!"
    elif mult >= 2.0:
        return f"{attack_type} is super effective vs {def_str}"
    elif mult <= 0.25:
        return f"{attack_type} is 4x resisted by {def_str}"
    elif mult <= 0.5:
        return f"{attack_type} is not very effective vs {def_str}"
    else:
        return f"{attack_type} is neutral vs {def_str}"
