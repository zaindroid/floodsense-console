"""Hand-checked Pydantic models for the shared contracts.

Wire names are the schema names (snake_case). Do not add fields here
without adding them to contracts/schemas/floodsense.schema.json.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Same strings as date_time and content_sha256 in the schema. CI enforces the schema.
DATE_TIME = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
SHA256 = r"^[a-f0-9]{64}$"

Layer = Literal["a", "b", "c"]
Storage = Literal["full_text", "pointer"]
Grounding = Literal["supported", "partial", "unsupported"]
ServedFrom = Literal["live", "cache", "replay"]
ApprovalStatus = Literal["pending", "approved", "edited", "rejected"]
ModelId = Literal[
    "meterless/fast",
    "meterless/deep",
    "nvidia/nemotron-3.5-super-vl-120b-a12b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "deterministic",
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Locator(ContractModel):
    section: str | None = None
    # Optional on layers a and b. On layer c the validator rejects null.
    # A section-structured source still sets a page-like id. Section does not replace page.
    page: int | None = Field(default=None, ge=1)
    paragraph: int | None = Field(default=None, ge=1)
    lines: str | None = None


class Citation(ContractModel):
    citation_id: str
    claim_id: str
    layer: Layer
    source_url: str
    title: str
    publisher: str
    accessed_at: str = Field(pattern=DATE_TIME)
    licence: str
    attribution: str
    # When quote is present, SHA-256 hex of that quote as UTF-8 (what the Judge compares).
    content_sha256: str = Field(pattern=SHA256)
    storage: Storage
    locator: Locator | None = None
    quote: str | None = None
    query_id: str | None = None
    chunk_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def layer_c_names_the_passage(self) -> Citation:
        """Layer c requires page >= 1 even when section is set. Section does not replace page."""
        if self.layer != "c":
            return self
        loc = self.locator
        if (
            not self.quote
            or not self.query_id
            or loc is None
            or loc.page is None
            or loc.paragraph is None
            or not loc.lines
        ):
            raise ValueError(
                "layer c requires quote, query_id, and locator.page, "
                "locator.paragraph, and locator.lines"
            )
        return self


class Evidence(ContractModel):
    query_id: str
    view: str
    sql: str
    rows_sample: list[dict[str, Any]] = Field(max_length=20)
    row_count: int = Field(ge=0)
    executed_at_utc: str = Field(pattern=DATE_TIME)


class DroppedNumber(ContractModel):
    value: float
    reason: str = Field(min_length=1)


class Claim(ContractModel):
    claim_id: str
    text: str
    numbers_dropped: list[DroppedNumber] | None = None


class JudgeClaim(ContractModel):
    claim_id: str
    grounding: Grounding
    citation_faithful: bool
    numbers_match: bool
    score: float = Field(ge=0, le=1)
    rationale: str
    model_id: ModelId
    numbers_dropped: list[DroppedNumber] | None = None


class Judge(ContractModel):
    claims: list[JudgeClaim] = Field(min_length=1)
    overall_score: float = Field(ge=0, le=1)


class PlaybookAction(ContractModel):
    action_id: str
    run_id: str
    title: str
    detail: str
    citation_ids: list[str] = Field(min_length=1)


class Approval(ContractModel):
    approval_id: str
    run_id: str
    action_id: str
    status: ApprovalStatus
    note: str | None = None
    judge: Judge | None = None


class Answer(ContractModel):
    run_id: str
    question: str
    claims: list[Claim] = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)
    evidence: list[Evidence]
    served_from: ServedFrom
    cached_at: str | None = Field(default=None, pattern=DATE_TIME)
    playbook_actions: list[PlaybookAction] = Field(default_factory=list)
    judge: Judge | None = None

    @model_validator(mode="after")
    def cached_at_matches_served_from(self) -> Answer:
        if self.served_from == "live":
            if self.cached_at is not None:
                raise ValueError("cached_at must be null when served_from is live")
        elif self.cached_at is None:
            raise ValueError("cached_at is required when served_from is not live")
        return self
