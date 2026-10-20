from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Literal

Stage = Literal['제안/예고', '공포/고시', '시행', '내부문서/미확인']

@dataclass(frozen=True)
class Document:
    title: str
    text: str
    version: str
    source_url: str = ''
    source_type: str = '사용자 업로드'
    stage: Stage = '내부문서/미확인'
    effective_date: str = ''
    published_date: str = ''
    verified: bool = False

@dataclass(frozen=True)
class Clause:
    id: str
    heading: str
    text: str

@dataclass(frozen=True)
class Change:
    kind: str
    clause_id: str
    before: str
    after: str
    previous_id: str = ''
    diff: str = ''

@dataclass(frozen=True)
class Assessment:
    change: Change
    area: str
    relevance: str
    impact: str
    reason: str
    actions: tuple[str, ...] = ()
    evidence: str = ''
    laya_suggestion: str = ''
    review_required: bool = True

@dataclass
class Report:
    title: str
    old_version: str
    new_version: str
    source_url: str
    source_type: str
    stage: Stage
    effective_date: str
    published_date: str
    verified: bool
    assessments: list[Assessment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ollama_notes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
