
import json
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from database_config import database_settings

# Load the existing project environment.
load_dotenv()

BACKUP = Path(
    "instance/theatre_backups/"
    "theatre_only_20261111_001154.json"
)

EXPECTED_THEATERS = 89
EXPECTED_SCREENS = 127

def main():
    if not BACKUP.is_file():
        raise RuntimeError(f"Backup not found: {BACKUP.resolve()}")

    with BACKUP.open("r", encoding="utf-8") as f:
        data = json.load(f)

    theaters = data["theaters"]
    screens = data["screens"]

    # Validate the backup before connecting.
    if len(theaters) != EXPECTED_THEATERS:
        raise RuntimeError("Unexpected theatre count in backup.")

    if len(screens) != EXPECTED_SCREENS:
        raise RuntimeError("Unexpected screen count in backup.")

    theater_ids = [t["id"] for t in theaters]
    screen_ids = [s["id"] for s in screens]

    if len(set(theater_ids)) != len(theater_ids):
        raise RuntimeError("Duplicate theatre IDs in backup.")

    if len(set(screen_ids)) != len(screen_ids):
        raise RuntimeError("Duplicate screen IDs in backup.")

    theater_names = [t["name"] for t in theaters]
    if len(set(theater_names)) != len(theater_names):
        raise RuntimeError("Duplicate theatre names in backup.")

    valid_theater_ids = set(theater_ids)

    for screen in screens:
        if screen["theater_id"] not in valid_theater_ids:
            raise RuntimeError(
                f"Screen {screen['id']} references a missing theatre."
            )
        if not isinstance(screen["layout_json"], str):
            raise RuntimeError(
                f"Screen {screen['id']} has an invalid layout_json value."
            )

    # Use the project's configured PostgreSQL connection.
    database_url, _ = database_settings()
    engine = create_engine(
        database_url,
        connect_args={"connect_timeout": 10}
    )

    try:
        # Everything inside this block is one transaction.
        # Any error automatically rolls back the import.
        with engine.begin() as conn:

            # Prevent concurrent changes while checking and importing.
            conn.execute(text(
                "LOCK TABLE public.theater, public.screen "
                "IN SHARE ROW EXCLUSIVE MODE"
            ))

            theater_count = conn.execute(text(
                "SELECT COUNT(*) FROM public.theater"
            )).scalar_one()

            screen_count = conn.execute(text(
                "SELECT COUNT(*) FROM public.screen"
            )).scalar_one()

            if theater_count != 0 or screen_count != 0:
                raise RuntimeError(
                    "Destination is not empty. Import cancelled."
                )

            # Insert theatres first.
            conn.execute(
                text("""
                    INSERT INTO public.theater
                    (id, name, location, city, address)
                    VALUES
                    (:id, :name, :location, :city, :address)
                """),
                theaters
            )

            # Insert screens, preserving IDs and layout JSON.
            conn.execute(
                text("""
                    INSERT INTO public.screen
                    (id, theater_id, name, screen_type, layout_json)
                    VALUES
                    (:id, :theater_id, :name, :screen_type, :layout_json)
                """),
                screens
            )

            # Synchronize generated ID sequences.
            conn.execute(text("""
                SELECT setval(
                    pg_get_serial_sequence('public.theater', 'id'),
                    (SELECT MAX(id) FROM public.theater),
                    true
                )
            """))

            conn.execute(text("""
                SELECT setval(
                    pg_get_serial_sequence('public.screen', 'id'),
                    (SELECT MAX(id) FROM public.screen),
                    true
                )
            """))

            # Verify counts before transaction commits.
            final_theaters = conn.execute(text(
                "SELECT COUNT(*) FROM public.theater"
            )).scalar_one()

            final_screens = conn.execute(text(
                "SELECT COUNT(*) FROM public.screen"
            )).scalar_one()

            if final_theaters != EXPECTED_THEATERS:
                raise RuntimeError("Theatre count verification failed.")

            if final_screens != EXPECTED_SCREENS:
                raise RuntimeError("Screen count verification failed.")

            invalid_relationships = conn.execute(text("""
                SELECT COUNT(*)
                FROM public.screen s
                LEFT JOIN public.theater t ON t.id = s.theater_id
                WHERE t.id IS NULL
            """)).scalar_one()

            if invalid_relationships != 0:
                raise RuntimeError("Screen relationship verification failed.")

        print("\nTHEATRE IMPORT SUCCESSFUL")
        print("Theatres:", EXPECTED_THEATERS)
        print("Screens:", EXPECTED_SCREENS)
        print("Invalid screen relationships:", 0)
        print("Original IDs and layout_json preserved.")
        print("Transaction committed successfully.")

    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
