"""A hand-written tool-calling agent (no Azure AI Foundry agent service).

All model calls go through the APIM gateway using the Azure OpenAI SDK; the
agent loop, tool registry, and message handling live here in plain Python.
"""
from __future__ import annotations

import ast
import json
import operator
import os
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

from openai import AzureOpenAI

from booking import BOOKING_SCHEMAS, BOOKING_TOOLS

# ----------------------------------------------------------------------- tools
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.USub: operator.neg, ast.FloorDiv: operator.floordiv,
}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


def calculator(expression: str) -> str:
    """Safely evaluate an arithmetic expression."""
    try:
        return str(_eval(ast.parse(expression, mode="eval").body))
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"


def get_current_time(timezone_name: str = "UTC") -> str:
    """Current UTC time (ISO 8601)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_KB = {
    "apim tiers": "Developer is for non-production use (no SLA); Standard/Premium are production tiers.",
    "token limit": "The gateway enforces a per-subscription tokens-per-minute budget via azure-openai-token-limit.",
    "auth": "Clients use an APIM subscription key; APIM authenticates to Azure OpenAI with its managed identity.",
}


def search_notes(query: str) -> str:
    """Keyword search over a tiny built-in knowledge base."""
    q = query.lower()
    hits = [f"{k}: {v}" for k, v in _KB.items() if any(w in k or w in v.lower() for w in q.split())]
    return "\n".join(hits) or "no matches"


TOOLS: dict[str, Callable[..., str]] = {
    "calculator": calculator,
    "get_current_time": get_current_time,
    "search_notes": search_notes,
}

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "calculator",
        "description": "Evaluate an arithmetic expression, e.g. '(12*7)/3'.",
        "parameters": {"type": "object",
                       "properties": {"expression": {"type": "string"}},
                       "required": ["expression"]}}},
    {"type": "function", "function": {
        "name": "get_current_time",
        "description": "Get the current date and time in UTC.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "search_notes",
        "description": "Search internal notes about APIM, auth and token limits.",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"]}}},
]

TOOLS.update(BOOKING_TOOLS)
TOOL_SCHEMAS.extend(BOOKING_SCHEMAS)


def system_prompt() -> str:
    today = datetime.now().strftime("%A %Y-%m-%d")
    return (
        "You are a concise hospital assistant that can also do math and tell the time. "
        f"Today is {today}. Use tools when they help. "
        "To book an appointment you need the patient's name, department, date and time: "
        "ask for anything missing, check availability, summarise the details and get the "
        "user's explicit confirmation before calling book_appointment. Offer other free "
        "slots if one is taken. Never invent booking ids or availability. "
        "You do not give medical advice or diagnoses; for emergencies tell the user to "
        "call local emergency services. After tool results arrive, give a clear final answer."
    )


# ----------------------------------------------------------------------- agent
class Agent:
    def __init__(self, client: AzureOpenAI | None = None, deployment: str | None = None,
                 max_steps: int = 6):
        self.client = client or AzureOpenAI(
            azure_endpoint=os.environ["APIM_GATEWAY_URL"],
            api_key=os.environ["APIM_SUBSCRIPTION_KEY"],
            api_version=os.environ.get("AOAI_API_VERSION", "2024-06-01"),
        )
        self.deployment = deployment or os.environ.get("AOAI_DEPLOYMENT", "chat")
        self.max_steps = max_steps

    def run(self, history: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
        """Run the loop on `history` (user/assistant messages). Mutates it with
        tool traffic and yields events: tool_call, tool_result, final, error."""
        messages = [{"role": "system", "content": system_prompt()}] + history
        usage = {"prompt": 0, "completion": 0}
        for _ in range(self.max_steps):
            try:
                resp = self.client.chat.completions.create(
                    model=self.deployment, messages=messages,
                    tools=TOOL_SCHEMAS, tool_choice="auto",
                )
            except Exception as exc:  # noqa: BLE001 (429 from APIM token limit, etc.)
                yield {"type": "error", "message": str(exc)}
                return
            if resp.usage:
                usage["prompt"] += resp.usage.prompt_tokens
                usage["completion"] += resp.usage.completion_tokens
            msg = resp.choices[0].message
            if not msg.tool_calls:
                history.append({"role": "assistant", "content": msg.content or ""})
                yield {"type": "final", "content": msg.content or "", "usage": usage}
                return

            call_msg = {"role": "assistant", "content": msg.content or "",
                        "tool_calls": [{"id": c.id, "type": "function",
                                        "function": {"name": c.function.name,
                                                     "arguments": c.function.arguments}}
                                       for c in msg.tool_calls]}
            messages.append(call_msg)
            history.append(call_msg)
            for call in msg.tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                yield {"type": "tool_call", "name": call.function.name, "args": args}
                fn = TOOLS.get(call.function.name)
                try:
                    result = fn(**args) if fn else f"error: unknown tool {call.function.name}"
                except Exception as exc:  # noqa: BLE001
                    result = f"error: {exc}"
                yield {"type": "tool_result", "name": call.function.name, "result": result}
                tool_msg = {"role": "tool", "tool_call_id": call.id, "content": result}
                messages.append(tool_msg)
                history.append(tool_msg)
        yield {"type": "error", "message": f"stopped after {self.max_steps} steps"}


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    hist: list[dict[str, Any]] = [{"role": "user", "content": input("you> ")}]
    for ev in Agent().run(hist):
        print(ev)
