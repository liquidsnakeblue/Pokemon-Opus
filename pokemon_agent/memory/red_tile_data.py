"""
Tileset classification tables for Pokemon Red/Blue.

All data in this file is derived from the pokered disassembly
(https://github.com/pret/pokered), specifically:

  constants/tileset_constants.asm     — tileset IDs
  data/tilesets/door_tile_ids.asm     — door tiles per tileset
  data/tilesets/warp_tile_ids.asm     — warp tiles per tileset
                                        (stairs, ladders, holes, etc.)
  data/tilesets/ledge_tiles.asm       — ledge tile IDs (universal)
  data/tilesets/water_tilesets.asm    — which tilesets contain water
  data/tilesets/bookshelf_tile_ids.asm — interactive bookshelf tiles
  home/overworld.asm                  — WATER_TILE constant ($14)

The runtime tile reader in red.py uses these tables alongside three
live RAM sources to build a fully classified map grid:

  - wTilesetCollisionPtr (D530): walkable 8×8 tile IDs per tileset
  - wGrassTile (D535):            the grass tile for encounters
  - wWarpEntries (D3AF):          exact (Y, X) coords of every warp
                                   on the current map, regardless of
                                   which tile the game happens to draw
  - wSignCoords (D4B1):           exact (Y, X) coords of every sign

Classification priority (highest wins):
  1. Player position      → P
  2. Sprites (NPC/I/O)    → N / I / O
  3. Warp positions       → D  (from RAM — authoritative)
  4. Sign positions       → S  (from RAM — authoritative)
  5. Ledge tile IDs       → L
  6. Water tile (+tileset)→ W
  7. Grass tile           → ~
  8. Door tile IDs        → D  (from static table — fallback)
  9. Bookshelf tile IDs   → O  (interactive furniture)
  10. Walkable collision  → .
  11. Everything else     → #
"""

from __future__ import annotations

from typing import Dict, Set

# ── Tileset IDs ────────────────────────────────────────────────────
# From pokered/constants/tileset_constants.asm

TILESET_OVERWORLD    = 0
TILESET_REDS_HOUSE_1 = 1
TILESET_MART         = 2
TILESET_FOREST       = 3
TILESET_REDS_HOUSE_2 = 4
TILESET_DOJO         = 5
TILESET_POKECENTER   = 6
TILESET_GYM          = 7
TILESET_HOUSE        = 8
TILESET_FOREST_GATE  = 9
TILESET_MUSEUM       = 10
TILESET_UNDERGROUND  = 11
TILESET_GATE         = 12
TILESET_SHIP         = 13
TILESET_SHIP_PORT    = 14
TILESET_CEMETERY     = 15
TILESET_INTERIOR     = 16
TILESET_CAVERN       = 17
TILESET_LOBBY        = 18
TILESET_MANSION      = 19
TILESET_LAB          = 20
TILESET_CLUB         = 21
TILESET_FACILITY     = 22
TILESET_PLATEAU      = 23

TILESET_NAMES: Dict[int, str] = {
    0: "Overworld", 1: "Red's House 1F", 2: "Mart", 3: "Forest",
    4: "Red's House 2F", 5: "Dojo", 6: "Pokecenter", 7: "Gym",
    8: "House", 9: "Forest Gate", 10: "Museum", 11: "Underground",
    12: "Gate", 13: "Ship", 14: "Ship Port", 15: "Cemetery",
    16: "Interior", 17: "Cavern", 18: "Lobby", 19: "Mansion",
    20: "Lab", 21: "Club", 22: "Facility", 23: "Plateau",
}

# ── Warp tile IDs per tileset ──────────────────────────────────────
# From data/tilesets/warp_tile_ids.asm
#
# These are the 8×8 tile IDs that visually represent warps in each
# tileset: doors, staircases, ladders, hole covers, etc. The game
# engine uses these to find warp candidates when rendering/walking,
# but authoritative warp positions live in the map header's warp
# table (wWarpEntries) — we prefer those.

WARP_TILES: Dict[int, Set[int]] = {
    TILESET_OVERWORLD:    {0x1B, 0x58},
    TILESET_REDS_HOUSE_1: {0x1A, 0x1C},
    TILESET_MART:         {0x5E},
    TILESET_FOREST:       {0x5A, 0x5C, 0x3A},
    TILESET_REDS_HOUSE_2: {0x1A, 0x1C},
    TILESET_DOJO:         {0x4A},
    TILESET_POKECENTER:   {0x5E},
    TILESET_GYM:          {0x4A},
    TILESET_HOUSE:        {0x54, 0x5C, 0x32},
    TILESET_FOREST_GATE:  {0x3B},
    TILESET_MUSEUM:       {0x3B},
    TILESET_UNDERGROUND:  {0x13},
    TILESET_GATE:         {0x3B},
    TILESET_SHIP:         {0x37, 0x39, 0x1E, 0x4A},
    # SHIP_PORT has no warp tiles (entrances handled at the map level)
    TILESET_CEMETERY:     {0x1B, 0x13},
    TILESET_INTERIOR:     {0x15, 0x55, 0x04},
    TILESET_CAVERN:       {0x18, 0x1A, 0x22},
    TILESET_LOBBY:        {0x1A, 0x1C, 0x38},
    TILESET_MANSION:      {0x1A, 0x1C, 0x53},
    TILESET_LAB:          {0x34},
    # CLUB has no warp tiles
    TILESET_FACILITY:     {0x43, 0x58, 0x20, 0x13},
    TILESET_PLATEAU:      {0x1B, 0x3B},
}

# ── Door tile IDs per tileset ──────────────────────────────────────
# From data/tilesets/door_tile_ids.asm
#
# Narrower than WARP_TILES — just the visual doors, not stairs/holes.
# Kept separate so we can distinguish them if needed later.

DOOR_TILES: Dict[int, Set[int]] = {
    TILESET_OVERWORLD:   {0x1B, 0x58},
    TILESET_FOREST:      {0x3A},
    TILESET_MART:        {0x5E},
    TILESET_HOUSE:       {0x54},
    TILESET_FOREST_GATE: {0x3B},
    TILESET_MUSEUM:      {0x3B},
    TILESET_GATE:        {0x3B},
    TILESET_SHIP:        {0x1E},
    TILESET_LOBBY:       {0x1C, 0x38, 0x1A},
    TILESET_MANSION:     {0x1A, 0x1C, 0x53},
    TILESET_LAB:         {0x34},
    TILESET_FACILITY:    {0x43, 0x58, 0x1B},
    TILESET_PLATEAU:     {0x3B, 0x1B},
}

# ── Ledge tile IDs (universal) ─────────────────────────────────────
# From data/tilesets/ledge_tiles.asm — the third column.
# Ledges are one-way down — the player can jump off but can't climb up.

LEDGE_TILES: Set[int] = {0x27, 0x37, 0x36, 0x0D, 0x1D}

# ── Water ──────────────────────────────────────────────────────────
# The water tile ID is hardcoded to $14 in home/overworld.asm.
# Different tilesets that contain water all use the same tile ID.

WATER_TILE = 0x14

WATER_TILESETS: Set[int] = {
    TILESET_OVERWORLD,
    TILESET_FOREST,
    TILESET_DOJO,
    TILESET_GYM,
    TILESET_SHIP,
    TILESET_SHIP_PORT,
    TILESET_CAVERN,
    TILESET_FACILITY,
    TILESET_PLATEAU,
}

# ── Bookshelf / interactive tiles per tileset ──────────────────────
# From data/tilesets/bookshelf_tile_ids.asm
#
# These are tiles you can press A on to read flavor text — typically
# bookshelves, posters, statues, or PCs. They count as interactive
# "objects" for navigation purposes.

BOOKSHELF_TILES: Dict[int, Set[int]] = {
    TILESET_PLATEAU:      {0x30},
    TILESET_HOUSE:        {0x3D, 0x1E},
    TILESET_MANSION:      {0x32},
    TILESET_REDS_HOUSE_1: {0x32},
    TILESET_LAB:          {0x28},
    TILESET_LOBBY:        {0x16, 0x50, 0x52},
    TILESET_GYM:          {0x1D},
    TILESET_DOJO:         {0x1D},
    TILESET_GATE:         {0x22},
    TILESET_MART:         {0x54, 0x55},
    TILESET_POKECENTER:   {0x54, 0x55},
    TILESET_SHIP:         {0x36},
}


def get_warp_tiles(tileset_id: int) -> Set[int]:
    return WARP_TILES.get(tileset_id, set())


def get_door_tiles(tileset_id: int) -> Set[int]:
    return DOOR_TILES.get(tileset_id, set())


def get_bookshelf_tiles(tileset_id: int) -> Set[int]:
    return BOOKSHELF_TILES.get(tileset_id, set())


def tileset_has_water(tileset_id: int) -> bool:
    return tileset_id in WATER_TILESETS
