"""Schema for slot prefilling via LLM."""
from __future__ import annotations

from typing import Dict, List, Literal

from pydantic import BaseModel, Field

DomainId = Literal[
    "distractions",
    "academic_confidence",
    "time_pressure",
    "social_comparison",
    "family_pressure",
    "motivation",
    "demotivation",
    "backlog_stress",
]

PrefillMap = Dict[str, Dict[str, str]]


class Person(BaseModel):
    role: str
    name: str | None = None


class Event(BaseModel):
    description: str
    known: bool = False


class SessionState(BaseModel):
    people: List[Person] = Field(default_factory=list)
    events: List[Event] = Field(default_factory=list)
    emotions: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    ignored_information: List[str] = Field(default_factory=list)


class SlotPrefillResponse(BaseModel):
    active_domains: List[DomainId] = Field(default_factory=list)
    prefill: PrefillMap = Field(default_factory=dict)
    negated_slots: List[str] = Field(default_factory=list)
    extracted_state: SessionState = Field(default_factory=SessionState)


__all__ = [
    "SlotPrefillResponse",
    "DomainId",
    "PrefillMap",
    "Person",
    "Event",
    "SessionState",
]
