"""M-Pesa premium collection: Safaricom Daraja "Lipa na M-Pesa Online" (STK push).

    request_premium()  send an STK push for a policy instalment to the farmer's phone
    handle_callback()  Safaricom's result for that push: credit the payment once
    recheck()          scheduled: ask Safaricom (STK query) about every push still without a final answer,
                       with backoff, until it is confirmed or failed; flag it if still unknown after the last try
    resolve()          a manager's decision on a flagged payment, after checking with the farmer

Clients:
  DarajaClient     sandbox or production Daraja API (MPESA_ENV=sandbox|production)
  SimulatedDaraja  no network (MPESA_ENV=simulated, the default): requests stay
                   pending until completed from the portal's /dev/mpesa page

Safeguards: a callback is matched to a push we sent (CheckoutRequestID), its
amount must equal what we asked for, each receipt is credited once, and outside
simulated mode the result is re-checked with an STK query before crediting. The
callback URL carries a secret path token. Phone numbers go only in request
bodies and are stored masked.

Nothing is dropped silently: a push with no callback, or a callback the status
query has not confirmed, is re-checked on the RECHECK_MINUTES schedule. If the
answer is still unknown after the last check, the request becomes "unconfirmed"
and shows on the officer's Home and the manager's Reports as "Payment not
confirmed: check with the farmer" until a manager resolves it. A payment started
before the sales close date counts toward cover even if it is confirmed after it.
"""
from __future__ import annotations

import base64
import logging
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from .crypto import mask_phone, normalise_phone
from .db import audit
from .models import MpesaRequest, Payment, Policy
from .services import MIN_INSTALMENT_KES, NAIROBI, Context, PaymentError, record_payment
from .settings import Mpesa

log = logging.getLogger("agroshield.mpesa")

# Minutes after the push at which each status check is due (6 checks over a day). Safaricom's own
# STK timeout is about a minute, so the first check comes soon after; later ones cover outages.
RECHECK_MINUTES = (2, 5, 15, 60, 240, 1440)
RECEIPT = re.compile(r"^[A-Z0-9]{8,12}$")       # M-Pesa receipt numbers, e.g. SKL2ABC3DE
# STK query result codes that mean "still being processed", not a final answer.
IN_PROGRESS = {4999}
OPEN = ("pending", "unconfirmed")               # no final answer yet


class MpesaError(RuntimeError):
    pass


def _msisdn(phone_e164: str) -> str:
    return phone_e164.lstrip("+")          # Daraja wants 2547XXXXXXXX


class DarajaClient:
    BASE = {"sandbox": "https://sandbox.safaricom.co.ke", "production": "https://api.safaricom.co.ke"}

    def __init__(self, cfg: Mpesa, callback_url: str, http: httpx.Client | None = None):
        missing = [k for k in ("consumer_key", "consumer_secret", "shortcode", "passkey") if not getattr(cfg, k)]
        if missing:
            raise MpesaError("M-Pesa " + cfg.env + " needs " + ", ".join("MPESA_" + m.upper() for m in missing))
        if not callback_url.startswith("https://"):
            raise MpesaError("MPESA_CALLBACK_BASE_URL must be a public https URL Safaricom can reach")
        self.cfg, self.env, self.callback_url = cfg, cfg.env, callback_url
        self.confirm_with_query = cfg.confirm_with_query
        self.base = self.BASE[cfg.env]
        self.http = http or httpx.Client(timeout=30)
        self._token: tuple[str, float] | None = None

    def _auth(self) -> dict:
        if not self._token or self._token[1] < time.time() + 60:
            r = self.http.get(f"{self.base}/oauth/v1/generate", params={"grant_type": "client_credentials"},
                              auth=(self.cfg.consumer_key, self.cfg.consumer_secret))
            r.raise_for_status()
            d = r.json()
            self._token = (d["access_token"], time.time() + int(d.get("expires_in", 3599)))
        return {"Authorization": f"Bearer {self._token[0]}"}

    def _password(self, ts: str) -> str:
        return base64.b64encode(f"{self.cfg.shortcode}{self.cfg.passkey}{ts}".encode()).decode()

    def stk_push(self, phone_e164: str, amount: int, account_ref: str, description: str) -> dict:
        ts = datetime.now(NAIROBI).strftime("%Y%m%d%H%M%S")
        body = {"BusinessShortCode": self.cfg.shortcode, "Password": self._password(ts), "Timestamp": ts,
                "TransactionType": "CustomerPayBillOnline", "Amount": int(amount), "PartyA": _msisdn(phone_e164),
                "PartyB": self.cfg.shortcode, "PhoneNumber": _msisdn(phone_e164), "CallBackURL": self.callback_url,
                "AccountReference": account_ref[:12], "TransactionDesc": description[:13]}
        r = self.http.post(f"{self.base}/mpesa/stkpush/v1/processrequest", json=body, headers=self._auth())
        d = r.json() if r.content else {}
        if r.status_code >= 400 or str(d.get("ResponseCode")) != "0":
            raise MpesaError(f"STK push refused: {d.get('errorMessage') or d.get('ResponseDescription') or r.status_code}")
        return {"merchant_request_id": d["MerchantRequestID"], "checkout_request_id": d["CheckoutRequestID"]}

    def b2c(self, phone_e164: str, amount: int, remarks: str) -> str:
        """Payouts (B2C) need the insurer's disbursement shortcode, an initiator and a security credential."""
        raise MpesaError("M-Pesa payouts (B2C) need the insurer's initiator name and security credential; "
                         "not configured yet. Pay through the SACCO and record the reference instead.")

    def stk_query(self, checkout_request_id: str) -> dict:
        ts = datetime.now(NAIROBI).strftime("%Y%m%d%H%M%S")
        r = self.http.post(f"{self.base}/mpesa/stkpushquery/v1/query", headers=self._auth(),
                           json={"BusinessShortCode": self.cfg.shortcode, "Password": self._password(ts),
                                 "Timestamp": ts, "CheckoutRequestID": checkout_request_id})
        d = r.json() if r.content else {}
        return {"result_code": int(d["ResultCode"]) if "ResultCode" in d else None, "result_desc": d.get("ResultDesc")}


class SimulatedDaraja:
    """Stands in for Daraja with no network. Completed by simulate_callback() (the /dev/mpesa page)."""
    env = "simulated"
    confirm_with_query = False

    def __init__(self):
        self.results: dict[str, int] = {}

    def stk_push(self, phone_e164: str, amount: int, account_ref: str, description: str) -> dict:
        n = secrets.token_hex(6)
        return {"merchant_request_id": f"SIM-{n}", "checkout_request_id": f"ws_CO_SIM_{n}"}

    def stk_query(self, checkout_request_id: str) -> dict:
        return {"result_code": self.results.get(checkout_request_id), "result_desc": "simulated"}

    def b2c(self, phone_e164: str, amount: int, remarks: str) -> str:
        """Simulated payout to the farmer's M-Pesa: returns a receipt; no money moves."""
        return "SIMB2C" + secrets.token_hex(4).upper()

    def simulate_callback(self, req: MpesaRequest, success: bool) -> dict:
        """The body Safaricom would POST to our callback URL."""
        code = 0 if success else 1032
        self.results[req.checkout_request_id] = code
        cb = {"MerchantRequestID": req.merchant_request_id, "CheckoutRequestID": req.checkout_request_id,
              "ResultCode": code, "ResultDesc": "The service request is processed successfully." if success
              else "Request cancelled by user"}
        if success:
            cb["CallbackMetadata"] = {"Item": [
                {"Name": "Amount", "Value": req.amount_kes},
                {"Name": "MpesaReceiptNumber", "Value": "SIM" + secrets.token_hex(4).upper()},
                {"Name": "TransactionDate", "Value": int(datetime.now(NAIROBI).strftime("%Y%m%d%H%M%S"))},
                {"Name": "PhoneNumber", "Value": 254700000000}]}
        return {"Body": {"stkCallback": cb}}


def make_client(cfg: Mpesa, callback_url: str):
    return SimulatedDaraja() if cfg.env == "simulated" else DarajaClient(cfg, callback_url)


def _utc(ctx: Context) -> datetime:
    """Every M-Pesa request time is stored in UTC (SQLite keeps no offset, and _aware reads it back as UTC)."""
    return ctx.now().astimezone(timezone.utc)


def _aware(d: datetime | None) -> datetime | None:
    """SQLite gives naive datetimes back; M-Pesa request times are stored in UTC."""
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def request_premium(ctx: Context, s: Session, pol: Policy, amount: int, requested_by: str,
                    phone: str | None = None) -> MpesaRequest:
    """STK push for an instalment of a policy's farmer share, to the farmer's registered phone (or `phone`)."""
    if ctx.mpesa is None:
        raise MpesaError("M-Pesa is not configured")
    if pol.status != "pending_payment":
        raise PaymentError(f"nothing to collect: the policy is {pol.status.replace('_', ' ')}")
    if ctx.date() > pol.sales_closes_on:
        raise PaymentError(f"sales closed on {pol.sales_closes_on:%d %b %Y}")
    balance = int(round(pol.balance_kes))
    low = min(MIN_INSTALMENT_KES, balance)
    if not isinstance(amount, int) or not low <= amount <= balance:
        raise PaymentError(f"amount must be a whole number of KES from {low} to {balance}")
    e164 = normalise_phone(phone) if phone else ctx.vault.decrypt(pol.farmer.phone_enc, "phone")
    r = ctx.mpesa.stk_push(e164, amount, pol.pay_ref, "AgroShield")
    now = _utc(ctx)
    req = MpesaRequest(policy_id=pol.id, amount_kes=amount, phone_masked=mask_phone(e164),
                       merchant_request_id=r["merchant_request_id"], checkout_request_id=r["checkout_request_id"],
                       environment=ctx.mpesa.env, requested_by=requested_by, created_at=now,
                       next_query_at=now + timedelta(minutes=RECHECK_MINUTES[0]))
    s.add(req)
    s.flush()
    audit(s, requested_by, "mpesa.stk_requested", "policy", pol.id, policy_no=pol.policy_no, amount_kes=amount,
          environment=ctx.mpesa.env)
    return req


def _meta(cb: dict) -> dict:
    return {i["Name"]: i.get("Value") for i in (cb.get("CallbackMetadata") or {}).get("Item", [])}


def _txn_time(v) -> datetime | None:
    """Safaricom's TransactionDate (Nairobi wall time), as UTC."""
    try:
        return datetime.strptime(str(int(v)), "%Y%m%d%H%M%S").replace(tzinfo=NAIROBI).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _claim(s: Session, req: MpesaRequest, status: str, **values) -> bool:
    """Move a request out of pending/unconfirmed exactly once. A callback, the re-check and a manager can race;
    the database decides who wins (compare-and-set), so a payment is never credited twice."""
    won = s.execute(update(MpesaRequest).where(MpesaRequest.id == req.id, MpesaRequest.status.in_(OPEN))
                    .values(status=status, **values).execution_options(synchronize_session=False)).rowcount == 1
    s.refresh(req)
    return won


def handle_callback(ctx: Context, s: Session, body: dict) -> dict:
    """Process one Safaricom STK callback. Idempotent; returns a short outcome for the audit trail."""
    cb = (body or {}).get("Body", {}).get("stkCallback") or {}
    req = s.scalar(select(MpesaRequest).where(MpesaRequest.checkout_request_id == str(cb.get("CheckoutRequestID", ""))))
    if req is None:
        log.warning("M-Pesa callback for an unknown request ignored")
        return {"outcome": "unknown_request"}
    try:
        code = int(cb.get("ResultCode", -1))
    except (TypeError, ValueError):
        code = -1
    m = _meta(cb)
    amount, receipt = m.get("Amount"), str(m.get("MpesaReceiptNumber") or "").strip().upper()
    good = code == 0 and amount is not None and int(round(float(amount))) == req.amount_kes and bool(receipt)
    if req.status == "paid" and good and req.receipt == req.checkout_request_id[:30]:
        # Paid on the status query alone; the late callback tells us the receipt. The payment is not touched.
        req.receipt = receipt[:30]
        audit(s, "mpesa", "mpesa.receipt_received_late", "policy", req.policy_id)
        return {"outcome": "receipt_recorded"}
    if req.status == "failed" and good and req.result_desc == "not paid (status query)":
        # Safaricom's query said no, its callback says paid: a person decides (never dropped, never auto-credited).
        req.status, req.callback_amount_kes, req.callback_receipt = "unconfirmed", float(amount), receipt[:30]
        req.callback_txn_at = _txn_time(m.get("TransactionDate"))
        audit(s, "mpesa", "mpesa.callback_after_query_failure", "policy", req.policy_id)
        return {"outcome": "flagged"}
    if req.status not in OPEN:
        return {"outcome": "duplicate", "status": req.status}
    if code != 0:
        if not _claim(s, req, "failed", result_code=code, result_desc=str(cb.get("ResultDesc", ""))[:200],
                      completed_at=_utc(ctx), next_query_at=None):
            return {"outcome": "duplicate", "status": req.status}
        audit(s, "mpesa", "mpesa.stk_failed", "policy", req.policy_id, result_code=code)
        return {"outcome": "failed", "result_code": code}
    if not good:
        if not _claim(s, req, "failed", result_code=code, completed_at=_utc(ctx), next_query_at=None,
                      result_desc="rejected: amount or receipt does not match the request"):
            return {"outcome": "duplicate", "status": req.status}
        audit(s, "mpesa", "mpesa.callback_rejected", "policy", req.policy_id, reason="amount or receipt mismatch")
        return {"outcome": "rejected"}
    if getattr(ctx.mpesa, "confirm_with_query", False):
        if _query(ctx, req)["result_code"] != 0:
            # Kept, not credited: the scheduled re-check credits it once Safaricom confirms it.
            req.callback_amount_kes, req.callback_receipt = float(amount), receipt[:30]
            req.callback_txn_at = _txn_time(m.get("TransactionDate"))
            if req.status == "pending" and req.next_query_at is None:
                req.next_query_at = _utc(ctx) + timedelta(minutes=RECHECK_MINUTES[0])
            audit(s, "mpesa", "mpesa.callback_unconfirmed", "policy", req.policy_id)
            return {"outcome": "unconfirmed"}
    return _credit(ctx, s, req, float(amount), receipt, _txn_time(m.get("TransactionDate")),
                   str(cb.get("ResultDesc", "")), "mpesa")


def _query(ctx: Context, req: MpesaRequest) -> dict:
    """One STK status query. Any transport or parsing error, or "still processing", counts as no answer yet."""
    try:
        res = ctx.mpesa.stk_query(req.checkout_request_id)
    except Exception as e:                      # network, Safaricom 5xx, bad JSON: try again later
        res = {"result_code": None, "result_desc": f"query error: {type(e).__name__}"}
    req.last_query_at = _utc(ctx)
    req.last_query_result = f"{res.get('result_code')}: {res.get('result_desc') or ''}"[:200]
    if res.get("result_code") in IN_PROGRESS:
        res = {**res, "result_code": None}
    return res


def _credit(ctx: Context, s: Session, req: MpesaRequest, amount: float, reference: str, paid_at: datetime | None,
            desc: str, actor: str) -> dict:
    """Mark the push paid and record the payment, once (see _claim). The sales window is judged by when the push
    was started, so a payment begun before the close date still counts toward cover when confirmed later."""
    if not _claim(s, req, "paid", result_code=0, receipt=reference[:30], result_desc=desc[:200],
                  completed_at=_utc(ctx), next_query_at=None):
        audit(s, actor, "mpesa.already_settled", "policy", req.policy_id, status=req.status)
        return {"outcome": "duplicate", "status": req.status}
    when = _aware(paid_at) or _utc(ctx)
    try:
        record_payment(ctx, s, req.policy, amount, "mpesa", reference, actor,
                       received_at=when.astimezone(NAIROBI), window_at=_aware(req.created_at))
    except PaymentError as e:           # receipt already recorded: keep the first
        audit(s, actor, "mpesa.payment_skipped", "policy", req.policy_id, reason=str(e))
        return {"outcome": "duplicate_receipt"}
    return {"outcome": "paid", "policy_no": req.policy.policy_no}


def due(s: Session, now: datetime) -> list[int]:
    """Requests waiting for an answer whose next status check is due."""
    now = now.astimezone(timezone.utc)
    rows = s.execute(select(MpesaRequest.id, MpesaRequest.next_query_at).where(
        MpesaRequest.status == "pending", MpesaRequest.next_query_at.is_not(None))
        .order_by(MpesaRequest.next_query_at)).all()
    return [i for i, at in rows if _aware(at) <= now]


def recheck_one(ctx: Context, s: Session, req_id: int, now: datetime) -> str:
    """One status check for one request: paid, failed, waiting, flagged or skipped."""
    req = s.get(MpesaRequest, req_id)
    if req is None or req.status != "pending" or req.next_query_at is None or _aware(req.next_query_at) > now:
        return "skipped"
    code = _query(ctx, req)["result_code"]          # the HTTP call comes before any write to the database
    s.refresh(req, ["status", "callback_receipt", "callback_amount_kes", "callback_txn_at"])
    if req.status != "pending":                     # a callback settled it while we were asking
        return "skipped"
    req.query_attempts = (req.query_attempts or 0) + 1
    if code == 0:
        if req.callback_receipt:            # Safaricom told us the receipt in the callback
            res = _credit(ctx, s, req, req.callback_amount_kes or float(req.amount_kes), req.callback_receipt,
                          req.callback_txn_at, "confirmed by status query", "mpesa-recheck")
        else:                               # no callback ever came: the query carries no receipt number
            res = _credit(ctx, s, req, float(req.amount_kes), req.checkout_request_id[:40], None,
                          "confirmed by status query; no receipt number was received", "mpesa-recheck")
        audit(s, "mpesa-recheck", "mpesa.confirmed_by_query", "policy", req.policy_id, attempt=req.query_attempts,
              outcome=res["outcome"])
        return "paid" if res["outcome"] in ("paid", "duplicate_receipt") else "skipped"
    if isinstance(code, int) and not req.callback_receipt:
        if not _claim(s, req, "failed", result_code=code, completed_at=_utc(ctx), next_query_at=None,
                      result_desc="not paid (status query)", query_attempts=req.query_attempts):
            return "skipped"
        audit(s, "mpesa-recheck", "mpesa.failed_by_query", "policy", req.policy_id, result_code=code)
        return "failed"
    if req.query_attempts >= len(RECHECK_MINUTES):
        # Still unknown (or a success callback the query contradicts): a person must check with the farmer.
        if not _claim(s, req, "unconfirmed", next_query_at=None, query_attempts=req.query_attempts):
            return "skipped"
        audit(s, "mpesa-recheck", "mpesa.unconfirmed_flagged", "policy", req.policy_id, attempts=req.query_attempts,
              had_callback=bool(req.callback_receipt))
        return "flagged"
    req.next_query_at = _aware(req.created_at) + timedelta(minutes=RECHECK_MINUTES[req.query_attempts])
    return "waiting"


def recheck(ctx: Context, s: Session, now: datetime | None = None) -> dict:
    """Scheduled job (also part of daily): query Safaricom about each push still waiting whose next check is due.
    Confirmed: credited. Refused (cancelled, timed out, wrong PIN, low balance): failed. No answer: tried again
    later, and flagged after the last try. One session for all; run_recheck uses one transaction per request."""
    now = (now or ctx.now()).astimezone(timezone.utc)
    out = {"checked": 0, "paid": 0, "failed": 0, "waiting": 0, "flagged": 0}
    for rid in due(s, now):
        res = recheck_one(ctx, s, rid, now)
        if res != "skipped":
            out["checked"] += 1
            out[res] += 1
    return out


def run_recheck(ctx: Context, factory, now: datetime | None = None) -> dict:
    """The scheduled re-check with a short transaction per request, so the database is never locked while
    waiting for Safaricom (callbacks keep working), and one bad request never undoes the others."""
    from .db import transaction
    now = (now or ctx.now()).astimezone(timezone.utc)
    with transaction(factory) as s:
        ids = due(s, now)
    out = {"checked": 0, "paid": 0, "failed": 0, "waiting": 0, "flagged": 0, "errors": 0}
    for rid in ids:
        try:
            with transaction(factory) as s:
                res = recheck_one(ctx, s, rid, now)
        except Exception:
            log.exception("M-Pesa re-check of request %s failed; it will be tried again", rid)
            out["errors"] += 1
            continue
        if res != "skipped":
            out["checked"] += 1
            out[res] += 1
    return out


def unconfirmed(s: Session, sacco_id: int) -> list[MpesaRequest]:
    """Payments flagged "not confirmed" for one SACCO, oldest first."""
    return list(s.scalars(select(MpesaRequest).join(Policy).where(Policy.sacco_id == sacco_id,
                                                                  MpesaRequest.status == "unconfirmed")
                          .order_by(MpesaRequest.created_at)))


class ResolveError(ValueError):
    pass


def resolve(ctx: Context, s: Session, req: MpesaRequest, actor: str, outcome: str, receipt: str = "",
            note: str = "") -> dict:
    """A manager closes a flagged payment after checking with the farmer: paid (the farmer shows the M-Pesa
    receipt from their SMS; it is credited once, toward cover if the push was started before the close date)
    or not paid. Audited either way."""
    from .crypto import scrub
    if req.status != "unconfirmed":
        raise ResolveError("This payment is not waiting for a decision.")
    note = scrub((note or "").strip())[:300]
    if outcome == "paid":
        receipt = (receipt or "").strip().upper()
        if not RECEIPT.match(receipt):
            raise ResolveError("Enter the M-Pesa receipt number from the farmer's SMS (8 to 12 letters and numbers).")
        used = s.scalar(select(Payment).where(Payment.reference == receipt)) or s.scalar(
            select(MpesaRequest).where(MpesaRequest.id != req.id,
                                       or_(MpesaRequest.receipt == receipt, MpesaRequest.callback_receipt == receipt)))
        if used:
            raise ResolveError("That receipt number is already recorded for another payment.")
        res = _credit(ctx, s, req, req.callback_amount_kes or float(req.amount_kes), receipt, req.callback_txn_at,
                      "confirmed by the manager with the farmer's receipt", actor)
        if res["outcome"] != "paid":
            raise ResolveError("This payment was settled meanwhile; reload the page.")
    elif outcome == "not_paid":
        if not _claim(s, req, "failed", completed_at=_utc(ctx), next_query_at=None,
                      result_desc="not paid (checked with the farmer)"):
            raise ResolveError("This payment was settled meanwhile; reload the page.")
    else:
        raise ResolveError("Choose paid or not paid.")
    req.resolution, req.resolved_by, req.resolution_note = outcome, actor, note or None
    audit(s, actor, "mpesa.resolved", "policy", req.policy_id, outcome=outcome, note=note)
    return {"outcome": outcome}
