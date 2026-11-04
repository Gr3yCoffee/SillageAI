"""Add persistent fragrance favorites."""
from alembic import op
import sqlalchemy as sa

revision = '0005_favorite_perfume'
down_revision = '0004_fragrance_catalog_metadata'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('perfumes', sa.Column('is_favorite', sa.Boolean(), nullable=False, server_default=sa.false()))

def downgrade():
    op.drop_column('perfumes', 'is_favorite')
