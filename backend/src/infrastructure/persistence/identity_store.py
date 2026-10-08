from contextlib import contextmanager
from sqlalchemy import create_engine, select, insert, update, delete, event
from sqlalchemy.pool import StaticPool
from src.infrastructure.persistence.identity_schema import TABLES
from src.infrastructure.persistence.sql_design_repository import SQLDesignRepository


def _key(table):
    """Columna de clave primaria (no todas las tablas usan `id`)."""
    (column,) = table.primary_key.columns
    return column


class SQLRecords:
    def __init__(self, connection):
        self.connection = connection
        self.designs = SQLDesignRepository(connection)

    def one(self, table, **filters):
        records = self.many(table, limit=1, **filters)
        return records[0] if records else None

    def many(self, table, *, limit=None, offset=0, **filters):
        t = TABLES[table]
        stmt = (
            select(t).filter_by(**filters).order_by(_key(t)).limit(limit).offset(offset)
        )
        return [dict(row) for row in self.connection.execute(stmt).mappings()]

    def ordered(self, table, column, *, after=None, limit=None, **filters):
        """Records ordered by `column`, optionally only those with `column > after`."""
        t = TABLES[table]
        stmt = select(t).filter_by(**filters)
        if after is not None:
            stmt = stmt.where(t.c[column] > after)
        stmt = stmt.order_by(t.c[column], _key(t)).limit(limit)
        return [dict(row) for row in self.connection.execute(stmt).mappings()]

    def add(self, table, **values):
        self.connection.execute(insert(TABLES[table]).values(**values))
        return values

    def change(self, table, record_id, **values):
        t = TABLES[table]
        self.connection.execute(update(t).where(_key(t) == record_id).values(**values))

    def remove(self, table, record_id):
        t = TABLES[table]
        self.connection.execute(delete(t).where(_key(t) == record_id))


class SQLIdentityStore:
    def __init__(self, url):
        options = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if ":memory:" in url:
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        if url.startswith("sqlite"):

            @event.listens_for(self.engine, "connect")
            def sqlite_foreign_keys(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")

    @contextmanager
    def transaction(self, *, write=False):
        with self.engine.begin() as connection:
            if write:
                # Cross-process transaction lock: serializes refresh, reset, role changes
                # and budget debit. PostgreSQL row lock; SQLite writer lock in tests.
                t = TABLES["security_lock"]
                result = connection.execute(
                    update(t)
                    .where(t.c.id == "identity")
                    .values(version=t.c.version + 1)
                )
                if result.rowcount != 1:
                    raise RuntimeError("Database migrations have not been applied")
            yield SQLRecords(connection)
