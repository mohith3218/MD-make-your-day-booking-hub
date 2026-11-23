# Render Free deployment: one Flask service, demo payments only

The same Python Web Service serves Flask routes, Jinja templates and static Three.js
assets. There is no separate frontend project and no real-money payment provider.
No deployment or account configuration has been performed by this change.

## Render service settings

- Runtime: Python; repository root as the working directory; instance type: Free.
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 app:app`
- Render assigns PORT and an onrender.com URL after a successful deployment.

Gunicorn loads `gunicorn.conf.py` from the working directory. Its production
preflight validates the private session key and runs the existing read-only
PostgreSQL schema/connectivity health check. An unhealthy database stops startup.
It never creates tables, migrates, seeds, resets users or changes existing data.

## Required environment variables

```dotenv
APP_ENV=production
DATABASE_URL=<existing private Supabase PostgreSQL Session pooler URI>
DATABASE_SSLMODE=require
SECRET_KEY=<private random value of at least 32 characters>
DEMO_PAYMENTS_ENABLED=true
BREVO_API_KEY=<private Brevo API v3 key>
BREVO_SENDER_EMAIL=<verified sender address>
BREVO_SENDER_NAME=CineWave
PASSWORD_RESET_ORIGIN=https://<your-render-service>.onrender.com
```

Store the real DATABASE_URL and SECRET_KEY only in Render's environment settings.
Use the existing pooler connection from Supabase Connect; encode its password
correctly and preserve TLS. Do not paste credentials into tracked files or logs.
The true demo setting is required to offer checkout; omitting it or setting false
keeps the production website available but blocks all demo payment/recharge routes.
Secure session and remembered-login cookies and HSTS stay enabled. Password
recovery requires a Brevo API v3 key, a verified sender, and the exact trusted
HTTPS origin. Without those values, the page reports that recovery email is
unavailable and does not claim to have sent a message.

Optional: `TMDB_API_KEY` for movie import and cast lookup. It is unnecessary for
browsing stored movies. ADMIN_PASSWORD is not required for existing production
accounts. The development-only SQLite seeder is never used in production.

## Protect the existing database

Back up the Supabase database before applying migrations. Do not run init/reseed/
transfer scripts or an automatic migration as a build step.
Existing IDs, users, movies, theatres, layouts, bookings, wallet values and payment
history stay intact. Apply the additive changes once from the service root with
`alembic upgrade head`, then run `python database_health.py`; the expected head is
`20261123_01`. Apply migrations as an operator step after reviewing the backup,
never as a build command. Do not run a baseline over populated tables.

Only a fresh local development database may be created using `python app.py` and
an explicitly supplied ADMIN_PASSWORD. Development deliberately uses SQLite even
if a private Supabase URL is present. Tests assign fresh disposable SQLite files.

## Demo transaction meaning

Choose simulated UPI, card or netbanking, then simulate success/failure. Wallet and
split payments use virtual credits. No network gateway is contacted, no sensitive
payment fields are collected and no real funds move. New payment metadata includes
`demo=true` and `settled=false`. Legacy PAID/CAPTURED states preserve booking logic;
they are not financial settlement claims. Demo tickets/QR codes/email and CSV
exports identify their demo meaning. Historical external records are preserved
and cannot be completed by the simulator.

## Free-tier limitations and remaining checks

- Free services have an ephemeral filesystem: do not store application data in
  SQLite in production. Uploaded trailers/reference photos stored on disk are not
  durable across restarts/redeploys. Already-committed static 3D assets remain part
  of each build. Durable upload storage is outside this focused change.
- Password recovery uses HTTPS to Brevo and does not depend on Render SMTP ports.
  Optional ticket email still uses the separately configured SMTP relay; on-screen
  e-tickets and QR downloads continue working when that relay is unavailable.
- Free services may spin down when idle and take time to wake. No availability or
  hardware-performance guarantee is made for an academic demo.
- An actual Linux/Gunicorn deployment, Supabase connectivity and recovery delivery
  with the live registered sender remain to be verified.
  Local tests must never use the real Supabase database.

References: [Render Flask deployment](https://render.com/docs/deploy-flask),
[Gunicorn configuration and hooks](https://gunicorn.org/reference/settings/),
[Free service limits](https://render.com/docs/free),
[SMTP restrictions](https://render.com/changelog/free-web-services-will-no-longer-allow-outbound-traffic-to-smtp-ports).
