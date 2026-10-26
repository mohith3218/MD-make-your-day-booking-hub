# Run doc — MD CineWave (Flask)

## Artifacts needed before first run
- Python deps are in a local venv at `venv\` (Windows layout). If missing or broken, rebuild:
  ```
  venv\Scripts\pip install -r requirements.txt
  ```
- No `.env` file is used. Optional env vars (all have working defaults, per README/app.py):
  - `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` — live gateway; without them the app runs the sandbox/mock gateway
  - `SECRET_KEY` — Flask secret
  - `TMDB_API_KEY` — movie import feature
- Database `instance\vizag_movies.db` is created and seeded automatically on first start
  (Vizag theatres + screens + default admin `admin` / `admin123`). Delete it for a clean reseed.

## Run the server
- Default port is **5000** (`app.run(debug=True)` in `app.py`), bound to 127.0.0.1.
- Start (detached on Windows, stdout/stderr to separate files):
  ```
  powershell -NoProfile -Command "(Start-Process -FilePath 'C:\Code\MD-booking-hub\venv\Scripts\python.exe' -ArgumentList 'app.py' -WorkingDirectory 'C:\Code\MD-booking-hub' -RedirectStandardOutput '<log>' -RedirectStandardError '<log>.err' -WindowStyle Hidden -PassThru).Id"
  ```
- In a foreground terminal, simply: `venv\Scripts\python.exe app.py`
- If 5000 is taken, either stop the other process or set a port by editing `app.run(..., port=XXXX)` in `app.py` (no env var support yet).
- Ready check: `curl http://127.0.0.1:5000/` → HTTP 200 (log shows "Serving Flask app 'app'").
- Stop: kill the python pid, e.g. `taskkill /PID <pid> /F`.

## Notes
- `debug=True` auto-reloads on code edits, so the preview stays current while developing.
- `python test_flow.py` rebuilds a fresh test DB end-to-end (safe to run anytime; it deletes/recreates the DB).
