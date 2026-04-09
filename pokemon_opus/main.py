"""
Pokemon-Opus — Main entry point.
Starts the game server check, orchestrator, and streaming server.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from .config import Config
from .game_client import GameClient
from .llm.client import LLMClient
from .orchestrator import Orchestrator
from .streaming.server import StreamServer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pokemon_opus")


BANNER = r"""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   ██████╗  ██████╗ ██╗  ██╗███████╗███╗   ███╗ ██████╗  ║
║   ██╔══██╗██╔═══██╗██║ ██╔╝██╔════╝████╗ ████║██╔═══██╗ ║
║   ██████╔╝██║   ██║█████╔╝ █████╗  ██╔████╔██║██║   ██║ ║
║   ██╔═══╝ ██║   ██║██╔═██╗ ██╔══╝  ██║╚██╔╝██║██║   ██║ ║
║   ██║     ╚██████╔╝██║  ██╗███████╗██║ ╚═╝ ██║╚██████╔╝ ║
║   ╚═╝      ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝ ╚═════╝ ║
║                        OPUS                               ║
║                                                          ║
║   AI Pokemon Blue Agent — powered by Claude Opus         ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
"""


async def run() -> None:
    """Main async entry point."""
    print(BANNER)

    # Load config
    config_path = Path("pyproject.toml")
    if config_path.exists():
        config = Config.from_toml(config_path)
        logger.info("Config loaded from pyproject.toml")
    else:
        config = Config()
        logger.info("Using default config")

    # Initialize game client
    game = GameClient(base_url=config.game_server_url)
    logger.info(f"Connecting to game server at {config.game_server_url}...")

    if not await game.wait_for_server(max_retries=10, delay=2.0):
        logger.error(
            f"Game server not available at {config.game_server_url}\n"
            f"Start it with: pokemon-agent serve --rom <path-to-pokemon-blue.gb>"
        )
        await game.close()
        sys.exit(1)

    logger.info("Game server connected!")

    # Verify initial state
    try:
        state = await game.get_state()
        map_name = state.get("map", {}).get("map_name", "Unknown")
        party_count = len(state.get("party", []))
        logger.info(f"Game state: {map_name}, Party: {party_count} Pokemon")
    except Exception as e:
        logger.error(f"Failed to read game state: {e}")
        await game.close()
        sys.exit(1)

    # Initialize components
    llm = LLMClient(config)
    stream = StreamServer(
        host=config.streaming_host,
        port=config.streaming_port,
        enable_cors=config.enable_cors,
    )

    # Build orchestrator
    orchestrator = Orchestrator(
        config=config,
        game_client=game,
        stream=stream,
        llm_client=llm,
        # Memory, objectives, map managers will be initialized later
        # as they're built out in subsequent phases
    )

    # Generate initial objectives
    await orchestrator.strategist.generate_initial_objectives(orchestrator.gs)

    logger.info(f"Viewer available at http://localhost:{config.streaming_port}")
    logger.info("Starting episode...")

    # Run streaming server and orchestrator concurrently
    async def run_orchestrator():
        try:
            result = await orchestrator.play_episode()
            logger.info(f"Episode complete: {result.get('performance', {})}")
        except KeyboardInterrupt:
            logger.info("Episode interrupted by user")
        except Exception as e:
            logger.error(f"Episode failed: {e}", exc_info=True)
        finally:
            await game.close()

    # Start both the streaming server and the orchestrator
    await asyncio.gather(
        stream.start(),
        run_orchestrator(),
    )


def main() -> None:
    """CLI entry point."""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
