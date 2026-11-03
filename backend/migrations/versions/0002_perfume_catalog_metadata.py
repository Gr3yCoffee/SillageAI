"""Store catalog metadata with collection fragrances."""
from alembic import op
import sqlalchemy as sa

revision = '0002_catalog_metadata'
down_revision = '0001_initial'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('perfumes', sa.Column('release_year', sa.Integer(), nullable=True))
    op.add_column('perfumes', sa.Column('secondary_family', sa.String(length=100), nullable=False, server_default=''))
    op.add_column('perfumes', sa.Column('character', sa.String(length=500), nullable=False, server_default=''))
    op.add_column('perfumes', sa.Column('gender', sa.String(length=40), nullable=False, server_default=''))
    op.add_column('perfumes', sa.Column('concentration', sa.String(length=80), nullable=False, server_default=''))
    op.add_column('perfumes', sa.Column('description', sa.Text(), nullable=False, server_default=''))
    op.add_column('perfumes', sa.Column('source_url', sa.String(length=500), nullable=False, server_default=''))
    op.add_column('perfumes', sa.Column('wear_times', sa.JSON(), nullable=False, server_default=sa.text("'[]'")))

def downgrade():
    for column in ('wear_times','source_url','description','concentration','gender','release_year','character','secondary_family'):
        op.drop_column('perfumes',column)
