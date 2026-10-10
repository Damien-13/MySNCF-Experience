"""ajoute ligne_bus

Revision ID: 004
Revises: 003
"""
from alembic import op
import sqlalchemy as sa


revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ligne_bus',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ref', sa.String(), nullable=True),
    sa.Column('nom', sa.String(), nullable=True),
    sa.Column('reseau', sa.String(), nullable=True),
    sa.Column('exploitant', sa.String(), nullable=True),
    sa.Column('de', sa.String(), nullable=True),
    sa.Column('vers', sa.String(), nullable=True),
    sa.Column('geometrie', sa.Text(), nullable=False),
    sa.Column('longueur_km', sa.Float(), nullable=True),
    sa.Column('lat_min', sa.Float(), nullable=False),
    sa.Column('lat_max', sa.Float(), nullable=False),
    sa.Column('lon_min', sa.Float(), nullable=False),
    sa.Column('lon_max', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ligne_bus_ref'), 'ligne_bus', ['ref'], unique=False)
    op.create_index(op.f('ix_ligne_bus_lat_min'), 'ligne_bus', ['lat_min'], unique=False)
    op.create_index(op.f('ix_ligne_bus_lat_max'), 'ligne_bus', ['lat_max'], unique=False)
    op.create_index(op.f('ix_ligne_bus_lon_min'), 'ligne_bus', ['lon_min'], unique=False)
    op.create_index(op.f('ix_ligne_bus_lon_max'), 'ligne_bus', ['lon_max'], unique=False)


def downgrade():
    op.drop_table('ligne_bus')
