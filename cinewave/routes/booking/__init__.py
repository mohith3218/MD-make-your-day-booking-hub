"""Routes for selecting, paying for, and managing a booking."""
from flask import Blueprint

bp = Blueprint("booking", __name__)

from .seats import book
from .preview import vr_seat_preview
from .checkout import checkout
from .split import split_pay, start_split_payment, split_payment_confirmation, simulate_split_payment
from .payments import update_booking_extras, pay_with_wallet, pay_gateway, pay_mock_confirmation, payment_callback, simulate
from .tickets import cancel_booking, refund_booking, resend_ticket_delivery, ticket, ticket_qr
