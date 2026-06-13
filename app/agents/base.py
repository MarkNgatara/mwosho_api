"""Base agent class with Anthropic tool-use agentic loop."""
import json
from typing import Any, Callable

import anthropic
from app.config import settings


class BaseAgent:
    name: str = "base"
    model: str = "claude-haiku-4-5"

    def __init__(self):
        self._client: anthropic.Anthropic | None = None

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        return self._client

    def run_with_tools(
        self,
        system: str,
        prompt: str,
        tool_definitions: list[dict],
        tool_handlers: dict[str, Callable[..., Any]],
        max_iterations: int = 15,
    ) -> str:
        """Agentic loop: Claude reasons, calls tools, gets results, repeats until done."""
        messages: list[dict] = [{"role": "user", "content": prompt}]

        for _ in range(max_iterations):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system,
                tools=tool_definitions,
                messages=messages,
            )

            if response.stop_reason == "end_turn":
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text
                return ""

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        handler = tool_handlers.get(block.name)
                        try:
                            result = handler(**block.input) if handler else {"error": f"No handler for {block.name}"}
                        except Exception as exc:
                            result = {"error": str(exc)}
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        })
                messages.append({"role": "user", "content": tool_results})

        return "Max iterations reached"

    def simple_chat(self, system: str, prompt: str, max_tokens: int = 2048) -> str:
        """One-shot Claude call without tools."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    def run(self, job: Any, db: Any) -> None:
        raise NotImplementedError
