import json
import requests
from config.settings import LOCAL_MODEL_URL, LOCAL_MODEL_NAME, LOCAL_MODEL_TIMEOUT, STREAM_OUTPUT
from tools.registry import TOOLS, parse_xml_tool_calls, strip_xml_tool_calls
from utils.logger import get_logger
from utils.token_tracker import tracker as _tracker

log = get_logger(__name__)

AGENT_SYSTEM_PROMPT = """You are an autonomous coding agent executing a specific step in a software task.

You have tools to read/write files, run commands, and interact with git.

## Before making any changes
1. Check for CLAUDE.md or README for build commands, test commands, and project conventions.
2. Read all files you will touch. Understand the code style, existing utilities, and patterns in use.
3. Never create a new file when editing an existing one will do. Never create documentation files unless explicitly asked.

## Executing the step
- Only work on what the step asks — complete it fully, but do not add unrequested features or refactoring.
- Mimic the existing code style exactly: indentation, naming conventions, import ordering, comment density.
- Prefer existing libraries and utilities over writing new ones.
- Minimize comments; avoid docstrings on code you didn't write. Only comment non-obvious logic.

## Verification (required)
After writing, you MUST verify by running the relevant command (pytest, python3 script.py, etc.).
- If verification fails, diagnose the error, fix it, and re-verify. Repeat until passing.
- Run at least one adversarial check beyond the happy path: an edge case, invalid input, or boundary value.
- Report each check with: command run → actual output → PASS or FAIL.

## Finishing
When the step is fully complete and verified, stop calling tools and give a concise summary:
- What files were changed and why
- Commands run and their verdicts (PASS/FAIL)
- Any issues encountered and how they were resolved

Do not narrate your thinking. State results directly."""


class LocalClient:
    def __init__(self):
        self.url = LOCAL_MODEL_URL
        self.model = LOCAL_MODEL_NAME
        self.timeout = LOCAL_MODEL_TIMEOUT

    def _call_streaming(self, payload: dict) -> tuple[str, list[dict] | None]:
        """Stream a response, printing content tokens as they arrive.
        Returns (full_content, native_tool_calls_or_none).
        """
        payload = {**payload, "stream": True, "stream_options": {"include_usage": True}}
        resp = requests.post(self.url, json=payload, timeout=self.timeout, stream=True)
        resp.raise_for_status()

        content_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}
        printed_any = False

        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode() if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            # Capture usage from the final chunk (sent when stream_options.include_usage=true)
            if chunk.get("usage"):
                u = chunk["usage"]
                _tracker.add_qwen(
                    input_tokens=u.get("prompt_tokens", 0),
                    output_tokens=u.get("completion_tokens", 0),
                )

            choices = chunk.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta", {})

            if delta.get("content"):
                tok = delta["content"]
                content_parts.append(tok)
                print(tok, end="", flush=True)
                printed_any = True

            for tc in delta.get("tool_calls", []):
                idx = tc.get("index", 0)
                if idx not in tool_calls_acc:
                    tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                if tc.get("id"):
                    tool_calls_acc[idx]["id"] = tc["id"]
                fn = tc.get("function", {})
                if fn.get("name"):
                    tool_calls_acc[idx]["name"] += fn["name"]
                if fn.get("arguments"):
                    tool_calls_acc[idx]["arguments"] += fn["arguments"]

        if printed_any:
            print()

        full_content = "".join(content_parts)

        if tool_calls_acc:
            tool_calls = [
                {
                    "id": v["id"] or f"stream_{k}",
                    "type": "function",
                    "function": {"name": v["name"], "arguments": v["arguments"]},
                }
                for k, v in sorted(tool_calls_acc.items())
            ]
            return full_content, tool_calls

        return full_content, None

    def _call(self, payload: dict) -> tuple[str, list[dict] | None, dict]:
        """Call the model (streaming or not).
        Returns (content, native_tool_calls_or_none, raw_msg).
        """
        if STREAM_OUTPUT:
            try:
                content, native_tc = self._call_streaming(payload)
                msg = {"role": "assistant", "content": content}
                if native_tc:
                    msg["tool_calls"] = native_tc
                return content, native_tc, msg
            except Exception as e:
                log.warning(f"  [stream] failed ({e}), falling back to non-streaming")

        # Non-streaming fallback
        resp = requests.post(self.url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        if usage:
            _tracker.add_qwen(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            )
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        return content, msg.get("tool_calls"), msg

    def run_agent_loop(self, task: str, dispatch_fn, max_turns: int = 30) -> dict:
        """
        Run the model in a tool-calling loop until it stops calling tools.
        dispatch_fn(name, args) is called for each tool use.
        Returns {"status", "final_message", "turns", "tool_calls_made"}.
        """
        messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]
        tool_calls_made = []

        for turn in range(max_turns):
            payload = {
                "model": self.model,
                "messages": messages,
                "tools": TOOLS,
                "tool_choice": "auto",
                "temperature": 0.1,
            }
            content, native_tool_calls, msg = self._call(payload)

            # Try XML fallback if no native tool calls
            xml_tool_calls = parse_xml_tool_calls(content) if not native_tool_calls else None
            tool_calls = native_tool_calls or xml_tool_calls

            if not tool_calls:
                return {
                    "status": "success",
                    "final_message": strip_xml_tool_calls(content),
                    "turns": turn + 1,
                    "tool_calls_made": tool_calls_made,
                }

            if native_tool_calls:
                messages.append(msg)
                tool_results = []
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    raw_args = tc["function"]["arguments"]
                    fn_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    result = dispatch_fn(fn_name, fn_args)
                    tool_calls_made.append({"name": fn_name, "args": fn_args})
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result) if not isinstance(result, str) else result,
                    })
                messages.extend(tool_results)
            else:
                # XML fallback: inject results as <tool_response> user message
                messages.append(msg)
                response_parts = []
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    raw_args = tc["function"]["arguments"]
                    fn_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    result = dispatch_fn(fn_name, fn_args)
                    tool_calls_made.append({"name": fn_name, "args": fn_args})
                    result_str = json.dumps(result) if not isinstance(result, str) else result
                    response_parts.append(f"<tool_response>\n{result_str}\n</tool_response>")
                messages.append({"role": "user", "content": "\n".join(response_parts)})

        return {
            "status": "max_turns",
            "final_message": f"Reached max_turns={max_turns} without finishing",
            "turns": max_turns,
            "tool_calls_made": tool_calls_made,
        }
