"""Shared dependencies for route modules. Routes use current_app through the `app` alias."""
import base64, csv, datetime as datetime_module, hashlib, hmac, io, json, os, qrcode, re, requests, secrets
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from flask import abort, current_app as app, flash, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func as sa_func
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
import payments
import seat_layout as sl
from cinewave.services.theatres import TheatreService
from vizag_theaters import seed_vizag_theaters
from cinewave.routes.theatre_discovery import cinema_now, validate_booking_context
from ..config import *
from ..data import *
from ..extensions import db
from ..models import *
from ..services import *

__all__ = [name for name in globals() if not name.startswith("__")]
