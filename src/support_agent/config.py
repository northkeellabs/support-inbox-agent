"""Settings from environment variables. Secrets are read here and nowhere else."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Frozen retrieval threshold: minimum cosine similarity of the best vector match.
# Chosen from evals/calibration/ only (never from the eval tickets); see README "Retrieval threshold".
# Below it the ticket is escalated as "low retrieval score".
# Frozen 2026-11-10 from evals/calibration/RESULTS.md (bge-m3, 15 questions): best balanced-accuracy cut = 0.66.
DEFAULT_MIN_RETRIEVAL_SCORE = 0.66


def _user_env(name: str) -> str:
    """Environment variable, falling back to the Windows user environment (registry)."""
    val = os.environ.get(name, "")
    if val or os.name != "nt":
        return val.strip()
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, name)[0]).strip()
    except OSError:
        return ""


def lacrm_api_key() -> str:
    return _user_env("LACRM_API_KEY")


def webhook_secret() -> str:
    return _user_env("SUPPORT_WEBHOOK_SECRET")


def known_secrets() -> list[str]:
    return [s for s in (lacrm_api_key(), webhook_secret(), os.environ.get("ANTHROPIC_API_KEY", ""),
                        os.environ.get("OPENAI_API_KEY", ""), os.environ.get("GOOGLE_API_KEY", "")) if s]


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass
class Settings:
    model_provider: str = field(default_factory=lambda: os.environ.get("MODEL_PROVIDER", "ollama").lower())
    model_name: str = field(default_factory=lambda: os.environ.get("MODEL_NAME", "qwen3:8b"))
    embed_model: str = field(default_factory=lambda: os.environ.get("EMBED_MODEL", "bge-m3"))
    ollama_base_url: str = field(default_factory=lambda: os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"))
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("SUPPORT_DATA_DIR", ROOT / "data")))
    kb_dir: Path = field(default_factory=lambda: Path(os.environ.get("SUPPORT_KB_DIR", ROOT / "kb")))
    min_retrieval_score: float = field(default_factory=lambda: _float_env("SUPPORT_MIN_RETRIEVAL_SCORE", DEFAULT_MIN_RETRIEVAL_SCORE))
    lacrm_mcp_dir: str = field(default_factory=lambda: _user_env("LACRM_MCP_DIR"))
    lacrm_mcp_env: str = field(default_factory=lambda: _user_env("LACRM_MCP_ENV"))

    def ensure_dirs(self) -> None:
        (self.data_dir / "audit").mkdir(parents=True, exist_ok=True)

    @property
    def checkpoint_db(self) -> Path:
        return self.data_dir / "checkpoints.sqlite"

    @property
    def kb_index(self) -> Path:
        return self.data_dir / "kb.sqlite"
