class TokenTracker:
    def __init__(self):
        self._claude_input = 0
        self._claude_output = 0
        self._claude_cache_read = 0
        self._claude_cache_write = 0
        self._claude_cost_usd = 0.0
        self._qwen_input = 0
        self._qwen_output = 0

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

    def has_data(self) -> bool:
        return (self._claude_input + self._claude_output +
                self._qwen_input + self._qwen_output) > 0

    def summary(self) -> str:
        lines = ["[tokens] ── Usage Summary ──────────────────────────"]
        lines.append(
            f"[tokens] Claude (cloud):  {self._claude_input:>7,} in / {self._claude_output:>6,} out"
            + (f"  |  {self._claude_cache_read:,} cache-read / {self._claude_cache_write:,} cache-write" if self._claude_cache_read or self._claude_cache_write else "")
            + f"  |  ${self._claude_cost_usd:.4f}"
        )
        qwen_total = self._qwen_input + self._qwen_output
        lines.append(
            f"[tokens] Qwen  (local):   {self._qwen_input:>7,} in / {self._qwen_output:>6,} out"
            + f"  |  {qwen_total:,} total"
        )
        lines.append("[tokens] ────────────────────────────────────────────")
        return "\n".join(lines)


tracker = TokenTracker()
