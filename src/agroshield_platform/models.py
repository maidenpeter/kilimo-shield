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


class Sacco(Base):
    __tablename__ = "sacco"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    county: Mapped[str] = mapped_column(String(60), default="Nakuru")
    # Demo SACCOs hold fictional members only. Live enrolment (is_demo False) is blocked
    # until the consent wording has a recorded legal and Kiswahili review.
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Officer(Base):
    __tablename__ = "officer"
    id: Mapped[int] = mapped_column(primary_key=True)
    sacco_id: Mapped[int] = mapped_column(ForeignKey("sacco.id"))
    username: Mapped[str] = mapped_column(String(60), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="officer")      # officer | manager
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    sacco: Mapped[Sacco] = relationship()


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
    status: Mapped[str] = mapped_column(String(12), default="pending")   # pending | paid | failed
    result_code: Mapped[int | None] = mapped_column(Integer)
    result_desc: Mapped[str | None] = mapped_column(String(200))
    receipt: Mapped[str | None] = mapped_column(String(30))
    requested_by: Mapped[str] = mapped_column(String(60))           # officer username or "ussd"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
