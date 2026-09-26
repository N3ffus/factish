"""Initial Factish schema with independent facts and fakes."""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("users", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("login", sa.String(32), nullable=False), sa.Column("display_name", sa.String(24), nullable=False), sa.Column("password_hash", sa.String(255), nullable=False), sa.Column("avatar", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_users_login", "users", ["login"], unique=True)
    for table in ("facts", "fakes"):
        op.create_table(table, sa.Column("id", sa.Integer(), primary_key=True), sa.Column("source_id", sa.Integer(), nullable=False, unique=True), sa.Column("category", sa.String(80), nullable=False), sa.Column("statement", sa.Text(), nullable=False, unique=True), sa.Column("explanation", sa.Text(), nullable=False), sa.Column("difficulty", sa.Integer(), nullable=False), sa.Column("active", sa.Boolean(), nullable=False))
        op.create_index(f"ix_{table}_active", table, ["active"])
    op.create_table("runs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")), sa.Column("guest_id", sa.String(36)), sa.Column("score", sa.Integer(), nullable=False), sa.Column("finished", sa.Boolean(), nullable=False), sa.Column("started_at", sa.DateTime(), nullable=False), sa.Column("finished_at", sa.DateTime()), sa.CheckConstraint("(user_id IS NOT NULL) != (guest_id IS NOT NULL)", name="run_one_owner"))
    op.create_index("ix_runs_user_id", "runs", ["user_id"])
    op.create_index("ix_runs_guest_id", "runs", ["guest_id"])
    op.create_index("ix_runs_user_finished", "runs", ["user_id", "finished", "finished_at"])
    op.create_table("rounds", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=False), sa.Column("fact_id", sa.Integer(), sa.ForeignKey("facts.id"), nullable=False), sa.Column("fake_id", sa.Integer(), sa.ForeignKey("fakes.id"), nullable=False), sa.Column("correct_side", sa.String(1), nullable=False), sa.Column("issued_at", sa.DateTime(), nullable=False), sa.Column("resolved_at", sa.DateTime()), sa.Column("selected_side", sa.String(1)), sa.Column("correct", sa.Boolean()))
    op.create_index("ix_rounds_run_id", "rounds", ["run_id"])
    op.create_table("auth_attempts", sa.Column("key", sa.String(100), primary_key=True), sa.Column("count", sa.Integer(), nullable=False), sa.Column("window_at", sa.DateTime(), nullable=False))


def downgrade():
    for table in ("auth_attempts", "rounds", "runs", "fakes", "facts", "users"):
        op.drop_table(table)
