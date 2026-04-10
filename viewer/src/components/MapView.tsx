import { useMemo } from 'react';

interface MapViewProps {
  /** The entire current map, classified. Prefer this over `tileGrid`. */
  fullGrid?: string[][];
  /** Legacy 9x10 camera viewport — fallback when full_grid isn't populated yet. */
  tileGrid?: string[][];
  /** Player absolute position on the full map (or on the viewport for fallback). */
  position?: [number, number];
  mapName?: string;
}

// Target cell size in SVG user units. The SVG scales to fit the panel via
// preserveAspectRatio, so this controls the aspect ratio / visual density
// rather than the absolute pixel size.
const CELL = 12;
const GRID_LINE = 0.5;

// Tile colors — high contrast, distinct types
const COLORS: Record<string, { fill: string; stroke?: string }> = {
  '.': { fill: '#e8e0d4', stroke: '#d8d0c4' },   // walkable — warm white
  '#': { fill: '#6b6b7b', stroke: '#5a5a6a' },   // wall/unknown solid — gray
  '~': { fill: '#5abf5a', stroke: '#4aaf4a' },   // tall grass — bright green
  'W': { fill: '#4a90d0', stroke: '#3a80c0' },   // water — blue
  'P': { fill: '#e8e0d4' },                       // player tile (walkable underneath)
  'N': { fill: '#e8e0d4' },                       // NPC tile (walkable underneath)
  'I': { fill: '#e8e0d4' },                       // Item (walkable underneath)
  'O': { fill: '#e8e0d4' },                       // Object (walkable underneath)
  'D': { fill: '#f0c860', stroke: '#d0a840' },   // door/warp — gold
  'F': { fill: '#d4a0b0', stroke: '#c490a0' },   // flowers — pink
  'f': { fill: '#8b7060', stroke: '#7b6050' },   // fence — brown
  'B': { fill: '#505068', stroke: '#404058' },   // building — dark blue-gray
  'S': { fill: '#c0b090', stroke: '#b0a080' },   // sign/mailbox — tan
  'T': { fill: '#3a7a3a', stroke: '#2a6a2a' },   // tree — dark green
  'L': { fill: '#a0a080', stroke: '#909070' },   // ledge — olive
  '?': { fill: '#1a1a25' },                       // unknown (dialog) — very dark
  'X': { fill: '#12121a' },                       // border — near black
};

// Player triangle facing down (default)
function PlayerMarker({ x, y, size }: { x: number; y: number; size: number }) {
  const cx = x + size / 2;
  const cy = y + size / 2;
  const s = size * 0.35;
  const points = `${cx},${cy + s} ${cx - s},${cy - s * 0.6} ${cx + s},${cy - s * 0.6}`;
  return (
    <>
      <circle cx={cx} cy={cy} r={size * 0.45} fill="#e03030" opacity={0.15} />
      <polygon points={points} fill="#1a1a2e" stroke="#e03030" strokeWidth={0.8} />
    </>
  );
}

// NPC marker
function NpcMarker({ x, y, size }: { x: number; y: number; size: number }) {
  const cx = x + size / 2;
  const cy = y + size / 2;
  const r = size * 0.3;
  return (
    <>
      <circle cx={cx} cy={cy} r={r} fill="#f06090" stroke="#d04070" strokeWidth={0.6} />
      <circle cx={cx - r * 0.35} cy={cy - r * 0.15} r={r * 0.18} fill="white" />
      <circle cx={cx + r * 0.35} cy={cy - r * 0.15} r={r * 0.18} fill="white" />
      <circle cx={cx - r * 0.35} cy={cy - r * 0.15} r={r * 0.09} fill="#1a1a2e" />
      <circle cx={cx + r * 0.35} cy={cy - r * 0.15} r={r * 0.09} fill="#1a1a2e" />
    </>
  );
}

// Item marker (Poke Ball-like circle)
function ItemMarker({ x, y, size }: { x: number; y: number; size: number }) {
  const cx = x + size / 2;
  const cy = y + size / 2;
  const r = size * 0.3;
  return (
    <>
      <circle cx={cx} cy={cy} r={r} fill="#e04040" stroke="#c03030" strokeWidth={0.6} />
      <line x1={cx - r} y1={cy} x2={cx + r} y2={cy} stroke="white" strokeWidth={0.8} />
      <circle cx={cx} cy={cy} r={r * 0.25} fill="white" />
    </>
  );
}

// Object marker (square)
function ObjectMarker({ x, y, size }: { x: number; y: number; size: number }) {
  const s = size * 0.45;
  return (
    <rect
      x={x + (size - s) / 2}
      y={y + (size - s) / 2}
      width={s}
      height={s}
      fill="#7090b0"
      stroke="#506880"
      strokeWidth={0.6}
      rx={1}
    />
  );
}

// Sign marker (small vertical rectangle on a stake)
function SignMarker({ x, y, size }: { x: number; y: number; size: number }) {
  const cx = x + size / 2;
  const top = y + size * 0.2;
  const w = size * 0.45;
  const h = size * 0.4;
  return (
    <>
      <rect
        x={cx - w / 2}
        y={top}
        width={w}
        height={h}
        fill="#8b6d3f"
        stroke="#5c4422"
        strokeWidth={0.5}
        rx={0.5}
      />
      <line
        x1={cx}
        y1={top + h}
        x2={cx}
        y2={y + size * 0.85}
        stroke="#5c4422"
        strokeWidth={0.8}
      />
    </>
  );
}

export function MapView({ fullGrid, tileGrid, mapName, position }: MapViewProps) {
  // Prefer the full current-map grid if present. Otherwise fall back to
  // the legacy 9x10 viewport snapshot so the panel still shows something
  // during the brief window before the first tile_update arrives.
  const gridData = useMemo(() => {
    const grid = fullGrid && fullGrid.length > 0 ? fullGrid : tileGrid;
    if (!grid || grid.length === 0) return null;

    const rows = grid.length;
    const cols = grid[0]?.length ?? 0;
    if (rows === 0 || cols === 0) return null;

    return { rows, cols, grid, usingFullMap: !!(fullGrid && fullGrid.length > 0) };
  }, [fullGrid, tileGrid]);

  if (!gridData) {
    return (
      <div className="panel flex flex-col" style={{ minHeight: '160px' }}>
        <div className="panel-header">
          <span>Map</span>
        </div>
        <div className="panel-body flex-1 flex items-center justify-center">
          <span className="text-text-tertiary text-xs italic">No map data yet</span>
        </div>
      </div>
    );
  }

  const svgW = gridData.cols * CELL;
  const svgH = gridData.rows * CELL;

  // The player position is in the same coordinate space as the grid we're
  // rendering: either absolute map coords (full map) or viewport-local
  // coords (fallback). In both cases the backend sends them matching.
  const playerY = position?.[0];
  const playerX = position?.[1];

  return (
    <div className="panel flex flex-col" style={{ minHeight: '160px' }}>
      <div className="panel-header">
        <span>{mapName ?? 'Map'}</span>
        {position && (
          <span className="ml-auto text-[10px] text-text-secondary font-mono">
            [{position[0]},{position[1]}]
            {!gridData.usingFullMap && ' (viewport)'}
          </span>
        )}
      </div>
      <div
        className="flex-1 flex items-center justify-center min-h-0 p-2"
        style={{ background: '#12121a' }}
      >
        <svg
          viewBox={`0 0 ${svgW} ${svgH}`}
          className="w-full h-full"
          preserveAspectRatio="xMidYMid meet"
          style={{ borderRadius: '4px', overflow: 'hidden' }}
        >
          {/* Background */}
          <rect width={svgW} height={svgH} fill="#12121a" />

          {/* Tile cells */}
          {gridData.grid.map((row, y) =>
            row.map((cell, x) => {
              if (cell === 'X') return null;
              const colors = COLORS[cell] ?? COLORS['#'];
              return (
                <rect
                  key={`${y}-${x}`}
                  x={x * CELL + GRID_LINE}
                  y={y * CELL + GRID_LINE}
                  width={CELL - GRID_LINE * 2}
                  height={CELL - GRID_LINE * 2}
                  fill={colors.fill}
                  stroke={colors.stroke ?? 'none'}
                  strokeWidth={colors.stroke ? GRID_LINE : 0}
                  rx={cell === '#' ? 0 : 1}
                />
              );
            })
          )}

          {/* Sprite markers (render on top of tile cells) */}
          {gridData.grid.map((row, y) =>
            row.map((cell, x) => {
              const px = x * CELL;
              const py = y * CELL;
              if (cell === 'N') {
                return <NpcMarker key={`npc-${y}-${x}`} x={px} y={py} size={CELL} />;
              }
              if (cell === 'I') {
                return <ItemMarker key={`item-${y}-${x}`} x={px} y={py} size={CELL} />;
              }
              if (cell === 'O') {
                return <ObjectMarker key={`obj-${y}-${x}`} x={px} y={py} size={CELL} />;
              }
              if (cell === 'S') {
                return <SignMarker key={`sign-${y}-${x}`} x={px} y={py} size={CELL} />;
              }
              return null;
            })
          )}

          {/* Player marker — rendered last so nothing overlaps it.
              If we're using the full map, place the marker at absolute
              (playerY, playerX). If we're using the fallback viewport,
              find the 'P' cell inside the viewport grid. */}
          {gridData.usingFullMap && playerY !== undefined && playerX !== undefined ? (
            <PlayerMarker
              key="player-marker"
              x={playerX * CELL}
              y={playerY * CELL}
              size={CELL}
            />
          ) : (
            gridData.grid.map((row, y) =>
              row.map((cell, x) => {
                if (cell === 'P') {
                  return (
                    <PlayerMarker
                      key={`player-${y}-${x}`}
                      x={x * CELL}
                      y={y * CELL}
                      size={CELL}
                    />
                  );
                }
                return null;
              })
            )
          )}

          {/* Grid lines overlay for structure */}
          {Array.from({ length: gridData.cols + 1 }).map((_, x) => (
            <line
              key={`vl-${x}`}
              x1={x * CELL}
              y1={0}
              x2={x * CELL}
              y2={svgH}
              stroke="#1a1a2e"
              strokeWidth={GRID_LINE * 0.5}
              opacity={0.3}
            />
          ))}
          {Array.from({ length: gridData.rows + 1 }).map((_, y) => (
            <line
              key={`hl-${y}`}
              x1={0}
              y1={y * CELL}
              x2={svgW}
              y2={y * CELL}
              stroke="#1a1a2e"
              strokeWidth={GRID_LINE * 0.5}
              opacity={0.3}
            />
          ))}
        </svg>
      </div>
    </div>
  );
}
