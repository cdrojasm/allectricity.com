"""Contract of `DesignRepository` for the in-memory and SQL adapters, and migrations 0007/0008.

With `TEST_DATABASE_URL` (as in `make test`) the SQL adapter runs on PostgreSQL in an isolated
schema; without it, on SQLite. The migration test requires PostgreSQL and is skipped otherwise.
"""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from src.domain.identity import ServiceError
from src.infrastructure.persistence.identity_store import SQLIdentityStore
from src.infrastructure.persistence.in_memory_design_repository import InMemoryDesignRepository

POSTGRES_URL = os.environ.get("TEST_DATABASE_URL")
SNAPSHOT = {"name": "Subestación piloto", "geometry": {"length_m": 20, "width_m": 20}}


def alembic_config():
    path = Path("backend/alembic.ini") if Path("backend/alembic.ini").exists() else Path("alembic.ini")
    return Config(str(path))


@pytest.fixture
def database_url(tmp_path, monkeypatch):
    """Empty database: an isolated schema in PostgreSQL, or a SQLite file."""
    if not POSTGRES_URL:
        url = f"sqlite:///{tmp_path / 'designs.db'}"
        monkeypatch.setenv("DATABASE_URL", url)
        yield url
        return
    url = make_url(POSTGRES_URL)
    assert url.database.endswith("_test"), "Only a dedicated _test database is allowed"
    admin = create_engine(POSTGRES_URL)
    schema = "test_" + uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = url.update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", scoped)
    yield scoped
    with admin.begin() as conn:
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


@pytest.fixture
def sql_store(database_url):
    command.upgrade(alembic_config(), "head")
    store = SQLIdentityStore(database_url)
    yield store
    store.engine.dispose()


def add_project(db, project_id="project-1", user_id="user-1"):
    if not db.one("users", id=user_id):
        db.add("users", id=user_id, email=f"{user_id}@example.com", first_name="Ana", last_name="Pérez",
               locale="es-CO", timezone="America/Bogota", active=True, email_verified=True, kind="human",
               idp_provider="local", idp_metadata={}, created_at=0, updated_at=0)
    db.add("projects", id=project_id, owner_id=user_id, name="Proyecto", description="", project_type="land",
           attachments=[], created_at=0, updated_at=0)


@pytest.fixture(params=["memory", "sql"])
def unit_of_work(request):
    """Callable that opens a unit of work and yields the repository bound to it."""
    if request.param == "memory":
        repository = InMemoryDesignRepository()

        class Memory:
            def __enter__(self):
                return repository

            def __exit__(self, *_):
                return False

        return Memory
    store = request.getfixturevalue("sql_store")
    with store.transaction(write=True) as db:
        add_project(db)
        add_project(db, "project-2")

    class SQL:
        def __enter__(self):
            self._tx = store.transaction(write=True)
            return self._tx.__enter__().designs

        def __exit__(self, *exc):
            return self._tx.__exit__(*exc)

    return SQL


def test_create_and_read_back_a_design(unit_of_work):
    with unit_of_work() as designs:
        created = designs.create("project-1", "Malla", SNAPSHOT, "user-1", {"kind": "user"})
    with unit_of_work() as designs:
        stored = designs.get_version("project-1", created["artifact_id"], 1)
        assert designs.exists("project-1", created["artifact_id"])
        assert designs.latest("project-1", created["artifact_id"]) == stored
    assert created["version"] == 1
    assert stored == created
    assert stored["snapshot"] == SNAPSHOT and stored["origin"] == {"kind": "user"}


def test_versions_are_appended_and_earlier_ones_preserved(unit_of_work):
    with unit_of_work() as designs:
        artifact_id = designs.create("project-1", "Malla", SNAPSHOT, "user-1", {"kind": "user"})["artifact_id"]
        edited = {**SNAPSHOT, "geometry": {"length_m": 30, "width_m": 20}}
        second = designs.append_version("project-1", artifact_id, "Malla 30 m", edited, "user-1",
                                        {"kind": "agent", "run_id": "run-1"}, expected_version=1)
    with unit_of_work() as designs:
        versions = designs.versions("project-1", artifact_id)
    assert second["version"] == 2
    assert [row["version"] for row in versions] == [2, 1]
    assert versions[0]["snapshot"] == edited and versions[0]["name"] == "Malla 30 m"
    assert versions[1]["snapshot"] == SNAPSHOT and versions[1]["name"] == "Malla"


def test_stale_expected_version_is_rejected_without_writing(unit_of_work):
    with unit_of_work() as designs:
        artifact_id = designs.create("project-1", "Malla", SNAPSHOT, "user-1", {"kind": "user"})["artifact_id"]
        designs.append_version("project-1", artifact_id, "Malla", SNAPSHOT, "user-1", {"kind": "user"})
    with pytest.raises(ServiceError) as error, unit_of_work() as designs:
        designs.append_version("project-1", artifact_id, "Malla", SNAPSHOT, "user-1", {"kind": "agent"},
                               expected_version=1)
    assert error.value.status == 409
    with unit_of_work() as designs:
        assert designs.latest("project-1", artifact_id)["version"] == 2


def test_unknown_or_foreign_artifact_is_not_found(unit_of_work):
    with unit_of_work() as designs:
        artifact_id = designs.create("project-1", "Malla", SNAPSHOT, "user-1", {"kind": "user"})["artifact_id"]
        assert not designs.exists("project-2", artifact_id)
        assert designs.get_version("project-2", artifact_id, 1) is None
        assert designs.versions("project-2", artifact_id) == []
        for project_id, target in (("project-1", "missing"), ("project-2", artifact_id)):
            with pytest.raises(ServiceError) as error:
                designs.append_version(project_id, target, "Malla", SNAPSHOT, "user-1", {"kind": "user"})
            assert error.value.status == 404


def test_deleted_version_numbers_are_never_reused(unit_of_work):
    with unit_of_work() as designs:
        artifact_id = designs.create("project-1", "Malla", SNAPSHOT, "user-1", {"kind": "user"})["artifact_id"]
        designs.append_version("project-1", artifact_id, "Malla", SNAPSHOT, "user-1", {"kind": "user"})
        assert designs.delete_version("project-1", artifact_id, 2)
        assert not designs.delete_version("project-1", artifact_id, 2)
        assert designs.latest("project-1", artifact_id)["version"] == 1
        third = designs.append_version("project-1", artifact_id, "Malla", SNAPSHOT, "user-1", {"kind": "user"},
                                       expected_version=2)
    assert third["version"] == 3


def test_latest_by_artifact_lists_one_row_per_artifact(unit_of_work):
    with unit_of_work() as designs:
        first = designs.create("project-1", "A", SNAPSHOT, "user-1", {"kind": "user"})["artifact_id"]
        designs.append_version("project-1", first, "A v2", SNAPSHOT, "user-1", {"kind": "user"})
        second = designs.create("project-1", "B", SNAPSHOT, "user-1", {"kind": "user"})["artifact_id"]
        designs.create("project-2", "C", SNAPSHOT, "user-1", {"kind": "user"})
        rows = designs.latest_by_artifact("project-1")
    assert {(row["artifact_id"], row["version"]) for row in rows} == {(first, 2), (second, 1)}


def test_database_rejects_a_duplicate_version(sql_store):
    with sql_store.transaction(write=True) as db:
        add_project(db)
        row = db.designs.create("project-1", "Malla", SNAPSHOT, "user-1", {"kind": "user"})
    with pytest.raises(IntegrityError), sql_store.transaction(write=True) as db:
        db.add("artefacto_diseno_tierras", **{**row, "id": str(uuid4())})


@pytest.mark.skipif(not POSTGRES_URL, reason="requires PostgreSQL (TEST_DATABASE_URL, as in `make test`)")
def test_migrations_up_to_0008_on_postgresql(database_url):
    assert make_url(database_url).get_backend_name() == "postgresql"
    config = alembic_config()
    command.upgrade(config, "0008_calculos_potencial_tierras")
    engine = create_engine(database_url)
    try:
        schema = inspect(engine)
        tables = set(schema.get_table_names())
        assert {"artefacto_diseno_tierras", "artefacto_diseno_tierras_counters",
                "calculos_potencial_tierras"} <= tables
        assert {c["name"] for c in schema.get_unique_constraints("artefacto_diseno_tierras")} == {
            "uq_artefacto_diseno_tierras_version"}
        assert "ck_calculo_potencial_status" in {
            c["name"] for c in schema.get_check_constraints("calculos_potencial_tierras")}
        types = {c["name"]: c["type"].__class__.__name__ for c in schema.get_columns("artefacto_diseno_tierras")}
        assert types["snapshot"] == "JSON" and types["version"] == "BIGINT"
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == \
                "0008_calculos_potencial_tierras"

        command.downgrade(config, "0006_file_ocr_confidence")
        tables = set(inspect(engine).get_table_names())
        assert not {"artefacto_diseno_tierras", "artefacto_diseno_tierras_counters",
                    "calculos_potencial_tierras"} & tables

        command.upgrade(config, "head")
        store = SQLIdentityStore(database_url)
        with store.transaction(write=True) as db:
            add_project(db)
            row = db.designs.create("project-1", "Malla", SNAPSHOT, "user-1", {"kind": "user"})
        with store.transaction() as db:
            assert db.designs.get_version("project-1", row["artifact_id"], 1)["snapshot"] == SNAPSHOT
        store.engine.dispose()
    finally:
        engine.dispose()


def test_migration_0013_versions_legacy_snapshots_and_calculation_documents(database_url):
    config = alembic_config()
    command.upgrade(config, "0012_upload_recovery")
    store = SQLIdentityStore(database_url)
    legacy_snapshot = {"name": "Malla histórica", "geometry": None}
    legacy_result = {"grid_resistance_ohm": 1.25, "old_result_field": "preserved"}
    legacy_trace = {"parameters": {"discretization_m": 1.0}, "old_trace_field": "preserved"}
    with store.transaction(write=True) as db:
        add_project(db)
        artifact = db.designs.create("project-1", "Malla histórica", legacy_snapshot, "user-1", {"kind": "user"})
        db.add("calculos_potencial_tierras", id="calculation-1", project_id="project-1",
               artifact_id=artifact["artifact_id"], artifact_version=1, status="completed", parameters={},
               result=legacy_result, trace=legacy_trace, error=None, created_by="user-1", created_at=1, updated_at=1)
    store.engine.dispose()

    command.upgrade(config, "head")
    store = SQLIdentityStore(database_url)
    try:
        with store.transaction() as db:
            migrated_artifact = db.designs.get_version("project-1", artifact["artifact_id"], 1)
            migrated_calculation = db.one("calculos_potencial_tierras", id="calculation-1")
        assert migrated_artifact["snapshot"] == {**legacy_snapshot, "schema_version": "1.0"}
        assert migrated_calculation["result"] == {**legacy_result, "schema_version": "0.legacy"}
        assert migrated_calculation["trace"] == {**legacy_trace, "schema_version": "0.legacy"}
    finally:
        store.engine.dispose()


def test_rods_of_different_lengths_are_stored_as_given(unit_of_work):
    """SV-28: the optimizer and the plan editor write a length per rod; `None` means "inherit rod_length_m"."""
    snapshot = {**SNAPSHOT, "geometry": {**SNAPSHOT["geometry"], "burial_depth_m": 0.5, "rod_length_m": 2.4,
                                         "conductors": [{"start": {"x": 0, "y": 0}, "end": {"x": 20, "y": 0}}],
                                         "rods": [{"x": 0, "y": 0, "length_m": 1.5}, {"x": 10, "y": 0, "length_m": None},
                                                  {"x": 20, "y": 0, "length_m": 6.0}]}}
    with unit_of_work() as designs:
        created = designs.create("project-1", "Malla", snapshot, "user-1", {"kind": "user"})
    with unit_of_work() as designs:
        stored = designs.get_version("project-1", created["artifact_id"], 1)
    assert stored["snapshot"]["geometry"]["rods"] == snapshot["geometry"]["rods"]
