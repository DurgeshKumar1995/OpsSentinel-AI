from collections.abc import Sequence
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class IncidentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    hitl_approved: bool
    agent_steps: int
