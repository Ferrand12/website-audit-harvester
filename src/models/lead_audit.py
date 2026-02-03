from __future__ import annotations

import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from pydantic import BaseModel, Field


class PSIScores(BaseModel):
    performance: int | None = None
    seo: int | None = None
    accessibility: int | None = None
    best_practices: int | None = None


class CWV(BaseModel):
    lcp_ms: int | None = None
    inp_ms: int | None = None
    cls: float | None = None
    ttfb_ms: int | None = None
    fcp_ms: int | None = None


class OpportunityItem(BaseModel):
    id: str
    title: str
    impact: str


class TrackingInfo(BaseModel):
    ga4: bool = False
    gtm: bool = False
    ua: bool = False
    meta_pixel: bool = False
    hotjar: bool = False
    clarity: bool = False
    segment: bool = False
    mixpanel: bool = False
    linkedin_insight: bool = False
    tiktok_pixel: bool = False


class TechInfo(BaseModel):
    cms: str | None = None
    framework: str | None = None
    ecommerce: str | None = None
    hosting_hints: list[str] = []


class HTMLMeta(BaseModel):
    http_status: int | None = None
    final_url: str | None = None
    response_time_ms: int | None = None
    third_party_script_count: int = 0


class BusinessSignals(BaseModel):
    """Business ability-to-pay signals detected from homepage."""
    has_careers_page: bool = False
    has_pricing_page: bool = False
    has_services_page: bool = False
    has_contact_form: bool = False
    has_ecommerce: bool = False
    has_multiple_locations_hint: bool = False
    languages_hint: list[str] = []
    phone_present: bool = False
    email_present: bool = False
    social_links_count: int = 0


class PainItem(BaseModel):
    pain_id: str
    severity: str  # "high", "medium", "low"
    business_impact: str
    proof: str


class OutreachMessage(BaseModel):
    subject: str
    body: str


class LeadAudit(BaseModel):
    lead_id: str
    url: str
    domain: str
    timestamp_utc: str
    status: str
    strategy: str
    score_letter: str | None = None
    score_points: int = 0
    score_reasons: list[str] = []
    roi_priority: str | None = None  # "high", "medium", "low"
    roi_reasons: list[str] = []
    scores: PSIScores = PSIScores()
    cwv: CWV = CWV()
    psi_opportunities: list[OpportunityItem] = []
    psi_diagnostics: list[OpportunityItem] = []
    tracking: TrackingInfo = TrackingInfo()
    # Evidence keyed by tracker name: {"gtm": ["GTM-ABC123"], "ga4": ["G-XYZ"]}
    tracking_evidence: dict[str, list[str]] = Field(default_factory=dict)
    tech: TechInfo = TechInfo()
    # Confidence per category: {"cms": 0.9, "framework": 0.6, "ecommerce": 0.0, "hosting": 0.8}
    tech_confidence: dict[str, float] = Field(default_factory=dict)
    html_meta: HTMLMeta = HTMLMeta()
    business_signals: BusinessSignals = BusinessSignals()
    pains: list[PainItem] = []
    outreach_en: OutreachMessage | None = None
    errors: list[str] = []

    @classmethod
    def from_url(cls, url: str, strategy: str) -> LeadAudit:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        return cls(
            lead_id=str(uuid.uuid4()),
            url=url,
            domain=parsed.netloc or parsed.path.split("/")[0],
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            status="pending",
            strategy=strategy,
        )
