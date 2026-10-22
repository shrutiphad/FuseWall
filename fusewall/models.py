"""Explicit wire contracts. No provider credentials or arbitrary upstream URLs."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{1,80}$")]
Money = Annotated[int, Field(strict=True, ge=0, le=1_000_000_000_000)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KeyCreate(Contract):
    name: Name
    client: Name = "Internal"
    budget_micro: Money = 1_000_000
    session_budget_micro: Money = 20_000
    max_calls: int = Field(25, ge=1, le=10_000, strict=True)
    duration_seconds: int = Field(1800, ge=1, le=86_400, strict=True)
    loop_threshold: int = Field(0, ge=0, le=100, strict=True)
    max_concurrent: int = Field(4, ge=1, le=32, strict=True)
    rpm: int = Field(60, ge=1, le=10_000, strict=True)
    allowed_models: list[Literal["fusewall/mini", "fusewall/pro"]] = Field(
        default_factory=lambda: ["fusewall/mini"], min_length=1, max_length=2
    )


class KeyPatch(Contract):
    active: bool = Field(strict=True)


class SettingsPatch(Contract):
    budget_micro: Money
    paused: bool = Field(strict=True)


class Message(Contract):
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=16_000)


class Completion(Contract):
    model: Literal["fusewall/mini", "fusewall/pro"] = "fusewall/mini"
    messages: list[Message] = Field(min_length=1, max_length=32)
    max_tokens: int = Field(64, ge=1, le=1024, strict=True)
    stream: bool = Field(False, strict=True)


class LabRun(Contract):
    key_id: Identifier
    session_id: Identifier
    scenario: Literal["normal", "slow", "provider_error", "interrupted"] = "normal"
    calls: int = Field(1, ge=1, le=50, strict=True)
    parallel: int = Field(1, ge=1, le=8, strict=True)
    max_tokens: int = Field(64, ge=1, le=1024, strict=True)
    model: Literal["fusewall/mini", "fusewall/pro"] = "fusewall/mini"
    prompt: str = Field("Summarize this week's support requests.", max_length=4000)


class Replay(Contract):
    budget_micro: Money
    limit: int = Field(100, ge=1, le=1000, strict=True)


class Preview(Contract):
    key_id: Identifier
    session_id: Identifier
    completion: Completion


class Resolution(Contract):
    actual_micro: Money
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=300)]


class Login(Contract):
    token: str = Field(min_length=16, max_length=200)
