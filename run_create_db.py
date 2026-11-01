import os
import sys
sys.path.append('c:\\Code\\MD-booking-hub')
from app import app, db
with app.app_context():
    db.create_all()
    print('Database tables created')
