"""Allow several content CSV files: source_id is unique only within its file."""

from alembic import op
import sqlalchemy as sa

revision = "0002_content_sources"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

# Names the unnamed UNIQUE constraints from 0001 so batch mode can drop them.
NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade():
    # Batch mode recreates the tables; rounds reference them, so the implicit
    # DELETE of DROP TABLE must not trip foreign key checks.
    op.execute("PRAGMA foreign_keys=OFF")
    for table in ("facts", "fakes"):
        with op.batch_alter_table(table, naming_convention=NAMING) as batch:
            batch.drop_constraint(f"uq_{table}_source_id", type_="unique")
            batch.add_column(sa.Column("source", sa.String(120), nullable=False, server_default=""))
    op.execute("PRAGMA foreign_keys=ON")


def downgrade():
    op.execute("PRAGMA foreign_keys=OFF")
    for table in ("facts", "fakes"):
        with op.batch_alter_table(table, naming_convention=NAMING) as batch:
            batch.drop_column("source")
            batch.create_unique_constraint(f"uq_{table}_source_id", ["source_id"])
    op.execute("PRAGMA foreign_keys=ON")
