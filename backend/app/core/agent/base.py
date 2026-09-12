from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from loguru import logger

from app.core.llm.gateway import LLMGateway


class BaseAgent(ABC):
    """Abstract base class for conversational agents.

    Provides a common interface for agent execution (sync and streaming)
    with optional tool binding support.
    """

    def __init__(
        self,
        llm_gateway: LLMGateway,
        system_prompt: str,
        model_name: str | None = None,
        tools: list | None = None,
    ) -> None:
        self._llm_gateway = llm_gateway
        self._system_prompt = system_prompt
        self._model_name = model_name
        self._tools = tools or []

    @property
    def llm_gateway(self) -> LLMGateway:
        return self._llm_gateway

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @property
    def tools(self) -> list:
        return list(self._tools)

    def _build_messages(
        self,
        user_input: str,
        history: list[dict[str, str]] | None = None,
    ) -> list[BaseMessage]:
        """Build a message list from system prompt, optional history, and user input."""
        messages: list[BaseMessage] = [SystemMessage(content=self._system_prompt)]

        if history:
            for msg in history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "assistant":
                    from langchain_core.messages import AIMessage

                    messages.append(AIMessage(content=content))
                else:
                    messages.append(HumanMessage(content=content))

        messages.append(HumanMessage(content=user_input))
        return messages

    def _get_llm(self) -> Any:
        """Get the raw LLM with tools bound if configured."""
        llm = self._llm_gateway.get_model(self._model_name)
        if self._tools:
            llm = llm.bind_tools(self._tools)
        return llm

    @abstractmethod
    async def arun(
        self,
        user_input: str,
        history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> str:
        """Run the agent with a single user input and return the final response."""
        ...

    @abstractmethod
    async def astream(
        self,
        user_input: str,
        history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Run the agent and yield response tokens as they are generated."""
        ...


class ReActAgent(BaseAgent):
    """A simple ReAct-style agent that calls the LLM directly.

    Uses tool binding via the LLM's native tool-calling interface.
    For multi-turn ReAct loops (tool call → observation → respond),
    use the LangGraph-based agent from langgraph_agent.py instead.
    """

    async def arun(
        self,
        user_input: str,
        history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> str:
        messages = self._build_messages(user_input, history)
        llm = self._get_llm()

        response = await llm.ainvoke(messages)
        text = response.content if hasattr(response, "content") else str(response)
        logger.info("ReActAgent arun | input_len={} | output_len={}", len(user_input), len(text))
        return text

    async def astream(
        self,
        user_input: str,
        history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        messages = self._build_messages(user_input, history)
        llm = self._get_llm()

        async for chunk in llm.astream(messages):
            content = chunk.content if hasattr(chunk, "content") else str(chunk)
            if content:
                yield content
