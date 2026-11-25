"""Settings, read from environment variables (or the .env file)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# Every SIEM use case must expose these fields.
BASELINE_FIELDS = ["Time", "Account", "Device", "Source_IP", "SAFE_name"]


@dataclass
class Settings:
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    model_name: str = os.getenv("MODEL_NAME", "openai/gpt-oss-120b")
    judge_model_name: str = os.getenv("JUDGE_MODEL_NAME", "qwen/qwen3.8-27b")
    temperature: float = float(os.getenv("TEMPERATURE", "0.2"))
    max_tokens: int = int(os.getenv("MAX_TOKENS", "2048"))
    max_agent_steps: int = int(os.getenv("MAX_AGENT_STEPS", "10"))
    web_search_enabled: bool = os.getenv("WEB_SEARCH_ENABLED", "true").lower() == "true"
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///data/splunk_agent.db")
    # Local model used when Groq fails (rate limit, network down, no API key).
    ollama_fallback: bool = os.getenv("OLLAMA_FALLBACK", "true").lower() == "true"
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3.5:4b")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
