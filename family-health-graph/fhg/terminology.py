"""Terminology normalization.

Maps free text ("my mom's breast cancer"), ICD-10-CM codes and SNOMED CT codes
onto a small set of canonical condition categories that the insight rules
understand. Also maps LOINC lab codes onto canonical observation codes.

The concept list is intentionally small and focused on conditions where family
history changes preventive care. Extending it is a data change, not a code change.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

SNOMED = "http://snomed.info/sct"
ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
ICD10_ALT = "http://hl7.org/fhir/sid/icd-10"
LOINC = "http://loinc.org"


@dataclass(frozen=True)
class Concept:
    category: str
    display: str
    group: str
    synonyms: tuple[str, ...]
    icd10_prefixes: tuple[str, ...] = ()
    snomed_codes: tuple[str, ...] = ()


CONCEPTS: tuple[Concept, ...] = (
    # --- cancers -----------------------------------------------------------
    Concept("breast_cancer", "Breast cancer", "cancer",
            ("breast cancer", "breast carcinoma", "carcinoma of breast", "ductal carcinoma",
             "lobular carcinoma", "malignant neoplasm of breast"),
            ("C50",), ("254837009",)),
    Concept("ovarian_cancer", "Ovarian cancer", "cancer",
            ("ovarian cancer", "ovary cancer", "cancer of the ovary", "ovarian carcinoma",
             "fallopian tube cancer", "primary peritoneal cancer", "malignant neoplasm of ovary"),
            ("C56", "C57.0"), ("363443007",)),
    Concept("pancreatic_cancer", "Pancreatic cancer", "cancer",
            ("pancreatic cancer", "pancreas cancer", "cancer of the pancreas",
             "pancreatic adenocarcinoma", "malignant neoplasm of pancreas"),
            ("C25",), ("363418001",)),
    Concept("prostate_cancer", "Prostate cancer", "cancer",
            ("prostate cancer", "cancer of the prostate", "prostate carcinoma",
             "malignant neoplasm of prostate"),
            ("C61",), ("399068003",)),
    Concept("colorectal_cancer", "Colorectal cancer", "cancer",
            ("colorectal cancer", "colon cancer", "rectal cancer", "bowel cancer",
             "cancer of the colon", "colorectal carcinoma", "colon carcinoma",
             "malignant neoplasm of colon"),
            ("C18", "C19", "C20"), ("363406005", "363351006")),
    Concept("endometrial_cancer", "Endometrial (uterine) cancer", "cancer",
            ("endometrial cancer", "uterine cancer", "cancer of the uterus", "womb cancer",
             "endometrial carcinoma"),
            ("C54", "C55")),
    Concept("stomach_cancer", "Stomach cancer", "cancer",
            ("stomach cancer", "gastric cancer"), ("C16",), ("363349007",)),
    Concept("melanoma", "Melanoma", "cancer", ("melanoma",), ("C43",), ("372244006",)),
    Concept("cancer_unspecified", "Cancer (type not recorded)", "cancer",
            ("cancer", "tumor", "tumour", "malignancy")),
    # --- cardiovascular ----------------------------------------------------
    Concept("coronary_artery_disease", "Coronary artery disease / heart attack", "cardiovascular",
            ("coronary artery disease", "coronary heart disease", "heart attack",
             "myocardial infarction", "cad", "angina", "ischemic heart disease",
             "ischaemic heart disease", "heart disease", "bypass surgery", "cabg"),
            ("I20", "I21", "I22", "I23", "I24", "I25"), ("53741008", "22298006")),
    Concept("congenital_heart_disease", "Congenital heart disease", "cardiovascular",
            ("congenital heart disease", "congenital heart defect"),
            ("Q20", "Q21", "Q22", "Q23", "Q24")),
    Concept("stroke", "Stroke", "cardiovascular",
            ("stroke", "cerebrovascular accident", "cva", "ischemic stroke"),
            ("I63", "I64"), ("230690007",)),
    Concept("hypertension", "High blood pressure", "cardiovascular",
            ("hypertension", "high blood pressure", "htn"), ("I10",), ("38341003",)),
    Concept("familial_hypercholesterolemia", "Familial hypercholesterolemia", "cardiovascular",
            ("familial hypercholesterolemia", "familial hypercholesterolaemia"),
            ("E78.01",), ("398036000",)),
    Concept("hyperlipidemia", "High cholesterol", "cardiovascular",
            ("high cholesterol", "hyperlipidemia", "hypercholesterolemia", "dyslipidemia"),
            ("E78.0", "E78.1", "E78.2", "E78.4", "E78.5"), ("55822004",)),
    # --- metabolic ---------------------------------------------------------
    Concept("type_1_diabetes", "Type 1 diabetes", "metabolic",
            ("type 1 diabetes", "type i diabetes", "juvenile diabetes", "diabetes mellitus type 1",
             "type 1 diabetes mellitus", "t1d"),
            ("E10",), ("46635009",)),
    Concept("type_2_diabetes", "Type 2 diabetes", "metabolic",
            ("type 2 diabetes", "type ii diabetes", "diabetes mellitus type 2",
             "type 2 diabetes mellitus", "t2d", "adult-onset diabetes", "diabetes"),
            ("E11",), ("44054006",)),
    # --- genetic / known hereditary syndromes --------------------------------
    Concept("hboc_variant", "Known BRCA1/BRCA2 variant", "genetic",
            ("brca1", "brca2", "brca mutation", "brca gene", "brca variant", "brca"),
            ("Z15.01", "Z15.02")),
    Concept("lynch_syndrome", "Lynch syndrome", "genetic",
            ("lynch syndrome", "hnpcc", "hereditary nonpolyposis colorectal cancer")),
    # --- safety ------------------------------------------------------------
    Concept("malignant_hyperthermia", "Malignant hyperthermia / anesthesia reaction", "safety",
            ("malignant hyperthermia", "bad reaction to anesthesia", "reaction to anesthesia",
             "anesthesia reaction", "reaction to anaesthesia"),
            ("T88.3",)),
    # --- neurological (informational only) -----------------------------------
    Concept("dementia", "Alzheimer's disease / dementia", "neurological",
            ("alzheimer's disease", "alzheimer's", "alzheimers", "dementia"), ("G30",)),
)

CONCEPTS_BY_CATEGORY: dict[str, Concept] = {c.category: c for c in CONCEPTS}

# Longest synonym first so "colon cancer" wins over "cancer".
_SYNONYMS: list[tuple[str, str]] = sorted(
    ((syn, c.category) for c in CONCEPTS for syn in c.synonyms),
    key=lambda pair: -len(pair[0]),
)
_SYNONYM_RE = re.compile(
    "|".join(f"(?<![a-z0-9]){re.escape(s)}(?![a-z0-9])" for s, _ in _SYNONYMS)
)
_SYNONYM_LOOKUP = {s: cat for s, cat in _SYNONYMS}

# "breast and ovarian cancer" -> "breast cancer and ovarian cancer"
_CANCER_SITES = "breast|ovarian|colon|prostate|pancreatic|stomach|uterine|endometrial|rectal|bowel"
_SHARED_NOUN_RE = re.compile(
    rf"\b({_CANCER_SITES})\s*(?:,|and|or|&)\s*({_CANCER_SITES})\s+cancers?\b"
)


def clean_text(text: str) -> str:
    text = text.lower().replace("’", "'").replace("‘", "'")
    text = _SHARED_NOUN_RE.sub(r"\1 cancer and \2 cancer", text)
    return re.sub(r"cancers\b", "cancer", text)


def find_conditions(text: str) -> list[tuple[str, str, int, int]]:
    """Return (category, matched_text, start, end) for each condition mention.

    ``text`` must already be passed through :func:`clean_text`.
    """
    return [
        (_SYNONYM_LOOKUP[m.group(0)], m.group(0), m.start(), m.end())
        for m in _SYNONYM_RE.finditer(text)
    ]


def category_from_text(text: str) -> Optional[str]:
    hits = find_conditions(clean_text(text))
    if not hits:
        return None
    # Prefer the most specific (non-generic) match.
    specific = [h for h in hits if h[0] != "cancer_unspecified"]
    return (specific or hits)[0][0]


def category_from_code(system: Optional[str], code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    code = code.strip()
    if system == SNOMED:
        for c in CONCEPTS:
            if code in c.snomed_codes:
                return c.category
        return None
    if system in (ICD10, ICD10_ALT) or (system is None and re.match(r"^[A-Z]\d", code.upper())):
        code = code.upper()
        best: tuple[int, Optional[str]] = (0, None)
        for c in CONCEPTS:
            for prefix in c.icd10_prefixes:
                if code.startswith(prefix) and len(prefix) > best[0]:
                    best = (len(prefix), c.category)
        return best[1]
    return None


def primary_coding(category: str) -> Optional[tuple[str, str]]:
    """A (system, code) pair to use when exporting a category to FHIR."""
    concept = CONCEPTS_BY_CATEGORY.get(category)
    if not concept:
        return None
    if concept.snomed_codes:
        return SNOMED, concept.snomed_codes[0]
    if concept.icd10_prefixes:
        return ICD10, concept.icd10_prefixes[0]
    return None


# --- observations -----------------------------------------------------------

LOINC_TO_OBSERVATION: dict[str, str] = {
    "13457-7": "ldl_cholesterol",
    "18262-6": "ldl_cholesterol",
    "2089-1": "ldl_cholesterol",
    "2093-3": "total_cholesterol",
    "2085-9": "hdl_cholesterol",
    "10835-7": "lipoprotein_a",
    "4548-4": "hba1c",
    "17856-6": "hba1c",
    "39156-5": "bmi",
    "8480-6": "systolic_bp",
    "8462-4": "diastolic_bp",
}
BP_PANEL_CODES = {"85354-9", "55284-4"}

OBSERVATION_TO_LOINC: dict[str, tuple[str, str]] = {
    "ldl_cholesterol": ("13457-7", "LDL cholesterol"),
    "total_cholesterol": ("2093-3", "Total cholesterol"),
    "hdl_cholesterol": ("2085-9", "HDL cholesterol"),
    "lipoprotein_a": ("10835-7", "Lipoprotein(a)"),
    "hba1c": ("4548-4", "Hemoglobin A1c"),
    "bmi": ("39156-5", "Body mass index"),
    "systolic_bp": ("8480-6", "Systolic blood pressure"),
    "diastolic_bp": ("8462-4", "Diastolic blood pressure"),
}

OBSERVATION_ALIASES: dict[str, str] = {
    "ldl": "ldl_cholesterol",
    "ldl cholesterol": "ldl_cholesterol",
    "ldl-c": "ldl_cholesterol",
    "a1c": "hba1c",
    "hba1c": "hba1c",
    "hemoglobin a1c": "hba1c",
    "bmi": "bmi",
    "systolic": "systolic_bp",
    "diastolic": "diastolic_bp",
    "lp(a)": "lipoprotein_a",
}


def ldl_mg_dl(value: float, unit: str) -> float:
    """Normalize an LDL value to mg/dL."""
    if "mmol" in (unit or "").lower():
        return value * 38.67
    return value
