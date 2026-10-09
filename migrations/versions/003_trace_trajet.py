"""ajoute trace_trajet

Revision ID: 003
Revises: 002
"""
from alembic import op
import sqlalchemy as sa


revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('trace_trajet',
    sa.Column('arret_depart_id', sa.String(), nullable=False),
    sa.Column('arret_arrivee_id', sa.String(), nullable=False),
    sa.Column('geometrie', sa.Text(), nullable=False),
    sa.Column('longueur_km', sa.Float(), nullable=True),
    sa.Column('sur_voie', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['arret_arrivee_id'], ['arret.id'], ),
    sa.ForeignKeyConstraint(['arret_depart_id'], ['arret.id'], ),
    sa.PrimaryKeyConstraint('arret_depart_id', 'arret_arrivee_id')
    )


def downgrade():
    op.drop_table('trace_trajet')
