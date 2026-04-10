import { useWebSocket } from '@/hooks/useWebSocket';
import { Layout } from '@/components/Layout';
import { GameScreen } from '@/components/GameScreen';
import { ReasoningPanel } from '@/components/ReasoningPanel';
import { TeamPanel } from '@/components/TeamPanel';
import { ObjectivesPanel } from '@/components/ObjectivesPanel';
import { InventoryPanel } from '@/components/InventoryPanel';
import { StatsBar } from '@/components/StatsBar';
import { MilestonesPanel } from '@/components/MilestonesPanel';
import { MapView } from '@/components/MapView';

export default function App() {
  const { connected, viewers, gameState, tiles, screenshot, reasoning, reasoningHistory, events } =
    useWebSocket();

  return (
    <Layout>
      {/* Header */}
      <div className="shrink-0">
        <StatsBar
          connected={connected}
          viewers={viewers}
          turn={gameState?.turn ?? 0}
          mode={gameState?.mode ?? 'explore'}
          runtime={gameState?.performance.runtime ?? '0:00:00'}
          tokens={gameState?.performance.total_tokens ?? 0}
          cost={gameState?.performance.total_cost_usd ?? 0}
          mapName={gameState?.player.map_name ?? '—'}
          badges={gameState?.player.badges ?? []}
        />
      </div>

      {/* Main content */}
      <div className="flex-1 flex gap-3 px-4 pb-3 min-h-0">
        {/* Left column */}
        <div className="flex flex-col gap-2 w-[460px] shrink-0 min-h-0">
          <GameScreen mode={gameState?.mode ?? 'explore'} />
          <MapView
            fullGrid={tiles?.fullGrid}
            tileGrid={tiles?.tileGrid ?? gameState?.tile_grid}
            mapName={gameState?.player.map_name}
            position={
              tiles
                ? [tiles.playerY, tiles.playerX]
                : gameState?.player.position
            }
          />
          <TeamPanel party={gameState?.party ?? []} />
        </div>

        {/* Center column */}
        <div className="flex-1 flex flex-col gap-2 min-h-0 min-w-0">
          <div className="shrink-0">
            <ObjectivesPanel objectives={gameState?.objectives ?? []} />
          </div>
          <div className="shrink-0">
            <MilestonesPanel milestones={gameState?.milestones ?? []} />
          </div>
          <ReasoningPanel
            reasoning={reasoning}
            reasoningHistory={reasoningHistory}
            turn={gameState?.turn ?? 0}
          />
        </div>

        {/* Right column */}
        <div className="flex flex-col gap-2 w-[260px] shrink-0 min-h-0">
          <div className="shrink-0">
            <InventoryPanel bag={gameState?.bag ?? []} money={gameState?.player.money ?? 0} />
          </div>
        </div>
      </div>
    </Layout>
  );
}
