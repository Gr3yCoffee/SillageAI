"""Cache Fragella-sourced details in collection and track monthly lookups."""
from alembic import op
import sqlalchemy as sa

revision = '0003_fragella_catalog'
down_revision = '0002_catalog_metadata'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('perfumes') as batch:
        batch.alter_column('longevity', existing_type=sa.Integer(), nullable=True)
        batch.alter_column('projection', existing_type=sa.Integer(), nullable=True)
    # Earlier catalog entries used 3 as an unverified placeholder when ratings
    # were absent. Preserve explicit non-neutral values and mark placeholders unknown.
    op.execute("UPDATE perfumes SET longevity = NULL WHERE longevity = 3")
    op.execute("UPDATE perfumes SET projection = NULL WHERE projection = 3")
    op.create_table(
        'fragella_usage',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_fragella_usage_requested_at', 'fragella_usage', ['requested_at'])

def downgrade():
    op.drop_index('ix_fragella_usage_requested_at', table_name='fragella_usage')
    op.drop_table('fragella_usage')
    with op.batch_alter_table('perfumes') as batch:
        batch.alter_column('longevity', existing_type=sa.Integer(), nullable=False)
        batch.alter_column('projection', existing_type=sa.Integer(), nullable=False)
