/** WebSocket event types from the Pokemon-Opus backend */

export interface Pokemon {
  species_id: number;
  species: string;
  nickname: string;
  level: number;
  hp: number;
  max_hp: number;
  status: string;
  types: string[];
  moves: Move[];
  attack: number;
  defense: number;
  speed: number;
  special: number;
}

export interface Move {
  id: number;
  name: string;
  pp: number;
}

export interface Objective {
  id: string;
  category: string;
  name: string;
  text: string;
  completion_condition: string;
  status: string;
  created_turn: number;
  completed_turn: number | null;
  target_map_id: number | null;
}

export interface Milestone {
  name: string;
  turn: number;
  details: string;
  category: string;
}

export interface BagItem {
  id: number;
  item: string;
  quantity: number;
}

export interface MapLocation {
  map_id: number;
  name: string;
  visits: number;
  positions: [number, number][];
  has_pokecenter: boolean;
  has_pokemart: boolean;
  has_gym: boolean;
}

export interface MapConnection {
  from_id: number;
  from_name: string;
  to_id: number;
  to_name: string;
  times_traversed: number;
}

export interface MapData {
  current_map_id: number;
  current_position: [number, number];
  locations: MapLocation[];
  connections: MapConnection[];
}

export interface GameState {
  episode_id: string;
  turn: number;
  mode: string;
  player: {
    name: string;
    rival: string;
    money: number;
    badges: string[];
    badge_count: number;
    position: [number, number];
    facing: string;
    map_id: number;
    map_name: string;
    play_time: string;
  };
  party: Pokemon[];
  bag: BagItem[];
  battle: {
    in_battle: boolean;
    type: string;
    enemy: Pokemon | null;
  };
  dialog_active: boolean;
  flags: {
    has_pokedex: boolean;
    pokedex_owned: number;
    pokedex_seen: number;
  };
  objectives: Objective[];
  milestones: Milestone[];
  performance: {
    total_tokens: number;
    total_cost_usd: number;
    runtime: string;
    runtime_seconds: number;
  };
  last_reasoning: string;
  last_actions: string[];
  map?: MapData;
  tile_grid?: string[][];  // 20x18 classified grid from emulator
  tile_sprites?: [number, number][];  // NPC positions
}

export interface Deltas {
  location_changed?: boolean;
  old_map_name?: string;
  new_map_name?: string;
  badge_gained?: string;
  pokemon_caught?: string;
  pokemon_leveled?: string;
  new_level?: number;
  item_gained?: string;
  battle_started?: boolean;
  battle_ended?: boolean;
}

// WebSocket event types
export type WSEvent =
  | { type: 'connected'; viewers: number }
  | { type: 'heartbeat' }
  | { type: 'turn_start'; turn: number; mode: string; map_name: string }
  | {
      type: 'turn_complete';
      turn: number;
      mode: string;
      actions: string[];
      state: GameState;
      screenshot: string;
      reasoning: string;
      deltas: Deltas;
    }
  | { type: 'reasoning_chunk'; turn: number; text: string }
  | { type: 'mode_change'; from: string; to: string }
  | { type: 'battle_start'; enemy: Pokemon; battle_type: string }
  | { type: 'battle_end'; result: string }
  | { type: 'milestone'; name: string; turn: number; details: string }
  | { type: 'objective_update'; objectives: Objective[] }
  | { type: 'memory_created'; location: string; category: string; text: string }
  | { type: 'map_update'; map_id: number; position: [number, number]; connections: unknown[] }
  | {
      // Real-time map snapshot pushed at ~5 Hz, decoupled from agent turns.
      type: 'tile_update';
      tile_grid: string[][];
      full_grid: string[][];
      player_y: number;
      player_x: number;
      map_height_cells: number;
      map_width_cells: number;
      sprites: Array<{ y: number; x: number; type: string; picture_id?: number }>;
    }
  | { type: 'episode_start'; episode_id: string }
  | { type: 'episode_end'; badges: number; pokedex: number; turns: number }
  | { type: 'error'; message: string };

/** Live tile snapshot, kept separate from gameState so it can update at
 *  high frequency without re-rendering everything. */
export interface TileSnapshot {
  tileGrid: string[][];
  fullGrid: string[][];
  playerY: number;
  playerX: number;
  mapHeightCells: number;
  mapWidthCells: number;
  sprites: Array<{ y: number; x: number; type: string }>;
}

// Badge names and colors
export const BADGES = [
  { name: 'Boulder', color: '#b8a038' },
  { name: 'Cascade', color: '#6890f0' },
  { name: 'Thunder', color: '#f8d030' },
  { name: 'Rainbow', color: '#78c850' },
  { name: 'Soul', color: '#f85888' },
  { name: 'Marsh', color: '#a040a0' },
  { name: 'Volcano', color: '#f08030' },
  { name: 'Earth', color: '#e0c068' },
] as const;

// Pokemon type color map
export const TYPE_COLORS: Record<string, string> = {
  Normal: '#a8a878',
  Fire: '#f08030',
  Water: '#6890f0',
  Grass: '#78c850',
  Electric: '#f8d030',
  Ice: '#98d8d8',
  Fighting: '#c03028',
  Poison: '#a040a0',
  Ground: '#e0c068',
  Flying: '#a890f0',
  Psychic: '#f85888',
  Bug: '#a8b820',
  Rock: '#b8a038',
  Ghost: '#705898',
  Dragon: '#7038f8',
};
