"""Run app test modules in separate processes because each selects its own test DB."""
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    'test_authentication',
    'test_theatre_discovery',
    'test_screen_reviews',
    'test_party',
    'test_demo_payments',
    'test_database_migration',
    'test_admin_movie_deletion',
    'test_auditorium_geometry',
    'test_tmdb_sync',
    'test_experience',
)


def main():
    failures = []
    for module in MODULES:
        print(f'\n=== {module} ===', flush=True)
        result = subprocess.run(
            [sys.executable, '-m', 'unittest', f'tests.{module}'], cwd=ROOT, check=False,
        )
        if result.returncode:
            failures.append(module)

    print('\n=== test_flow.py ===', flush=True)
    result = subprocess.run([sys.executable, '-m', 'tests.test_flow'], cwd=ROOT, check=False)
    if result.returncode:
        failures.append('test_flow.py')

    if failures:
        print('\nFAILED: ' + ', '.join(failures), file=sys.stderr)
        return 1
    print('\nAll isolated Python suites passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
