import { useCallback, useEffect, useRef, useState } from 'react';
import type { WSEvent, GameState } from '@/lib/types';

interface UseWebSocketReturn {
  connected: boolean;
  viewers: number;
  gameState: GameState | null;
  screenshot: string;
  reasoning: string;
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
  const [screenshot, setScreenshot] = useState('');
  const [reasoning, setReasoning] = useState('');
  const [events, setEvents] = useState<WSEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectDelay = useRef(RECONNECT_BASE_DELAY);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();

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

  return { connected, viewers, gameState, screenshot, reasoning, events };
}
