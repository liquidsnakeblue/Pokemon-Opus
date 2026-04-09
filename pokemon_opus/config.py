"""
Configuration — loads from pyproject.toml and environment.
Single source of truth for all settings. Adapted from Zork-Opus config.py.
"""

import os
import tomllib
from typing import Optional
from pathlib import Path
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv


def _default_retry() -> dict:
    return {
        "max_retries": 5,
        "initial_delay": 1.0,
        "max_delay": 60.0,
        "exponential_base": 2.0,
        "jitter_factor": 0.1,
        "timeout_seconds": 120.0,
        "circuit_breaker_failure_threshold": 10,
        "circuit_breaker_recovery_timeout": 300.0,
    }


class Config(BaseSettings):
    """All settings for Pokemon-Opus. Loaded from pyproject.toml [tool.pokemon-opus]."""

    # Game server
    game_server_url: str = "http://localhost:8765"
    max_turns_per_episode: int = 10000
    turn_delay_seconds: float = 0.5
    save_interval: int = 50

    # LLM
    client_base_url: str = "https://api.anthropic.com/v1"
    client_api_key: Optional[str] = None
    agent_model: str = "claude-opus-4-20250514"
    strategist_model: str = "claude-opus-4-20250514"
    memory_model: str = "claude-opus-4-20250514"
    battle_model: str = "claude-opus-4-20250514"

    # Per-model base URL overrides
    agent_base_url: Optional[str] = None
    strategist_base_url: Optional[str] = None
    memory_base_url: Optional[str] = None
    battle_base_url: Optional[str] = None

    # Retry
    retry: dict = Field(default_factory=_default_retry)

    # Sampling parameters per role
    agent_sampling: dict = Field(default_factory=lambda: {"temperature": 0.7, "max_tokens": 4096})
    strategist_sampling: dict = Field(
        default_factory=lambda: {"temperature": 0.5, "max_tokens": 8192}
    )
    battle_sampling: dict = Field(default_factory=lambda: {"temperature": 0.3, "max_tokens": 2048})
    memory_sampling: dict = Field(default_factory=lambda: {"temperature": 0.4, "max_tokens": 4096})

    # Memory
    memory_file: str = "memories.md"
    max_memories_shown: int = 15
    knowledge_file: str = "knowledge.md"
    knowledge_update_interval: int = 100

    # Objectives
    objective_update_interval: int = 20
    max_objectives: int = 8
    completion_check_interval: int = 5

    # Map
    map_state_file: str = "map_state.json"
    enable_tile_tracking: bool = True
    screenshot_on_move: bool = True

    # Streaming
    streaming_host: str = "0.0.0.0"
    streaming_port: int = 3000
    enable_cors: bool = True

    # Stuck detection
    max_turns_stuck: int = 200
    stuck_check_interval: int = 20
    stuck_warning_threshold: int = 50

    # Files
    game_workdir: str = "game_files"
    state_export_file: str = "current_state.json"
    episode_log_file: str = "episode_log.jsonl"

    # Prompt logging
    enable_prompt_logger: bool = True
    prompt_log_dir: str = "game_files/prompt_logs"

    model_config = SettingsConfigDict(
        env_prefix="POKEMON_OPUS_",
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def _validate_stuck(self) -> "Config":
        if self.max_turns_stuck < self.stuck_check_interval:
            raise ValueError("max_turns_stuck must be >= stuck_check_interval")
        return self

    def model_post_init(self, __context) -> None:
        if self.client_api_key is None:
            self.client_api_key = os.environ.get("ANTHROPIC_API_KEY")
        Path(self.game_workdir).mkdir(parents=True, exist_ok=True)

    def base_url_for(self, role: str) -> str:
        """Get effective base URL for a model role (agent, battle, strategist, memory)."""
        override = getattr(self, f"{role}_base_url", None)
        return override or self.client_base_url

    def api_key_for(self, role: str) -> Optional[str]:
        """Get effective API key for a model role."""
        url = self.base_url_for(role).lower()
        if "openrouter" in url:
            return os.environ.get("OPENROUTER_API_KEY") or self.client_api_key
        if "anthropic" in url:
            return os.environ.get("ANTHROPIC_API_KEY") or self.client_api_key
        return self.client_api_key or os.environ.get("LOCAL_LLM_API_KEY", "not-needed")

    def model_for(self, role: str) -> str:
        """Get model name for a role."""
        return getattr(self, f"{role}_model", self.agent_model)

    def sampling_for(self, role: str) -> dict:
        """Get sampling parameters for a role."""
        return getattr(self, f"{role}_sampling", self.agent_sampling)

    @classmethod
    def from_toml(cls, path: Optional[Path] = None) -> "Config":
        load_dotenv()
        path = path or Path("pyproject.toml")
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {path}")

        with open(path, "rb") as f:
            raw = tomllib.load(f)

        cfg = raw.get("tool", {}).get("pokemon-opus", {})
        game = cfg.get("game", {})
        llm = cfg.get("llm", {})
        mem = cfg.get("memory", {})
        obj = cfg.get("objectives", {})
        mp = cfg.get("map", {})
        st = cfg.get("streaming", {})
        stuck = cfg.get("stuck_detection", {})

        d: dict = {}

        # Game
        if game.get("server_url"):
            d["game_server_url"] = game["server_url"]
        for k in ["max_turns_per_episode", "turn_delay_seconds", "save_interval"]:
            if game.get(k) is not None:
                d[k] = game[k]

        # LLM
        for k in [
            "client_base_url",
            "agent_model",
            "strategist_model",
            "memory_model",
            "battle_model",
            "agent_base_url",
            "strategist_base_url",
            "memory_base_url",
            "battle_base_url",
        ]:
            if llm.get(k) is not None:
                d[k] = llm[k]

        # Sampling
        for role in ["agent", "strategist", "battle", "memory"]:
            key = f"{role}_sampling"
            if llm.get(key):
                d[key] = llm[key]

        # Memory
        for k in ["memory_file", "max_memories_shown", "knowledge_file", "knowledge_update_interval"]:
            if mem.get(k) is not None:
                d[k] = mem[k]

        # Objectives
        for k in ["update_interval", "max_objectives", "completion_check_interval"]:
            if obj.get(k) is not None:
                mapped = f"objective_{k}" if k == "update_interval" else k
                d[mapped] = obj[k]

        # Map
        for k in ["state_file", "enable_tile_tracking", "screenshot_on_move"]:
            if mp.get(k) is not None:
                mapped = f"map_{k}" if k == "state_file" else k
                d[mapped] = mp[k]

        # Streaming
        if st.get("host"):
            d["streaming_host"] = st["host"]
        if st.get("port"):
            d["streaming_port"] = st["port"]
        if st.get("enable_cors") is not None:
            d["enable_cors"] = st["enable_cors"]

        # Stuck detection
        for k in ["max_turns_stuck", "check_interval", "warning_threshold"]:
            if stuck.get(k) is not None:
                mapped = k if k == "max_turns_stuck" else f"stuck_{k}"
                d[mapped] = stuck[k]

        # Filter None values so Pydantic uses defaults
        d = {k: v for k, v in d.items() if v is not None}
        return cls.model_validate(d)
