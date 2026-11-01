"""Database model: SACCOs, officers, farmers, plots, consents, policies, KIAMIS records, audit.

Portable SQLAlchemy 2.0 models: SQLite for development and tests, PostgreSQL in
deployment. Plot geometry is stored as GeoJSON text plus a point, so it can move
to a PostGIS geometry column without changing the services.

Personal data rules: national ID and phone are only ever stored encrypted
(*_enc) with a keyed lookup hash (*_hash); no column holds them in clear.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Insurer(Base):
    """The underwriter: the paying customer. SACCOs distribute its cover; it sees only its own book."""
    __tablename__ = "insurer"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    # Where SACCOs send premium (M-Pesa paybill or bank account). Set by platform staff (agroshield-portal
    # set-paybill), never from a web form; None shows "the insurer's paybill (to be configured)".
    premium_paybill: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Sacco(Base):
    __tablename__ = "sacco"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    county: Mapped[str] = mapped_column(String(60), default="Nakuru")
    # Demo SACCOs hold fictional members only. Live enrolment (is_demo False) is blocked
    # until the consent wording has a recorded legal and Kiswahili review.
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    insurer_id: Mapped[int | None] = mapped_column(ForeignKey("insurer.id"))     # who underwrites its cover
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    insurer: Mapped[Insurer | None] = relationship()


class Officer(Base):
    __tablename__ = "officer"
    id: Mapped[int] = mapped_column(primary_key=True)
    # SACCO users (officer, manager) have a SACCO; underwriters have an insurer and no SACCO; AgroShield
    # operations staff (ops) have neither and look after what every SACCO sees (platform-wide weather advisories).
    sacco_id: Mapped[int | None] = mapped_column(ForeignKey("sacco.id"))
    insurer_id: Mapped[int | None] = mapped_column(ForeignKey("insurer.id"))
    username: Mapped[str] = mapped_column(String(60), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="officer")      # officer | manager | underwriter | ops
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    sacco: Mapped[Sacco | None] = relationship()
    insurer: Mapped[Insurer | None] = relationship()


class Farmer(Base):
    __tablename__ = "farmer"
    __table_args__ = (UniqueConstraint("sacco_id", "member_no"), UniqueConstraint("sacco_id", "national_id_hash"))
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    sacco_id: Mapped[int] = mapped_column(ForeignKey("sacco.id"))
    member_no: Mapped[str] = mapped_column(String(40))
    full_name: Mapped[str] = mapped_column(String(120))
    national_id_enc: Mapped[str] = mapped_column(Text)
    national_id_hash: Mapped[str] = mapped_column(String(64), index=True)
    national_id_masked: Mapped[str] = mapped_column(String(16))
    phone_enc: Mapped[str] = mapped_column(Text)
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    phone_masked: Mapped[str] = mapped_column(String(24))
    gender: Mapped[str] = mapped_column(String(16), default="undisclosed")   # for inclusion reporting only
    ward_id: Mapped[str] = mapped_column(String(40))
    kiamis_status: Mapped[str] = mapped_column(String(20), default="not_checked")
    language: Mapped[str] = mapped_column(String(2), default="en")          # en | sw, for SMS and USSD
    created_by: Mapped[int | None] = mapped_column(ForeignKey("officer.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    sacco: Mapped[Sacco] = relationship()
    plots: Mapped[list["Plot"]] = relationship(back_populates="farmer")
    policies: Mapped[list["Policy"]] = relationship(back_populates="farmer")
    consents: Mapped[list["Consent"]] = relationship(back_populates="farmer")


class Plot(Base):
    __tablename__ = "plot"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    farmer_id: Mapped[str] = mapped_column(ForeignKey("farmer.id"))
    ward_id: Mapped[str] = mapped_column(String(40))
    crop: Mapped[str] = mapped_column(String(30), default="maize")
    acreage: Mapped[float] = mapped_column(Float)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    polygon_geojson: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="officer")     # officer | csv | kiamis
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    farmer: Mapped[Farmer] = relationship(back_populates="plots")


class Consent(Base):
    """One record per purpose (Data Protection Act: purpose limitation), never overwritten."""
    __tablename__ = "consent"
    id: Mapped[int] = mapped_column(primary_key=True)
    farmer_id: Mapped[str] = mapped_column(ForeignKey("farmer.id"))
    purpose: Mapped[str] = mapped_column(String(40))          # data_processing | sms | loan_linked_payout
    granted: Mapped[bool] = mapped_column(Boolean)
    wording_version: Mapped[str] = mapped_column(String(20))
    wording_sha256: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(20))          # portal | csv | ussd
    captured_by: Mapped[int | None] = mapped_column(ForeignKey("officer.id"))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    farmer: Mapped[Farmer] = relationship(back_populates="consents")


class Policy(Base):
    __tablename__ = "policy"
    __table_args__ = (UniqueConstraint("plot_id", "season", "year"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    policy_no: Mapped[str] = mapped_column(String(40), unique=True)       # AgroShield certificate reference
    insurer_policy_number: Mapped[str | None] = mapped_column(String(60))  # issued by the underwriter, added later
    pay_ref: Mapped[str] = mapped_column(String(12), unique=True)          # M-Pesa account reference (max 12 chars)
    farmer_id: Mapped[str] = mapped_column(ForeignKey("farmer.id"))
    plot_id: Mapped[str] = mapped_column(ForeignKey("plot.id"))
    sacco_id: Mapped[int] = mapped_column(ForeignKey("sacco.id"))
    insurer_id: Mapped[int | None] = mapped_column(ForeignKey("insurer.id"), index=True)   # underwriter at sale
    ward_id: Mapped[str] = mapped_column(String(40))
    season: Mapped[str] = mapped_column(String(4))
    year: Mapped[int] = mapped_column(Integer)
    layers: Mapped[str] = mapped_column(String(8))                 # "B" or "A,B"
    acres: Mapped[float] = mapped_column(Float)
    sum_insured_per_acre: Mapped[float | None] = mapped_column(Float)
    gross_kes: Mapped[float] = mapped_column(Float)
    government_share_kes: Mapped[float] = mapped_column(Float)
    farmer_share_kes: Mapped[float] = mapped_column(Float)
    resilience_points: Mapped[float] = mapped_column(Float, default=0)
    discount_kes: Mapped[float] = mapped_column(Float)
    discount_funder: Mapped[str] = mapped_column(String(20))       # platform | seed_company | sacco
    farmer_pays_kes: Mapped[float] = mapped_column(Float)
    amount_due_kes: Mapped[int] = mapped_column(Integer)            # farmer share rounded up to whole KES
    paid_kes: Mapped[float] = mapped_column(Float, default=0.0)
    refund_due_kes: Mapped[float] = mapped_column(Float, default=0.0)
    sales_closes_on: Mapped[date] = mapped_column(Date)             # fully paid by this date, or no cover
    cover_active_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subsidy_status: Mapped[str] = mapped_column(String(20))
    payment_route: Mapped[str] = mapped_column(String(20))         # sacco_deduction | mpesa
    payment_status: Mapped[str] = mapped_column(String(20), default="pending")    # pending | part_paid | paid
    # pending_payment | active | lapsed_unpaid (window closed before full payment) | cancelled
    status: Mapped[str] = mapped_column(String(20), default="pending_payment")
    loan_linked: Mapped[bool] = mapped_column(Boolean, default=False)
    loan_ref: Mapped[str | None] = mapped_column(String(40))
    quote_id: Mapped[str] = mapped_column(String(40))
    quote_snapshot: Mapped[dict] = mapped_column(JSON)              # the full quote, as priced
    created_by: Mapped[int | None] = mapped_column(ForeignKey("officer.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    farmer: Mapped[Farmer] = relationship(back_populates="policies")
    plot: Mapped[Plot] = relationship()
    payments: Mapped[list["Payment"]] = relationship(back_populates="policy", order_by="Payment.received_at")

    @property
    def balance_kes(self) -> float:
        return max(0.0, round(self.amount_due_kes - self.paid_kes, 2))


class Payment(Base):
    """One premium payment (instalments allowed). Never edited; a reversal is a new row."""
    __tablename__ = "payment"
    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policy.id"))
    amount_kes: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(20))                 # mpesa | sacco_deduction
    reference: Mapped[str] = mapped_column(String(40), unique=True)  # M-Pesa receipt or SACCO deduction ref
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    within_window: Mapped[bool] = mapped_column(Boolean)
    recorded_by: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    policy: Mapped[Policy] = relationship(back_populates="payments")


class MpesaRequest(Base):
    """An M-Pesa STK push (Lipa na M-Pesa Online) sent to a farmer's phone."""
    __tablename__ = "mpesa_request"
    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policy.id"))
    amount_kes: Mapped[int] = mapped_column(Integer)
    phone_masked: Mapped[str] = mapped_column(String(24))
    merchant_request_id: Mapped[str] = mapped_column(String(60))
    checkout_request_id: Mapped[str] = mapped_column(String(60), unique=True)
    environment: Mapped[str] = mapped_column(String(12))            # simulated | sandbox | production
    # pending (waiting for Safaricom) | paid | failed | unconfirmed (still unknown after the last status check:
    # shown to officers and managers as "Payment not confirmed: check with the farmer" until a manager resolves it)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    result_code: Mapped[int | None] = mapped_column(Integer)
    result_desc: Mapped[str | None] = mapped_column(String(200))
    receipt: Mapped[str | None] = mapped_column(String(30))
    requested_by: Mapped[str] = mapped_column(String(60))           # officer username or "ussd"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Status re-checks (mpesa.recheck): how many STK queries so far and when the next one is due.
    query_attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_query_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_query_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_query_result: Mapped[str | None] = mapped_column(String(200))
    # A success callback that the status query has not confirmed yet: kept so a later confirmation credits it.
    callback_amount_kes: Mapped[float | None] = mapped_column(Float)
    callback_receipt: Mapped[str | None] = mapped_column(String(30))
    callback_txn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A manager's decision on an unconfirmed payment: paid (with the receipt the farmer shows) or not_paid.
    resolution: Mapped[str | None] = mapped_column(String(12))
    resolved_by: Mapped[str | None] = mapped_column(String(60))
    resolution_note: Mapped[str | None] = mapped_column(String(300))
    policy: Mapped[Policy] = relationship()


class SmsMessage(Base):
    """Outbox. The recipient is the farmer (phone decrypted only at send time); bodies hold no ID or phone."""
    __tablename__ = "sms_message"
    id: Mapped[int] = mapped_column(primary_key=True)
    farmer_id: Mapped[str] = mapped_column(ForeignKey("farmer.id"))
    policy_id: Mapped[str | None] = mapped_column(ForeignKey("policy.id"))
    template: Mapped[str] = mapped_column(String(30))
    language: Mapped[str] = mapped_column(String(2))
    body: Mapped[str] = mapped_column(String(320))
    dedupe_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(12), default="queued")    # queued | sent | logged | failed
    provider: Mapped[str | None] = mapped_column(String(20))
    provider_message_id: Mapped[str | None] = mapped_column(String(80))
    error: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    farmer: Mapped[Farmer] = relationship()


class KiamisRecord(Base):
    """KIAMIS data imported from a CSV export (manual fallback until an API exists)."""
    __tablename__ = "kiamis_record"
    id: Mapped[int] = mapped_column(primary_key=True)
    national_id_hash: Mapped[str] = mapped_column(String(64), unique=True)
    registered_acreage: Mapped[float | None] = mapped_column(Float)
    certified_seed_purchased: Mapped[bool] = mapped_column(Boolean, default=False)
    subsidy_eligible: Mapped[bool | None] = mapped_column(Boolean)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    source_sha256: Mapped[str] = mapped_column(String(64))


class AuditEvent(Base):
    __tablename__ = "audit_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    actor: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


# ------------------------------------------------------------------ milestone 7
class WardStatus(Base):
    """One monitoring run for a ward and season (agroshield_pricing.monitor). Never edited."""
    __tablename__ = "ward_status"
    id: Mapped[int] = mapped_column(primary_key=True)
    ward_id: Mapped[str] = mapped_column(String(40), index=True)
    season: Mapped[str] = mapped_column(String(4))
    year: Mapped[int] = mapped_column(Integer)
    as_of: Mapped[date] = mapped_column(Date)
    data_through: Mapped[date | None] = mapped_column(Date)
    mode: Mapped[str] = mapped_column(String(10))                  # live | replay
    phase: Mapped[str] = mapped_column(String(20))                 # before_season | waiting_for_rains | in_season | complete
    level: Mapped[str] = mapped_column(String(10))                 # none | normal | watch | alert | payout
    projected_wrsi: Mapped[float | None] = mapped_column(Float)
    projected_share: Mapped[float] = mapped_column(Float, default=0.0)
    index_version: Mapped[str] = mapped_column(String(20))
    inputs_sha256: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)                     # the full monitor output
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Payout(Base):
    """A payout on one policy, created only from a CONFIRMED trigger."""
    __tablename__ = "payout"
    __table_args__ = (UniqueConstraint("policy_id", "kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policy.id"))
    kind: Mapped[str] = mapped_column(String(24))                  # wrsi | failed_onset | replant_voucher
    share: Mapped[float | None] = mapped_column(Float)             # share of sum insured (cash payouts)
    amount_kes: Mapped[float] = mapped_column(Float)
    ward_status_id: Mapped[int] = mapped_column(ForeignKey("ward_status.id"))
    index_version: Mapped[str] = mapped_column(String(20))
    confirmed_on: Mapped[date] = mapped_column(Date)               # the day the index confirmed the trigger
    due_by: Mapped[date] = mapped_column(Date)                     # confirmed_on + payout_within_days
    method: Mapped[str] = mapped_column(String(16))                # mpesa | sacco_loan | voucher
    # calculated -> approved (cash) or issued (voucher) by the underwriter -> paid / redeemed; or held with a reason
    status: Mapped[str] = mapped_column(String(16), default="calculated")
    approved_by: Mapped[str | None] = mapped_column(String(60))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hold_reason: Mapped[str | None] = mapped_column(String(300))
    voucher_code: Mapped[str | None] = mapped_column(String(16), unique=True)
    reference: Mapped[str | None] = mapped_column(String(40))      # M-Pesa B2C receipt or SACCO reference
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_by: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    policy: Mapped[Policy] = relationship()
    ward_status: Mapped[WardStatus] = relationship()


class MissedPayoutReport(Base):
    """Basis-risk report: "my crop failed but the payout did not match". Recorded and reviewed;
    it never changes a payout, it informs index review."""
    __tablename__ = "missed_payout_report"
    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(12), unique=True)
    farmer_id: Mapped[str] = mapped_column(ForeignKey("farmer.id"))
    policy_id: Mapped[str | None] = mapped_column(ForeignKey("policy.id"))
    ward_id: Mapped[str] = mapped_column(String(40))
    season: Mapped[str] = mapped_column(String(4))
    year: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(24))              # failed_no_payout | payout_too_small | other
    channel: Mapped[str] = mapped_column(String(10))               # ussd | portal
    note: Mapped[str | None] = mapped_column(String(500))          # officer's words, scrubbed of IDs and phones
    index_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)   # ward status when reported
    status: Mapped[str] = mapped_column(String(12), default="open")    # open | reviewed
    outcome: Mapped[str | None] = mapped_column(String(30))
    review_note: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[str | None] = mapped_column(String(60))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reported_by: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    farmer: Mapped[Farmer] = relationship()
    policy: Mapped[Policy | None] = relationship()


class WeatherFetch(Base):
    """Each request to a weather source, so the minimum interval and robots.txt are provable."""
    __tablename__ = "weather_fetch"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(30), index=True)
    url: Mapped[str] = mapped_column(String(400))
    status: Mapped[str] = mapped_column(String(20))                # ok | skipped_interval | disallowed | error
    detail: Mapped[str | None] = mapped_column(String(300))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WeatherItem(Base):
    """A weather advisory (display only). Shown only after a person writes and approves the summary."""
    __tablename__ = "weather_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(30))                # config id, e.g. kmd_nakuru
    source_label: Mapped[str] = mapped_column(String(40))          # e.g. "Source: KMD"
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(400))
    pdf_sha256: Mapped[str | None] = mapped_column(String(64), index=True)   # unique per audience (weather.store_pdf)
    pdf_path: Mapped[str | None] = mapped_column(String(300))
    text_excerpt: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    origin: Mapped[str] = mapped_column(String(10))                # fetched | uploaded
    summary_en: Mapped[str | None] = mapped_column(String(480))
    summary_sw: Mapped[str | None] = mapped_column(String(480))
    status: Mapped[str] = mapped_column(String(12), default="draft")   # draft | approved | withdrawn
    # Who sees it: one SACCO (uploaded by that SACCO's manager, who approves it) or, when None, every SACCO
    # (fetched from KMD or uploaded by AgroShield operations, who alone approve or withdraw it).
    sacco_id: Mapped[int | None] = mapped_column(ForeignKey("sacco.id"), index=True)
    approved_by: Mapped[str | None] = mapped_column(String(60))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PublicEnquiry(Base):
    """A "Request a demo" or livestock "Register interest" form from the public site. Stored here only:
    nothing is emailed or sent anywhere. Contact details are encrypted like farmer data, with a masked copy."""
    __tablename__ = "public_enquiry"
    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(12), unique=True)
    kind: Mapped[str] = mapped_column(String(20))                  # demo | livestock_interest
    name_enc: Mapped[str] = mapped_column(Text)
    email_enc: Mapped[str] = mapped_column(Text)
    email_masked: Mapped[str] = mapped_column(String(80))
    phone_enc: Mapped[str | None] = mapped_column(Text)
    phone_masked: Mapped[str | None] = mapped_column(String(24))
    organisation: Mapped[str | None] = mapped_column(String(120))
    org_type: Mapped[str] = mapped_column(String(20))              # insurer | reinsurer | sacco | herder | other ...
    county: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str | None] = mapped_column(String(1000))      # scrubbed of IDs and phone numbers
    consent_text: Mapped[str] = mapped_column(String(300))         # the exact consent line the person agreed to
    status: Mapped[str] = mapped_column(String(12), default="new") # new | handled
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PremiumRemittance(Base):
    """Premium a SACCO reports sending on to its insurer (a record, not a payment). Never edited or deleted:
    a correction is a new negative entry. The insurer's underwriter confirms receipt or queries it."""
    __tablename__ = "premium_remittance"
    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(12), unique=True)
    sacco_id: Mapped[int] = mapped_column(ForeignKey("sacco.id"), index=True)
    insurer_id: Mapped[int] = mapped_column(ForeignKey("insurer.id"), index=True)
    amount_kes: Mapped[float] = mapped_column(Float)
    remitted_on: Mapped[date] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(16))                # bank_transfer | mpesa | cheque | other
    reference: Mapped[str] = mapped_column(String(40))             # bank or M-Pesa reference
    period: Mapped[str | None] = mapped_column(String(20))         # optional label, e.g. 2027-LR
    note: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(12), default="recorded")   # recorded | confirmed | queried
    recorded_by: Mapped[str] = mapped_column(String(60))
    reviewed_by: Mapped[str | None] = mapped_column(String(60))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Refund(Base):
    """Money paid back to a farmer (an overpayment, or premium paid after the sales close). Owed amounts stay on
    the policy (refund_due_kes); each refund actually paid is one row here. Never edited or deleted."""
    __tablename__ = "refund"
    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(12), unique=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policy.id"), index=True)
    amount_kes: Mapped[float] = mapped_column(Float)
    paid_on: Mapped[date] = mapped_column(Date)
    method: Mapped[str] = mapped_column(String(16))                # mpesa | sacco_account | bank_transfer | other
    reference: Mapped[str] = mapped_column(String(40))             # M-Pesa, bank or SACCO ledger reference
    note: Mapped[str | None] = mapped_column(String(300))
    recorded_by: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    policy: Mapped[Policy] = relationship()


# ------------------------------------------------------------------ milestone 8: photo app
class AppUser(Base):
    """A farmer (or champion farmer) who signs in to the photo app with their phone number and a PIN the SACCO
    officer set up. Champion farmers photograph several farmers' plots (AppAssignment)."""
    __tablename__ = "app_user"
    id: Mapped[int] = mapped_column(primary_key=True)
    farmer_id: Mapped[str] = mapped_column(ForeignKey("farmer.id"), unique=True)
    role: Mapped[str] = mapped_column(String(12), default="farmer")        # farmer | champion
    pin_hash: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_version: Mapped[int] = mapped_column(Integer, default=0)       # raised on PIN reset or disable: signs out
    created_by: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    farmer: Mapped[Farmer] = relationship()


class AppAssignment(Base):
    """A plot a champion farmer may photograph for another farmer (same SACCO), set by the SACCO."""
    __tablename__ = "app_assignment"
    __table_args__ = (UniqueConstraint("user_id", "plot_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    plot_id: Mapped[str] = mapped_column(ForeignKey("plot.id"))
    created_by: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    plot: Mapped[Plot] = relationship()


class PhotoPoint(Base):
    """A fixed spot on a plot that is photographed again at each stage, so pictures can be compared."""
    __tablename__ = "photo_point"
    id: Mapped[int] = mapped_column(primary_key=True)
    plot_id: Mapped[str] = mapped_column(ForeignKey("plot.id"), index=True)
    label: Mapped[str] = mapped_column(String(40))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RiderClaim(Base):
    """Picture-based rider (ILLUSTRATIVE, not on sale): a damage report with photos, assessed by a reviewer.
    The assessment is a labelled illustration; it never creates a Payout."""
    __tablename__ = "rider_claim"
    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(12), unique=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policy.id"), index=True)
    reported_by: Mapped[int] = mapped_column(ForeignKey("app_user.id"))
    cause: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(12), default="submitted")       # submitted | assessed
    extent: Mapped[str | None] = mapped_column(String(8))
    illustrative_amount_kes: Mapped[float | None] = mapped_column(Float)
    assessed_by: Mapped[str | None] = mapped_column(String(60))
    assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    policy: Mapped[Policy] = relationship()


class Photo(Base):
    """One crop photo. The stored file is re-encoded without EXIF or GPS; location and times are kept here.
    status: rejected (failed a hard check, never reviewed) | in_review | reviewed."""
    __tablename__ = "photo"
    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(12), unique=True)
    client_id: Mapped[str] = mapped_column(String(64), unique=True)          # offline queue key: retries are harmless
    plot_id: Mapped[str] = mapped_column(ForeignKey("plot.id"), index=True)
    farmer_id: Mapped[str] = mapped_column(ForeignKey("farmer.id"), index=True)
    policy_id: Mapped[str | None] = mapped_column(ForeignKey("policy.id"))
    photo_point_id: Mapped[int | None] = mapped_column(ForeignKey("photo_point.id"))
    taken_by: Mapped[int] = mapped_column(ForeignKey("app_user.id"))
    stage: Mapped[str] = mapped_column(String(16))
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))       # UTC, as the app reported it
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float)
    distance_m: Mapped[float | None] = mapped_column(Float)                   # from the registered plot point
    sha256: Mapped[str] = mapped_column(String(64), index=True)                # of the stripped file
    phash: Mapped[str] = mapped_column(String(16), index=True)                 # 64-bit dHash, hex
    file_path: Mapped[str] = mapped_column(String(300))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    flags: Mapped[list] = mapped_column(JSON, default=list)                    # e.g. ["duplicate", "time_mismatch"]
    on_schedule: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(12), default="in_review")
    reject_reason: Mapped[str | None] = mapped_column(String(200))
    rider_claim_id: Mapped[int | None] = mapped_column(ForeignKey("rider_claim.id"))
    plot: Mapped[Plot] = relationship()
    farmer: Mapped[Farmer] = relationship()
    point: Mapped[PhotoPoint | None] = relationship()


class PhotoSuggestion(Base):
    """What the AI service suggested for one photo (shown to the reviewer as "Suggestion"), or why it did not.
    status: ok | no_consent | no_key | off | error. sent_sha256 is the hash of the exact bytes sent (EXIF-free)."""
    __tablename__ = "photo_suggestion"
    id: Mapped[int] = mapped_column(primary_key=True)
    photo_id: Mapped[int] = mapped_column(ForeignKey("photo.id"), index=True)
    status: Mapped[str] = mapped_column(String(12))
    tag: Mapped[str | None] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(300))
    model: Mapped[str | None] = mapped_column(String(40))
    sent_sha256: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PhotoReview(Base):
    """The human agronomist's decision, logged next to the suggestion they saw (if any). The reviewer decides."""
    __tablename__ = "photo_review"
    id: Mapped[int] = mapped_column(primary_key=True)
    photo_id: Mapped[int] = mapped_column(ForeignKey("photo.id"), unique=True)
    reviewer: Mapped[str] = mapped_column(String(60))
    tag: Mapped[str] = mapped_column(String(20))           # healthy | drought_stress | pest | disease | flood | other
    extent: Mapped[str] = mapped_column(String(8))          # none | lt25 | 25_50 | 50_75 | gt75
    note: Mapped[str | None] = mapped_column(String(500))
    suggestion_id: Mapped[int | None] = mapped_column(ForeignKey("photo_suggestion.id"))
    suggestion_tag: Mapped[str | None] = mapped_column(String(20))
    agreed_with_suggestion: Mapped[bool | None] = mapped_column(Boolean)
    flags_cleared: Mapped[bool] = mapped_column(Boolean, default=False)       # reviewer judged the flags harmless
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
