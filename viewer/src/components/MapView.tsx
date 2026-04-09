import { useMemo } from 'react';
import type { MapData } from '@/lib/types';

interface MapViewProps {
  map: MapData | undefined;
}

const TILE_SIZE = 4;
const PLAYER_COLOR = '#e03030';
const TILE_COLOR = '#d8d8d0';
const TILE_BORDER = '#b8b8b0';
const BG_COLOR = '#101018';
const POI_POKECENTER = '#4090e0';
const POI_MART = '#e0c040';
const POI_GYM = '#e06040';

export function MapView({ map }: MapViewProps) {
  const currentLocation = useMemo(() => {
    if (!map) return null;
    return map.locations.find(l => l.map_id === map.current_map_id) ?? null;
  }, [map]);

  const { tiles, bounds, playerPos, pois } = useMemo(() => {
    if (!currentLocation || currentLocation.positions.length === 0) {
      return { tiles: new Set<string>(), bounds: null, playerPos: null, pois: [] };
    }

    const positions = currentLocation.positions;
    let minY = Infinity, maxY = -Infinity, minX = Infinity, maxX = -Infinity;
    for (const [y, x] of positions) {
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
    }

    minY -= 2; minX -= 2; maxY += 2; maxX += 2;

    const posSet = new Set(positions.map(([y, x]) => `${y},${x}`));
    const pp = map ? { y: map.current_position[0], x: map.current_position[1] } : null;

    // Collect POIs from all locations
    const poiList: { mapId: number; name: string; color: string }[] = [];
    for (const loc of map.locations) {
      if (loc.has_pokecenter) poiList.push({ mapId: loc.map_id, name: loc.name, color: POI_POKECENTER });
      if (loc.has_pokemart) poiList.push({ mapId: loc.map_id, name: loc.name, color: POI_MART });
      if (loc.has_gym) poiList.push({ mapId: loc.map_id, name: loc.name, color: POI_GYM });
    }

    return { tiles: posSet, bounds: { minY, maxY, minX, maxX }, playerPos: pp, pois: poiList };
  }, [currentLocation, map]);

  if (!map || !bounds) {
    return (
      <div className="panel flex flex-col" style={{ minHeight: 200 }}>
        <div className="panel-header"><span>Map</span></div>
        <div className="panel-body flex-1 flex items-center justify-center">
          <span className="text-text-tertiary text-sm italic">No map data yet</span>
        </div>
      </div>
    );
  }

  const gridW = bounds.maxX - bounds.minX + 1;
  const gridH = bounds.maxY - bounds.minY + 1;
  const svgW = gridW * TILE_SIZE;
  const svgH = gridH * TILE_SIZE;
  const playerRadius = TILE_SIZE * 0.8;

  // Build tile rects
  const tileRects: JSX.Element[] = [];
  for (let y = bounds.minY; y <= bounds.maxY; y++) {
    for (let x = bounds.minX; x <= bounds.maxX; x++) {
      if (tiles.has(`${y},${x}`)) {
        tileRects.push(
          <rect
            key={`${y},${x}`}
            x={(x - bounds.minX) * TILE_SIZE}
            y={(y - bounds.minY) * TILE_SIZE}
            width={TILE_SIZE}
            height={TILE_SIZE}
            fill={TILE_COLOR}
            stroke={TILE_BORDER}
            strokeWidth={0.2}
          />
        );
      }
    }
  }

  return (
    <div className="panel flex flex-col" style={{ minHeight: 200 }}>
      <div className="panel-header">
        <span>Map</span>
        <span className="ml-auto text-[10px] text-text-tertiary font-mono">
          {currentLocation?.name}
        </span>
      </div>
      <div className="panel-body flex-1 flex flex-col gap-1 min-h-0 p-0">
        {/* SVG map */}
        <div className="flex-1 flex items-center justify-center min-h-0 p-1" style={{ background: BG_COLOR }}>
          <svg
            viewBox={`0 0 ${svgW} ${svgH}`}
            className="w-full h-full"
            preserveAspectRatio="xMidYMid meet"
          >
            <rect width={svgW} height={svgH} fill={BG_COLOR} />
            {tileRects}
            {/* Player dot */}
            {playerPos && (
              <>
                {/* Glow */}
                <circle
                  cx={(playerPos.x - bounds.minX) * TILE_SIZE + TILE_SIZE / 2}
                  cy={(playerPos.y - bounds.minY) * TILE_SIZE + TILE_SIZE / 2}
                  r={playerRadius * 1.5}
                  fill={PLAYER_COLOR}
                  opacity={0.2}
                />
                {/* Dot */}
                <circle
                  cx={(playerPos.x - bounds.minX) * TILE_SIZE + TILE_SIZE / 2}
                  cy={(playerPos.y - bounds.minY) * TILE_SIZE + TILE_SIZE / 2}
                  r={playerRadius}
                  fill={PLAYER_COLOR}
                />
              </>
            )}
          </svg>
        </div>
        {/* Footer with coordinates and area count */}
        <div className="flex items-center justify-between px-2 py-1 text-[10px] font-mono border-t border-white/5">
          <span className="text-text-tertiary">
            ({map.current_position[0]}, {map.current_position[1]})
          </span>
          <span className="text-text-tertiary">
            {tiles.size} tiles — {map.locations.length} area{map.locations.length !== 1 ? 's' : ''}
          </span>
        </div>
      </div>
    </div>
  );
}
