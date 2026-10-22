"""A scripted chat model, so the AI paths are tested without API keys."""

import json

from langchain_core.messages import AIMessage


class _Bound:
    def __init__(self, llm):
        self.llm = llm

    async def ainvoke(self, messages):
        self.llm.tool_rounds += 1
        if self.llm.tool_plan:
            return self.llm.tool_plan.pop(0)
        return AIMessage(content=self.llm.final_answer)


class FakeLLM:
    def __init__(self, replies: dict | None = None, tool_plan: list | None = None, final_answer: str = "",
                 model_name: str = "fake-model", error: Exception | None = None):
        self.replies = replies or {}
        self.tool_plan = list(tool_plan or [])
        self.final_answer = final_answer
        self.model_name = model_name
        self.error = error
        self.calls: list = []
        self.tool_rounds = 0

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if self.error:
            raise self.error
        system = str(messages[0].content)
        for key, value in self.replies.items():
            if key in system:
                return AIMessage(content=value if isinstance(value, str) else json.dumps(value))
        return AIMessage(content="{}")

    def bind_tools(self, tools):
        if self.error:
            raise self.error
        return _Bound(self)
