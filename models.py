"""
Datamodeller för träningsplattformen.
Hanterar idrottare, träningspass, program och loggposter.
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Optional
import json


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
            "planned_session_id": self.planned_session_id
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
            "log_id": self.log_id
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
    test_type: str  # "sprint_30m", "sprint_60m", "standing_jump", "strength", etc.
    test_name: str  # Visningsnamn, t.ex. "30m sprint"
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
    "sprint": "Sprint & Snabbhet",
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
    discipline: str  # "sprint", "medel", "distans", "hopp", "kast", "mångkamp"
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
            "total_logs": len(self.logs)
        }


class DataStore:
    """Enkel in-memory datalagring (för prototyp)."""

    def __init__(self):
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

    def create_athlete_for_user(self, user_id: int, name: str, birth_year: int, discipline: str) -> Athlete:
        """Skapa en idrottarprofil kopplad till en användare."""
        athlete = Athlete(
            id=self.next_athlete_id,
            user_id=user_id,
            name=name,
            birth_year=birth_year,
            discipline=discipline
        )
        self.athletes[athlete.id] = athlete
        self.athletes_by_user[user_id] = athlete
        self.next_athlete_id += 1
        return athlete

    def get_athlete(self, athlete_id: int) -> Optional[Athlete]:
        """Hämta en idrottare via ID."""
        return self.athletes.get(athlete_id)

    def get_athlete_by_user(self, user_id: int) -> Optional[Athlete]:
        """Hämta idrottarprofil för en användare."""
        return self.athletes_by_user.get(user_id)

    def get_all_athletes(self) -> list[Athlete]:
        """Hämta alla idrottare."""
        return list(self.athletes.values())

    def get_athletes_for_coach(self, coach_user_id: int, auth_db) -> list[Athlete]:
        """Hämta alla idrottare kopplade till en coach."""
        # Hämta alla users som är kopplade till denna coach
        athlete_users = auth_db.get_athletes_for_coach(coach_user_id)

        # Returnera deras athlete-profiler
        athletes = []
        for user in athlete_users:
            athlete = self.athletes_by_user.get(user.id)
            if athlete:
                athletes.append(athlete)
        return athletes

    def add_log(self, athlete_id: int, log_date: date, session_type: str,
                duration: int, rpe: int, comment: str = "",
                planned_session_id: Optional[int] = None) -> Optional[TrainingLog]:
        """Lägg till en loggpost för en idrottare."""
        athlete = self.get_athlete(athlete_id)
        if not athlete:
            return None

        log = TrainingLog(
            id=self.next_log_id,
            athlete_id=athlete_id,
            date=log_date,
            session_type=session_type,
            duration_minutes=duration,
            rpe=rpe,
            comment=comment,
            planned_session_id=planned_session_id
        )
        athlete.add_log(log)
        self.next_log_id += 1

        # Markera planerat pass som genomfört
        if planned_session_id:
            for ps in athlete.planned_sessions:
                if ps.id == planned_session_id:
                    ps.completed = True
                    ps.log_id = log.id
                    break

        return log

    def add_planned_session(self, athlete_id: int, session_date: date,
                            template_id: str, session_name: str, session_type: str,
                            planned_duration: int, planned_intensity: str,
                            exercises: list[dict] = None,
                            coach_notes: str = "") -> Optional[PlannedSession]:
        """Lägg till ett planerat pass."""
        athlete = self.get_athlete(athlete_id)
        if not athlete:
            return None

        planned = PlannedSession(
            id=self.next_planned_session_id,
            athlete_id=athlete_id,
            date=session_date,
            template_id=template_id,
            session_name=session_name,
            session_type=session_type,
            planned_duration=planned_duration,
            planned_intensity=planned_intensity,
            exercises=exercises or [],
            coach_notes=coach_notes
        )
        athlete.planned_sessions.append(planned)
        self.next_planned_session_id += 1
        return planned

    def get_planned_session(self, session_id: int) -> Optional[PlannedSession]:
        """Hämta ett planerat pass via ID."""
        for athlete in self.athletes.values():
            for ps in athlete.planned_sessions:
                if ps.id == session_id:
                    return ps
        return None

    def delete_planned_session(self, session_id: int) -> bool:
        """Ta bort ett planerat pass."""
        for athlete in self.athletes.values():
            for i, ps in enumerate(athlete.planned_sessions):
                if ps.id == session_id:
                    del athlete.planned_sessions[i]
                    return True
        return False

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
        for athlete in self.athletes.values():
            for log in athlete.logs:
                if log.id == log_id:
                    return log
        return None

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
