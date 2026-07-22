from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

app.config["SECRET_KEY"] = "bookinghub123"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///bookinghub.db"

db = SQLAlchemy(app)

from models.user import User
from models.wallet import Wallet
from models.booking import Booking
from models.service import Service
from models.recharge import Recharge

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)