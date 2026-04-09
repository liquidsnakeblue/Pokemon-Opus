"""
Pokemon Blue map data — connections, landmarks, and progression info.
Used by the map graph and strategist for navigation planning.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class MapLocation:
    """A known game location with metadata."""
    id: int
    name: str
    category: str  # city, route, dungeon, building, special
    has_pokecenter: bool = False
    has_pokemart: bool = False
    has_gym: bool = False
    gym_leader: Optional[str] = None
    gym_badge: Optional[str] = None
    gym_type: Optional[str] = None
    required_hm: Optional[str] = None  # HM needed to access
    wild_pokemon_levels: Optional[Tuple[int, int]] = None  # (min, max) level range


# Key cities and routes with their connections
# This is seeded knowledge — the agent discovers actual connections through play
KNOWN_LOCATIONS: Dict[int, MapLocation] = {
    0: MapLocation(0, "Pallet Town", "city"),
    1: MapLocation(1, "Viridian City", "city", has_pokecenter=True, has_pokemart=True),
    2: MapLocation(2, "Pewter City", "city", has_pokecenter=True, has_pokemart=True,
                   has_gym=True, gym_leader="Brock", gym_badge="Boulder", gym_type="Rock"),
    3: MapLocation(3, "Cerulean City", "city", has_pokecenter=True, has_pokemart=True,
                   has_gym=True, gym_leader="Misty", gym_badge="Cascade", gym_type="Water"),
    4: MapLocation(4, "Lavender Town", "city", has_pokecenter=True, has_pokemart=True),
    5: MapLocation(5, "Vermilion City", "city", has_pokecenter=True, has_pokemart=True,
                   has_gym=True, gym_leader="Lt. Surge", gym_badge="Thunder", gym_type="Electric",
                   required_hm="Cut"),
    6: MapLocation(6, "Celadon City", "city", has_pokecenter=True, has_pokemart=True,
                   has_gym=True, gym_leader="Erika", gym_badge="Rainbow", gym_type="Grass"),
    7: MapLocation(7, "Fuchsia City", "city", has_pokecenter=True, has_pokemart=True,
                   has_gym=True, gym_leader="Koga", gym_badge="Soul", gym_type="Poison"),
    8: MapLocation(8, "Cinnabar Island", "city", has_pokecenter=True, has_pokemart=True,
                   has_gym=True, gym_leader="Blaine", gym_badge="Volcano", gym_type="Fire"),
    9: MapLocation(9, "Indigo Plateau", "city", has_pokecenter=True),
    10: MapLocation(10, "Saffron City", "city", has_pokecenter=True, has_pokemart=True,
                    has_gym=True, gym_leader="Sabrina", gym_badge="Marsh", gym_type="Psychic"),
}

# Route connections (bidirectional by default)
# Format: (map_id_a, map_id_b, route_name_or_id)
KNOWN_CONNECTIONS: List[Tuple[int, int, str]] = [
    (0, 12, "Route 1"),      # Pallet Town — Route 1
    (12, 1, "Route 1"),      # Route 1 — Viridian City
    (1, 13, "Route 2"),      # Viridian City — Route 2
    (13, 2, "Route 2"),      # Route 2 — Pewter City (through Viridian Forest)
    (2, 14, "Route 3"),      # Pewter City — Route 3
    (3, 15, "Route 4"),      # Route 4 — Cerulean City
    (3, 16, "Route 5"),      # Cerulean City — Route 5
    (3, 17, "Route 24"),     # Cerulean City — Route 24 (Nugget Bridge)
    (5, 18, "Route 6"),      # Vermilion City — Route 6
    (6, 19, "Route 7"),      # Celadon City — Route 7
    (4, 20, "Route 8"),      # Lavender Town — Route 8
    (6, 21, "Route 16"),     # Celadon City — Route 16 (Cycling Road north)
    (7, 22, "Route 18"),     # Fuchsia City — Route 18 (Cycling Road south)
]

# Gym progression order (recommended)
GYM_ORDER = [
    {"badge": "Boulder", "leader": "Brock", "city": "Pewter City", "type": "Rock",
     "recommended_level": 12, "weakness": ["Water", "Grass"]},
    {"badge": "Cascade", "leader": "Misty", "city": "Cerulean City", "type": "Water",
     "recommended_level": 21, "weakness": ["Grass", "Electric"]},
    {"badge": "Thunder", "leader": "Lt. Surge", "city": "Vermilion City", "type": "Electric",
     "recommended_level": 24, "weakness": ["Ground"]},
    {"badge": "Rainbow", "leader": "Erika", "city": "Celadon City", "type": "Grass",
     "recommended_level": 29, "weakness": ["Fire", "Ice", "Flying"]},
    {"badge": "Soul", "leader": "Koga", "city": "Fuchsia City", "type": "Poison",
     "recommended_level": 43, "weakness": ["Ground", "Psychic"]},
    {"badge": "Marsh", "leader": "Sabrina", "city": "Saffron City", "type": "Psychic",
     "recommended_level": 43, "weakness": ["Bug"]},  # Gen 1: Psychic is OP, Bug is weak
    {"badge": "Volcano", "leader": "Blaine", "city": "Cinnabar Island", "type": "Fire",
     "recommended_level": 47, "weakness": ["Water", "Ground"]},
    {"badge": "Earth", "leader": "Giovanni", "city": "Viridian City", "type": "Ground",
     "recommended_level": 50, "weakness": ["Water", "Grass", "Ice"]},
]

# HM locations and requirements
HM_DATA = {
    "Cut": {"hm_number": 1, "location": "SS Anne (Vermilion City)", "badge_required": "Cascade"},
    "Fly": {"hm_number": 2, "location": "Route 16 (west of Celadon)", "badge_required": "Thunder"},
    "Surf": {"hm_number": 3, "location": "Safari Zone (Fuchsia City)", "badge_required": "Soul"},
    "Strength": {"hm_number": 4, "location": "Safari Zone (Fuchsia City)", "badge_required": "Rainbow"},
    "Flash": {"hm_number": 5, "location": "Route 2 (gate building)", "badge_required": "Boulder"},
}

# Key progression milestones
PROGRESSION_MILESTONES = [
    "Choose starter Pokemon",
    "Deliver Oak's Parcel",
    "Receive Pokedex",
    "Boulder Badge (Brock)",
    "Cascade Badge (Misty)",
    "Get HM01 Cut (SS Anne)",
    "Thunder Badge (Lt. Surge)",
    "Get Poke Flute (Pokemon Tower)",
    "Rainbow Badge (Erika)",
    "Get Silph Scope (Rocket Hideout)",
    "Soul Badge (Koga)",
    "Get HM03 Surf (Safari Zone)",
    "Marsh Badge (Sabrina)",
    "Get Secret Key (Pokemon Mansion)",
    "Volcano Badge (Blaine)",
    "Earth Badge (Giovanni)",
    "Victory Road",
    "Elite Four",
    "Champion",
]

# Starter Pokemon info
STARTERS = {
    "Bulbasaur": {"type": ["Grass", "Poison"], "advantage": "Brock, Misty",
                  "disadvantage": "Lt. Surge is neutral"},
    "Charmander": {"type": ["Fire"], "advantage": "Erika",
                   "disadvantage": "Brock, Misty are hard early"},
    "Squirtle": {"type": ["Water"], "advantage": "Brock, Blaine, Giovanni",
                 "disadvantage": "Misty, Erika are harder"},
}
