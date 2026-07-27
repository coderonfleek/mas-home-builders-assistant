from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field

AgentSource = Literal["listings", "neighborhood", "schools"]

class AgentInput(TypedDict):
    """State passed to a specialist agent node."""
    query: str


class AgentOutput(TypedDict):
    """State returned by a specialist agent node."""
    source: str # specifies the agent that produced this result
    result: str


class Classification(TypedDict):
    """A single routing decision: which agent to call with what query."""
    source: AgentSource # agent to send to
    query: str # query to be sent


class RouterState(TypedDict):
    """The main graph state.

    The reducer ``operator.add`` on ``results`` is what makes parallel
    fan-out work — each specialist returns a single-element list, and
    LangGraph concatenates them as the parallel branches complete.
    """
    query: str # user's main question to the MAS
    classifications: list[Classification]
    results: Annotated[list[AgentOutput], operator.add]
    final_answer: str

class ClassificationItem(BaseModel):
    """One routing decision."""
    source: AgentSource = Field(
        description=(
            "Which specialist agent to call. Must be exactly one of: "
            "'listings', 'neighborhood', 'schools'."
        )
    )
    query: str = Field(
        description=(
            "The sub-question rewritten for this specific agent. "
            "Should be concrete and tailored to the agent's domain."
        )
    )


class ClassificationResult(BaseModel):
    """The full classification output — a list of routing decisions."""
    classifications: list[ClassificationItem] = Field(
        description=(
            "List of agents to invoke with their targeted sub-questions. "
            "Only include agents that are actually relevant to the user's query."
        )
    )

