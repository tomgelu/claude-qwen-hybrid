import os


def get_workspace() -> str:
    """Return the workspace directory, resolved at call time from env or cwd."""
    return os.environ.get("WORKSPACE_DIR", os.getcwd())


# Claude Code CLI settings (uses your Claude Code subscription, no API key needed)
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

# Local model settings — SGLang + Qwen3 on GB10
LOCAL_MODEL_URL = os.environ.get("LOCAL_MODEL_URL", "http://127.0.0.1:8000/v1/chat/completions")
LOCAL_MODEL_NAME = os.environ.get("LOCAL_MODEL_NAME", "qwen3-next-80b")
LOCAL_MODEL_TIMEOUT = int(os.environ.get("LOCAL_MODEL_TIMEOUT", "120"))

# Execution settings
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
STREAM_OUTPUT = os.environ.get("STREAM_OUTPUT", "true").lower() == "true"

# Reviewer settings
ENABLE_REVIEWER = os.environ.get("ENABLE_REVIEWER", "false").lower() == "true"
