"""
Huvudapplikation - Flask webapp för träningsplattformen.
Med autentisering, roller (coach/idrottare), planering och uppföljning.
"""

import os
import calendar
import csv
import io
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from datetime import date, datetime, timedelta
from functools import wraps

from database import init_db
from models import db
from auth import auth_db
from competition_results import (
    get_results_summary,
    find_athlete_results,
    get_personal_bests,
    search_athletes
)
from ai_schedule import generate_week_schedule, generate_schedule_for_weeks, generate_month_schedule
from tempo_model import TEMPO_MODEL_RUNNERS, parse_pace_to_seconds_per_km, calibrate_runner_offset_from_logs

# Skapa Flask app
app = Flask(__name__,
            template_folder='templates',
            static_folder='static')

init_db()

# Secret key för sessions (byt i produktion!)
app.secret_key = 'dev-secret-key-change-in-production'

AI_PROFILE_FIELDS = [
    "running_focus",
    "training_experience_level",
    "weekly_training_amount",
    "primary_goal",
    "injury_constraints",
    "best_5k_time",
    "best_alt_distance",
    "best_alt_time",
    "easy_pace",
    "threshold_pace",
    "training_surface",
    "tempo_model_runner_key",
    "response_notes",
]

BEST_RESULT_DISTANCE_OPTIONS = [
    ("800 m", "800 m"),
    ("1500 m", "1500 m"),
    ("3000 m", "3000 m"),
    ("5 km", "5 km"),
    ("10 km", "10 km"),
    ("halvmaraton", "Halvmaraton"),
    ("maraton", "Maraton"),
    ("annan", "Annan distans"),
]

BEST_RESULT_DISTANCE_VALUES = {value for value, _label in BEST_RESULT_DISTANCE_OPTIONS if value != "annan"}


def _clean_form_value(value: str) -> str:
    return (value or "").strip()


def _parse_birth_year_value(value: str) -> int | None:
    value = _clean_form_value(value)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_ai_profile_from_form(form) -> dict:
    """Normalisera AI-onboardingfält från formulär."""
    profile = {field: _clean_form_value(form.get(field, "")) for field in AI_PROFILE_FIELDS}
    _apply_unified_best_result_fields(profile, form)
    profile["has_external_training_data"] = form.get("has_external_training_data") in {"on", "true", "1", "yes"}
    if not profile["has_external_training_data"]:
        profile["tempo_model_runner_key"] = ""
    return profile


def _apply_unified_best_result_fields(profile: dict, form) -> None:
    """Mappa det samlade bästa-tid-fältet till befintliga interna fält."""
    if "best_result_distance" not in form and "best_result_time" not in form:
        return

    selected_distance = _clean_form_value(form.get("best_result_distance", ""))
    custom_distance = _clean_form_value(form.get("best_result_custom_distance", ""))
    result_time = _clean_form_value(form.get("best_result_time", ""))
    distance = custom_distance if selected_distance == "annan" else selected_distance

    profile["best_5k_time"] = ""
    profile["best_alt_distance"] = ""
    profile["best_alt_time"] = ""

    if not distance and not result_time:
        return

    if distance == "5 km":
        profile["best_5k_time"] = result_time
    else:
        profile["best_alt_distance"] = distance
        profile["best_alt_time"] = result_time


def _parse_actual_pace_from_form(form) -> float | None:
    return parse_pace_to_seconds_per_km(form.get("actual_pace", ""))


def _normalize_csv_key(value: str) -> str:
    return (
        (value or "")
        .strip()
        .lower()
        .replace("å", "a")
        .replace("ä", "a")
        .replace("ö", "o")
        .replace(" ", "_")
        .replace("-", "_")
    )


def _csv_value(row: dict, *candidates: str) -> str:
    normalized = {_normalize_csv_key(key): value for key, value in row.items()}
    for candidate in candidates:
        value = normalized.get(_normalize_csv_key(candidate))
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _parse_csv_date(value: str) -> date | None:
    value = _clean_form_value(value)
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt).date()
        except ValueError:
            continue
    return None


def _parse_duration_minutes(value: str) -> int | None:
    value = _clean_form_value(value).lower()
    if not value:
        return None
    if ":" in value:
        try:
            parts = [float(part) for part in value.split(":")]
        except ValueError:
            return None
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + part
        return max(1, int(round(seconds / 60)))
    try:
        numeric = float(value.replace(",", ".").replace("min", "").strip())
    except ValueError:
        return None
    return max(1, int(round(numeric)))


def _import_training_csv_for_athlete(athlete, uploaded_file) -> dict:
    """Importera enkel tränings-CSV som loggar för personlig tempokalibrering."""
    if not uploaded_file or not uploaded_file.filename:
        return {"imported": 0, "skipped": 0, "error": ""}
    if not uploaded_file.filename.lower().endswith(".csv"):
        return {"imported": 0, "skipped": 0, "error": "Filen måste vara en CSV-fil."}

    try:
        raw_text = uploaded_file.stream.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        uploaded_file.stream.seek(0)
        raw_text = uploaded_file.stream.read().decode("latin-1")

    if not raw_text.strip():
        return {"imported": 0, "skipped": 0, "error": "CSV-filen är tom."}

    sample = raw_text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(raw_text), dialect=dialect)

    imported = 0
    skipped = 0
    for row in reader:
        actual_pace = parse_pace_to_seconds_per_km(_csv_value(
            row,
            "actual_pace",
            "pace",
            "medeltempo",
            "average_pace",
            "avg_pace",
            "tempo",
            "faktiskt_medeltempo",
        ))
        if not actual_pace:
            skipped += 1
            continue

        log_date = _parse_csv_date(_csv_value(row, "date", "datum", "start_time", "starttid", "start"))
        duration = _parse_duration_minutes(_csv_value(row, "duration_minutes", "duration", "tid", "time", "elapsed_time"))
        rpe_raw = _csv_value(row, "rpe", "anstrangning", "kansla")
        try:
            rpe = int(float(rpe_raw.replace(",", "."))) if rpe_raw else 5
        except ValueError:
            rpe = 5
        rpe = min(10, max(1, rpe))

        session_type = _csv_value(row, "session_type", "type", "passtyp", "activity_type", "aktivitet") or "uthållighet"
        comment = _csv_value(row, "comment", "kommentar", "name", "namn", "title")

        db.add_log(
            athlete.id,
            log_date or date.today(),
            session_type,
            duration or 45,
            rpe,
            comment=f"CSV-import: {comment}".strip(),
            actual_pace_seconds_per_km=actual_pace,
        )
        imported += 1

    athlete.has_external_training_data = True
    db.save_athlete(athlete)
    refreshed_athlete = db.get_athlete(athlete.id)
    calibration = _refresh_athlete_tempo_calibration(refreshed_athlete)
    return {
        "imported": imported,
        "skipped": skipped,
        "error": "",
        "calibration": calibration,
    }


def _format_pace_seconds_per_km(value: float | None) -> str:
    if value is None:
        return ""
    total_seconds = int(round(float(value)))
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d} min/km"


def _refresh_athlete_tempo_calibration(athlete) -> dict:
    calibration = calibrate_runner_offset_from_logs(athlete)
    athlete.tempo_model_personal_offset_seconds = calibration["offset_seconds"] if calibration["is_calibrated"] else 0.0
    athlete.tempo_model_offset_samples = calibration["sample_count"]
    db.save_athlete(athlete)
    return calibration


def _apply_ai_profile_to_athlete(athlete, form) -> dict:
    """Spara AI-profilfält på athlete och returnera normaliserat dict."""
    previous_runner_key = getattr(athlete, "tempo_model_runner_key", "")
    profile = _parse_ai_profile_from_form(form)
    for field, value in profile.items():
        setattr(athlete, field, value)
    if profile.get("tempo_model_runner_key", "") != previous_runner_key:
        athlete.tempo_model_personal_offset_seconds = 0.0
        athlete.tempo_model_offset_samples = 0
    return profile


@app.context_processor
def inject_shared_template_context():
    return {
        "tempo_model_runners": TEMPO_MODEL_RUNNERS,
        "format_pace_seconds_per_km": _format_pace_seconds_per_km,
        "best_result_distance_options": BEST_RESULT_DISTANCE_OPTIONS,
        "best_result_distance_values": BEST_RESULT_DISTANCE_VALUES,
    }


def _can_manage_athlete(user, athlete) -> bool:
    if not user or not athlete:
        return False
    if user.is_athlete():
        return athlete.user_id == user.id
    athlete_user = auth_db.get_user(athlete.user_id)
    return bool(athlete_user and athlete_user.connected_coach_id == user.id)


def _week_start_for(target_date: date) -> date:
    return target_date - timedelta(days=target_date.weekday())


def _parse_coach_notes_metadata(coach_notes: str) -> dict:
    metadata = {}
    for raw_line in (coach_notes or "").splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def _session_description(session) -> str:
    for exercise in session.exercises or []:
        description = (exercise.get("description") or exercise.get("details") or "").strip()
        if description:
            return description
    return ""


def _session_status(session, today: date) -> str:
    if session.completed:
        return "completed"
    if session.date < today:
        return "missed"
    if session.date == today:
        return "today"
    return "upcoming"


def _is_recovery_week(week_theme: str, training_phase: str) -> bool:
    theme = (week_theme or "").lower()
    phase = (training_phase or "").lower()
    return "aterhamt" in theme or "återhämt" in theme or "aterhamt" in phase or "återhämt" in phase


def _is_competition_week(week_theme: str, training_phase: str) -> bool:
    theme = (week_theme or "").lower()
    phase = (training_phase or "").lower()
    return "tavl" in theme or "tävl" in theme or "tavl" in phase or "tävl" in phase


def _build_session_view(session, today: date) -> dict:
    note_meta = _parse_coach_notes_metadata(session.coach_notes)
    description = _session_description(session)
    status = _session_status(session, today)
    preview = ""
    for line in description.splitlines():
        stripped = line.strip()
        if stripped and ":" not in stripped:
            preview = stripped
            break

    tempo_source = getattr(session, "tempo_source", "") or note_meta.get("Tempo", "")
    tempo_source_label = {
        "garmin_model_offset": "Garmin-modell med personlig profil",
        "garmin_model_offset_calibrated": "Garmin-modell med profil + personlig kalibrering",
        "garmin_model_calibrated": "Garmin-modell med personlig kalibrering",
        "garmin_model_population": "Garmin-modell",
        "race_based_heuristic": "Profil-/tävlingsbaserad uppskattning",
        "ai_description_pace": "Tempo från passdetaljen",
    }.get(tempo_source, tempo_source)

    return {
        "id": session.id,
        "date": session.date,
        "session_name": session.session_name,
        "session_type": session.session_type,
        "planned_duration": session.planned_duration,
        "planned_intensity": session.planned_intensity,
        "completed": session.completed,
        "log_id": session.log_id,
        "source": session.source,
        "is_key_session": bool(getattr(session, "is_key_session", False)),
        "week_theme": getattr(session, "week_theme", "") or note_meta.get("Veckofokus", ""),
        "training_phase": getattr(session, "training_phase", "") or "",
        "description": description,
        "description_lines": [line.strip() for line in description.splitlines() if line.strip()],
        "description_preview": preview,
        "coach_notes": session.coach_notes or "",
        "plan_status": note_meta.get("Planstatus", "AI-genererad" if session.source == "ai" else "Coachplanerad"),
        "key_session_note": note_meta.get("Nyckelpass", ""),
        "sources": note_meta.get("Källor", ""),
        "coach_explanation": note_meta.get("Coachförklaring", ""),
        "week_focus_note": note_meta.get("Veckofokus", ""),
        "estimated_low_minutes": getattr(session, "estimated_low_minutes", 0),
        "estimated_medium_minutes": getattr(session, "estimated_medium_minutes", 0),
        "estimated_high_minutes": getattr(session, "estimated_high_minutes", 0),
        "intensity_distribution_source": getattr(session, "intensity_distribution_source", ""),
        "tempo_source": tempo_source,
        "tempo_source_label": tempo_source_label,
        "tempo_assumptions": getattr(session, "tempo_assumptions", ""),
        "tempo_surface_options": getattr(session, "tempo_surface_options", []) or [],
        "status": status,
        "status_label": {
            "completed": "Genomfort",
            "missed": "Missat",
            "today": "Idag",
            "upcoming": "Kommande",
        }[status],
    }


def _first_of_month(target_date: date) -> date:
    return target_date.replace(day=1)


def _next_month(target_date: date) -> date:
    year = target_date.year + (1 if target_date.month == 12 else 0)
    month = 1 if target_date.month == 12 else target_date.month + 1
    return date(year, month, 1)


def _month_label(target_month: date) -> str:
    month_names = [
        "januari", "februari", "mars", "april", "maj", "juni",
        "juli", "augusti", "september", "oktober", "november", "december"
    ]
    return f"{month_names[target_month.month - 1]} {target_month.year}"


def _build_month_grid_from_sessions(target_month: date, sessions: list, today: date) -> list[list[dict]]:
    month_start = _first_of_month(target_month)
    month_end = date(target_month.year, target_month.month, calendar.monthrange(target_month.year, target_month.month)[1])
    grid_start = _week_start_for(month_start)
    grid_end = month_end + timedelta(days=6 - month_end.weekday())

    sessions_by_date = {}
    for session in sessions:
        session_view = _build_session_view(session, today)
        sessions_by_date.setdefault(session.date, []).append(session_view)

    rows = []
    cursor = grid_start
    while cursor <= grid_end:
        week_row = []
        for _ in range(7):
            day_sessions = sorted(sessions_by_date.get(cursor, []), key=lambda item: item["id"])
            week_row.append({
                "date": cursor,
                "in_month": cursor.month == target_month.month,
                "is_today": cursor == today,
                "sessions": day_sessions,
            })
            cursor += timedelta(days=1)
        rows.append(week_row)
    return rows


def _build_calendar_context_for_sessions(sessions: list, today: date, month_param: str = "") -> dict:
    filtered_sessions = sorted(sessions, key=lambda session: (session.date, session.id))
    if filtered_sessions:
        first_month = _first_of_month(filtered_sessions[0].date)
        last_month = _first_of_month(filtered_sessions[-1].date)
    else:
        first_month = _first_of_month(today)
        last_month = first_month

    available_months = []
    cursor = first_month
    while cursor <= last_month:
        available_months.append(cursor)
        cursor = _next_month(cursor)

    selected_month = None
    if month_param:
        try:
            selected_month = datetime.strptime(month_param, '%Y-%m').date().replace(day=1)
        except ValueError:
            selected_month = None
    if selected_month not in available_months:
        selected_month = _first_of_month(today)
        if selected_month not in available_months:
            selected_month = available_months[0]

    selected_index = available_months.index(selected_month)
    prev_month = available_months[selected_index - 1] if selected_index > 0 else None
    next_month = available_months[selected_index + 1] if selected_index < len(available_months) - 1 else None
    month_grid = _build_month_grid_from_sessions(selected_month, filtered_sessions, today)
    session_views = [_build_session_view(session, today) for session in filtered_sessions]

    return {
        "available_months": available_months,
        "selected_month": selected_month,
        "prev_month": prev_month,
        "next_month": next_month,
        "month_label": _month_label(selected_month),
        "month_grid": month_grid,
        "session_views": session_views,
    }


def init_demo_data():
    """Initiera demo-data och koppla till users."""
    # Demo-data för idrottare:
    # - Ebba 3 och Daniel visar Garmin-baserad tempomodell
    athletes_info = [
        (
            "ebba@demo.se",
            "Ebba 3",
            2003,
            "distans",
            "",
            "ai",
            {
                "running_focus": "distans",
                "training_experience_level": "mer än 3 år",
                "weekly_training_amount": "5 pass eller 45 km",
                "training_surface": "plan_vag",
                "tempo_model_runner_key": "Ebba 3",
                "has_external_training_data": True,
            },
        ),
        (
            "daniel@demo.se",
            "Daniel",
            2001,
            "medel",
            "",
            "ai",
            {
                "running_focus": "medel",
                "training_experience_level": "mer än 3 år",
                "weekly_training_amount": "5 pass eller 50 km",
                "training_surface": "plan_vag",
                "tempo_model_runner_key": "Daniel",
                "has_external_training_data": True,
            },
        ),
    ]

    for user_email, name, birth_year, discipline, club, training_mode, ai_profile in athletes_info:
        user = auth_db.get_user_by_email(user_email)
        if not user:
            continue
        athlete = db.create_athlete_for_user(
            user.id, name, birth_year, discipline, club,
            training_mode=training_mode,
            **ai_profile,
        )
        athlete = db.get_athlete(athlete.id)
        if training_mode == 'ai':
            # Rensa eventuella gamla AI-pass (skyddar mot dubbletter vid omstart)
            db.clear_future_ai_sessions(athlete.id)
            # Använd bara lokal fallbacklogik vid uppstart så att servern
            # inte blir beroende av extern AI/API redan vid boot.
            try:
                generate_month_schedule(athlete, db, use_rag=False)
                print(f"  ✓ Demo-schema genererat för {name}")
            except Exception as e:
                print(f"  ⚠ Kunde inte generera demoschema för {name}: {e}")


# Initiera demo-data
init_demo_data()


# ============================================================
# AUTH DECORATORS
# ============================================================

def login_required(f):
    """Decorator: Kräver inloggning."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if auth_db.get_user(session['user_id']) is None:
            session.clear()
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def coach_required(f):
    """Decorator: Kräver coach-roll."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = auth_db.get_user(session['user_id'])
        if not user or not user.is_coach():
            flash('Du måste vara coach för att se denna sida.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def get_current_user():
    """Hämta inloggad användare."""
    if 'user_id' in session:
        return auth_db.get_user(session['user_id'])
    return None


# ============================================================
# AUTH ROUTES
# ============================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Inloggningssida."""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    error = None
    if request.method == 'POST':
        email = request.form.get('email', '')
        password = request.form.get('password', '')

        user = auth_db.login(email, password)
        if user:
            session['user_id'] = user.id
            session['user_name'] = user.name
            session['user_role'] = user.role
            return redirect(url_for('dashboard'))
        else:
            error = 'Fel e-post eller lösenord'

    return render_template('login.html', error=error)


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Registreringssida."""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    error = None
    if request.method == 'POST':
        name = request.form.get('name', '')
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        role = request.form.get('role', 'athlete')

        # Validera
        if len(password) < 6:
            error = 'Lösenordet måste vara minst 6 tecken'
        elif not name or not email:
            error = 'Fyll i alla obligatoriska fält'
        else:
            # Försök registrera
            user = auth_db.register(email, password, name, role)
            if not user and role == 'athlete':
                existing_user = auth_db.get_user_by_email(email)
                existing_athlete = db.get_athlete_by_user(existing_user.id) if existing_user else None
                if existing_user and existing_user.is_athlete() and not existing_athlete:
                    auth_db.delete_user(existing_user.id)
                    user = auth_db.register(email, password, name, role)

            if not user:
                error = 'E-postadressen är redan registrerad'
            else:
                try:
                    # Om idrottare, skapa athlete-profil
                    if role == 'athlete':
                        birth_year = _parse_birth_year_value(request.form.get('birth_year', '')) or 2000
                        discipline = request.form.get('discipline', 'medel')
                        club = request.form.get('club', '').strip()
                        training_mode = request.form.get('training_mode', 'coach')
                        training_days_str = request.form.get('training_days', '').strip()
                        training_days = int(training_days_str) if training_days_str else 4
                        training_phase = request.form.get('training_phase', 'grundträning')
                        ai_profile = _parse_ai_profile_from_form(request.form)

                        if training_mode == 'ai' and not ai_profile.get('training_experience_level'):
                            auth_db.delete_user(user.id)
                            error = 'Välj din träningsvana för att få AI-genererad planering.'
                            return render_template('register.html', error=error)

                        athlete = db.create_athlete_for_user(
                            user.id, name, birth_year, discipline, club,
                            training_mode=training_mode,
                            training_days_per_week=training_days,
                            training_phase=training_phase,
                            **ai_profile
                        )
                        csv_import = _import_training_csv_for_athlete(athlete, request.files.get("training_data_csv"))
                        if csv_import.get("error"):
                            flash(csv_import["error"], "warning")
                        elif csv_import.get("imported"):
                            flash(f'{csv_import["imported"]} pass importerades från CSV och används för tempokalibrering.', 'success')

                        # Om AI-schema valdes, generera en månadsplan direkt
                        if training_mode == 'ai':
                            athlete = db.get_athlete(athlete.id)
                            sessions = generate_month_schedule(athlete, db, use_rag=True)
                            flash(f'🤖 Ditt AI-schema är klart! {len(sessions)} pass planerade för 4 veckor.', 'success')
                            if club:
                                flash('Tävlingsresultat matchas automatiskt mot namn, ålder och klubb om sådana finns.', 'info')
                            else:
                                flash('Du kan lämna frivilliga AI-frågor tomma, men fler svar ger bättre individanpassning och tempouppskattning.', 'info')

                        # Koppla till coach om kod angavs
                        coach_code = request.form.get('coach_code', '').strip()
                        if coach_code:
                            if not auth_db.connect_athlete_to_coach(user.id, coach_code):
                                flash('Coach-koden hittades inte, men ditt konto skapades.', 'warning')
                except Exception as exc:
                    auth_db.delete_user(user.id)
                    error = f'Kunde inte skapa profilen: {exc}'
                    return render_template('register.html', error=error)

                # Logga in direkt
                session['user_id'] = user.id
                session['user_name'] = user.name
                session['user_role'] = user.role
                return redirect(url_for('dashboard'))

    return render_template('register.html', error=error)


@app.route('/logout')
def logout():
    """Logga ut."""
    session.clear()
    return redirect(url_for('login'))


# ============================================================
# DASHBOARD ROUTES
# ============================================================

@app.route('/')
def index():
    """Startsida - omdirigera till dashboard eller login."""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    """Huvuddashboard - olika vy för coach vs idrottare."""
    user = get_current_user()
    if user is None:
        session.clear()
        return redirect(url_for('login'))

    if user.is_coach():
        # Coach ser alla sina idrottare med prioritering
        athletes = db.get_athletes_for_coach(user.id, auth_db)

        athletes_data = []

        for athlete in athletes:
            days_since_log = athlete.get_days_since_last_log()
            upcoming = athlete.get_upcoming_sessions(7)

            data = {
                "athlete": athlete,
                "logs_7d": len(athlete.get_logs_last_n_days(7)),
                "days_since_log": days_since_log,
                "upcoming_sessions": len(upcoming),
                "todays_session": athlete.get_todays_session(),
            }

            athletes_data.append(data)

        return render_template('coach_dashboard.html',
                               user=user,
                               athletes=athletes_data,
                               today=date.today())
    else:
        # Idrottare ser sin egen data
        athlete = db.get_athlete_by_user(user.id)
        if not athlete:
            flash('Din idrottsprofil hittades inte.', 'error')
            return redirect(url_for('logout'))

        recent_logs = sorted(
            athlete.get_logs_last_n_days(14),
            key=lambda x: x.date,
            reverse=True
        )

        # Hämta coach-info
        coach = auth_db.get_coach_for_athlete(user.id)

        # Hämta dagens planerade pass
        todays_session = athlete.get_todays_session()

        # Förhandsvisa närmaste del av schemat, men skicka med hela planen för expandera-vy
        upcoming_sessions = athlete.get_upcoming_sessions(14)
        future_planned_dates = [
            ps.date for ps in athlete.planned_sessions
            if ps.date >= date.today() and not ps.completed
        ]
        horizon_days = 35
        if future_planned_dates:
            horizon_days = max(horizon_days, (max(future_planned_dates) - date.today()).days + 1)
        all_upcoming_sessions = athlete.get_upcoming_sessions(horizon_days)
        calendar_sessions = athlete.get_calendar_sessions(days_past=60, days_future=max(90, horizon_days))
        calendar_context = _build_calendar_context_for_sessions(
            calendar_sessions,
            today=date.today(),
            month_param=request.args.get('month', '')
        )

        # Räkna ut om schemat snart tar slut (för AI-idrottare)
        schedule_expiring_soon = False
        days_until_schedule_end = None
        last_planned_date = None

        if getattr(athlete, 'training_mode', 'coach') == 'ai':
            if all_upcoming_sessions:
                last_planned_date = max(s.date for s in all_upcoming_sessions)
                days_left = (last_planned_date - date.today()).days
                days_until_schedule_end = days_left
                schedule_expiring_soon = days_left <= 7  # Varna om 7 dagar kvar

        return render_template('athlete_dashboard.html',
                               user=user,
                               athlete=athlete,
                               recent_logs=recent_logs,
                               coach=coach,
                               todays_session=todays_session,
                               upcoming_sessions=upcoming_sessions,
                               all_upcoming_sessions=all_upcoming_sessions,
                               has_more_upcoming=len(all_upcoming_sessions) > len(upcoming_sessions),
                               selected_month=calendar_context["selected_month"],
                               prev_month=calendar_context["prev_month"],
                               next_month=calendar_context["next_month"],
                               month_label=calendar_context["month_label"],
                               month_grid=calendar_context["month_grid"],
                               calendar_session_views=calendar_context["session_views"],
                               today=date.today(),
                               schedule_expiring_soon=schedule_expiring_soon,
                               days_until_schedule_end=days_until_schedule_end,
                               last_planned_date=last_planned_date)


# ============================================================
# ATHLETE ROUTES (för coach att se detaljer)
# ============================================================

@app.route('/athlete/<int:athlete_id>')
@login_required
def athlete_detail(athlete_id: int):
    """Detaljvy för en idrottare."""
    user = get_current_user()
    athlete = db.get_athlete(athlete_id)

    if not athlete:
        flash('Idrottaren hittades inte.', 'error')
        return redirect(url_for('dashboard'))

    # Kontrollera behörighet
    if user.is_athlete():
        # Idrottare kan bara se sig själv
        if athlete.user_id != user.id:
            flash('Du har inte behörighet att se denna idrottare.', 'error')
            return redirect(url_for('dashboard'))
    else:
        # Coach kan bara se sina egna idrottare
        athlete_user = auth_db.get_user(athlete.user_id)
        if not athlete_user or athlete_user.connected_coach_id != user.id:
            flash('Denna idrottare är inte kopplad till dig.', 'error')
            return redirect(url_for('dashboard'))

    recent_logs = sorted(
        athlete.get_logs_last_n_days(14),
        key=lambda x: x.date,
        reverse=True
    )

    # Hämta kommande och dagens pass
    upcoming_sessions = athlete.get_upcoming_sessions(14)
    future_planned_dates = [
        ps.date for ps in athlete.planned_sessions
        if ps.date >= date.today() and not ps.completed
    ]
    horizon_days = 35
    if future_planned_dates:
        horizon_days = max(horizon_days, (max(future_planned_dates) - date.today()).days + 1)
    all_upcoming_sessions = athlete.get_upcoming_sessions(horizon_days)
    todays_session = athlete.get_todays_session()
    calendar_sessions = athlete.get_calendar_sessions(days_past=60, days_future=max(90, horizon_days))
    calendar_context = _build_calendar_context_for_sessions(
        calendar_sessions,
        today=date.today(),
        month_param=request.args.get('month', '')
    )

    schedule_expiring_soon = False
    days_until_schedule_end = None
    last_planned_date = None

    if getattr(athlete, 'training_mode', 'coach') == 'ai':
        if all_upcoming_sessions:
            last_planned_date = max(s.date for s in all_upcoming_sessions)
            days_left = (last_planned_date - date.today()).days
            days_until_schedule_end = days_left
            schedule_expiring_soon = days_left <= 7

    return render_template(
        'athlete.html',
        user=user,
        athlete=athlete,
        recent_logs=recent_logs,
        upcoming_sessions=upcoming_sessions,
        all_upcoming_sessions=all_upcoming_sessions,
        has_more_upcoming=len(all_upcoming_sessions) > len(upcoming_sessions),
        selected_month=calendar_context["selected_month"],
        prev_month=calendar_context["prev_month"],
        next_month=calendar_context["next_month"],
        month_label=calendar_context["month_label"],
        month_grid=calendar_context["month_grid"],
        calendar_session_views=calendar_context["session_views"],
        todays_session=todays_session,
        today=date.today(),
        schedule_expiring_soon=schedule_expiring_soon,
        days_until_schedule_end=days_until_schedule_end,
        last_planned_date=last_planned_date,
    )


@app.route('/athlete/<int:athlete_id>/update-ai-profile', methods=['POST'])
@login_required
def update_ai_profile(athlete_id: int):
    """Uppdatera AI-profilen för en idrottare."""
    user = get_current_user()
    athlete = db.get_athlete(athlete_id)

    if not athlete:
        flash('Idrottaren hittades inte.', 'error')
        return redirect(url_for('dashboard'))

    if not _can_manage_athlete(user, athlete):
        flash('Du har inte behörighet att uppdatera AI-profilen.', 'error')
        return redirect(url_for('dashboard'))

    if getattr(athlete, 'training_mode', 'coach') != 'ai':
        flash('AI-profil kan bara uppdateras för AI-idrottare.', 'error')
        return redirect(url_for('athlete_detail', athlete_id=athlete.id))

    profile = _apply_ai_profile_to_athlete(athlete, request.form)
    birth_year = _parse_birth_year_value(request.form.get('birth_year', ''))
    if birth_year:
        athlete.birth_year = birth_year
    elif _clean_form_value(request.form.get('birth_year', '')):
        flash('Födelseår måste vara ett giltigt årtal.', 'error')
        target = request.form.get('return_to', 'dashboard')
        if target == 'athlete_detail':
            return redirect(url_for('athlete_detail', athlete_id=athlete.id))
        return redirect(url_for('dashboard'))
    club = _clean_form_value(request.form.get('club', athlete.club))
    athlete.club = club
    db.save_athlete(athlete)
    csv_import = _import_training_csv_for_athlete(athlete, request.files.get("training_data_csv"))
    if csv_import.get("error"):
        flash(csv_import["error"], "warning")
    elif csv_import.get("imported"):
        calibration = csv_import.get("calibration", {})
        if calibration.get("is_calibrated"):
            flash(f'{csv_import["imported"]} pass importerades från CSV och personlig tempooffset uppdaterades.', 'success')
        else:
            flash(f'{csv_import["imported"]} pass importerades från CSV. Minst 3 pass med medeltempo krävs för personlig tempooffset.', 'info')

    if not profile.get('training_experience_level'):
        flash('Träningsvana är obligatorisk för AI-planering.', 'error')
    else:
        flash('AI-profilen uppdaterades. Nästa schema använder de nya uppgifterna.', 'success')
        if athlete.club:
            flash('Tävlingsresultat matchas automatiskt mot namn, ålder och klubb om sådana finns.', 'info')
        else:
            flash('Ingen klubb angiven, så automatisk tävlingsmatchning körs inte.', 'info')

    target = request.form.get('return_to', 'dashboard')
    if target == 'athlete_detail':
        return redirect(url_for('athlete_detail', athlete_id=athlete.id))
    return redirect(url_for('dashboard'))


@app.route('/athlete/<int:athlete_id>/log', methods=['GET', 'POST'])
@login_required
def add_log(athlete_id: int):
    """Lägg till ny loggpost - förifylld om planerat pass finns."""
    user = get_current_user()
    athlete = db.get_athlete(athlete_id)

    if not athlete:
        return redirect(url_for('dashboard'))

    # Bara idrottaren själv kan logga
    if athlete.user_id != user.id:
        flash('Du kan bara logga dina egna pass.', 'error')
        return redirect(url_for('dashboard'))

    # Kolla om det finns ett planerat pass att logga mot
    planned_session_id = request.args.get('planned', type=int)
    planned_session = None
    if planned_session_id:
        planned_session = db.get_planned_session(planned_session_id)

    # Eller hämta dagens planerade pass
    if not planned_session:
        planned_session = athlete.get_todays_session()

    if request.method == 'POST':
        log_date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        session_type = request.form['session_type']
        duration = int(request.form['duration'])
        rpe = int(request.form['rpe'])
        comment = request.form.get('comment', '')
        planned_id = request.form.get('planned_session_id', type=int)
        actual_pace_seconds_per_km = _parse_actual_pace_from_form(request.form)

        # Om loggen inte hör till ett planerat pass, skapa en kalenderpost
        # så passet syns i kalendern både för idrottare och coach
        if not planned_id:
            new_planned = db.add_planned_session(
                athlete_id,
                log_date,
                "logged",
                f"Loggat pass ({session_type})",
                session_type,
                duration,
                "medel",
                [],
                "",
                source="athlete",
            )
            if new_planned:
                planned_id = new_planned.id

        db.add_log(
            athlete_id,
            log_date,
            session_type,
            duration,
            rpe,
            comment,
            planned_id,
            actual_pace_seconds_per_km=actual_pace_seconds_per_km,
        )
        calibration = _refresh_athlete_tempo_calibration(athlete)
        if actual_pace_seconds_per_km and calibration["is_calibrated"]:
            flash(
                f"Personlig tempooffset uppdaterad från {calibration['sample_count']} loggade pass.",
                'success',
            )
        flash('Träningspasset har loggats!', 'success')
        return redirect(url_for('dashboard'))

    return render_template('add_log.html',
                           user=user,
                           athlete=athlete,
                           today=date.today(),
                           planned_session=planned_session)


@app.route('/athlete/<int:athlete_id>/quick-log', methods=['POST'])
@login_required
def quick_log(athlete_id: int):
    """Snabb loggning av planerat pass - minimal input."""
    user = get_current_user()
    athlete = db.get_athlete(athlete_id)

    if not athlete or athlete.user_id != user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    planned_id = request.form.get('planned_session_id', type=int)
    rpe = request.form.get('rpe', type=int, default=5)
    comment = request.form.get('comment', '')
    actual_pace_seconds_per_km = _parse_actual_pace_from_form(request.form)

    planned_session = db.get_planned_session(planned_id)
    if not planned_session:
        return jsonify({'error': 'Session not found'}), 404

    # Skapa logg från planerat pass
    db.add_log(
        athlete_id,
        planned_session.date,
        planned_session.session_type,
        planned_session.planned_duration,
        rpe,
        comment,
        planned_id,
        actual_pace_seconds_per_km=actual_pace_seconds_per_km,
    )

    calibration = _refresh_athlete_tempo_calibration(athlete)
    if actual_pace_seconds_per_km and calibration["is_calibrated"]:
        flash(
            f"Personlig tempooffset uppdaterad från {calibration['sample_count']} loggade pass.",
            'success',
        )
    flash('Pass loggat!', 'success')
    redirect_url = request.form.get('redirect_url', '').strip()
    return redirect(redirect_url or url_for('dashboard'))


# ============================================================
# PLANNING ROUTES (Coach planerar pass för idrottare)
# ============================================================

@app.route('/athlete/<int:athlete_id>/plan', methods=['GET', 'POST'])
@login_required
def plan_session(athlete_id: int):
    """Coach planerar pass för en idrottare."""
    user = get_current_user()
    athlete = db.get_athlete(athlete_id)

    if not athlete:
        flash('Idrottaren hittades inte.', 'error')
        return redirect(url_for('dashboard'))

    # Kontrollera behörighet (coach eller idrottaren själv)
    if user.is_athlete() and athlete.user_id != user.id:
        flash('Du har inte behörighet.', 'error')
        return redirect(url_for('dashboard'))

    if user.is_coach():
        athlete_user = auth_db.get_user(athlete.user_id)
        if not athlete_user or athlete_user.connected_coach_id != user.id:
            flash('Denna idrottare är inte kopplad till dig.', 'error')
            return redirect(url_for('dashboard'))

    if request.method == 'POST':
        session_date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        coach_notes = request.form.get('coach_notes', '')

        # Eget pass - coachen skriver in allt själv
        session_name = request.form.get('session_name', 'Eget pass')
        session_type = request.form.get('session_type', 'kombinerat')
        duration = int(request.form.get('duration', 60))
        intensity = request.form.get('intensity', 'medel')
        description = request.form.get('description', '')

        # Samla övningar från formuläret
        exercises = []
        i = 0
        while f'exercises[{i}][name]' in request.form:
            ex_name = request.form.get(f'exercises[{i}][name]', '').strip()
            ex_details = request.form.get(f'exercises[{i}][details]', '').strip()
            if ex_name:
                exercises.append({
                    "id": f"custom_{i}",
                    "name": ex_name,
                    "details": ex_details,
                    "description": ex_details
                })
            i += 1

        if description and not exercises:
            exercises.append({
                "id": "description",
                "name": "Passbeskrivning",
                "description": description
            })

        db.add_planned_session(
            athlete_id,
            session_date,
            "custom",
            session_name,
            session_type,
            duration,
            intensity,
            exercises,
            coach_notes,
            source="coach",
            training_phase=getattr(athlete, 'training_phase', '')
        )
        flash(f'Eget pass planerat för {session_date.strftime("%d/%m")}!', 'success')
        return redirect(url_for('athlete_detail', athlete_id=athlete_id))

    today = date.today()

    return render_template('plan_session.html',
                           user=user,
                           athlete=athlete,
                           today=today)


@app.route('/planned-session/<int:session_id>/update', methods=['POST'])
@coach_required
def update_planned_session(session_id: int):
    """Uppdatera ett planerat pass från veckovyn."""
    user = get_current_user()
    planned_session = db.get_planned_session(session_id)

    if not planned_session:
        flash('Passet hittades inte.', 'error')
        return redirect(url_for('dashboard'))

    athlete = db.get_athlete(planned_session.athlete_id)
    if not athlete or not _can_manage_athlete(user, athlete):
        flash('Du har inte behörighet att uppdatera detta pass.', 'error')
        return redirect(url_for('dashboard'))

    try:
        from ai_schedule import estimate_intensity_distribution

        planned_session.date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        planned_session.session_name = _clean_form_value(request.form.get('session_name', planned_session.session_name)) or planned_session.session_name
        planned_session.session_type = _clean_form_value(request.form.get('session_type', planned_session.session_type)) or planned_session.session_type
        planned_session.planned_duration = int(request.form.get('planned_duration', planned_session.planned_duration))
        planned_session.planned_intensity = _clean_form_value(request.form.get('planned_intensity', planned_session.planned_intensity)) or planned_session.planned_intensity
        planned_session.coach_notes = request.form.get('coach_notes', planned_session.coach_notes)
        planned_session.is_key_session = request.form.get('is_key_session') == '1'
        planned_session.week_theme = _clean_form_value(request.form.get('week_theme', planned_session.week_theme))
        planned_session.training_phase = _clean_form_value(request.form.get('training_phase', planned_session.training_phase)) or getattr(athlete, 'training_phase', '')

        description = request.form.get('description', '').strip()
        if description:
            updated = False
            for exercise in planned_session.exercises:
                if exercise.get("description") or exercise.get("name") == "Passbeskrivning":
                    exercise["description"] = description
                    exercise.setdefault("name", "Passbeskrivning")
                    updated = True
                    break
            if not updated:
                planned_session.exercises.insert(0, {
                    "id": "coach_edit_description",
                    "name": "Passbeskrivning",
                    "description": description
                })

        description_text = _session_description(planned_session)
        distribution = estimate_intensity_distribution(
            session_name=planned_session.session_name,
            session_type=planned_session.session_type,
            planned_duration=planned_session.planned_duration,
            planned_intensity=planned_session.planned_intensity,
            description=description_text,
        )
        planned_session.estimated_low_minutes = distribution["low"]
        planned_session.estimated_medium_minutes = distribution["medium"]
        planned_session.estimated_high_minutes = distribution["high"]
        planned_session.intensity_distribution_source = distribution["source"]
        planned_session.tempo_source = ""
        planned_session.tempo_assumptions = ""
        planned_session.tempo_surface_options = []
        db.save_planned_session(planned_session)
        flash('Passet uppdaterades.', 'success')
    except ValueError:
        flash('Kontrollera datum och duration innan du sparar.', 'error')

    redirect_url = request.form.get('redirect_url', '').strip()
    return redirect(redirect_url or url_for('athlete_detail', athlete_id=athlete.id))


@app.route('/planned-session/<int:session_id>/delete', methods=['POST'])
@coach_required
def delete_planned_session(session_id: int):
    """Ta bort ett planerat pass."""
    user = get_current_user()
    session = db.get_planned_session(session_id)

    if session:
        athlete = db.get_athlete(session.athlete_id)
        if not athlete or not _can_manage_athlete(user, athlete):
            flash('Du har inte behörighet att ta bort detta pass.', 'error')
            return redirect(url_for('dashboard'))
        db.delete_planned_session(session_id)
        flash('Passet har tagits bort.', 'success')
    else:
        flash('Passet hittades inte.', 'error')

    # Redirect tillbaka till där användaren kom från
    redirect_url = request.form.get('redirect_url', url_for('dashboard'))
    return redirect(redirect_url)


# ============================================================
# KOMMENTARER PÅ LOGGADE PASS
# ============================================================

@app.route('/log/<int:log_id>')
@login_required
def view_log(log_id: int):
    """Visa ett loggat pass med kommentarer."""
    user = get_current_user()
    log = db.get_log_by_id(log_id)

    if not log:
        flash('Loggen hittades inte.', 'error')
        return redirect(url_for('dashboard'))

    athlete = db.get_athlete(log.athlete_id)
    comments = db.get_comments_for_log(log_id)

    # Kontrollera behörighet
    can_view = False
    if user.is_athlete() and athlete.user_id == user.id:
        can_view = True
    elif user.is_coach():
        athlete_user = auth_db.get_user(athlete.user_id)
        if athlete_user and athlete_user.connected_coach_id == user.id:
            can_view = True

    if not can_view:
        flash('Du har inte behörighet att se denna logg.', 'error')
        return redirect(url_for('dashboard'))

    return render_template('view_log.html',
                           user=user,
                           log=log,
                           athlete=athlete,
                           comments=comments)


@app.route('/log/<int:log_id>/comment', methods=['POST'])
@login_required
def add_comment(log_id: int):
    """Lägg till kommentar på ett loggat pass."""
    user = get_current_user()
    log = db.get_log_by_id(log_id)

    if not log:
        return jsonify({'error': 'Log not found'}), 404

    content = request.form.get('content', '').strip()
    if not content:
        flash('Kommentaren kan inte vara tom.', 'error')
        return redirect(url_for('view_log', log_id=log_id))

    comment = db.add_comment(
        log_id=log_id,
        author_id=user.id,
        author_name=user.name,
        author_role=user.role,
        content=content
    )

    flash('Kommentar tillagd!', 'success')
    return redirect(url_for('view_log', log_id=log_id))


# ============================================================
# TESTRESULTAT OCH UTVECKLING
# ============================================================

@app.route('/athlete/<int:athlete_id>/tests')
@login_required
def athlete_tests(athlete_id: int):
    """Visa testresultat och utveckling för en idrottare."""
    from models import TEST_TYPES
    user = get_current_user()
    athlete = db.get_athlete(athlete_id)

    if not athlete:
        flash('Idrottaren hittades inte.', 'error')
        return redirect(url_for('dashboard'))

    # Gruppera testresultat efter typ
    tests_by_type = {}
    for test in athlete.test_results:
        if test.test_type not in tests_by_type:
            tests_by_type[test.test_type] = []
        tests_by_type[test.test_type].append(test)

    # Sortera varje lista efter datum
    for test_type in tests_by_type:
        tests_by_type[test_type].sort(key=lambda x: x.test_date, reverse=True)

    return render_template('athlete_tests.html',
                           user=user,
                           athlete=athlete,
                           tests_by_type=tests_by_type,
                           test_types=TEST_TYPES)


@app.route('/athlete/<int:athlete_id>/tests/add', methods=['GET', 'POST'])
@login_required
def add_test(athlete_id: int):
    """Lägg till nytt testresultat."""
    from models import TEST_TYPES
    user = get_current_user()
    athlete = db.get_athlete(athlete_id)

    if not athlete:
        flash('Idrottaren hittades inte.', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        test_date = datetime.strptime(request.form['test_date'], '%Y-%m-%d').date()
        test_type = request.form['test_type']
        value = float(request.form['value'])
        notes = request.form.get('notes', '')
        test_name = request.form.get('test_name', '').strip() or 'Eget test'
        unit = request.form.get('unit', '').strip()

        db.add_test_result(
            athlete_id=athlete_id,
            test_date=test_date,
            test_type=test_type,
            test_name=test_name,
            value=value,
            unit=unit,
            notes=notes,
            recorded_by_id=user.id
        )

        flash(f'Testresultat för {test_name} tillagt!', 'success')
        return redirect(url_for('athlete_tests', athlete_id=athlete_id))

    return render_template('add_test.html',
                           user=user,
                           athlete=athlete,
                           test_types=TEST_TYPES,
                           today=date.today())


# ============================================================
# SKADESTATUS OCH FRÅNVARO
# ============================================================

@app.route('/athlete/<int:athlete_id>/injuries')
@login_required
def athlete_injuries(athlete_id: int):
    """Visa skadehistorik för en idrottare."""
    from models import BODY_PARTS
    from datetime import timedelta
    user = get_current_user()
    athlete = db.get_athlete(athlete_id)

    if not athlete:
        flash('Idrottaren hittades inte.', 'error')
        return redirect(url_for('dashboard'))

    active_injuries = athlete.get_active_injuries()
    all_injuries = athlete.get_injury_history()
    past_injuries = [i for i in all_injuries if not i.is_active]

    # Statistik - senaste 12 månaderna
    one_year_ago = date.today() - timedelta(days=365)
    recent_injuries = [i for i in all_injuries if i.start_date >= one_year_ago]
    total_injuries = len(recent_injuries)

    # Beräkna totala förlorade dagar
    total_days_lost = 0
    for injury in recent_injuries:
        if injury.end_date:
            days = (injury.end_date - injury.start_date).days
        else:
            days = (date.today() - injury.start_date).days
        total_days_lost += days

    return render_template('athlete_injuries.html',
                           user=user,
                           athlete=athlete,
                           active_injuries=active_injuries,
                           past_injuries=past_injuries,
                           total_injuries=total_injuries,
                           total_days_lost=total_days_lost,
                           today=date.today())


@app.route('/athlete/<int:athlete_id>/injuries/add', methods=['GET', 'POST'])
@login_required
def add_injury(athlete_id: int):
    """Registrera ny skada eller frånvaro."""
    from models import BODY_PARTS
    user = get_current_user()
    athlete = db.get_athlete(athlete_id)

    if not athlete:
        flash('Idrottaren hittades inte.', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
        injury_type = request.form['injury_type']
        body_part = request.form.get('body_part', '')
        severity = request.form['severity']
        description = request.form['description']
        treatment = request.form.get('treatment', '')
        training_modifications = request.form.get('training_modifications', '')

        db.add_injury(
            athlete_id=athlete_id,
            start_date=start_date,
            injury_type=injury_type,
            body_part=body_part,
            severity=severity,
            description=description,
            treatment=treatment,
            training_modifications=training_modifications,
            recorded_by_id=user.id
        )

        flash('Skada/frånvaro registrerad!', 'success')
        return redirect(url_for('athlete_injuries', athlete_id=athlete_id))

    return render_template('add_injury.html',
                           user=user,
                           athlete=athlete,
                           body_parts=BODY_PARTS,
                           today=date.today())


@app.route('/athlete/<int:athlete_id>/injuries/<int:injury_id>/close', methods=['POST'])
@login_required
def close_injury(athlete_id: int, injury_id: int):
    """Markera en skada som avslutad."""
    end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()

    db.update_injury(injury_id, end_date=end_date, is_active=False)
    flash('Skada markerad som avslutad!', 'success')
    return redirect(url_for('athlete_injuries', athlete_id=athlete_id))


# ============================================================
# COACH ROUTES
# ============================================================

@app.route('/coach/settings')
@coach_required
def coach_settings():
    """Coach-inställningar med coach-kod."""
    user = get_current_user()
    athletes = db.get_athletes_for_coach(user.id, auth_db)

    return render_template('coach_settings.html',
                           user=user,
                           athletes=athletes)


@app.route('/coach/mass-plan', methods=['GET', 'POST'])
@coach_required
def mass_plan():
    """Massplanera pass för flera idrottare med individuella datum."""
    user = get_current_user()
    athletes = db.get_athletes_for_coach(user.id, auth_db)

    if request.method == 'POST':
        coach_notes = request.form.get('coach_notes', '')

        session_name = request.form.get('session_name', 'Eget pass')
        session_type = request.form.get('session_type', 'annat')
        duration = int(request.form.get('duration', 60))
        intensity = request.form.get('intensity', 'medel')
        exercises = []

        # Gå igenom alla idrottare och skapa pass för de som är valda
        count = 0
        for athlete in athletes:
            athlete_key = f'athletes[{athlete.id}][selected]'
            date_key = f'athletes[{athlete.id}][date]'

            if request.form.get(athlete_key) == '1':
                athlete_date_str = request.form.get(date_key, '')
                if athlete_date_str:
                    try:
                        athlete_date = datetime.strptime(athlete_date_str, '%Y-%m-%d').date()
                        db.add_planned_session(
                            athlete.id,
                            athlete_date,
                            "custom",
                            session_name,
                            session_type,
                            duration,
                            intensity,
                            exercises,
                            coach_notes,
                            source="coach"
                        )
                        count += 1
                    except ValueError:
                        pass

        if count > 0:
            flash(f'"{session_name}" har planerats för {count} idrottare!', 'success')
        else:
            flash('Inga idrottare valdes.', 'warning')

        return redirect(url_for('dashboard'))

    return render_template('mass_plan.html',
                           user=user,
                           athletes=athletes,
                           today=date.today())


# ============================================================
# SHARED ROUTES
# ============================================================

@app.route('/connect-coach', methods=['GET', 'POST'])
@login_required
def connect_coach():
    """Idrottare kopplar sig till en coach."""
    user = get_current_user()
    if user is None:
        session.clear()
        return redirect(url_for('login'))

    if not user.is_athlete():
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        coach_code = request.form.get('coach_code', '').strip()
        if auth_db.connect_athlete_to_coach(user.id, coach_code):
            flash('Du är nu kopplad till din coach!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Ogiltig coach-kod. Kontrollera och försök igen.', 'error')

    current_coach = auth_db.get_coach_for_athlete(user.id)
    return render_template('connect_coach.html', user=user, current_coach=current_coach)


# ============================================================
# TÄVLINGSRESULTAT ROUTES
# ============================================================

@app.route('/athlete/<int:athlete_id>/competition-results')
@login_required
def athlete_competition_results(athlete_id: int):
    """Visa tävlingsresultat för en idrottare."""
    user = get_current_user()
    athlete = db.get_athlete(athlete_id)

    if not athlete:
        flash('Idrottaren hittades inte.', 'error')
        return redirect(url_for('dashboard'))

    # Hämta resultat baserat på idrottarens namn, födelseår och klubb
    summary = get_results_summary(
        name=athlete.name,
        birth_year=athlete.birth_year,
        club=getattr(athlete, 'club', None)
    )

    # Hämta alla resultat för detaljvy
    results = find_athlete_results(
        name=athlete.name,
        birth_year=athlete.birth_year,
        club=getattr(athlete, 'club', None)
    )

    return render_template('competition_results.html',
                           user=user,
                           athlete=athlete,
                           summary=summary,
                           results=results)


@app.route('/competition-results/search')
@login_required
def search_competition_results():
    """Sök efter idrottare i tävlingsresultat."""
    query = request.args.get('q', '')
    results = []

    if query and len(query) >= 2:
        results = search_athletes(query)

    return render_template('competition_search.html',
                           query=query,
                           results=results)


@app.route('/api/competition-results/<name>')
@login_required
def api_competition_results(name: str):
    """API endpoint för tävlingsresultat (JSON)."""
    birth_year = request.args.get('birth_year', type=int)
    club = request.args.get('club', '')

    summary = get_results_summary(name, birth_year, club)
    return jsonify(summary)


@app.route('/competition-results/update', methods=['POST'])
@coach_required
def update_competition_results():
    """Uppdatera tävlingsresultat genom att köra scrapern."""
    import subprocess
    import sys

    scraper_path = os.path.join(os.path.dirname(__file__), 'scraping', 'friidrottsstatistik-api.py')

    if not os.path.exists(scraper_path):
        flash('Scrapern hittades inte.', 'error')
        return redirect(url_for('coach_settings'))

    try:
        # Kör scrapern som subprocess
        # Sätt cwd till projektmappen så att .env-filen hittas
        project_dir = os.path.dirname(__file__)
        result = subprocess.run(
            [sys.executable, scraper_path, 'scrape'],
            capture_output=True,
            text=True,
            timeout=120,  # Max 2 minuter
            cwd=project_dir,  # Projektmappen där .env ligger
            env={**os.environ}  # Skicka med miljövariabler
        )

        # Logga output för debugging
        print("=== SCRAPER OUTPUT ===")
        print("STDOUT:", result.stdout[:500] if result.stdout else "(tom)")
        print("STDERR:", result.stderr[:500] if result.stderr else "(tom)")
        print("RETURN CODE:", result.returncode)
        print("======================")

        if result.returncode == 0:
            # Läs från JSON-filen för att få exakt antal
            import json
            json_path = os.path.join(os.path.dirname(scraper_path), 'friidrottsstatistik-goteborg-2026.json')
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                count = len(data.get('indoor', [])) + len(data.get('outdoor', []))
                athletes = len(data.get('athletes', {}))
                flash(f'Tävlingsresultat uppdaterade! ({count} resultat från {athletes} idrottare)', 'success')
            except Exception as e:
                flash(f'Tävlingsresultat uppdaterade! (kunde inte läsa antal: {e})', 'success')
        else:
            flash(f'Fel vid uppdatering: {result.stderr[:300] if result.stderr else result.stdout[:300]}', 'error')

    except subprocess.TimeoutExpired:
        flash('Uppdateringen tog för lång tid. Försök igen senare.', 'error')
    except Exception as e:
        flash(f'Kunde inte uppdatera: {str(e)}', 'error')

    return redirect(url_for('coach_settings'))


# ============================================================
# AI SCHEMA ROUTES
# ============================================================

@app.route('/athlete/<int:athlete_id>/generate-schedule', methods=['POST'])
@login_required
def generate_ai_schedule(athlete_id: int):
    """Generera nytt AI-schema för en idrottare."""
    try:
        user = get_current_user()
        if user is None:
            session.clear()
            return redirect(url_for('login'))

        athlete = db.get_athlete(athlete_id)

        if not athlete:
            flash('Idrottaren hittades inte.', 'error')
            return redirect(url_for('dashboard'))

        # Kontrollera behörighet (idrottaren själv eller coach)
        if user.is_athlete() and athlete.user_id != user.id:
            flash('Du har inte behörighet.', 'error')
            return redirect(url_for('dashboard'))

        # Byt till AI-läge om idrottaren begär det (för coach-mode användare)
        if request.form.get('switch_to_ai') == '1':
            athlete.training_mode = 'ai'

        # Uppdatera träningsfas och dagar om angett
        new_phase = request.form.get('training_phase', '')
        if new_phase and new_phase in ['grundträning', 'uppbyggnad', 'tävling', 'återhämtning']:
            athlete.training_phase = new_phase

        new_days = request.form.get('training_days', '')
        if new_days:
            athlete.training_days_per_week = int(new_days)

        start_date = None
        start_date_raw = (request.form.get('start_date') or '').strip()
        if start_date_raw:
            try:
                start_date = datetime.strptime(start_date_raw, '%Y-%m-%d').date()
            except ValueError:
                flash('Startdatumet är inte giltigt. Välj ett datum i formatet ÅÅÅÅ-MM-DD.', 'error')
                target = 'athlete_detail' if user.is_coach() else 'dashboard'
                target_kwargs = {'athlete_id': athlete.id} if user.is_coach() else {}
                return redirect(url_for(target, **target_kwargs))

        # Kontrollera om RAG ska användas
        use_rag = 'use_rag' in request.form

        # Dokumentval — vilka PDF:er RAG ska söka i
        selected_docs = request.form.getlist('rag_documents')
        if use_rag:
            from rag_knowledge import resolve_allowed_doc_keys
            running_type = {
                "medel": "medel",
                "distans": "distans",
            }.get(getattr(athlete, 'discipline', ''), "medel")
            athlete.rag_documents = resolve_allowed_doc_keys(selected_docs or getattr(athlete, 'rag_documents', None), running_type)

        db.save_athlete(athlete)

        # Rensa gamla AI-pass innan nytt schema genereras (undviker dubbletter)
        removed = db.clear_future_ai_sessions(athlete.id)
        if removed:
            print(f"  🗑 Rensade {removed} gamla AI-pass för {athlete.name}")

        # Generera alltid en fullständig månadsplan (4 veckor)
        sessions = generate_month_schedule(
            athlete,
            db,
            start_date=start_date,
            use_rag=use_rag,
        ) or []

        all_fallback = bool(sessions) and all(
            "Planstatus: Regelbaserad fallback" in (getattr(session_obj, 'coach_notes', '') or '')
            for session_obj in sessions
        )
        fallback_reason = ""
        if all_fallback and sessions:
            notes = getattr(sessions[0], 'coach_notes', '') or ''
            for line in notes.splitlines():
                if line.startswith("Coachförklaring:"):
                    fallback_reason = line.replace("Coachförklaring:", "").strip()
                    break

        from rag_knowledge import DOCUMENT_REGISTRY
        doc_names = [DOCUMENT_REGISTRY[k]["title"] for k in (athlete.rag_documents or []) if k in DOCUMENT_REGISTRY]
        rag_label = f"RAG ({', '.join(doc_names)})" if use_rag and doc_names else ("RAG" if use_rag else "regelbaserat")
        if not sessions:
            flash('Kunde inte generera något schema just nu. Försök igen senare.', 'error')
        elif all_fallback:
            flash(
                f'🤖 Månadsschemat genererades med reservupplägg ({rag_label}). {fallback_reason or "AI-generering kunde inte användas."}',
                'warning'
            )
        else:
            flash(f'🤖 Nytt månadsschema genererat ({rag_label})! {len(sessions)} pass planerade för 4 veckor.', 'success')
        return redirect(url_for('dashboard'))
    except Exception as e:
        import traceback
        print("⚠️ generate_ai_schedule kraschade:")
        traceback.print_exc()
        flash(f'Kunde inte generera träningsplan: {e}', 'error')
        return redirect(url_for('dashboard'))


# ============================================================
# API ROUTES
# ============================================================

@app.route('/api/session/<int:session_id>/delete', methods=['POST'])
@login_required
def api_delete_session(session_id: int):
    """Ta bort ett planerat pass."""
    user = get_current_user()
    planned = db.get_planned_session(session_id)

    if not planned:
        return jsonify({'error': 'Session not found'}), 404

    # Kontrollera behörighet
    athlete = db.get_athlete(planned.athlete_id)
    if user.is_athlete() and athlete.user_id != user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    db.delete_planned_session(session_id)
    return jsonify({'success': True})


# ============================================================
# CONTEXT PROCESSOR
# ============================================================

@app.context_processor
def inject_user():
    """Gör användare tillgänglig i alla templates."""
    return {'current_user': get_current_user()}


@app.template_filter('weekday_sv')
def weekday_sv_filter(d):
    """Konvertera datum till svensk veckodagsnamn."""
    weekdays = ['Måndag', 'Tisdag', 'Onsdag', 'Torsdag', 'Fredag', 'Lördag', 'Söndag']
    return weekdays[d.weekday()]


@app.template_filter('short_weekday')
def short_weekday_filter(d):
    """Kort veckodagsnamn."""
    weekdays = ['Mån', 'Tis', 'Ons', 'Tor', 'Fre', 'Lör', 'Sön']
    return weekdays[d.weekday()]


@app.template_filter('date_sv')
def date_sv_filter(d, with_year=False):
    """Formatera datum på svenska, t.ex. 'Måndag 01 juni' eller 'Måndag 01 juni 2026'."""
    weekdays = ['Måndag', 'Tisdag', 'Onsdag', 'Torsdag', 'Fredag', 'Lördag', 'Söndag']
    months = ['januari', 'februari', 'mars', 'april', 'maj', 'juni',
              'juli', 'augusti', 'september', 'oktober', 'november', 'december']
    base = f"{weekdays[d.weekday()]} {d.day:02d} {months[d.month - 1]}"
    if with_year:
        return f"{base} {d.year}"
    return base


@app.template_filter('date_short_sv')
def date_short_sv_filter(d, with_year=False):
    """Kort svenskt datumformat, t.ex. '01 jun' eller '01 jun 2026'."""
    months = ['jan', 'feb', 'mar', 'apr', 'maj', 'jun',
              'jul', 'aug', 'sep', 'okt', 'nov', 'dec']
    base = f"{d.day:02d} {months[d.month - 1]}"
    if with_year:
        return f"{base} {d.year}"
    return base


# ============================================================
# RUN
# ============================================================

if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080

    print('=' * 50)
    print('🏃 Träningsplattform - Prototyp')
    print('=' * 50)
    print(f'Öppna i webbläsaren: http://localhost:{port}')
    print('')
    print('Demo-konton:')
    print('  Coach:     coach@demo.se / demo123')
    print('  Idrottare: ebba@demo.se / demo123 (Garmin-tempomodell)')
    print('             daniel@demo.se / demo123 (Garmin-tempomodell)')
    print('')
    print('Tryck Ctrl+C för att avsluta')
    print('=' * 50)
    app.run(debug=True, port=port)
