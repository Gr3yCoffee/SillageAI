"""Initial application schema"""
from alembic import op
from sqlalchemy import inspect
from app.db import Base, engine
from app import models
revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None
def upgrade(): Base.metadata.create_all(bind=op.get_bind())
def downgrade(): Base.metadata.drop_all(bind=op.get_bind())
