from ..config import WELCOME_WALLET_BALANCE
from ..extensions import db
from ..models import Wallet, WalletTransaction



def create_wallet(user, balance=WELCOME_WALLET_BALANCE):
    """New wallet with the signup bonus already credited."""
    wallet = Wallet(user_id=user.id, balance=balance)
    db.session.add(wallet)
    db.session.commit()
    if balance:
        db.session.add(WalletTransaction(wallet_id=wallet.id, amount=balance,
                                         type='RECHARGE',
                                         description='Welcome bonus'))
        db.session.commit()
    return wallet


def get_wallet(user):
    wallet = Wallet.query.filter_by(user_id=user.id).first()
    if not wallet:
        wallet = create_wallet(user)
    return wallet
