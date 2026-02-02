from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Base

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    if settings.database_url.startswith("sqlite:///"):
        db_path = settings.database_url.replace("sqlite:///", "", 1)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _sqlite_migrate()
    Base.metadata.create_all(bind=engine)


def _sqlite_migrate() -> None:
    with engine.connect() as conn:
        def table_columns(table: str) -> set[str]:
            result = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            return {row[1] for row in result}

        posts_exists = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='posts'"
        ).fetchone()
        if posts_exists:
            columns = table_columns("posts")
            if "score" not in columns:
                conn.exec_driver_sql("ALTER TABLE posts ADD COLUMN score INTEGER DEFAULT 0")

        comments_exists = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='comments'"
        ).fetchone()
        if comments_exists:
            columns = table_columns("comments")
            if "score" not in columns:
                conn.exec_driver_sql("ALTER TABLE comments ADD COLUMN score INTEGER DEFAULT 0")
            if "parent_comment_id" not in columns:
                conn.exec_driver_sql("ALTER TABLE comments ADD COLUMN parent_comment_id INTEGER")

        votes_exists = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='votes'"
        ).fetchone()
        if not votes_exists:
            conn.exec_driver_sql(
                """
                CREATE TABLE votes (
                    id INTEGER PRIMARY KEY,
                    value INTEGER NOT NULL,
                    created_at DATETIME,
                    voter_id INTEGER NOT NULL,
                    post_id INTEGER,
                    comment_id INTEGER,
                    FOREIGN KEY(voter_id) REFERENCES agents(id),
                    FOREIGN KEY(post_id) REFERENCES posts(id),
                    FOREIGN KEY(comment_id) REFERENCES comments(id)
                )
                """
            )

        # AgentPersona table
        personas_exists = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_personas'"
        ).fetchone()
        if not personas_exists:
            conn.exec_driver_sql(
                """
                CREATE TABLE agent_personas (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(100) UNIQUE,
                    display_name VARCHAR(200),
                    description TEXT,
                    personality_traits TEXT DEFAULT '[]',
                    communication_style VARCHAR(50) DEFAULT 'casual',
                    expertise_areas TEXT DEFAULT '[]',
                    activity_level VARCHAR(20) DEFAULT 'moderate',
                    response_tendency FLOAT DEFAULT 0.5,
                    post_tendency FLOAT DEFAULT 0.3,
                    base_system_prompt TEXT,
                    example_messages TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME
                )
                """
            )

        # ConversationMemory table
        memories_exists = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='conversation_memories'"
        ).fetchone()
        if not memories_exists:
            conn.exec_driver_sql(
                """
                CREATE TABLE conversation_memories (
                    id INTEGER PRIMARY KEY,
                    agent_id INTEGER NOT NULL,
                    context_type VARCHAR(50),
                    context_key VARCHAR(200),
                    summary TEXT,
                    key_points TEXT DEFAULT '[]',
                    sentiment VARCHAR(20),
                    importance_score FLOAT DEFAULT 0.5,
                    last_accessed DATETIME,
                    access_count INTEGER DEFAULT 0,
                    created_at DATETIME,
                    expires_at DATETIME,
                    FOREIGN KEY(agent_id) REFERENCES agents(id)
                )
                """
            )

        # Add new columns to agents table
        agents_exists = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agents'"
        ).fetchone()
        if agents_exists:
            columns = table_columns("agents")
            if "persona_id" not in columns:
                conn.exec_driver_sql("ALTER TABLE agents ADD COLUMN persona_id INTEGER")
            if "status" not in columns:
                conn.exec_driver_sql("ALTER TABLE agents ADD COLUMN status VARCHAR(20) DEFAULT 'idle'")
            if "last_action_at" not in columns:
                conn.exec_driver_sql("ALTER TABLE agents ADD COLUMN last_action_at DATETIME")
            if "action_count" not in columns:
                conn.exec_driver_sql("ALTER TABLE agents ADD COLUMN action_count INTEGER DEFAULT 0")
            if "posts_created" not in columns:
                conn.exec_driver_sql("ALTER TABLE agents ADD COLUMN posts_created INTEGER DEFAULT 0")
            if "comments_created" not in columns:
                conn.exec_driver_sql("ALTER TABLE agents ADD COLUMN comments_created INTEGER DEFAULT 0")
            if "total_score_received" not in columns:
                conn.exec_driver_sql("ALTER TABLE agents ADD COLUMN total_score_received INTEGER DEFAULT 0")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
