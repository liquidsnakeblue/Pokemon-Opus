import { useCallback, useEffect, useRef, useState } from 'react';
import type { WSEvent, GameState, TileSnapshot } from '@/lib/types';

export interface ReasoningEntry {
  turn: number;
  text: string;
  actions?: string[];
  timestamp: number;
}

interface UseWebSocketReturn {
  connected: boolean;
  viewers: number;
  gameState: GameState | null;
  /** High-frequency tile snapshot, updated independently of agent turns. */
  tiles: TileSnapshot | null;
  screenshot: string;
  reasoning: string;
  reasoningHistory: ReasoningEntry[];
  events: WSEvent[];
}

const WS_URL = `ws://${window.location.hostname}:3000/ws`;
const RECONNECT_BASE_DELAY = 1000;
const RECONNECT_MAX_DELAY = 30000;
const MAX_EVENTS = 200;

export function useWebSocket(): UseWebSocketReturn {
  const [connected, setConnected] = useState(false);
  const [viewers, setViewers] = useState(0);
  const [gameState, setGameState] = useState<GameState | null>(null);
  const [tiles, setTiles] = useState<TileSnapshot | null>(null);
  const [screenshot, setScreenshot] = useState('');
  const [reasoning, setReasoning] = useState('');
  const [reasoningHistory, setReasoningHistory] = useState<ReasoningEntry[]>([]);
  const [events, setEvents] = useState<WSEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectDelay = useRef(RECONNECT_BASE_DELAY);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const addEvent = useCallback((event: WSEvent) => {
    setEvents(prev => {
      const next = [...prev, event];
      return next.length > MAX_EVENTS ? next.slice(-MAX_EVENTS) : next;
    });
  }, []);

  const handleMessage = useCallback(
    (data: WSEvent) => {
      addEvent(data);

      switch (data.type) {
        case 'connected':
          setViewers(data.viewers);
          break;

        case 'turn_complete':
          setGameState(data.state);
          setScreenshot(data.screenshot);
          setReasoning(data.reasoning);
          if (data.reasoning) {
            setReasoningHistory(prev => {
              const turn = data.state?.turn ?? 0;
              // Deduplicate: skip if last entry has the same turn and text
              if (prev.length > 0) {
                const last = prev[prev.length - 1];
                if (last.turn === turn && last.text === data.reasoning) {
                  return prev;
                }
              }
              const entry: ReasoningEntry = {
                turn,
                text: data.reasoning,
                actions: data.actions,
                timestamp: Date.now(),
              };
              const next = [...prev, entry];
              return next.length > 50 ? next.slice(-50) : next;
            });
          }
          break;

        case 'tile_update':
          setTiles({
            tileGrid: data.tile_grid,
            fullGrid: data.full_grid,
            playerY: data.player_y,
            playerX: data.player_x,
            mapHeightCells: data.map_height_cells,
            mapWidthCells: data.map_width_cells,
            sprites: data.sprites,
          });
          break;

        case 'reasoning_chunk':
          setReasoning(prev => prev + data.text);
          break;

        case 'turn_start':
          setReasoning('');
          break;

        case 'objective_update':
          setGameState(prev =>
            prev ? { ...prev, objectives: data.objectives } : prev
          );
          break;

        case 'episode_start':
          setReasoning('');
          setEvents([]);
          break;
      }
    },
    [addEvent]
  );

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      reconnectDelay.current = RECONNECT_BASE_DELAY;
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as WSEvent;
        handleMessage(data);
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;

      // Reconnect with exponential backoff
      const delay = reconnectDelay.current;
      reconnectDelay.current = Math.min(delay * 2, RECONNECT_MAX_DELAY);
      reconnectTimer.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [handleMessage]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { connected, viewers, gameState, tiles, screenshot, reasoning, reasoningHistory, events };
}
