interface GameScreenProps {
  mode: string;
}

const STREAM_URL = `http://${window.location.hostname}:3000/stream`;

export function GameScreen({ mode }: GameScreenProps) {
  return (
    <div className="panel flex flex-col shrink-0 overflow-hidden">
      <img
        src={STREAM_URL}
        alt="Game Screen"
        className="w-full"
        style={{ imageRendering: 'pixelated', display: 'block', objectFit: 'fill' }}
      />
    </div>
  );
}
