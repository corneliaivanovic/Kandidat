"""
SQLite-stöd för träningsplattformen.

Håller kärndatan persistent mellan omstarter:
- användare
- idrottarprofiler
- loggade pass
- planerade pass
- kommentarer på loggar
- testresultat
- skador/frånvaro
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent / "app.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            coach_code TEXT,
            connected_coach_id INTEGER,
            FOREIGN KEY (connected_coach_id) REFERENCES users(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS athletes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            name TEXT NOT NULL,
            birth_year INTEGER NOT NULL,
            discipline TEXT NOT NULL,
            club TEXT DEFAULT '',
            training_mode TEXT DEFAULT 'coach',
            training_days_per_week INTEGER DEFAULT 4,
            training_phase TEXT DEFAULT 'grundträning',
            running_focus TEXT DEFAULT '',
            training_experience_level TEXT DEFAULT '',
            weekly_training_amount TEXT DEFAULT '',
            primary_goal TEXT DEFAULT '',
            injury_constraints TEXT DEFAULT '',
            best_5k_time TEXT DEFAULT '',
            best_alt_distance TEXT DEFAULT '',
            best_alt_time TEXT DEFAULT '',
            easy_pace TEXT DEFAULT '',
            threshold_pace TEXT DEFAULT '',
            training_surface TEXT DEFAULT '',
            tempo_model_runner_key TEXT DEFAULT '',
            tempo_model_personal_offset_seconds REAL DEFAULT 0,
            tempo_model_offset_samples INTEGER DEFAULT 0,
            response_notes TEXT DEFAULT '',
            has_external_training_data INTEGER DEFAULT 0,
            rag_documents TEXT DEFAULT '[]',
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS training_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            athlete_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            session_type TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            rpe INTEGER NOT NULL,
            comment TEXT DEFAULT '',
            planned_session_id INTEGER,
            actual_pace_seconds_per_km REAL,
            FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS planned_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            athlete_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            template_id TEXT NOT NULL,
            session_name TEXT NOT NULL,
            session_type TEXT NOT NULL,
            planned_duration INTEGER NOT NULL,
            planned_intensity TEXT NOT NULL,
            exercises_json TEXT DEFAULT '[]',
            coach_notes TEXT DEFAULT '',
            completed INTEGER DEFAULT 0,
            log_id INTEGER,
            source TEXT DEFAULT 'coach',
            is_key_session INTEGER DEFAULT 0,
            week_theme TEXT DEFAULT '',
            training_phase TEXT DEFAULT '',
            estimated_low_minutes INTEGER DEFAULT 0,
            estimated_medium_minutes INTEGER DEFAULT 0,
            estimated_high_minutes INTEGER DEFAULT 0,
            intensity_distribution_source TEXT DEFAULT '',
            tempo_source TEXT DEFAULT '',
            tempo_assumptions TEXT DEFAULT '',
            tempo_surface_options_json TEXT DEFAULT '[]',
            FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS log_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            author_name TEXT NOT NULL,
            author_role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (log_id) REFERENCES training_logs(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS test_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            athlete_id INTEGER NOT NULL,
            test_date TEXT NOT NULL,
            test_type TEXT NOT NULL,
            test_name TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            recorded_by_id INTEGER,
            FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS injuries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            athlete_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT,
            injury_type TEXT NOT NULL,
            body_part TEXT DEFAULT '',
            severity TEXT NOT NULL,
            description TEXT DEFAULT '',
            treatment TEXT DEFAULT '',
            training_modifications TEXT DEFAULT '',
            recorded_by_id INTEGER,
            is_active INTEGER DEFAULT 1,
            FOREIGN KEY (athlete_id) REFERENCES athletes(id) ON DELETE CASCADE
        )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_athletes_user_id ON athletes(user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_athlete_id ON training_logs(athlete_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_athlete_id ON planned_sessions(athlete_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_comments_log_id ON log_comments(log_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tests_athlete_id ON test_results(athlete_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_injuries_athlete_id ON injuries(athlete_id)")

    conn.commit()
    conn.close()

