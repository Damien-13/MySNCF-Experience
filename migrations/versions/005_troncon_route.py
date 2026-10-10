"""ajoute troncon_route

Revision ID: 005
Revises: 004
"""
from alembic import op
import sqlalchemy as sa


revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('troncon_route',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('classe', sa.String(), nullable=False),
    sa.Column('sens', sa.Integer(), nullable=False),
    sa.Column('tuile', sa.Integer(), nullable=False),
    sa.Column('geometrie', sa.Text(), nullable=False),
    sa.Column('longueur_m', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_troncon_route_tuile'), 'troncon_route', ['tuile'], unique=False)


def downgrade():
    op.drop_table('troncon_route')
