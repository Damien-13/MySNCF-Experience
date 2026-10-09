"""ajoute troncon_voie

Revision ID: 002
Revises: 001
"""
from alembic import op
import sqlalchemy as sa


revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('troncon_voie',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('code_ligne', sa.String(), nullable=False),
    sa.Column('type_voie', sa.String(), nullable=True),
    sa.Column('nom_voie', sa.String(), nullable=True),
    sa.Column('geometrie', sa.Text(), nullable=False),
    sa.Column('longueur_km', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('troncon_voie', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_troncon_voie_source'), ['source'], unique=False)
        batch_op.create_index(batch_op.f('ix_troncon_voie_code_ligne'), ['code_ligne'], unique=False)


def downgrade():
    with op.batch_alter_table('troncon_voie', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_troncon_voie_code_ligne'))
        batch_op.drop_index(batch_op.f('ix_troncon_voie_source'))

    op.drop_table('troncon_voie')
