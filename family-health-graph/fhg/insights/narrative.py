"""Plain-language summary of an insight report.

Design choice: the *rules* decide what is medically true for this user; the
language model only rewrites those already-computed, de-identified insights
into friendlier prose. It never sees raw records or relative names, and it is
instructed not to add claims. If no API key is configured, or the user hasn't
consented to AI processing, a deterministic template is used instead.

Production note: sending health information to an LLM provider requires a
signed BAA (if operating under HIPAA) and a data-processing agreement.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from ..models import InsightReport, Level

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You turn structured, pre-computed health insights into a short, warm, \
plain-language summary (about an 8th-grade reading level) for the person they are about.

Rules you must follow:
- Use ONLY the facts, numbers and recommendations present in the JSON you are given. \
Do not add risks, statistics, conditions, tests or advice that are not in it.
- Do not diagnose and do not say the person "has" or "will get" anything.
- Lead with the most important item ("high" level first). Group related items.
- Keep it under 250 words. Use short paragraphs or a brief bulleted list.
- End by encouraging them to share this with their clinician or a genetic counselor."""


def _template(report: InsightReport) -> str:
    if not report.insights:
        return ("Nothing in your current record stands out. Adding more family history, "
                "especially ages at diagnosis, helps keep these insights accurate.")
    heads = {Level.HIGH: "Worth discussing soon", Level.MODERATE: "Bring up at your next visit",
             Level.INFO: "Good to know"}
    lines = []
    for level in (Level.HIGH, Level.MODERATE, Level.INFO):
        items = [i for i in report.insights if i.level == level]
        if items:
            lines.append(f"{heads[level]}:")
            lines.extend(f"- {i.title}. {i.recommendation}" for i in items)
    lines.append("")
    lines.append("Share this summary with your clinician; they can put it in the context of your full history.")
    return "\n".join(lines)


def _llm_payload(report: InsightReport) -> str:
    # Only derived insight content; no identifiers, names, or raw records.
    return json.dumps([
        {"level": i.level.value, "title": i.title, "summary": i.summary,
         "evidence": i.evidence, "recommendation": i.recommendation}
        for i in report.insights
    ], indent=2)


def summarize(report: InsightReport, allow_llm: bool, client: Optional[object] = None) -> dict:
    """Return ``{"text": ..., "generated_by": "template" | "<model id>"}``."""
    if not allow_llm or not report.insights:
        return {"text": _template(report), "generated_by": "template"}

    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return {"text": _template(report), "generated_by": "template"}
        try:
            import anthropic
        except ImportError:
            return {"text": _template(report), "generated_by": "template"}
        client = anthropic.Anthropic()

    model = os.environ.get("FHG_LLM_MODEL", DEFAULT_MODEL)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "Insights JSON:\n" + _llm_payload(report)}],
        )
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
        if text:
            return {"text": text, "generated_by": model}
    except Exception:
        log.exception("LLM summary failed; falling back to template")
    return {"text": _template(report), "generated_by": "template"}
