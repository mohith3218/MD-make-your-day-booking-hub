"""Local-only demo payments and existing fee calculations.

No network client or real-money provider exists here. Legacy mock gateway values
and order prefixes remain compatible with stored demo records.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import time

from flask import current_app, has_app_context

CONVENIENCE_FEE_PER_SEAT = 20.0
GST_RATE = 0.18
DEMO_METHODS = frozenset({'upi', 'card', 'netbanking', 'split'})
_PROCESS_DEMO_SECRET = secrets.token_bytes(32)


class PaymentGatewayError(RuntimeError):
    """The requested demo payment cannot be performed safely."""


def mock_payments_enabled() -> bool:
    """Production requires explicit opt-in; local development keeps its simulator."""
    setting = os.environ.get('DEMO_PAYMENTS_ENABLED')
    if setting is not None:
        return setting.strip().lower() in {'1', 'true', 'yes'}
    return os.environ.get('APP_ENV', 'development').strip().lower() in {'development', 'testing'}


def gateway_name() -> str:
    return 'mock' if mock_payments_enabled() else 'disabled'


def compute_amounts(ticket_amount: float, seat_count: int) -> dict:
    """Preserve the existing fee, GST and rounding rules."""
    fee = round(CONVENIENCE_FEE_PER_SEAT * seat_count, 2)
    gst = round(fee * GST_RATE, 2)
    total = round(ticket_amount + fee + gst, 2)
    return {'ticket_amount': round(ticket_amount, 2), 'convenience_fee': fee,
            'gst': gst, 'total': total}


def create_order(amount_rupees: float, receipt: str, notes: dict | None = None) -> dict:
    if not mock_payments_enabled():
        raise PaymentGatewayError('Demo payments are disabled. No real payment is available.')
    try:
        amount = float(amount_rupees)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PaymentGatewayError('Payment amount must be a finite positive value.') from exc
    if not math.isfinite(amount) or not math.isfinite(amount * 100) or amount <= 0:
        raise PaymentGatewayError('Payment amount must be a finite positive value.')
    amount_paise = int(round(amount * 100))
    if amount_paise <= 0:
        raise PaymentGatewayError('Payment amount is below the supported minimum.')
    return {'order_id': f'order_mock_{secrets.token_hex(8)}', 'amount_paise': amount_paise,
            'currency': 'INR', 'gateway': 'mock',
            'raw': json.dumps({'demo': True, 'settled': False, 'receipt': receipt,
                               'created_at': int(time.time())})}


def mock_signature(order_id: str, payment_id: str) -> str:
    """Bind demo responses to the private app secret instead of a public constant."""
    key = current_app.config.get('SECRET_KEY') if has_app_context() else os.environ.get('SECRET_KEY')
    if isinstance(key, str):
        key = key.encode()
    return hmac.new(key or _PROCESS_DEMO_SECRET,
                    f'demo|{order_id}|{payment_id}'.encode(), hashlib.sha256).hexdigest()


def verify_signature(order_id: str, payment_id: str, signature: str) -> bool:
    if not all(isinstance(value, str) for value in (order_id, payment_id, signature)):
        return False
    return bool(mock_payments_enabled() and order_id and payment_id and signature
                and len(signature) == 64 and signature.isascii()
                and order_id.startswith('order_mock_') and payment_id.startswith('pay_mock_')
                and hmac.compare_digest(signature, mock_signature(order_id, payment_id)))


def simulate_payment(order_id: str, method: str = 'upi', succeed: bool = True) -> dict:
    if not mock_payments_enabled() or not order_id.startswith('order_mock_'):
        raise PaymentGatewayError('Payment simulation is disabled or this is not a demo order.')
    if method not in DEMO_METHODS:
        raise PaymentGatewayError('Choose a supported demo payment method.')
    payment_id = f'pay_mock_{secrets.token_hex(8)}'
    return {'ok': bool(succeed), 'payment_id': payment_id, 'method': method,
            'signature': mock_signature(order_id, payment_id) if succeed else '',
            'error': None if succeed else 'Demo payment declined (simulated). No money was charged.'}
