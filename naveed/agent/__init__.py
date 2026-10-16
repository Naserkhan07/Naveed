"""The agent: understanding the request, seeing the screen, acting, reporting."""

from __future__ import annotations

from ..lazy import lazy_attrs

__all__ = [
    "AgentBridge",
    "LLMClient",
    "LLMError",
    "NaveedAgent",
    "Planner",
    "Task",
    "TaskStatus",
    "describe_screen",
    "extract_json",
]

__getattr__ = lazy_attrs(
    globals(),
    {
        "llm": "naveed.agent.llm",
        "LLMClient": "naveed.agent.llm:LLMClient",
        "LLMError": "naveed.agent.llm:LLMError",
        "extract_json": "naveed.agent.llm:extract_json",
        "Planner": "naveed.agent.planner:Planner",
        "prompts": "naveed.agent.prompts",
        "describe_screen": "naveed.agent.planner:describe_screen",
        "NaveedAgent": "naveed.agent.executor:NaveedAgent",
        "Task": "naveed.agent.executor:Task",
        "TaskStatus": "naveed.agent.executor:TaskStatus",
        "bridge": "naveed.agent.bridge",
        "AgentBridge": "naveed.agent.bridge:AgentBridge",
    },
)
