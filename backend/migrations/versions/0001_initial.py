from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    op.create_table(
        'repos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('ingested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('chunk_count', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('url')
    )

    op.create_table(
        'chunks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('repo_id', sa.Integer(), nullable=False),
        sa.Column('file_path', sa.Text(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(768), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['repo_id'], ['repos.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    op.execute('CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops)')

def downgrade() -> None:
    op.drop_table('chunks')
    op.drop_table('repos')