# Local run notes

- Install dependencies with `.venv/Scripts/python.exe -m pip install -r requirements.txt`.
- Copy `.env.example` only if `.env` does not exist. Keep private settings untracked.
- Run `.venv/Scripts/python.exe app.py`; open http://127.0.0.1:5000.
- Development uses SQLite. First-time local initialization requires ADMIN_PASSWORD;
  existing accounts and credentials are preserved. Never delete a database to reseed it.
- All payment methods are demo-only. Production requires explicit DEMO_PAYMENTS_ENABLED=true.
- For Render Free commands, variables and limitations, see docs/PRODUCTION_DEPLOYMENT_GUIDE.md.
- Tests always use disposable databases. Never run tests against Supabase.
