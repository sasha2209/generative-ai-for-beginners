"""Core domain models for the Family Health Graph.

Everything the platform stores about a user lives in a single ``HealthProfile``:
their own conditions, observations (labs/vitals) and medications, plus a list of
blood relatives and the conditions those relatives have had.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .terminology import CONCEPTS_BY_CATEGORY


def _id() -> str:
    return uuid.uuid4().hex[:12]


class Sex(str, Enum):
    FEMALE = "female"
    MALE = "male"
    OTHER = "other"
    UNKNOWN = "unknown"


class Relationship(str, Enum):
    MOTHER = "mother"
    FATHER = "father"
    SISTER = "sister"
    BROTHER = "brother"
    DAUGHTER = "daughter"
    SON = "son"
    MATERNAL_GRANDMOTHER = "maternal_grandmother"
    MATERNAL_GRANDFATHER = "maternal_grandfather"
    PATERNAL_GRANDMOTHER = "paternal_grandmother"
    PATERNAL_GRANDFATHER = "paternal_grandfather"
    GRANDMOTHER = "grandmother"
    GRANDFATHER = "grandfather"
    MATERNAL_AUNT = "maternal_aunt"
    MATERNAL_UNCLE = "maternal_uncle"
    PATERNAL_AUNT = "paternal_aunt"
    PATERNAL_UNCLE = "paternal_uncle"
    AUNT = "aunt"
    UNCLE = "uncle"
    HALF_SISTER = "half_sister"
    HALF_BROTHER = "half_brother"
    NIECE = "niece"
    NEPHEW = "nephew"
    MATERNAL_COUSIN = "maternal_cousin"
    PATERNAL_COUSIN = "paternal_cousin"
    COUSIN = "cousin"
    OTHER = "other"


# relationship -> (degree of relatedness, lineage side, implied sex)
# Side is None when the relative is not on a single parental line (siblings,
# children) or when the side was not specified.
RELATIONSHIP_META: dict[Relationship, tuple[Optional[int], Optional[str], Optional[str]]] = {
    Relationship.MOTHER: (1, "maternal", "female"),
    Relationship.FATHER: (1, "paternal", "male"),
    Relationship.SISTER: (1, None, "female"),
    Relationship.BROTHER: (1, None, "male"),
    Relationship.DAUGHTER: (1, None, "female"),
    Relationship.SON: (1, None, "male"),
    Relationship.MATERNAL_GRANDMOTHER: (2, "maternal", "female"),
    Relationship.MATERNAL_GRANDFATHER: (2, "maternal", "male"),
    Relationship.PATERNAL_GRANDMOTHER: (2, "paternal", "female"),
    Relationship.PATERNAL_GRANDFATHER: (2, "paternal", "male"),
    Relationship.GRANDMOTHER: (2, None, "female"),
    Relationship.GRANDFATHER: (2, None, "male"),
    Relationship.MATERNAL_AUNT: (2, "maternal", "female"),
    Relationship.MATERNAL_UNCLE: (2, "maternal", "male"),
    Relationship.PATERNAL_AUNT: (2, "paternal", "female"),
    Relationship.PATERNAL_UNCLE: (2, "paternal", "male"),
    Relationship.AUNT: (2, None, "female"),
    Relationship.UNCLE: (2, None, "male"),
    Relationship.HALF_SISTER: (2, None, "female"),
    Relationship.HALF_BROTHER: (2, None, "male"),
    Relationship.NIECE: (2, None, "female"),
    Relationship.NEPHEW: (2, None, "male"),
    Relationship.MATERNAL_COUSIN: (3, "maternal", None),
    Relationship.PATERNAL_COUSIN: (3, "paternal", None),
    Relationship.COUSIN: (3, None, None),
    Relationship.OTHER: (None, None, None),
}

# Relatives of whom a person has exactly one; used when merging data sources.
SINGULAR_RELATIONSHIPS = {
    Relationship.MOTHER,
    Relationship.FATHER,
    Relationship.MATERNAL_GRANDMOTHER,
    Relationship.MATERNAL_GRANDFATHER,
    Relationship.PATERNAL_GRANDMOTHER,
    Relationship.PATERNAL_GRANDFATHER,
}


class Condition(BaseModel):
    id: str = Field(default_factory=_id)
    name: str
    category: Optional[str] = None  # canonical concept, see terminology.py
    code: Optional[str] = None
    code_system: Optional[str] = None
    onset_age: Optional[int] = None
    age_estimated: bool = False
    onset_date: Optional[date] = None
    status: str = "unknown"
    source: str = "manual"

    @property
    def display_name(self) -> str:
        concept = CONCEPTS_BY_CATEGORY.get(self.category or "")
        return concept.display if concept else self.name


class Observation(BaseModel):
    id: str = Field(default_factory=_id)
    code: str  # canonical: ldl_cholesterol, hba1c, bmi, systolic_bp, ...
    value: float
    unit: str = ""
    effective_date: Optional[date] = None
    source: str = "manual"


class Medication(BaseModel):
    id: str = Field(default_factory=_id)
    name: str
    status: str = "active"
    source: str = "manual"


class FamilyMember(BaseModel):
    id: str = Field(default_factory=_id)
    relationship: Relationship
    name: Optional[str] = None
    sex: Optional[Sex] = None
    deceased: Optional[bool] = None
    age: Optional[int] = None  # current age, or age at death
    conditions: list[Condition] = Field(default_factory=list)
    source: str = "manual"

    @property
    def degree(self) -> Optional[int]:
        return RELATIONSHIP_META[self.relationship][0]

    @property
    def side(self) -> Optional[str]:
        return RELATIONSHIP_META[self.relationship][1]

    @property
    def effective_sex(self) -> Optional[str]:
        if self.sex and self.sex not in (Sex.UNKNOWN,):
            return self.sex.value
        return RELATIONSHIP_META[self.relationship][2]

    @property
    def lineage_sides(self) -> set[str]:
        """Parental lines this relative informs. Full siblings and children share
        both of the user's lines, so they count toward either side."""
        if self.side:
            return {self.side}
        if self.relationship in (
            Relationship.SISTER,
            Relationship.BROTHER,
            Relationship.DAUGHTER,
            Relationship.SON,
        ):
            return {"maternal", "paternal"}
        return set()

    @property
    def label(self) -> str:
        # Names are deliberately left out of labels so that evidence strings
        # (which may be sent to partners or an LLM) never carry them.
        return self.relationship.value.replace("_", " ").capitalize()


class HealthProfile(BaseModel):
    user_id: str = ""
    sex: Optional[Sex] = None
    birth_date: Optional[date] = None
    conditions: list[Condition] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    medications: list[Medication] = Field(default_factory=list)
    family: list[FamilyMember] = Field(default_factory=list)
    updated_at: Optional[datetime] = None

    def age(self, today: Optional[date] = None) -> Optional[int]:
        if not self.birth_date:
            return None
        today = today or date.today()
        years = today.year - self.birth_date.year
        if (today.month, today.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years

    def affected(
        self, categories: set[str], max_degree: int = 2
    ) -> list[tuple[FamilyMember, Condition]]:
        """Relatives (within ``max_degree``) with a condition in ``categories``."""
        hits = []
        for member in self.family:
            if member.degree is None or member.degree > max_degree:
                continue
            for cond in member.conditions:
                if cond.category in categories:
                    hits.append((member, cond))
        return hits

    def own_conditions(self, categories: set[str]) -> list[Condition]:
        return [c for c in self.conditions if c.category in categories]

    def latest(self, code: str) -> Optional[Observation]:
        obs = [o for o in self.observations if o.code == code]
        if not obs:
            return None
        return max(obs, key=lambda o: o.effective_date or date.min)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


class Level(str, Enum):
    HIGH = "high"  # discuss with a clinician soon
    MODERATE = "moderate"  # bring up at the next routine visit
    INFO = "info"  # good to know / improve your record


LEVEL_ORDER = {Level.HIGH: 0, Level.MODERATE: 1, Level.INFO: 2}


class Reference(BaseModel):
    title: str
    url: str


class Insight(BaseModel):
    rule_id: str
    category: str
    level: Level
    title: str
    summary: str
    evidence: list[str] = Field(default_factory=list)
    recommendation: str
    references: list[Reference] = Field(default_factory=list)


class InsightReport(BaseModel):
    generated_at: datetime
    insights: list[Insight]
    pedigree: dict
    disclaimer: str
