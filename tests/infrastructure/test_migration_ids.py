import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "backend" / "migrations" / "versions"
if not MIGRATIONS.exists():  # test image layout: /app/migrations
    MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def test_revision_ids_fit_postgresql_alembic_version_column():
    """alembic_version.version_num is VARCHAR(32) on PostgreSQL; SQLite does not enforce it, so check here."""
    revisions = {path.name: re.search(r'^revision = "([^"]+)"', path.read_text(), re.M).group(1)
                 for path in MIGRATIONS.glob("*.py")}
    assert revisions
    assert {name: rev for name, rev in revisions.items() if len(rev) > 32} == {}
