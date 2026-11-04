"""Preserve extended fragrance catalog details for the collection view."""
from alembic import op
import sqlalchemy as sa

revision = '0004_fragrance_catalog_metadata'
down_revision = '0003_fragella_catalog'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('perfumes', sa.Column('catalog_metadata', sa.JSON(), nullable=False, server_default=sa.text("'{}'")))

def downgrade():
    op.drop_column('perfumes', 'catalog_metadata')
