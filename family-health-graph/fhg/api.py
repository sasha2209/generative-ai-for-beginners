"""HTTP API (FastAPI)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from .ingest import CsvImportError, parse_family_csv, parse_family_history_text, parse_fhir, to_fhir_bundle
from .insights import generate_insights, summarize
from .merge import merge_into
from .models import Condition, FamilyMember, HealthProfile, Observation, Relationship, Sex
from .security import constant_time_equals, load_cipher, pseudonym
from .sharing import CONSENT_LLM, CONSENT_RESEARCH, PARTNERS, deidentify, partner_payload, share_scope
from .storage import Store
from .terminology import OBSERVATION_ALIASES, category_from_text

PKG_DIR = Path(__file__).parent
MAX_INGEST_BYTES = 5 * 1024 * 1024


@dataclass
class Settings:
    db_path: str = "data/fhg.sqlite3"
    encryption_key: Optional[str] = None
    key_file: str = "data/dev.key"
    admin_key: Optional[str] = None
    pseudonym_secret: str = "dev-pseudonym-secret"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=os.environ.get("FHG_DB_PATH", cls.db_path),
            encryption_key=os.environ.get("FHG_ENCRYPTION_KEY"),
            key_file=os.environ.get("FHG_KEY_FILE", cls.key_file),
            admin_key=os.environ.get("FHG_ADMIN_KEY"),
            pseudonym_secret=os.environ.get("FHG_PSEUDONYM_SECRET", cls.pseudonym_secret),
        )


# --- request bodies -------------------------------------------------------------

class TextIn(BaseModel):
    text: str = Field(..., max_length=50_000)


class CsvIn(BaseModel):
    content: str = Field(..., max_length=MAX_INGEST_BYTES)


class DemographicsIn(BaseModel):
    sex: Optional[Sex] = None
    birth_date: Optional[date] = None


class ConditionIn(BaseModel):
    name: str
    onset_age: Optional[int] = Field(None, ge=0, le=120)


class FamilyMemberIn(BaseModel):
    relationship: Relationship
    name: Optional[str] = None
    sex: Optional[Sex] = None
    deceased: Optional[bool] = None
    conditions: list[ConditionIn] = Field(default_factory=list)


class ObservationIn(BaseModel):
    code: str
    value: float
    unit: str = ""
    effective_date: Optional[date] = None


class ConsentIn(BaseModel):
    scope: str
    granted: bool


def _dump(model: Any) -> Any:
    return model.model_dump(mode="json")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Store(settings.db_path, load_cipher(settings.encryption_key, Path(settings.key_file)))
    app = FastAPI(
        title="Family Health Graph",
        version="0.1.0",
        description="Ingest personal and family medical history, store it securely, and "
                    "generate guideline-based, explainable preventive-care insights.",
    )
    app.state.store = store
    valid_scopes = {CONSENT_LLM, CONSENT_RESEARCH} | {share_scope(p) for p in PARTNERS}

    def current_user(authorization: Optional[str] = Header(None)) -> str:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "Missing bearer token")
        user_id = store.user_for_token(authorization[7:].strip())
        if not user_id:
            raise HTTPException(401, "Invalid token")
        return user_id

    def ingest(user_id: str, source: str, raw: str, fragment: HealthProfile,
               preview: bool, warnings: Optional[list[str]] = None) -> dict:
        if preview:
            return {"preview": True, "parsed": _dump(fragment), "warnings": warnings or []}
        with store.write_lock:
            profile = store.get_profile(user_id)
            stats = merge_into(profile, fragment)
            store.save_profile(profile)
        event_id = store.record_ingest(user_id, source, raw, stats)
        store.audit(user_id, "user", f"ingest.{source}", {"event_id": event_id, **stats})
        return {"preview": False, "ingest_id": event_id, "merged": stats, "warnings": warnings or []}

    # --- UI & meta ---------------------------------------------------------
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        return (PKG_DIR / "static" / "index.html").read_text()

    @app.get("/sample/{name}", include_in_schema=False)
    def sample(name: str):
        files = {"fhir": "fhir_bundle.json", "text": "family_history.txt", "csv": "family.csv"}
        if name not in files:
            raise HTTPException(404)
        content = (PKG_DIR / "sample_data" / files[name]).read_text()
        return JSONResponse(json.loads(content) if name == "fhir" else {"content": content})

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    # --- accounts --------------------------------------------------------------
    @app.post("/v1/users", status_code=201)
    def create_user() -> dict:
        user_id, token = store.create_user()
        return {"user_id": user_id, "token": token,
                "note": "Store this token securely; it cannot be recovered."}

    @app.delete("/v1/me", status_code=204)
    def delete_me(user_id: str = Depends(current_user)) -> None:
        store.delete_user(user_id)

    # --- profile -----------------------------------------------------------------
    @app.get("/v1/profile")
    def get_profile(user_id: str = Depends(current_user)) -> dict:
        store.audit(user_id, "user", "profile.read")
        return _dump(store.get_profile(user_id))

    @app.put("/v1/profile/demographics")
    def set_demographics(body: DemographicsIn, user_id: str = Depends(current_user)) -> dict:
        with store.write_lock:
            profile = store.get_profile(user_id)
            if body.sex is not None:
                profile.sex = body.sex
            if body.birth_date is not None:
                profile.birth_date = body.birth_date
            profile.touch()
            store.save_profile(profile)
        store.audit(user_id, "user", "profile.demographics")
        return _dump(profile)

    @app.post("/v1/family", status_code=201)
    def add_family_member(body: FamilyMemberIn, user_id: str = Depends(current_user)) -> dict:
        member = FamilyMember(
            relationship=body.relationship, name=body.name, sex=body.sex, deceased=body.deceased,
            conditions=[Condition(name=c.name, category=category_from_text(c.name),
                                  onset_age=c.onset_age) for c in body.conditions],
        )
        return ingest(user_id, "manual", body.model_dump_json(),
                      HealthProfile(family=[member]), preview=False)

    @app.delete("/v1/family/{member_id}", status_code=204)
    def delete_family_member(member_id: str, user_id: str = Depends(current_user)) -> None:
        with store.write_lock:
            profile = store.get_profile(user_id)
            before = len(profile.family)
            profile.family = [m for m in profile.family if m.id != member_id]
            if len(profile.family) == before:
                raise HTTPException(404, "No such relative")
            profile.touch()
            store.save_profile(profile)
        store.audit(user_id, "user", "family.delete", {"member_id": member_id})

    @app.post("/v1/observations", status_code=201)
    def add_observation(body: ObservationIn, user_id: str = Depends(current_user)) -> dict:
        code = OBSERVATION_ALIASES.get(body.code.strip().lower(), body.code.strip().lower())
        obs = Observation(code=code, value=body.value, unit=body.unit, effective_date=body.effective_date)
        return ingest(user_id, "manual", body.model_dump_json(),
                      HealthProfile(observations=[obs]), preview=False)

    # --- ingestion ---------------------------------------------------------------
    @app.post("/v1/ingest/fhir")
    def ingest_fhir(bundle: dict, preview: bool = Query(False),
                    user_id: str = Depends(current_user)) -> dict:
        raw = json.dumps(bundle)
        if len(raw) > MAX_INGEST_BYTES:
            raise HTTPException(413, "Bundle too large")
        try:
            fragment = parse_fhir(bundle)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return ingest(user_id, "fhir", raw, fragment, preview)

    @app.post("/v1/ingest/text")
    def ingest_text(body: TextIn, preview: bool = Query(False),
                    user_id: str = Depends(current_user)) -> dict:
        fragment = parse_family_history_text(body.text)
        warnings = [] if (fragment.family or fragment.conditions) else [
            "No relatives or conditions were recognised. Try sentences like "
            "'My mother had breast cancer at 46.'"
        ]
        return ingest(user_id, "text", body.text, fragment, preview, warnings)

    @app.post("/v1/ingest/csv")
    def ingest_csv(body: CsvIn, preview: bool = Query(False),
                   user_id: str = Depends(current_user)) -> dict:
        try:
            fragment, warnings = parse_family_csv(body.content)
        except CsvImportError as exc:
            raise HTTPException(422, str(exc)) from exc
        return ingest(user_id, "csv", body.content, fragment, preview, warnings)

    @app.get("/v1/ingests")
    def list_ingests(user_id: str = Depends(current_user)) -> list[dict]:
        return store.list_ingests(user_id)

    # --- insights ------------------------------------------------------------------
    @app.get("/v1/insights")
    def insights(user_id: str = Depends(current_user)) -> dict:
        report = generate_insights(store.get_profile(user_id))
        store.audit(user_id, "system", "insights.generated", {"count": len(report.insights)})
        return _dump(report)

    @app.get("/v1/insights/summary")
    def insights_summary(user_id: str = Depends(current_user)) -> dict:
        report = generate_insights(store.get_profile(user_id))
        allow = store.has_consent(user_id, CONSENT_LLM)
        result = summarize(report, allow_llm=allow)
        store.audit(user_id, "system", "insights.summary", {"generated_by": result["generated_by"]})
        return result | {"disclaimer": report.disclaimer}

    # --- consent, sharing, portability ---------------------------------------------
    @app.get("/v1/consents")
    def list_consents(user_id: str = Depends(current_user)) -> dict:
        return {"consents": store.consents(user_id), "available_scopes": sorted(valid_scopes)}

    @app.post("/v1/consents")
    def set_consent(body: ConsentIn, user_id: str = Depends(current_user)) -> dict:
        if body.scope not in valid_scopes:
            raise HTTPException(422, f"Unknown scope. Valid scopes: {sorted(valid_scopes)}")
        store.set_consent(user_id, body.scope, body.granted)
        store.audit(user_id, "user", "consent." + ("grant" if body.granted else "revoke"),
                    {"scope": body.scope})
        return {"consents": store.consents(user_id)}

    @app.get("/v1/partners")
    def list_partners(user_id: str = Depends(current_user)) -> list[dict]:
        return [
            {"id": p.id, "name": p.name, "kind": p.kind, "purpose": p.purpose,
             "data_shared": sorted(p.categories),
             "consented": store.has_consent(user_id, share_scope(p.id))}
            for p in PARTNERS.values()
        ]

    @app.post("/v1/partners/{partner_id}/share")
    def share_with_partner(partner_id: str, user_id: str = Depends(current_user)) -> dict:
        partner = PARTNERS.get(partner_id)
        if not partner:
            raise HTTPException(404, "Unknown partner")
        if not store.has_consent(user_id, share_scope(partner_id)):
            raise HTTPException(403, f"Consent '{share_scope(partner_id)}' has not been granted")
        payload = partner_payload(store.get_profile(user_id), partner)
        store.audit(user_id, "system", "share.partner",
                    {"partner": partner_id, "categories": sorted(partner.categories)})
        # In production this payload is POSTed to the partner's FHIR endpoint.
        return {"status": "delivered (simulated)", "payload": payload}

    @app.get("/v1/export/fhir")
    def export_fhir(user_id: str = Depends(current_user)) -> dict:
        store.audit(user_id, "user", "export.fhir")
        return to_fhir_bundle(store.get_profile(user_id))

    @app.get("/v1/audit")
    def audit(user_id: str = Depends(current_user)) -> list[dict]:
        return store.audit_log(user_id)

    # --- research (admin) -------------------------------------------------------------
    @app.get("/admin/research/export")
    def research_export(x_admin_key: Optional[str] = Header(None)) -> dict:
        if not settings.admin_key or not x_admin_key or not constant_time_equals(
            x_admin_key, settings.admin_key
        ):
            raise HTTPException(403, "Admin key required")
        records = []
        for uid in store.users_with_consent(CONSENT_RESEARCH):
            records.append(deidentify(store.get_profile(uid), pseudonym(settings.pseudonym_secret, uid)))
            store.audit(uid, "admin", "research.export")
        return {"count": len(records), "records": records}

    return app
