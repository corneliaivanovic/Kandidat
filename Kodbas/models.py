"""
Datamodeller för träningsplattformen.
Hanterar idrottare, träningspass, program och loggposter.
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Optional
import json

from database import get_connection, init_db


@dataclass
class TrainingLog:
    """En loggpost för ett genomfört träningspass."""
    id: int
    athlete_id: int
    date: date
    session_type: str  # "uthållighet", "styrka", "teknik", "snabbhet", "vila"
    duration_minutes: int
    rpe: int  # Rate of Perceived Exertion (1-10)
    comment: str = ""
    planned_session_id: Optional[int] = None  # Koppling till planerat pass
    actual_pace_seconds_per_km: Optional[float] = None

    @property
    def load(self) -> int:
        """Session-RPE load = duration × RPE"""
        return self.duration_minutes * self.rpe

    def to_dict(self):
        return {
            "id": self.id,
            "athlete_id": self.athlete_id,
            "date": self.date.isoformat(),
            "session_type": self.session_type,
            "duration_minutes": self.duration_minutes,
            "rpe": self.rpe,
            "comment": self.comment,
            "load": self.load,
            "planned_session_id": self.planned_session_id,
            "actual_pace_seconds_per_km": self.actual_pace_seconds_per_km,
        }


@dataclass
class PlannedSession:
    """Ett planerat träningspass."""
    id: int
    athlete_id: int
    date: date
    template_id: str  # Referens till SESSION_TEMPLATES
    session_name: str
    session_type: str
    planned_duration: int
    planned_intensity: str  # "låg", "medel", "hög"
    exercises: list[dict] = field(default_factory=list)
    coach_notes: str = ""
    completed: bool = False
    log_id: Optional[int] = None  # Koppling till faktisk logg
    source: str = "coach"  # "ai" eller "coach"
    is_key_session: bool = False
    week_theme: str = ""
    training_phase: str = ""
    estimated_low_minutes: int = 0
    estimated_medium_minutes: int = 0
    estimated_high_minutes: int = 0
    intensity_distribution_source: str = ""
    tempo_source: str = ""
    tempo_assumptions: str = ""
    tempo_surface_options: list[dict] = field(default_factory=list)

    def to_dict(self):
        return {
            "id": self.id,
            "athlete_id": self.athlete_id,
            "date": self.date.isoformat(),
            "template_id": self.template_id,
            "session_name": self.session_name,
            "session_type": self.session_type,
            "planned_duration": self.planned_duration,
            "planned_intensity": self.planned_intensity,
            "exercises": self.exercises,
            "coach_notes": self.coach_notes,
            "completed": self.completed,
            "log_id": self.log_id,
            "source": self.source,
            "is_key_session": self.is_key_session,
            "week_theme": self.week_theme,
            "training_phase": self.training_phase,
            "estimated_low_minutes": self.estimated_low_minutes,
            "estimated_medium_minutes": self.estimated_medium_minutes,
            "estimated_high_minutes": self.estimated_high_minutes,
            "intensity_distribution_source": self.intensity_distribution_source,
            "tempo_source": self.tempo_source,
            "tempo_assumptions": self.tempo_assumptions,
            "tempo_surface_options": self.tempo_surface_options,
        }


@dataclass
class WeekProgram:
    """Ett veckoprogram för en idrottare."""
    id: int
    athlete_id: int
    week_start: date  # Måndag i veckan
    focus: str  # "uthållighet", "styrka", "teknik", etc.
    coach_summary: str = ""
    created_by_coach_id: Optional[int] = None

    def to_dict(self):
        return {
            "id": self.id,
            "athlete_id": self.athlete_id,
            "week_start": self.week_start.isoformat(),
            "focus": self.focus,
            "coach_summary": self.coach_summary,
            "created_by_coach_id": self.created_by_coach_id
        }


@dataclass
class LogComment:
    """En kommentar på ett loggat pass - för coach-idrottare kommunikation."""
    id: int
    log_id: int
    author_id: int  # user_id för den som skrev
    author_name: str
    author_role: str  # "coach" eller "athlete"
    content: str
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "log_id": self.log_id,
            "author_id": self.author_id,
            "author_name": self.author_name,
            "author_role": self.author_role,
            "content": self.content,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class TestResult:
    """Ett fysiskt testresultat för att spåra utveckling."""
    id: int
    athlete_id: int
    test_date: date
    test_type: str  # "standing_jump", "strength", etc.
    test_name: str  # Visningsnamn
    value: float
    unit: str  # "s", "m", "kg", "reps", etc.
    notes: str = ""
    recorded_by_id: Optional[int] = None  # Coach som registrerade

    def to_dict(self):
        return {
            "id": self.id,
            "athlete_id": self.athlete_id,
            "test_date": self.test_date.isoformat(),
            "test_type": self.test_type,
            "test_name": self.test_name,
            "value": self.value,
            "unit": self.unit,
            "notes": self.notes,
            "recorded_by_id": self.recorded_by_id
        }


# Fördefinierade testkategorier (för dropdown i formulär)
TEST_TYPES = {
    "hopp": "Hopp & Explosivitet",
    "styrka": "Styrka",
    "uthållighet": "Uthållighet & Kondition",
    "rörlighet": "Rörlighet & Mobilitet",
    "annat": "Annat"
}


@dataclass
class CustomSessionTemplate:
    """En coach-skapad passmall som kan återanvändas."""
    id: int
    coach_id: int
    coach_name: str
    name: str
    session_type: str  # "uthållighet", "styrka", "teknik", "snabbhet", "återhämtning"
    duration: int  # minuter
    intensity: str  # "låg", "medel", "hög"
    description: str
    exercises: list[dict] = field(default_factory=list)
    is_public: bool = True  # Synlig för idrottare
    created_at: datetime = field(default_factory=datetime.now)
    use_count: int = 0  # Antal gånger passet har använts

    def to_dict(self):
        return {
            "id": self.id,
            "coach_id": self.coach_id,
            "coach_name": self.coach_name,
            "name": self.name,
            "session_type": self.session_type,
            "duration": self.duration,
            "intensity": self.intensity,
            "description": self.description,
            "exercises": self.exercises,
            "is_public": self.is_public,
            "created_at": self.created_at.isoformat(),
            "use_count": self.use_count
        }


@dataclass
class InjuryRecord:
    """En skaderegistrering eller frånvaro."""
    id: int
    athlete_id: int
    start_date: date
    end_date: Optional[date]  # None = pågående
    injury_type: str  # "skada", "sjukdom", "annat"
    body_part: str  # "knä", "vrist", "rygg", etc. (tom för sjukdom)
    severity: str  # "lätt", "måttlig", "allvarlig"
    description: str
    treatment: str = ""  # Vad som görs
    training_modifications: str = ""  # Vad som kan göras trots skadan
    recorded_by_id: Optional[int] = None
    is_active: bool = True

    def to_dict(self):
        return {
            "id": self.id,
            "athlete_id": self.athlete_id,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "injury_type": self.injury_type,
            "body_part": self.body_part,
            "severity": self.severity,
            "description": self.description,
            "treatment": self.treatment,
            "training_modifications": self.training_modifications,
            "recorded_by_id": self.recorded_by_id,
            "is_active": self.is_active
        }

    @property
    def duration_days(self) -> int:
        """Antal dagar skadan varat."""
        end = self.end_date or date.today()
        return (end - self.start_date).days + 1


# Fördefinierade skadeområden
BODY_PARTS = {
    "huvud": "Huvud",
    "nacke": "Nacke",
    "axel": "Axel",
    "överarm": "Överarm",
    "armbåge": "Armbåge",
    "underarm": "Underarm",
    "handled": "Handled",
    "hand": "Hand",
    "rygg_övre": "Övre rygg",
    "rygg_nedre": "Nedre rygg/Ländrygg",
    "höft": "Höft",
    "ljumske": "Ljumske",
    "lår_fram": "Lår (framsida)",
    "lår_bak": "Lår (baksida/Hamstring)",
    "knä": "Knä",
    "vad": "Vad",
    "smalben": "Smalben",
    "vrist": "Vrist/Fotled",
    "fot": "Fot",
    "tå": "Tå",
    "allmänt": "Allmänt/Hela kroppen",
    "annat": "Annat"
}


@dataclass
class Athlete:
    """En idrottare med träningshistorik."""
    id: int
    user_id: int  # Koppling till User
    name: str
    birth_year: int
    discipline: str  # "medel", "distans", "hopp", "kast", "mångkamp"
    club: str = ""  # Klubbtillhörighet för matchning med tävlingsresultat
    training_mode: str = "coach"  # "coach" = tränare lägger in pass, "ai" = AI genererar schema
    training_days_per_week: int = 4  # Antal träningsdagar per vecka (för AI-schema)
    training_phase: str = "grundträning"  # "grundträning", "uppbyggnad", "tävling", "återhämtning"
    rag_documents: list = field(default_factory=lambda: ["loptranare", "friidrottslara", "uppbyggnad"])
    running_focus: str = ""  # "medel", "distans" - separat från friidrottsgren
    training_experience_level: str = ""  # nivå för träningsvana
    weekly_training_amount: str = ""
    primary_goal: str = ""
    injury_constraints: str = ""
    best_5k_time: str = ""
    best_alt_distance: str = ""
    best_alt_time: str = ""
    easy_pace: str = ""
    threshold_pace: str = ""
    training_surface: str = ""
    tempo_model_runner_key: str = ""
    tempo_model_personal_offset_seconds: float = 0.0
    tempo_model_offset_samples: int = 0
    response_notes: str = ""
    has_external_training_data: bool = False
    # Vilka PDF-dokument som används i RAG-sökningen (se DOCUMENT_REGISTRY i rag_knowledge.py)
    logs: list[TrainingLog] = field(default_factory=list)
    planned_sessions: list[PlannedSession] = field(default_factory=list)
    week_programs: list[WeekProgram] = field(default_factory=list)
    test_results: list = field(default_factory=list)  # list[TestResult]
    injuries: list = field(default_factory=list)  # list[InjuryRecord]

    def add_log(self, log: TrainingLog):
        self.logs.append(log)

    def get_logs_last_n_days(self, days: int) -> list[TrainingLog]:
        """Hämta loggposter från de senaste N dagarna."""
        cutoff = date.today() - timedelta(days=days)
        return [log for log in self.logs if log.date >= cutoff]

    def get_total_load_last_n_days(self, days: int) -> int:
        """Total belastning (session-RPE load) senaste N dagarna."""
        return sum(log.load for log in self.get_logs_last_n_days(days))

    def get_session_count_by_type(self, days: int) -> dict[str, int]:
        """Antal pass per typ de senaste N dagarna."""
        logs = self.get_logs_last_n_days(days)
        counts = {}
        for log in logs:
            counts[log.session_type] = counts.get(log.session_type, 0) + 1
        return counts

    def get_planned_sessions_for_week(self, week_start: date) -> list[PlannedSession]:
        """Hämta planerade pass för en specifik vecka."""
        week_end = week_start + timedelta(days=6)
        return [
            ps for ps in self.planned_sessions
            if week_start <= ps.date <= week_end
        ]

    def get_planned_session_for_date(self, target_date: date) -> Optional[PlannedSession]:
        """Hämta planerat pass för ett specifikt datum."""
        for ps in self.planned_sessions:
            if ps.date == target_date and not ps.completed:
                return ps
        return None

    def get_todays_session(self) -> Optional[PlannedSession]:
        """Hämta dagens planerade pass."""
        return self.get_planned_session_for_date(date.today())

    def get_upcoming_sessions(self, days: int = 7) -> list[PlannedSession]:
        """Hämta kommande planerade pass."""
        today = date.today()
        end_date = today + timedelta(days=days)
        return sorted(
            [ps for ps in self.planned_sessions
             if today <= ps.date <= end_date and not ps.completed],
            key=lambda x: x.date
        )

    def get_days_since_last_log(self) -> int:
        """Antal dagar sedan senaste logg."""
        if not self.logs:
            return 999
        latest = max(log.date for log in self.logs)
        return (date.today() - latest).days

    def get_completion_rate_last_n_days(self, days: int) -> float:
        """Andel genomförda av planerade pass senaste N dagarna."""
        cutoff = date.today() - timedelta(days=days)
        planned = [ps for ps in self.planned_sessions if ps.date >= cutoff and ps.date <= date.today()]
        if not planned:
            return 1.0
        completed = sum(1 for ps in planned if ps.completed)
        return completed / len(planned)

    def get_test_history(self, test_type: str) -> list:
        """Hämta testhistorik för en specifik testtyp, sorterad efter datum."""
        return sorted(
            [t for t in self.test_results if t.test_type == test_type],
            key=lambda x: x.test_date
        )

    def get_latest_test(self, test_type: str):
        """Hämta senaste testresultat för en testtyp."""
        history = self.get_test_history(test_type)
        return history[-1] if history else None

    def get_active_injuries(self) -> list:
        """Hämta aktiva skador/frånvaro."""
        return [i for i in self.injuries if i.is_active]

    def get_injury_history(self) -> list:
        """Hämta all skadehistorik, sorterad efter startdatum."""
        return sorted(self.injuries, key=lambda x: x.start_date, reverse=True)

    def has_active_injury(self) -> bool:
        """Kolla om idrottaren har en aktiv skada."""
        return len(self.get_active_injuries()) > 0

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "birth_year": self.birth_year,
            "discipline": self.discipline,
            "club": self.club,
            "training_mode": self.training_mode,
            "training_days_per_week": self.training_days_per_week,
            "training_phase": self.training_phase,
            "running_focus": self.running_focus,
            "training_experience_level": self.training_experience_level,
            "weekly_training_amount": self.weekly_training_amount,
            "primary_goal": self.primary_goal,
            "injury_constraints": self.injury_constraints,
            "best_5k_time": self.best_5k_time,
            "best_alt_distance": self.best_alt_distance,
            "best_alt_time": self.best_alt_time,
            "easy_pace": self.easy_pace,
            "threshold_pace": self.threshold_pace,
            "training_surface": self.training_surface,
            "tempo_model_runner_key": self.tempo_model_runner_key,
            "tempo_model_personal_offset_seconds": self.tempo_model_personal_offset_seconds,
            "tempo_model_offset_samples": self.tempo_model_offset_samples,
            "response_notes": self.response_notes,
            "has_external_training_data": self.has_external_training_data,
            "total_logs": len(self.logs)
        }


class DataStore:
    """Enkel in-memory datalagring (för prototyp)."""

    def __init__(self):
        init_db()
        self.athletes: dict[int, Athlete] = {}
        self.athletes_by_user: dict[int, Athlete] = {}  # user_id -> Athlete
        self.log_comments: dict[int, list[LogComment]] = {}  # log_id -> comments
        self.next_athlete_id = 1
        self.next_log_id = 1
        self.next_planned_session_id = 1
        self.next_week_program_id = 1
        self.next_comment_id = 1
        self.next_test_id = 1
        self.next_injury_id = 1
        self.next_custom_template_id = 1
        self.custom_templates: dict[int, CustomSessionTemplate] = {}  # id -> template

    def _row_to_training_log(self, row) -> Optional[TrainingLog]:
        if not row:
            return None
        return TrainingLog(
            id=row["id"],
            athlete_id=row["athlete_id"],
            date=date.fromisoformat(row["date"]),
            session_type=row["session_type"],
            duration_minutes=row["duration_minutes"],
            rpe=row["rpe"],
            comment=row["comment"] or "",
            planned_session_id=row["planned_session_id"],
            actual_pace_seconds_per_km=row["actual_pace_seconds_per_km"],
        )

    def _row_to_planned_session(self, row) -> Optional[PlannedSession]:
        if not row:
            return None
        return PlannedSession(
            id=row["id"],
            athlete_id=row["athlete_id"],
            date=date.fromisoformat(row["date"]),
            template_id=row["template_id"],
            session_name=row["session_name"],
            session_type=row["session_type"],
            planned_duration=row["planned_duration"],
            planned_intensity=row["planned_intensity"],
            exercises=json.loads(row["exercises_json"] or "[]"),
            coach_notes=row["coach_notes"] or "",
            completed=bool(row["completed"]),
            log_id=row["log_id"],
            source=row["source"] or "coach",
            is_key_session=bool(row["is_key_session"]),
            week_theme=row["week_theme"] or "",
            training_phase=row["training_phase"] or "",
            estimated_low_minutes=row["estimated_low_minutes"] or 0,
            estimated_medium_minutes=row["estimated_medium_minutes"] or 0,
            estimated_high_minutes=row["estimated_high_minutes"] or 0,
            intensity_distribution_source=row["intensity_distribution_source"] or "",
            tempo_source=row["tempo_source"] or "",
            tempo_assumptions=row["tempo_assumptions"] or "",
            tempo_surface_options=json.loads(row["tempo_surface_options_json"] or "[]"),
        )

    def _hydrate_athlete(self, row) -> Optional[Athlete]:
        if not row:
            return None

        cached = self.athletes.get(row["id"])
        athlete = Athlete(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            birth_year=row["birth_year"],
            discipline=row["discipline"],
            club=row["club"] or "",
            training_mode=row["training_mode"] or "coach",
            training_days_per_week=row["training_days_per_week"] or 4,
            training_phase=row["training_phase"] or "grundträning",
            rag_documents=json.loads(row["rag_documents"] or "[]") or ["loptranare", "friidrottslara", "uppbyggnad"],
            running_focus=row["running_focus"] or "",
            training_experience_level=row["training_experience_level"] or "",
            weekly_training_amount=row["weekly_training_amount"] or "",
            primary_goal=row["primary_goal"] or "",
            injury_constraints=row["injury_constraints"] or "",
            best_5k_time=row["best_5k_time"] or "",
            best_alt_distance=row["best_alt_distance"] or "",
            best_alt_time=row["best_alt_time"] or "",
            easy_pace=row["easy_pace"] or "",
            threshold_pace=row["threshold_pace"] or "",
            training_surface=row["training_surface"] or "",
            tempo_model_runner_key=row["tempo_model_runner_key"] or "",
            tempo_model_personal_offset_seconds=row["tempo_model_personal_offset_seconds"] or 0.0,
            tempo_model_offset_samples=row["tempo_model_offset_samples"] or 0,
            response_notes=row["response_notes"] or "",
            has_external_training_data=bool(row["has_external_training_data"]),
            logs=[],
            planned_sessions=[],
            week_programs=cached.week_programs[:] if cached else [],
            test_results=cached.test_results[:] if cached else [],
            injuries=cached.injuries[:] if cached else [],
        )

        conn = get_connection()
        log_rows = conn.execute(
            "SELECT * FROM training_logs WHERE athlete_id = ? ORDER BY date ASC, id ASC",
            (athlete.id,),
        ).fetchall()
        athlete.logs = [self._row_to_training_log(log_row) for log_row in log_rows]

        session_rows = conn.execute(
            "SELECT * FROM planned_sessions WHERE athlete_id = ? ORDER BY date ASC, id ASC",
            (athlete.id,),
        ).fetchall()
        athlete.planned_sessions = [self._row_to_planned_session(session_row) for session_row in session_rows]
        conn.close()

        self.athletes[athlete.id] = athlete
        self.athletes_by_user[athlete.user_id] = athlete
        return athlete

    def create_athlete_for_user(self, user_id: int, name: str, birth_year: int, discipline: str,
                                club: str = "", training_mode: str = "coach",
                                training_days_per_week: int = 4, training_phase: str = "grundträning",
                                **ai_profile) -> Athlete:
        """Skapa en idrottarprofil kopplad till en användare."""
        existing = self.get_athlete_by_user(user_id)
        if existing:
            return existing

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO athletes (
                user_id, name, birth_year, discipline, club, training_mode,
                training_days_per_week, training_phase, running_focus,
                training_experience_level, weekly_training_amount, primary_goal,
                injury_constraints, best_5k_time, best_alt_distance, best_alt_time,
                easy_pace, threshold_pace, training_surface, tempo_model_runner_key,
                tempo_model_personal_offset_seconds, tempo_model_offset_samples,
                response_notes, has_external_training_data, rag_documents
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, name, birth_year, discipline, club, training_mode,
                training_days_per_week, training_phase, ai_profile.get("running_focus", ""),
                ai_profile.get("training_experience_level", ""), ai_profile.get("weekly_training_amount", ""),
                ai_profile.get("primary_goal", ""), ai_profile.get("injury_constraints", ""),
                ai_profile.get("best_5k_time", ""), ai_profile.get("best_alt_distance", ""),
                ai_profile.get("best_alt_time", ""), ai_profile.get("easy_pace", ""),
                ai_profile.get("threshold_pace", ""), ai_profile.get("training_surface", ""),
                ai_profile.get("tempo_model_runner_key", ""),
                float(ai_profile.get("tempo_model_personal_offset_seconds", 0.0) or 0.0),
                int(ai_profile.get("tempo_model_offset_samples", 0) or 0),
                ai_profile.get("response_notes", ""),
                1 if ai_profile.get("has_external_training_data", False) else 0,
                json.dumps(ai_profile.get("rag_documents", ["loptranare", "friidrottslara", "uppbyggnad"])),
            ),
        )
        athlete_id = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM athletes WHERE id = ?", (athlete_id,)).fetchone()
        conn.close()
        return self._hydrate_athlete(row)

    def get_athlete(self, athlete_id: int) -> Optional[Athlete]:
        """Hämta en idrottare via ID."""
        conn = get_connection()
        row = conn.execute("SELECT * FROM athletes WHERE id = ?", (athlete_id,)).fetchone()
        conn.close()
        return self._hydrate_athlete(row)

    def get_athlete_by_user(self, user_id: int) -> Optional[Athlete]:
        """Hämta idrottarprofil för en användare."""
        conn = get_connection()
        row = conn.execute("SELECT * FROM athletes WHERE user_id = ?", (user_id,)).fetchone()
        conn.close()
        return self._hydrate_athlete(row)

    def get_all_athletes(self) -> list[Athlete]:
        """Hämta alla idrottare."""
        conn = get_connection()
        rows = conn.execute("SELECT * FROM athletes ORDER BY name").fetchall()
        conn.close()
        return [self._hydrate_athlete(row) for row in rows]

    def get_athletes_for_coach(self, coach_user_id: int, auth_db) -> list[Athlete]:
        """Hämta alla idrottare kopplade till en coach."""
        # Hämta alla users som är kopplade till denna coach
        athlete_users = auth_db.get_athletes_for_coach(coach_user_id)

        # Returnera deras athlete-profiler
        athletes = []
        for user in athlete_users:
            athlete = self.get_athlete_by_user(user.id)
            if athlete:
                athletes.append(athlete)
        return athletes

    def save_athlete(self, athlete: Athlete) -> Optional[Athlete]:
        """Spara uppdateringar på en idrottarprofil."""
        if not athlete:
            return None

        conn = get_connection()
        conn.execute(
            """
            UPDATE athletes
            SET name = ?, birth_year = ?, discipline = ?, club = ?, training_mode = ?,
                training_days_per_week = ?, training_phase = ?, running_focus = ?,
                training_experience_level = ?, weekly_training_amount = ?, primary_goal = ?,
                injury_constraints = ?, best_5k_time = ?, best_alt_distance = ?, best_alt_time = ?,
                easy_pace = ?, threshold_pace = ?, training_surface = ?, tempo_model_runner_key = ?,
                tempo_model_personal_offset_seconds = ?, tempo_model_offset_samples = ?, response_notes = ?,
                has_external_training_data = ?, rag_documents = ?
            WHERE id = ?
            """,
            (
                athlete.name,
                athlete.birth_year,
                athlete.discipline,
                athlete.club,
                athlete.training_mode,
                athlete.training_days_per_week,
                athlete.training_phase,
                athlete.running_focus,
                athlete.training_experience_level,
                athlete.weekly_training_amount,
                athlete.primary_goal,
                athlete.injury_constraints,
                athlete.best_5k_time,
                athlete.best_alt_distance,
                athlete.best_alt_time,
                athlete.easy_pace,
                athlete.threshold_pace,
                athlete.training_surface,
                athlete.tempo_model_runner_key,
                athlete.tempo_model_personal_offset_seconds,
                athlete.tempo_model_offset_samples,
                athlete.response_notes,
                1 if athlete.has_external_training_data else 0,
                json.dumps(athlete.rag_documents or []),
                athlete.id,
            ),
        )
        conn.commit()
        conn.close()
        self.athletes[athlete.id] = athlete
        self.athletes_by_user[athlete.user_id] = athlete
        return athlete

    def add_log(self, athlete_id: int, log_date: date, session_type: str,
                duration: int, rpe: int, comment: str = "",
                planned_session_id: Optional[int] = None,
                actual_pace_seconds_per_km: Optional[float] = None) -> Optional[TrainingLog]:
        """Lägg till en loggpost för en idrottare."""
        athlete = self.get_athlete(athlete_id)
        if not athlete:
            return None

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO training_logs (
                athlete_id, date, session_type, duration_minutes, rpe, comment,
                planned_session_id, actual_pace_seconds_per_km
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                athlete_id,
                log_date.isoformat(),
                session_type,
                duration,
                rpe,
                comment,
                planned_session_id,
                actual_pace_seconds_per_km,
            ),
        )
        log_id = cur.lastrowid

        # Markera planerat pass som genomfört
        if planned_session_id:
            cur.execute(
                "UPDATE planned_sessions SET completed = 1, log_id = ? WHERE id = ?",
                (log_id, planned_session_id),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM training_logs WHERE id = ?", (log_id,)).fetchone()
        conn.close()
        log = self._row_to_training_log(row)
        athlete.add_log(log)
        return log

    def add_planned_session(self, athlete_id: int, session_date: date,
                            template_id: str, session_name: str, session_type: str,
                            planned_duration: int, planned_intensity: str,
                            exercises: list[dict] = None,
                            coach_notes: str = "",
                            source: str = "coach",
                            is_key_session: bool = False,
                            week_theme: str = "",
                            training_phase: str = "",
                            estimated_low_minutes: int = 0,
                            estimated_medium_minutes: int = 0,
                            estimated_high_minutes: int = 0,
                            intensity_distribution_source: str = "",
                            tempo_source: str = "",
                            tempo_assumptions: str = "",
                            tempo_surface_options: list[dict] = None) -> Optional[PlannedSession]:
        """Lägg till ett planerat pass."""
        athlete = self.get_athlete(athlete_id)
        if not athlete:
            return None

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO planned_sessions (
                athlete_id, date, template_id, session_name, session_type,
                planned_duration, planned_intensity, exercises_json, coach_notes,
                completed, log_id, source, is_key_session, week_theme,
                training_phase, estimated_low_minutes, estimated_medium_minutes,
                estimated_high_minutes, intensity_distribution_source,
                tempo_source, tempo_assumptions, tempo_surface_options_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                athlete_id,
                session_date.isoformat(),
                template_id,
                session_name,
                session_type,
                planned_duration,
                planned_intensity,
                json.dumps(exercises or []),
                coach_notes,
                source,
                1 if is_key_session else 0,
                week_theme,
                training_phase,
                estimated_low_minutes,
                estimated_medium_minutes,
                estimated_high_minutes,
                intensity_distribution_source,
                tempo_source,
                tempo_assumptions,
                json.dumps(tempo_surface_options or []),
            ),
        )
        session_id = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM planned_sessions WHERE id = ?", (session_id,)).fetchone()
        conn.close()
        planned = self._row_to_planned_session(row)
        athlete.planned_sessions.append(planned)
        return planned

    def get_planned_session(self, session_id: int) -> Optional[PlannedSession]:
        """Hämta ett planerat pass via ID."""
        conn = get_connection()
        row = conn.execute("SELECT * FROM planned_sessions WHERE id = ?", (session_id,)).fetchone()
        conn.close()
        return self._row_to_planned_session(row)

    def save_planned_session(self, planned_session: PlannedSession) -> Optional[PlannedSession]:
        """Spara uppdateringar på ett planerat pass."""
        if not planned_session:
            return None
        conn = get_connection()
        conn.execute(
            """
            UPDATE planned_sessions
            SET date = ?, template_id = ?, session_name = ?, session_type = ?,
                planned_duration = ?, planned_intensity = ?, exercises_json = ?,
                coach_notes = ?, completed = ?, log_id = ?, source = ?, is_key_session = ?,
                week_theme = ?, training_phase = ?, estimated_low_minutes = ?,
                estimated_medium_minutes = ?, estimated_high_minutes = ?,
                intensity_distribution_source = ?, tempo_source = ?, tempo_assumptions = ?,
                tempo_surface_options_json = ?
            WHERE id = ?
            """,
            (
                planned_session.date.isoformat(),
                planned_session.template_id,
                planned_session.session_name,
                planned_session.session_type,
                planned_session.planned_duration,
                planned_session.planned_intensity,
                json.dumps(planned_session.exercises or []),
                planned_session.coach_notes,
                1 if planned_session.completed else 0,
                planned_session.log_id,
                planned_session.source,
                1 if planned_session.is_key_session else 0,
                planned_session.week_theme,
                planned_session.training_phase,
                planned_session.estimated_low_minutes,
                planned_session.estimated_medium_minutes,
                planned_session.estimated_high_minutes,
                planned_session.intensity_distribution_source,
                planned_session.tempo_source,
                planned_session.tempo_assumptions,
                json.dumps(planned_session.tempo_surface_options or []),
                planned_session.id,
            ),
        )
        conn.commit()
        conn.close()
        return planned_session

    def delete_planned_session(self, session_id: int) -> bool:
        """Ta bort ett planerat pass."""
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM planned_sessions WHERE id = ?", (session_id,))
        deleted = cur.rowcount > 0
        conn.commit()
        conn.close()
        if deleted:
            for athlete in self.athletes.values():
                athlete.planned_sessions = [ps for ps in athlete.planned_sessions if ps.id != session_id]
        return deleted

    def clear_future_ai_sessions(self, athlete_id: int, from_date: date = None) -> int:
        """
        Ta bort alla kommande AI-genererade pass för en idrottare.
        Används innan ett nytt schema genereras för att undvika dubbletter.

        Args:
            athlete_id: Idrottarens ID
            from_date:  Från och med vilket datum (default: idag)

        Returns:
            Antal borttagna pass
        """
        if from_date is None:
            from_date = date.today()

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM planned_sessions
            WHERE athlete_id = ? AND date >= ? AND source = 'ai'
            """,
            (athlete_id, from_date.isoformat()),
        )
        removed = cur.rowcount
        conn.commit()
        conn.close()
        athlete = self.athletes.get(athlete_id)
        if athlete:
            athlete.planned_sessions = [
                ps for ps in athlete.planned_sessions
                if not (ps.date >= from_date and getattr(ps, 'source', 'coach') == 'ai')
            ]
        return removed

    # ============================================================
    # KOMMENTARER
    # ============================================================

    def add_comment(self, log_id: int, author_id: int, author_name: str,
                    author_role: str, content: str) -> Optional[LogComment]:
        """Lägg till en kommentar på ett loggat pass."""
        comment = LogComment(
            id=self.next_comment_id,
            log_id=log_id,
            author_id=author_id,
            author_name=author_name,
            author_role=author_role,
            content=content
        )
        if log_id not in self.log_comments:
            self.log_comments[log_id] = []
        self.log_comments[log_id].append(comment)
        self.next_comment_id += 1
        return comment

    def get_comments_for_log(self, log_id: int) -> list[LogComment]:
        """Hämta alla kommentarer för ett loggat pass."""
        return self.log_comments.get(log_id, [])

    def get_log_by_id(self, log_id: int) -> Optional[TrainingLog]:
        """Hämta en logg via ID."""
        conn = get_connection()
        row = conn.execute("SELECT * FROM training_logs WHERE id = ?", (log_id,)).fetchone()
        conn.close()
        return self._row_to_training_log(row)

    # ============================================================
    # TESTRESULTAT
    # ============================================================

    def add_test_result(self, athlete_id: int, test_date: date, test_type: str,
                        test_name: str, value: float, unit: str,
                        notes: str = "", recorded_by_id: int = None) -> Optional[TestResult]:
        """Lägg till ett testresultat."""
        athlete = self.get_athlete(athlete_id)
        if not athlete:
            return None

        test = TestResult(
            id=self.next_test_id,
            athlete_id=athlete_id,
            test_date=test_date,
            test_type=test_type,
            test_name=test_name,
            value=value,
            unit=unit,
            notes=notes,
            recorded_by_id=recorded_by_id
        )
        athlete.test_results.append(test)
        self.next_test_id += 1
        return test

    def get_test_result(self, test_id: int) -> Optional[TestResult]:
        """Hämta ett testresultat via ID."""
        for athlete in self.athletes.values():
            for test in athlete.test_results:
                if test.id == test_id:
                    return test
        return None

    def delete_test_result(self, test_id: int) -> bool:
        """Ta bort ett testresultat."""
        for athlete in self.athletes.values():
            for i, test in enumerate(athlete.test_results):
                if test.id == test_id:
                    del athlete.test_results[i]
                    return True
        return False

    # ============================================================
    # SKADOR
    # ============================================================

    def add_injury(self, athlete_id: int, start_date: date, injury_type: str,
                   body_part: str, severity: str, description: str,
                   treatment: str = "", training_modifications: str = "",
                   recorded_by_id: int = None) -> Optional[InjuryRecord]:
        """Lägg till en skaderegistrering."""
        athlete = self.get_athlete(athlete_id)
        if not athlete:
            return None

        injury = InjuryRecord(
            id=self.next_injury_id,
            athlete_id=athlete_id,
            start_date=start_date,
            end_date=None,
            injury_type=injury_type,
            body_part=body_part,
            severity=severity,
            description=description,
            treatment=treatment,
            training_modifications=training_modifications,
            recorded_by_id=recorded_by_id
        )
        athlete.injuries.append(injury)
        self.next_injury_id += 1
        return injury

    def update_injury(self, injury_id: int, end_date: date = None,
                      is_active: bool = None, treatment: str = None,
                      training_modifications: str = None) -> Optional[InjuryRecord]:
        """Uppdatera en skaderegistrering."""
        for athlete in self.athletes.values():
            for injury in athlete.injuries:
                if injury.id == injury_id:
                    if end_date is not None:
                        injury.end_date = end_date
                    if is_active is not None:
                        injury.is_active = is_active
                    if treatment is not None:
                        injury.treatment = treatment
                    if training_modifications is not None:
                        injury.training_modifications = training_modifications
                    return injury
        return None

    def get_injury(self, injury_id: int) -> Optional[InjuryRecord]:
        """Hämta en skaderegistrering via ID."""
        for athlete in self.athletes.values():
            for injury in athlete.injuries:
                if injury.id == injury_id:
                    return injury
        return None

    # ============================================================
    # EGNA PASSMALLAR (TRÄNINGSBANKEN)
    # ============================================================

    def add_custom_template(self, coach_id: int, coach_name: str, name: str,
                            session_type: str, duration: int, intensity: str,
                            description: str, exercises: list[dict] = None,
                            is_public: bool = True) -> CustomSessionTemplate:
        """Lägg till en egen passmall i träningsbanken."""
        template = CustomSessionTemplate(
            id=self.next_custom_template_id,
            coach_id=coach_id,
            coach_name=coach_name,
            name=name,
            session_type=session_type,
            duration=duration,
            intensity=intensity,
            description=description,
            exercises=exercises or [],
            is_public=is_public
        )
        self.custom_templates[template.id] = template
        self.next_custom_template_id += 1
        return template

    def get_custom_template(self, template_id: int) -> Optional[CustomSessionTemplate]:
        """Hämta en passmall via ID."""
        return self.custom_templates.get(template_id)

    def get_custom_templates_for_coach(self, coach_id: int) -> list[CustomSessionTemplate]:
        """Hämta alla passmallar för en coach."""
        return [t for t in self.custom_templates.values() if t.coach_id == coach_id]

    def get_all_custom_templates(self) -> list[CustomSessionTemplate]:
        """Hämta alla publika passmallar."""
        return [t for t in self.custom_templates.values() if t.is_public]

    def delete_custom_template(self, template_id: int) -> bool:
        """Ta bort en passmall."""
        if template_id in self.custom_templates:
            del self.custom_templates[template_id]
            return True
        return False

    def increment_template_use(self, template_id: int):
        """Öka användningsräknaren för en mall."""
        template = self.custom_templates.get(template_id)
        if template:
            template.use_count += 1

    def generate_demo_logs(self, athlete: Athlete):
        """Generera realistisk träningsdata för demo."""
        today = date.today()
        session_types = ["uthållighet", "styrka", "teknik", "snabbhet"]

        # Generera 4 veckors data
        for days_ago in range(28, -1, -1):
            log_date = today - timedelta(days=days_ago)

            # Träna 4-5 dagar per vecka (hoppa över vissa dagar)
            if log_date.weekday() in [0, 2, 3, 5] or (days_ago % 3 == 0):
                # Variera passtyp
                session_type = session_types[days_ago % len(session_types)]

                # Variera duration och RPE
                if session_type == "uthållighet":
                    duration = 45 + (days_ago % 30)
                    rpe = 5 + (days_ago % 3)
                elif session_type == "styrka":
                    duration = 60
                    rpe = 6 + (days_ago % 4)
                elif session_type == "snabbhet":
                    duration = 30 + (days_ago % 15)
                    rpe = 7 + (days_ago % 3)
                else:
                    duration = 40
                    rpe = 4 + (days_ago % 3)

                # Begränsa RPE till 1-10
                rpe = min(10, max(1, rpe))

                comments = [
                    "Bra pass!",
                    "Kände mig trött idag",
                    "Fokus på teknik",
                    "Högt tempo",
                    "Återhämtningspass",
                    ""
                ]
                comment = comments[days_ago % len(comments)]

                self.add_log(
                    athlete.id,
                    log_date,
                    session_type,
                    duration,
                    rpe,
                    comment
                )

    def generate_demo_planned_sessions(self, athlete: Athlete):
        """Generera planerade pass för kommande vecka."""
        from exercise_bank import SESSION_TEMPLATES, get_exercise

        today = date.today()

        # Hitta måndag denna vecka
        monday = today - timedelta(days=today.weekday())

        # Skapa ett veckoprogram
        templates_to_use = [
            ("end01", 0),   # Måndag: Uthållighet
            ("str01", 1),   # Tisdag: Styrka
            ("tec01", 2),   # Onsdag: Teknik
            ("rec01", 3),   # Torsdag: Återhämtning
            ("spd01", 4),   # Fredag: Snabbhet
            ("end02", 5),   # Lördag: Fartlek
        ]

        for template_id, day_offset in templates_to_use:
            session_date = monday + timedelta(days=day_offset)

            # Hoppa över pass som redan är i det förflutna
            if session_date < today - timedelta(days=1):
                continue

            template = SESSION_TEMPLATES.get(template_id)
            if template:
                exercises = []
                for ex_id in template.exercises:
                    ex = get_exercise(ex_id)
                    if ex:
                        exercises.append({
                            "id": ex.id,
                            "name": ex.name,
                            "duration": ex.duration_minutes,
                            "description": ex.description
                        })

                self.add_planned_session(
                    athlete.id,
                    session_date,
                    template_id,
                    template.name,
                    template.category,
                    template.total_duration,
                    template.intensity,
                    exercises
                )


# Global datastore instance
db = DataStore()
