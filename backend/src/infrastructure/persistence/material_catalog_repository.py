"""Project scoped, versioned material catalog persistence."""

from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    JSON,
    Numeric,
    String,
    Table,
    Text,
    insert,
    select,
    update,
)
from src.infrastructure.persistence.identity_schema import metadata


material_catalog_items = Table(
    "material_catalog_items",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
    Column("created_by", String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
    Column("updated_by", String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
    Column("name", String(240), nullable=False),
    Column("category", String(60), nullable=False),
    Column("material", String(160)),
    Column("specification", Text, nullable=False),
    Column("structured_options", JSON),
    Column("service_details", JSON),
    Column("contact_data", JSON),
    Column("availability", JSON),
    Column("field_provenance", JSON),
    Column("quantity", Numeric(18, 4)),
    Column("quantity_unit", String(40)),
    Column("quantity_basis", Text),
    Column("price_per_unit", Numeric(18, 4)),
    Column("price_currency", String(3)),
    Column("supplier", String(240)),
    Column("source_name", String(240)),
    Column("source_url", Text),
    Column("country", String(120)),
    Column("city", String(120)),
    Column("quoted_at", BigInteger),
    Column("expires_at", BigInteger),
    Column("notes", Text),
    Column("status", String(20), nullable=False),
    Column("version", BigInteger, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    CheckConstraint("status IN ('candidate', 'approved', 'archived')", name="ck_material_catalog_status"),
    CheckConstraint("quantity IS NULL OR quantity >= 0", name="ck_material_catalog_quantity"),
    CheckConstraint("price_per_unit IS NULL OR price_per_unit >= 0", name="ck_material_catalog_price"),
    CheckConstraint("expires_at IS NULL OR quoted_at IS NULL OR expires_at >= quoted_at", name="ck_material_catalog_quote_dates"),
)
Index("ix_material_catalog_project_status", material_catalog_items.c.project_id, material_catalog_items.c.status)
Index("ix_material_catalog_personal_owner", material_catalog_items.c.created_by, material_catalog_items.c.status)

material_catalog_versions = Table(
    "material_catalog_versions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("item_id", String(36), ForeignKey("material_catalog_items.id", ondelete="CASCADE"), nullable=False),
    Column("project_id", String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
    Column("version", BigInteger, nullable=False),
    Column("action", String(24), nullable=False),
    Column("snapshot", JSON, nullable=False),
    Column("created_by", String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", BigInteger, nullable=False),
    CheckConstraint("action IN ('created', 'updated', 'approved', 'unapproved', 'archived')", name="ck_material_catalog_version_action"),
    Index("uq_material_catalog_item_version", "item_id", "version", unique=True),
    Index("ix_material_catalog_versions_project", "project_id", "item_id", "version"),
)


EDITABLE_FIELDS = (
    "name", "category", "material", "specification", "structured_options", "service_details", "contact_data", "availability", "field_provenance", "quantity", "quantity_unit",
    "quantity_basis", "price_per_unit", "price_currency", "supplier", "source_name",
    "source_url", "country", "city", "quoted_at", "expires_at", "notes",
)


def _plain(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def present(row):
    result = {key: _plain(value) for key, value in dict(row).items()}
    quantity = Decimal(str(result["quantity"])) if result.get("quantity") is not None else None
    price = Decimal(str(result["price_per_unit"])) if result.get("price_per_unit") is not None else None
    result["estimated_cost"] = format(quantity * price, "f") if quantity is not None and price is not None else None
    return result


class MaterialCatalogRepository:
    def __init__(self, connection):
        self.connection = connection

    def get(self, project_id, item_id):
        row = self.connection.execute(
            select(material_catalog_items).where(
                material_catalog_items.c.project_id == project_id,
                material_catalog_items.c.id == item_id,
            )
        ).mappings().first()
        return present(row) if row else None

    def list(self, project_id, status=None):
        stmt = select(material_catalog_items).where(material_catalog_items.c.project_id == project_id)
        if status:
            stmt = stmt.where(material_catalog_items.c.status == status)
        rows = self.connection.execute(stmt.order_by(material_catalog_items.c.updated_at.desc(), material_catalog_items.c.id)).mappings()
        return [present(row) for row in rows]

    def list_personal(self, owner_id, status=None):
        stmt = select(material_catalog_items).where(material_catalog_items.c.project_id.is_(None), material_catalog_items.c.created_by == owner_id)
        if status:
            stmt = stmt.where(material_catalog_items.c.status == status)
        else:
            stmt = stmt.where(material_catalog_items.c.status.in_(("candidate", "approved")))
        rows = self.connection.execute(stmt.order_by(material_catalog_items.c.updated_at.desc(), material_catalog_items.c.id)).mappings()
        return [present(row) for row in rows]

    def get_personal(self, owner_id, item_id):
        row = self.connection.execute(select(material_catalog_items).where(
            material_catalog_items.c.project_id.is_(None), material_catalog_items.c.created_by == owner_id,
            material_catalog_items.c.id == item_id,
        )).mappings().first()
        return present(row) if row else None

    def update_personal(self, owner_id, item_id, values):
        self.connection.execute(update(material_catalog_items).where(
            material_catalog_items.c.project_id.is_(None), material_catalog_items.c.created_by == owner_id,
            material_catalog_items.c.id == item_id,
        ).values(**values))
        return self.get_personal(owner_id, item_id)

    def insert(self, values):
        self.connection.execute(insert(material_catalog_items).values(**values))
        return self.get(values["project_id"], values["id"])

    def update(self, project_id, item_id, values):
        self.connection.execute(
            update(material_catalog_items).where(
                material_catalog_items.c.project_id == project_id,
                material_catalog_items.c.id == item_id,
            ).values(**values)
        )
        return self.get(project_id, item_id)

    def add_version(self, version):
        self.connection.execute(insert(material_catalog_versions).values(**version))

    def add_personal_version(self, version):
        self.add_version(version)

    def versions(self, project_id, item_id):
        rows = self.connection.execute(
            select(material_catalog_versions).where(
                material_catalog_versions.c.project_id == project_id,
                material_catalog_versions.c.item_id == item_id,
            ).order_by(material_catalog_versions.c.version.desc())
        ).mappings()
        return [dict(row) for row in rows]

    def personal_versions(self, owner_id, item_id):
        rows = self.connection.execute(select(material_catalog_versions).where(
            material_catalog_versions.c.project_id.is_(None), material_catalog_versions.c.item_id == item_id,
            material_catalog_versions.c.created_by == owner_id,
        ).order_by(material_catalog_versions.c.version.desc())).mappings()
        return [dict(row) for row in rows]

    def recent_versions(self, project_id, limit=50):
        rows = self.connection.execute(
            select(material_catalog_versions)
            .where(material_catalog_versions.c.project_id == project_id)
            .order_by(
                material_catalog_versions.c.created_at.desc(),
                material_catalog_versions.c.id.desc(),
            )
            .limit(limit)
        ).mappings()
        return [dict(row) for row in rows]
