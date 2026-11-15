"""Parse free-text family history into structured relatives and conditions.

Handles the way people actually describe family history, e.g.::

    My mom was diagnosed with breast cancer at 46.
    My mother's sister had ovarian cancer in her late 50s.
    Dad had a heart attack at 51 and also has type 2 diabetes.
    Grandpa on my father's side died of colon cancer when he was 72.
    My mother and sister both have high cholesterol.

The parser is deterministic and conservative: anything it is unsure about is
left unset (e.g. unknown age) rather than guessed, and the API offers a
preview mode so the user can confirm before anything is saved.
"""
from __future__ import annotations

import re
from typing import Optional

from ..models import Condition, FamilyMember, HealthProfile, Relationship
from ..terminology import clean_text, find_conditions

_PARENT = {"mother": ("mother", "mom", "mum", "mommy"), "father": ("father", "dad", "daddy")}
_SIDE_OF = {"mother": "maternal", "father": "paternal"}

_BASE_WORDS: dict[str, Relationship] = {
    "maternal grandmother": Relationship.MATERNAL_GRANDMOTHER,
    "maternal grandfather": Relationship.MATERNAL_GRANDFATHER,
    "paternal grandmother": Relationship.PATERNAL_GRANDMOTHER,
    "paternal grandfather": Relationship.PATERNAL_GRANDFATHER,
    "maternal aunt": Relationship.MATERNAL_AUNT,
    "maternal uncle": Relationship.MATERNAL_UNCLE,
    "paternal aunt": Relationship.PATERNAL_AUNT,
    "paternal uncle": Relationship.PATERNAL_UNCLE,
    "maternal cousin": Relationship.MATERNAL_COUSIN,
    "paternal cousin": Relationship.PATERNAL_COUSIN,
    "half-sister": Relationship.HALF_SISTER,
    "half sister": Relationship.HALF_SISTER,
    "half-brother": Relationship.HALF_BROTHER,
    "half brother": Relationship.HALF_BROTHER,
    "grandmother": Relationship.GRANDMOTHER,
    "grandma": Relationship.GRANDMOTHER,
    "granny": Relationship.GRANDMOTHER,
    "grandfather": Relationship.GRANDFATHER,
    "grandpa": Relationship.GRANDFATHER,
    "aunt": Relationship.AUNT,
    "auntie": Relationship.AUNT,
    "uncle": Relationship.UNCLE,
    "cousin": Relationship.COUSIN,
    "niece": Relationship.NIECE,
    "nephew": Relationship.NEPHEW,
    "sister": Relationship.SISTER,
    "brother": Relationship.BROTHER,
    "daughter": Relationship.DAUGHTER,
    "son": Relationship.SON,
}
for _p, _words in _PARENT.items():
    for _w in _words:
        _BASE_WORDS[_w] = Relationship(_p)

# "<parent>'s <relative>" -> sided relationship
_POSSESSIVE_TARGETS = {
    "mother": "grandmother", "mom": "grandmother", "mum": "grandmother",
    "father": "grandfather", "dad": "grandfather",
    "sister": "aunt", "brother": "uncle",
}
for _p, _words in _PARENT.items():
    side = _SIDE_OF[_p]
    for _w in _words:
        for _target, _rel in _POSSESSIVE_TARGETS.items():
            _BASE_WORDS[f"{_w}'s {_target}"] = Relationship(f"{side}_{_rel}")

_REL_PHRASES = sorted(_BASE_WORDS, key=len, reverse=True)
_REL_RE = re.compile("|".join(rf"\b{re.escape(p)}\b" for p in _REL_PHRASES))

_SIDE_RE = re.compile(
    r"(?:on\s+)?(?:my\s+|the\s+)?(?:(mother|mom|mum|father|dad)'s|(maternal|paternal))\s+side"
)
_DISTINCT_RE = re.compile(r"(?:other|another|second|older|younger|oldest|youngest|twin)\s+$")
_SELF_RE = re.compile(r"(?<![a-z'])(i|i've|i'm|me|myself)(?![a-z'])")
_DECEASED_RE = re.compile(r"\b(died|passed away|passed|deceased|death)\b")

_AGE_PATTERNS: list[tuple[re.Pattern, bool]] = [
    (re.compile(r"\b(?:at|aged?|age of)\s+(?:about|around|roughly|approximately|~)\s*(\d{1,3})\b"), True),
    (re.compile(r"\b(?:at|aged?|age of)\s+(?:age\s+)?(\d{1,3})\b"), False),
    (re.compile(r"\bwhen (?:she|he|they) (?:was|were) (?:about |around )?(\d{1,3})\b"), False),
    (re.compile(r"\((?:age\s*|aged\s*)?(\d{1,3})\)"), False),
]
_DECADE_RE = re.compile(r"\bin (?:her|his|their) (early |mid |mid-|late )?(\d)0'?s\b")
_DECADE_OFFSET = {"early ": 2, "mid ": 5, "mid-": 5, "late ": 8, None: 5}

_SINGULAR = {
    Relationship.MOTHER, Relationship.FATHER,
    Relationship.MATERNAL_GRANDMOTHER, Relationship.MATERNAL_GRANDFATHER,
    Relationship.PATERNAL_GRANDMOTHER, Relationship.PATERNAL_GRANDFATHER,
}

_UNSIDED_TO_SIDED = {
    Relationship.GRANDMOTHER: "grandmother",
    Relationship.GRANDFATHER: "grandfather",
    Relationship.AUNT: "aunt",
    Relationship.UNCLE: "uncle",
    Relationship.COUSIN: "cousin",
}


def _find_age(segment: str) -> tuple[Optional[int], bool]:
    for pattern, estimated in _AGE_PATTERNS:
        m = pattern.search(segment)
        if m:
            age = int(m.group(1))
            if 0 < age < 120:
                return age, estimated
    m = _DECADE_RE.search(segment)
    if m:
        return int(m.group(2)) * 10 + _DECADE_OFFSET[m.group(1)], True
    return None, False


def parse_relationship(text: str) -> Optional[Relationship]:
    """Parse a relationship label such as 'Maternal Aunt' or "mom's mom"."""
    raw = text.strip().lower()
    try:
        return Relationship(raw.replace(" ", "_").replace("-", "_"))
    except ValueError:
        pass
    cleaned = clean_text(raw)
    side_m = _SIDE_RE.search(cleaned)
    side = None
    if side_m:
        side = side_m.group(2) or _SIDE_OF["mother" if side_m.group(1) in _PARENT["mother"] else "father"]
        cleaned = cleaned[: side_m.start()] + cleaned[side_m.end():]
    m = _REL_RE.search(cleaned)
    if not m:
        return None
    rel = _BASE_WORDS[m.group(0)]
    if side and rel in _UNSIDED_TO_SIDED:
        rel = Relationship(f"{side}_{_UNSIDED_TO_SIDED[rel]}")
    return rel


def parse_family_history_text(text: str) -> HealthProfile:
    """Return a profile fragment containing what the text describes."""
    fragment = HealthProfile()
    members: list[FamilyMember] = []

    def get_member(rel: Relationship, distinct: bool) -> FamilyMember:
        if not distinct or rel in _SINGULAR:
            for m in members:
                if m.relationship == rel:
                    return m
        member = FamilyMember(relationship=rel, source="text")
        members.append(member)
        return member

    for raw_sentence in re.split(r"[.\n;!?]+", text):
        sentence = clean_text(raw_sentence).strip()
        if not sentence:
            continue

        side = None
        side_m = _SIDE_RE.search(sentence)
        if side_m:
            word = side_m.group(1)
            side = side_m.group(2) or ("maternal" if word in _PARENT["mother"] else "paternal")
            # Blank out the side phrase so "mother's" there is not read as a relative.
            sentence = sentence[: side_m.start()] + " " * (side_m.end() - side_m.start()) + sentence[side_m.end():]

        conditions = find_conditions(sentence)
        if not conditions:
            continue

        rel_matches = list(_REL_RE.finditer(sentence))
        targets: list[FamilyMember] = []
        for m in rel_matches:
            rel = _BASE_WORDS[m.group(0)]
            if side and rel in _UNSIDED_TO_SIDED:
                rel = Relationship(f"{side}_{_UNSIDED_TO_SIDED[rel]}")
            distinct = bool(_DISTINCT_RE.search(sentence[max(0, m.start() - 12): m.start()]))
            member = get_member(rel, distinct)
            if member not in targets:
                targets.append(member)

        is_self = not targets and bool(_SELF_RE.search(sentence))
        if not targets and not is_self:
            continue

        deceased = bool(_DECEASED_RE.search(sentence))
        lone_age = _find_age(sentence)

        for i, (category, matched, _start, end) in enumerate(conditions):
            next_start = conditions[i + 1][2] if i + 1 < len(conditions) else len(sentence)
            age, estimated = _find_age(sentence[end:next_start])
            if age is None and len(conditions) == 1:
                age, estimated = lone_age
            cond_kwargs = dict(
                name=matched, category=category, onset_age=age,
                age_estimated=estimated, source="text",
            )
            if is_self:
                fragment.conditions.append(Condition(**cond_kwargs))
                continue
            for member in targets:
                if any(c.category == category for c in member.conditions):
                    continue
                member.conditions.append(Condition(**cond_kwargs))
                if deceased:
                    member.deceased = True

    fragment.family = members
    return fragment
