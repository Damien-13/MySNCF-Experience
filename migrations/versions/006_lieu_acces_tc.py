"""ajoute lieu.acces_tc

Revision ID: 006
Revises: 005
"""
from alembic import op
import sqlalchemy as sa


revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('lieu') as batch_op:
        batch_op.add_column(sa.Column('acces_tc', sa.Boolean(), nullable=True))


def downgrade():
    with op.batch_alter_table('lieu') as batch_op:
        batch_op.drop_column('acces_tc')
