# utils/token_tracker.py
from __future__ import annotations


class TokenTracker:
    def __init__(self):
        self._claude_input = 0
        self._claude_output = 0
        self._claude_cache_read = 0
        self._claude_cache_write = 0
        self._claude_cost_usd = 0.0
        self._qwen_input = 0
        self._qwen_output = 0
        # Total bytes of tool results fed back into Qwen context (kept for backwards compat)
        self.tool_response_bytes = 0
        # Per-tool breakdown: {"run_command": 12400, "read_file": 3200, ...}
        self.tool_bytes_by_name: dict[str, int] = {}
        # Time-to-first-token and generation time per streaming call (seconds)
        self.ttft_samples: list[float] = []
        self.generation_samples: list[float] = []
        # Context trimming
        self.trim_events: int = 0        # calls to _trim_messages that truncated ≥1 message
        self.trim_bytes_saved: int = 0   # total bytes removed by truncation
        # Retry / reviewer overhead
        self.retry_count: int = 0        # total retries across all steps
        self.reviewer_calls: int = 0     # total reviewer invocations

    def add_claude(self, input_tokens: int = 0, output_tokens: int = 0,
                   cache_read: int = 0, cache_write: int = 0, cost_usd: float = 0.0):
        self._claude_input += input_tokens
        self._claude_output += output_tokens
        self._claude_cache_read += cache_read
        self._claude_cache_write += cache_write
        self._claude_cost_usd += cost_usd

    def add_qwen(self, input_tokens: int = 0, output_tokens: int = 0):
        self._qwen_input += input_tokens
        self._qwen_output += output_tokens

    def add_tool_bytes(self, tool_name: str, byte_count: int):
        """Record bytes injected into context for a named tool result."""
        self.tool_response_bytes += byte_count
        self.tool_bytes_by_name[tool_name] = (
            self.tool_bytes_by_name.get(tool_name, 0) + byte_count
        )

    def add_ttft(self, ttft_s: float, generation_s: float):
        """Record time-to-first-token and total generation time for one call."""
        self.ttft_samples.append(ttft_s)
        self.generation_samples.append(generation_s)

    def has_data(self) -> bool:
        return (self._claude_input + self._claude_output +
                self._qwen_input + self._qwen_output) > 0

    def summary(self) -> str:
        lines = ["[tokens] ── Usage Summary ──────────────────────────"]
        lines.append(
            f"[tokens] Claude (cloud):  {self._claude_input:>7,} in / {self._claude_output:>6,} out"
            + (f"  |  {self._claude_cache_read:,} cache-read / {self._claude_cache_write:,} cache-write"
               if self._claude_cache_read or self._claude_cache_write else "")
            + f"  |  ${self._claude_cost_usd:.4f}"
        )
        qwen_total = self._qwen_input + self._qwen_output
        lines.append(
            f"[tokens] Qwen  (local):   {self._qwen_input:>7,} in / {self._qwen_output:>6,} out"
            + f"  |  {qwen_total:,} total"
        )
        if self.tool_response_bytes:
            lines.append(
                f"[tokens] Tool resp bytes: {self.tool_response_bytes:>7,}  (context bloat)"
            )
            if self.tool_bytes_by_name:
                top = sorted(self.tool_bytes_by_name.items(), key=lambda x: -x[1])[:5]
                lines.append("[tokens]   by tool: " + "  ".join(f"{k}={v:,}" for k, v in top))
        if self.trim_events:
            lines.append(
                f"[tokens] Trim events: {self.trim_events}  saved {self.trim_bytes_saved:,} bytes"
            )
        if self.retry_count or self.reviewer_calls:
            lines.append(
                f"[tokens] Retries: {self.retry_count}  Reviewer calls: {self.reviewer_calls}"
            )
        if self.ttft_samples:
            mean_ttft = sum(self.ttft_samples) / len(self.ttft_samples)
            lines.append(
                f"[tokens] TTFT: min={min(self.ttft_samples):.2f}s  "
                f"mean={mean_ttft:.2f}s  max={max(self.ttft_samples):.2f}s"
            )
        if self.generation_samples:
            mean_gen = sum(self.generation_samples) / len(self.generation_samples)
            lines.append(
                f"[tokens] Gen time: min={min(self.generation_samples):.2f}s  "
                f"mean={mean_gen:.2f}s  max={max(self.generation_samples):.2f}s"
            )
        lines.append("[tokens] ────────────────────────────────────────────")
        return "\n".join(lines)


_tracker = TokenTracker()


def get_tracker() -> TokenTracker:
    """Return the current active tracker. All callers use this instead of importing
    `tracker` directly so that benchmark resets (reassigning _tracker) take effect."""
    return _tracker


def reset_tracker() -> TokenTracker:
    """Replace the active tracker with a fresh instance and return it.
    Call this between benchmark runs to isolate measurements."""
    global _tracker
    _tracker = TokenTracker()
    return _tracker
