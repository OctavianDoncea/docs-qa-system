from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("""
        ALTER TABLE chunks
        ADD COLUMN content_tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED
    """)

    op.execute('CREATE INDEX idx_chunks_content_tsv ON chunks USING GIN (content_tsv)')

def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS idx_chunks_content_tsv')
    op.execute('ALTER TABLE chunks DROP COLUMN IF EXISTS content_tsv')