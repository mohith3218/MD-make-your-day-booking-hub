from datetime import datetime
from ..extensions import db



class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    gateway = db.Column(db.String(30), default='mock')      # demo or historical gateway value
    order_id = db.Column(db.String(80), nullable=True)
    payment_id = db.Column(db.String(80), nullable=True)
    signature = db.Column(db.String(200), nullable=True)
    method = db.Column(db.String(40), nullable=True)        # upi / card / netbanking / wallet
    amount = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(10), default='INR')
    status = db.Column(db.String(20), default='CREATED')    # CREATED|CAPTURED|FAILED|REFUNDED
    error_message = db.Column(db.String(300), nullable=True)
    raw_response = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.Index('ix_payment_order_id', 'order_id'),)

    @property
    def is_demo(self):
        """Classify stored values without rewriting history or changing the schema."""
        return self.gateway in {'mock', 'mock-split', 'wallet'}


class Wallet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    balance = db.Column(db.Float, default=0)

    user = db.relationship('User', backref=db.backref('wallet', uselist=False))


class WalletTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey('wallet.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    type = db.Column(db.String(20), nullable=False)   # RECHARGE / PAYMENT / REFUND
    description = db.Column(db.String(200), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    wallet = db.relationship('Wallet', backref=db.backref('transactions', lazy=True))


class WalletPointConversion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    idempotency_key = db.Column(db.String(64), nullable=False)
    points = db.Column(db.Integer, nullable=False)
    credit = db.Column(db.Float, nullable=False)
    balance_after = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'idempotency_key',
                                          name='uq_wallet_points_conversion_request'),)


class RechargeRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='PENDING')   # PENDING/APPROVED/REJECTED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('recharge_requests', lazy=True))
