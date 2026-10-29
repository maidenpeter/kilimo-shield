"""M-Pesa premium collection: Safaricom Daraja "Lipa na M-Pesa Online" (STK push).

    request_premium()  send an STK push for a policy instalment to the farmer's phone
    handle_callback()  Safaricom's result for that push: credit the payment once

Clients:
  DarajaClient     sandbox or production Daraja API (MPESA_ENV=sandbox|production)
  SimulatedDaraja  no network (MPESA_ENV=simulated, the default): requests stay
                   pending until completed from the portal's /dev/mpesa page

Safeguards: a callback is matched to a push we sent (CheckoutRequestID), its
amount must equal what we asked for, each receipt is credited once, and outside
simulated mode the result is re-checked with an STK query before crediting. The
callback URL carries a secret path token. Phone numbers go only in request
bodies and are stored masked.
"""
from __future__ import annotations

import base64
import logging
import secrets
import time
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .crypto import mask_phone, normalise_phone
from .db import audit
from .models import MpesaRequest, Policy
from .services import MIN_INSTALMENT_KES, NAIROBI, Context, PaymentError, record_payment
from .settings import Mpesa

log = logging.getLogger("agroshield.mpesa")


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
    req = MpesaRequest(policy_id=pol.id, amount_kes=amount, phone_masked=mask_phone(e164),
                       merchant_request_id=r["merchant_request_id"], checkout_request_id=r["checkout_request_id"],
                       environment=ctx.mpesa.env, requested_by=requested_by)
    s.add(req)
    s.flush()
    audit(s, requested_by, "mpesa.stk_requested", "policy", pol.id, policy_no=pol.policy_no, amount_kes=amount,
          environment=ctx.mpesa.env)
    return req


def _meta(cb: dict) -> dict:
    return {i["Name"]: i.get("Value") for i in (cb.get("CallbackMetadata") or {}).get("Item", [])}


def _txn_time(v) -> datetime | None:
    try:
        return datetime.strptime(str(int(v)), "%Y%m%d%H%M%S").replace(tzinfo=NAIROBI)
    except (TypeError, ValueError):
        return None


def handle_callback(ctx: Context, s: Session, body: dict) -> dict:
    """Process one Safaricom STK callback. Idempotent; returns a short outcome for the audit trail."""
    cb = (body or {}).get("Body", {}).get("stkCallback") or {}
    req = s.scalar(select(MpesaRequest).where(MpesaRequest.checkout_request_id == str(cb.get("CheckoutRequestID", ""))))
    if req is None:
        log.warning("M-Pesa callback for an unknown request ignored")
        return {"outcome": "unknown_request"}
    if req.status != "pending":
        return {"outcome": "duplicate", "status": req.status}
    try:
        code = int(cb.get("ResultCode", -1))
    except (TypeError, ValueError):
        code = -1
    if code != 0:
        req.status, req.result_code = "failed", code
        req.result_desc, req.completed_at = str(cb.get("ResultDesc", ""))[:200], ctx.now()
        audit(s, "mpesa", "mpesa.stk_failed", "policy", req.policy_id, result_code=code)
        return {"outcome": "failed", "result_code": code}
    m = _meta(cb)
    amount, receipt = m.get("Amount"), str(m.get("MpesaReceiptNumber") or "")
    if amount is None or int(round(float(amount))) != req.amount_kes or not receipt:
        req.status, req.result_code, req.completed_at = "failed", code, ctx.now()
        req.result_desc = "rejected: amount or receipt does not match the request"
        audit(s, "mpesa", "mpesa.callback_rejected", "policy", req.policy_id, reason="amount or receipt mismatch")
        return {"outcome": "rejected"}
    if getattr(ctx.mpesa, "confirm_with_query", False):
        if ctx.mpesa.stk_query(req.checkout_request_id)["result_code"] != 0:
            audit(s, "mpesa", "mpesa.callback_unconfirmed", "policy", req.policy_id)
            return {"outcome": "unconfirmed"}      # stays pending; a later callback or query can complete it
    req.status, req.result_code, req.receipt = "paid", 0, receipt
    req.result_desc, req.completed_at = str(cb.get("ResultDesc", ""))[:200], ctx.now()
    try:
        record_payment(ctx, s, req.policy, float(amount), "mpesa", receipt, "mpesa",
                       received_at=_txn_time(m.get("TransactionDate")) or ctx.now())
    except PaymentError as e:           # receipt already recorded: keep the first
        audit(s, "mpesa", "mpesa.payment_skipped", "policy", req.policy_id, reason=str(e))
        return {"outcome": "duplicate_receipt"}
    return {"outcome": "paid", "policy_no": req.policy.policy_no}
