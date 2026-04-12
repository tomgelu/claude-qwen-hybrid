import os

# Load .env from repo root if present (does not override existing env vars)
_env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.isfile(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                _k = _k.strip()
                _v = _v.strip().strip('"').strip("'")
                os.environ.setdefault(_k, _v)


def get_workspace() -> str:
    """Return the workspace directory, resolved at call time from env or cwd."""
    return os.environ.get("WORKSPACE_DIR", os.getcwd())


# Claude Code CLI settings (uses your Claude Code subscription, no API key needed)
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

# Local model — any OpenAI-compatible server (Ollama, vLLM, LM Studio, llama.cpp, ...)
LOCAL_MODEL_URL = os.environ.get("LOCAL_MODEL_URL", "http://127.0.0.1:8000/v1/chat/completions")
LOCAL_MODEL_NAME = os.environ.get("LOCAL_MODEL_NAME", "qwen2.5-coder:7b")
LOCAL_MODEL_TIMEOUT = int(os.environ.get("LOCAL_MODEL_TIMEOUT", "120"))

# Execution settings
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
STREAM_OUTPUT = os.environ.get("STREAM_OUTPUT", "true").lower() == "true"

# Reviewer settings
ENABLE_REVIEWER = os.environ.get("ENABLE_REVIEWER", "false").lower() == "true"
