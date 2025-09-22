"""Utility tool definitions for the application LLM agent."""

from collections.abc import Iterable

from pydantic_ai.tools import Tool


async def ping() -> str:
    """Simple liveness tool used to exercise the agent tool chain."""

    return "pong"


PING_TOOL = Tool(ping)


def get_tools() -> Iterable[Tool]:
    """Return the collection of registered tools."""

    return (PING_TOOL,)
