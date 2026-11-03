"""
CineWave - payment gateway layer
================================
Three payment methods, one interface:

  1. WALLET   - CineWave wallet balance (uses your existing Wallet /
                WalletTransaction / RechargeRequest models)
  2. RAZORPAY - real Razorpay Checkout, used automatically when
                RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET env vars are set
  3. MOCK     - sandbox UPI / Card / Netbanking simulator so the whole flow is
                demoable (and gradeable) without any gateway account

Set real keys like this before running:
    export RAZORPAY_KEY_ID=rzp_test_xxxxxxxx
    export RAZORPAY_KEY_SECRET=yyyyyyyyyyyy
No keys -> the app silently falls back to MOCK mode and says so in the UI.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "").strip()
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()

# ---- fee rules (kept in one place so the invoice always adds up) -----------
CONVENIENCE_FEE_PER_SEAT = 20.0     # what BookMyShow calls "internet handling"
GST_RATE = 0.18                     # 18% GST, charged on the convenience fee


class PaymentGatewayError(RuntimeError):
    """A configured live gateway could not create an order safely."""


def is_live_gateway() -> bool:
    """True when real Razorpay keys are configured."""
    return bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)


def mock_payments_enabled() -> bool:
    """Mock checkout is an explicit development/testing capability only."""
    return os.environ.get('APP_ENV', 'development').strip().lower() in {'development', 'testing'}


def gateway_name() -> str:
    if is_live_gateway():
        return "razorpay"
    if mock_payments_enabled():
        return "mock"
    raise PaymentGatewayError("A live payment gateway is required in this environment.")


def compute_amounts(ticket_amount: float, seat_count: int) -> dict:
    """Ticket price -> convenience fee -> GST -> grand total."""
    fee = round(CONVENIENCE_FEE_PER_SEAT * seat_count, 2)
    gst = round(fee * GST_RATE, 2)
    total = round(ticket_amount + fee + gst, 2)
    return {"ticket_amount": round(ticket_amount, 2),
            "convenience_fee": fee,
            "gst": gst,
            "total": total}


# ---------------------------------------------------------------------------
# order creation
# ---------------------------------------------------------------------------

def create_order(amount_rupees: float, receipt: str, notes: dict | None = None) -> dict:
    """
    Create a gateway order. Returns
      {"order_id", "amount_paise", "currency", "gateway", "key_id"}
    Razorpay works in paise, so every amount is multiplied by 100.
    """
    amount_rupees = float(amount_rupees)
    if not amount_rupees > 0:
        raise ValueError("Payment amount must be greater than zero.")
    amount_paise = int(round(amount_rupees * 100))
    if amount_paise <= 0:
        raise ValueError("Payment amount is below the minimum supported amount.")

    if is_live_gateway():
        try:
            import razorpay  # pip install razorpay
            client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
            order = client.order.create({
                "amount": amount_paise,
                "currency": "INR",
                "receipt": receipt,
                "payment_capture": 1,
                "notes": notes or {},
            })
            return {"order_id": order["id"], "amount_paise": amount_paise,
                    "currency": "INR", "gateway": "razorpay",
                    "key_id": RAZORPAY_KEY_ID, "raw": json.dumps(order)}
        except Exception as exc:                       # keys wrong / lib missing / no net
            # Never silently turn a failed live payment into a free sandbox payment.
            raise PaymentGatewayError(
                "Razorpay could not create a payment order. Please retry later."
            ) from exc

    # ---- mock order -------------------------------------------------------
    if not mock_payments_enabled():
        raise PaymentGatewayError("Mock payments are disabled outside development and testing.")
    return {"order_id": f"order_mock_{secrets.token_hex(8)}",
            "amount_paise": amount_paise, "currency": "INR",
            "gateway": "mock", "key_id": None,
            "raw": json.dumps({"mock": True, "receipt": receipt,
                               "created_at": int(time.time())})}


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------

def verify_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """
    Razorpay signature check: HMAC-SHA256 of "order_id|payment_id" using the
    key secret. This is the step that stops a user from faking a success
    callback, so never skip it in live mode.
    """
    if not (order_id and payment_id and signature):
        return False

    if order_id.startswith("order_mock_"):
        return mock_payments_enabled() and hmac.compare_digest(
            signature, mock_signature(order_id, payment_id))

    if not RAZORPAY_KEY_SECRET:
        return False

    expected = hmac.new(RAZORPAY_KEY_SECRET.encode(),
                        f"{order_id}|{payment_id}".encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def mock_signature(order_id: str, payment_id: str) -> str:
    """Deterministic stand-in signature for sandbox mode."""
    return hmac.new(b"cinewave-mock-secret",
                    f"{order_id}|{payment_id}".encode(),
                    hashlib.sha256).hexdigest()


def simulate_payment(order_id: str, method: str = "upi", succeed: bool = True) -> dict:
    """
    Sandbox payment. The 'Pay' button on the mock checkout posts here, which is
    what a real Razorpay Checkout popup would hand back to you.
    """
    if not mock_payments_enabled() or not order_id.startswith('order_mock_'):
        raise PaymentGatewayError("Payment simulation is disabled in this environment.")
    payment_id = f"pay_mock_{secrets.token_hex(8)}"
    if not succeed:
        return {"ok": False, "payment_id": payment_id, "method": method,
                "signature": "", "error": "Payment declined by the bank (simulated)."}
    return {"ok": True, "payment_id": payment_id, "method": method,
            "signature": mock_signature(order_id, payment_id), "error": None}


def verify_webhook(body: bytes, received_signature: str) -> bool:
    """Razorpay webhook verification (set RAZORPAY_WEBHOOK_SECRET to use it)."""
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "").strip()
    if not (secret and received_signature):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received_signature)


def fetch_captured_payment(order_id: str, payment_id: str, expected_amount_paise: int) -> bool:
    """Confirm a callback against Razorpay's API, including order, amount and currency."""
    if not is_live_gateway() or not (order_id and payment_id):
        return False
    try:
        import razorpay
        client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        entity = client.payment.fetch(payment_id)
        return (entity.get('order_id') == order_id
                and int(entity.get('amount', -1)) == int(expected_amount_paise)
                and entity.get('currency') == 'INR'
                and entity.get('status') == 'captured')
    except Exception:
        return False
