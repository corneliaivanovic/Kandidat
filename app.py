"""
Huvudapplikation - Flask webapp för träningsplattformen.
Med autentisering, roller (coach/idrottare), planering och uppföljning.
"""

import os
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from datetime import date, datetime, timedelta
from functools import wraps

from models import db
from auth import auth_db
from readiness import calculate_readiness, get_week_trend
from ai_summary import generate_week_summary, generate_coach_action_items, invalidate_cache
from exercise_bank import (
    get_suggested_sessions, get_session_template,
    EXERCISES, SESSION_TEMPLATES, get_exercise
)
from ai_chat import ai_chat
from agent_core import run_agent, get_available_skills, load_memory
from strava_integration import (
    is_configured as strava_is_configured,
    get_authorization_url as strava_auth_url,
    exchange_code_for_tokens,
    refresh_access_token,
    get_recent_activities,
    strava_activity_to_log_data,
    StravaTokens
)

# Skapa Flask app
app = Flask(__name__,
            template_folder='templates',
            static_folder='static')

# Secret key för sessions (byt i produktion!)
app.secret_key = 'dev-secret-key-change-in-production'


def init_demo_data():
    """Initiera demo-data och koppla till users."""
    # Demo-data för idrottare
    athletes_info = [
        (2, "Emma Lindström", 2008, "sprint"),   # user_id 2
        (3, "Oscar Bergman", 2007, "medel"),      # user_id 3
        (4, "Maja Eriksson", 2009, "hopp"),       # user_id 4
    ]

    for user_id, name, birth_year, discipline in athletes_info:
        athlete = db.create_athlete_for_user(user_id, name, birth_year, discipline)
        db.generate_demo_logs(athlete)
        db.generate_demo_planned_sessions(athlete)


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
        email = request.form.get('email', '')
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
            if not user:
                error = 'E-postadressen är redan registrerad'
            else:
                # Om idrottare, skapa athlete-profil
                if role == 'athlete':
                    birth_year = int(request.form.get('birth_year', 2000))
                    discipline = request.form.get('discipline', 'sprint')
                    athlete = db.create_athlete_for_user(user.id, name, birth_year, discipline)

                    # Koppla till coach om kod angavs
                    coach_code = request.form.get('coach_code', '').strip()
                    if coach_code:
                        if not auth_db.connect_athlete_to_coach(user.id, coach_code):
                            flash('Coach-koden hittades inte, men ditt konto skapades.', 'warning')

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

    if user.is_coach():
        # Coach ser alla sina idrottare med prioritering
        athletes = db.get_athletes_for_coach(user.id, auth_db)

        athletes_data = []
        attention_needed = []

        for athlete in athletes:
            readiness = calculate_readiness(athlete)
            days_since_log = athlete.get_days_since_last_log()
            upcoming = athlete.get_upcoming_sessions(7)

            data = {
                "athlete": athlete,
                "readiness": readiness,
                "logs_7d": len(athlete.get_logs_last_n_days(7)),
                "days_since_log": days_since_log,
                "upcoming_sessions": len(upcoming),
                "todays_session": athlete.get_todays_session(),
                "needs_attention": False,
                "attention_reason": None
            }

            # Bestäm om idrottaren behöver uppmärksamhet
            if readiness.level == 'röd':
                data["needs_attention"] = True
                data["attention_reason"] = "Hög belastning - behöver vila"
            elif days_since_log >= 3:
                data["needs_attention"] = True
                data["attention_reason"] = f"Har inte loggat på {days_since_log} dagar"
            elif readiness.level == 'gul':
                data["needs_attention"] = True
                data["attention_reason"] = "Förhöjd belastning - håll koll"

            if data["needs_attention"]:
                attention_needed.append(data)

            athletes_data.append(data)

        # Sortera: de som behöver uppmärksamhet först
        def sort_key(x):
            if x['readiness'].level == 'röd':
                return (0, -x['days_since_log'])
            if x['needs_attention']:
                return (1, -x['days_since_log'])
            if x['readiness'].level == 'gul':
                return (2, 0)
            return (3, 0)

        athletes_data.sort(key=sort_key)

        # Generera AI-sammanfattning för coachen
        action_items = generate_coach_action_items(athletes_data)

        return render_template('coach_dashboard.html',
                               user=user,
                               athletes=athletes_data,
                               attention_needed=attention_needed,
                               action_items=action_items,
                               today=date.today())
    else:
        # Idrottare ser sin egen data
        athlete = db.get_athlete_by_user(user.id)
        if not athlete:
            flash('Din idrottsprofil hittades inte.', 'error')
            return redirect(url_for('logout'))

        readiness = calculate_readiness(athlete)
        summary = generate_week_summary(athlete, use_ai=True)
        recent_logs = sorted(
            athlete.get_logs_last_n_days(14),
            key=lambda x: x.date,
            reverse=True
        )

        # Hämta coach-info
        coach = auth_db.get_coach_for_athlete(user.id)

        # Hämta dagens planerade pass
        todays_session = athlete.get_todays_session()

        # Hämta kommande pass
        upcoming_sessions = athlete.get_upcoming_sessions(7)

        # Hämta trenddata
        trend_data = get_week_trend(athlete)

        return render_template('athlete_dashboard.html',
                               user=user,
                               athlete=athlete,
                               readiness=readiness,
                               summary=summary,
                               recent_logs=recent_logs,
                               coach=coach,
                               todays_session=todays_session,
                               upcoming_sessions=upcoming_sessions,
                               trend_data=trend_data,
                               today=date.today())


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

    # Generera data (med AI för personlig veckosammanfattning)
    summary = generate_week_summary(athlete, use_ai=True)
    readiness = calculate_readiness(athlete)
    suggested_sessions = get_suggested_sessions(
        readiness.recommendation,
        summary["next_focus"]["type"]
    )

    recent_logs = sorted(
        athlete.get_logs_last_n_days(14),
        key=lambda x: x.date,
        reverse=True
    )

    # Hämta kommande och dagens pass
    upcoming_sessions = athlete.get_upcoming_sessions(7)
    todays_session = athlete.get_todays_session()

    # Hämta trenddata
    trend_data = get_week_trend(athlete)

    return render_template(
        'athlete.html',
        user=user,
        athlete=athlete,
        summary=summary,
        suggested_sessions=suggested_sessions,
        recent_logs=recent_logs,
        readiness=readiness,
        upcoming_sessions=upcoming_sessions,
        todays_session=todays_session,
        trend_data=trend_data,
        today=date.today()
    )


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

        db.add_log(athlete_id, log_date, session_type, duration, rpe, comment, planned_id)
        invalidate_cache(athlete_id)  # Rensa cache så AI-sammanfattningen uppdateras
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
        planned_id
    )

    invalidate_cache(athlete_id)  # Rensa cache så AI-sammanfattningen uppdateras
    flash('Pass loggat!', 'success')
    return redirect(url_for('dashboard'))


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
        plan_type = request.form.get('plan_type', 'template')
        coach_notes = request.form.get('coach_notes', '')

        if plan_type == 'custom':
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
                if ex_name:  # Bara lägg till om namn finns
                    exercises.append({
                        "id": f"custom_{i}",
                        "name": ex_name,
                        "details": ex_details,
                        "description": ex_details
                    })
                i += 1

            # Lägg till beskrivningen som en "övning" om den finns
            if description and not exercises:
                exercises.append({
                    "id": "description",
                    "name": "Passbeskrivning",
                    "description": description
                })

            # Kolla om vi ska spara till träningsbanken
            save_to_library = request.form.get('save_to_library') == '1'
            only_save_library = request.form.get('only_save_library') == '1'
            is_public = request.form.get('is_public') == '1'

            if save_to_library or only_save_library:
                # Spara till träningsbanken
                db.add_custom_template(
                    coach_id=user.id,
                    coach_name=user.name,
                    name=session_name,
                    session_type=session_type,
                    duration=duration,
                    intensity=intensity,
                    description=description,
                    exercises=exercises,
                    is_public=is_public
                )
                flash(f'"{session_name}" sparat till träningsbanken!', 'success')

            if not only_save_library:
                # Lägg till i idrottarens plan
                db.add_planned_session(
                    athlete_id,
                    session_date,
                    "custom",
                    session_name,
                    session_type,
                    duration,
                    intensity,
                    exercises,
                    coach_notes
                )
                flash(f'Eget pass planerat för {session_date.strftime("%d/%m")}!', 'success')

            return redirect(url_for('athlete_detail', athlete_id=athlete_id))

        else:
            # Mall-baserat pass
            template_id = request.form.get('template_id', '')
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

                db.add_planned_session(
                    athlete_id,
                    session_date,
                    template_id,
                    template.name,
                    template.category,
                    template.total_duration,
                    template.intensity,
                    exercises,
                    coach_notes
                )
                flash(f'Pass planerat för {session_date.strftime("%d/%m")}!', 'success')
                return redirect(url_for('athlete_detail', athlete_id=athlete_id))

    # Hämta rekommenderade pass baserat på readiness
    readiness = calculate_readiness(athlete)
    summary = generate_week_summary(athlete)
    suggested = get_suggested_sessions(readiness.recommendation, summary["next_focus"]["type"])

    # Hämta veckoöversikt
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    week_sessions = athlete.get_planned_sessions_for_week(monday)

    return render_template('plan_session.html',
                           user=user,
                           athlete=athlete,
                           readiness=readiness,
                           suggested_sessions=suggested,
                           templates=SESSION_TEMPLATES,
                           week_sessions=week_sessions,
                           today=today,
                           monday=monday,
                           timedelta=timedelta)


@app.route('/athlete/<int:athlete_id>/week-plan')
@login_required
def week_plan(athlete_id: int):
    """Visa och hantera veckoplan för en idrottare."""
    user = get_current_user()
    athlete = db.get_athlete(athlete_id)

    if not athlete:
        flash('Idrottaren hittades inte.', 'error')
        return redirect(url_for('dashboard'))

    # Hämta veckostartdatum från query string (eller använd aktuell vecka)
    week_param = request.args.get('week')
    if week_param:
        try:
            week_start = datetime.strptime(week_param, '%Y-%m-%d').date()
            # Justera till måndag
            week_start = week_start - timedelta(days=week_start.weekday())
        except ValueError:
            week_start = date.today() - timedelta(days=date.today().weekday())
    else:
        week_start = date.today() - timedelta(days=date.today().weekday())

    week_end = week_start + timedelta(days=6)
    prev_week = week_start - timedelta(days=7)
    next_week = week_start + timedelta(days=7)
    today = date.today()

    # Hämta planerade pass för veckan
    planned_sessions = athlete.get_planned_sessions_for_week(week_start)

    # Hämta loggar för veckan
    logs_this_week = [log for log in athlete.logs if week_start <= log.date <= week_end]

    # Beräkna totala minuter
    total_planned_duration = sum(ps.planned_duration for ps in planned_sessions)
    completed_sessions = sum(1 for ps in planned_sessions if ps.completed)

    # Kontrollera om användaren är coach
    is_coach = user.is_coach()

    return render_template('week_plan.html',
                           user=user,
                           athlete=athlete,
                           planned_sessions=planned_sessions,
                           logs_this_week=logs_this_week,
                           week_start=week_start,
                           week_end=week_end,
                           prev_week=prev_week,
                           next_week=next_week,
                           total_planned_duration=total_planned_duration,
                           completed_sessions=completed_sessions,
                           today=today,
                           is_coach=is_coach,
                           timedelta=timedelta)


@app.route('/planned-session/<int:session_id>/delete', methods=['POST'])
@coach_required
def delete_planned_session(session_id: int):
    """Ta bort ett planerat pass."""
    session = db.get_planned_session(session_id)

    if session:
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

        # Hämta testinfo
        test_info = TEST_TYPES.get(test_type, TEST_TYPES['custom'])
        test_name = test_info['name']
        unit = request.form.get('unit', test_info['unit'])

        if test_type == 'custom':
            test_name = request.form.get('custom_name', 'Eget test')

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

        invalidate_cache(athlete_id)  # Rensa cache så AI-sammanfattningen uppdateras
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


@app.route('/coach/library')
@coach_required
def session_library():
    """Visa träningsbanken med coachens egna mallar."""
    user = get_current_user()
    custom_templates = db.get_custom_templates_for_coach(user.id)

    return render_template('session_library.html',
                           user=user,
                           custom_templates=custom_templates,
                           builtin_templates=SESSION_TEMPLATES)


@app.route('/coach/library/create', methods=['GET', 'POST'])
@coach_required
def create_template():
    """Skapa en ny passmall direkt i träningsbanken."""
    user = get_current_user()

    if request.method == 'POST':
        name = request.form.get('name', '')
        session_type = request.form.get('session_type', 'annat')
        duration = int(request.form.get('duration', 60))
        intensity = request.form.get('intensity', 'medel')
        description = request.form.get('description', '')
        is_public = request.form.get('is_public') == '1'

        # Samla övningar
        exercises = []
        i = 0
        while f'exercises[{i}][name]' in request.form:
            ex_name = request.form.get(f'exercises[{i}][name]', '').strip()
            ex_details = request.form.get(f'exercises[{i}][details]', '').strip()
            if ex_name:
                exercises.append({"name": ex_name, "details": ex_details})
            i += 1

        db.add_custom_template(
            coach_id=user.id,
            coach_name=user.name,
            name=name,
            session_type=session_type,
            duration=duration,
            intensity=intensity,
            description=description,
            exercises=exercises,
            is_public=is_public
        )
        flash(f'Passmallen "{name}" har sparats!', 'success')
        return redirect(url_for('session_library'))

    return render_template('create_template.html', user=user)


@app.route('/coach/library/<int:template_id>/use')
@coach_required
def use_template(template_id: int):
    """Välj idrottare att använda mallen för."""
    user = get_current_user()
    template = db.get_custom_template(template_id)

    if not template:
        flash('Mallen hittades inte.', 'error')
        return redirect(url_for('session_library'))

    athletes = db.get_athletes_for_coach(user.id, auth_db)

    return render_template('use_template.html',
                           user=user,
                           template=template,
                           athletes=athletes,
                           today=date.today())


@app.route('/coach/library/<int:template_id>/apply', methods=['POST'])
@coach_required
def apply_template(template_id: int):
    """Applicera mall på valda idrottare."""
    user = get_current_user()
    template = db.get_custom_template(template_id)

    if not template:
        flash('Mallen hittades inte.', 'error')
        return redirect(url_for('session_library'))

    coach_notes = request.form.get('coach_notes', '')
    athletes = db.get_athletes_for_coach(user.id, auth_db)

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
                        f"custom_{template.id}",
                        template.name,
                        template.session_type,
                        template.duration,
                        template.intensity,
                        template.exercises,
                        coach_notes
                    )
                    count += 1
                except ValueError:
                    pass

    if count > 0:
        db.increment_template_use(template_id)
        flash(f'Passet "{template.name}" har lagts till för {count} idrottare!', 'success')
    else:
        flash('Inga idrottare valdes.', 'warning')

    return redirect(url_for('session_library'))


@app.route('/coach/library/<int:template_id>/delete', methods=['POST'])
@coach_required
def delete_template(template_id: int):
    """Ta bort en passmall."""
    template = db.get_custom_template(template_id)

    if template:
        db.delete_custom_template(template_id)
        flash(f'Mallen "{template.name}" har tagits bort.', 'success')
    else:
        flash('Mallen hittades inte.', 'error')

    return redirect(url_for('session_library'))


@app.route('/coach/mass-plan', methods=['GET', 'POST'])
@coach_required
def mass_plan():
    """Massplanera pass för flera idrottare med individuella datum."""
    user = get_current_user()
    athletes = db.get_athletes_for_coach(user.id, auth_db)
    custom_templates = db.get_custom_templates_for_coach(user.id)

    if request.method == 'POST':
        pass_source = request.form.get('pass_source', 'template')
        coach_notes = request.form.get('coach_notes', '')

        # Bestäm passinfo baserat på källa
        if pass_source == 'template':
            template_id = request.form.get('template_id', '')
            template = SESSION_TEMPLATES.get(template_id)
            if not template:
                flash('Välj en mall.', 'error')
                return redirect(url_for('mass_plan'))
            session_name = template.name
            session_type = template.category
            duration = template.total_duration
            intensity = template.intensity
            exercises = []
            for ex_id in template.exercises:
                ex = get_exercise(ex_id)
                if ex:
                    exercises.append({"name": ex.name, "details": f"{ex.duration_minutes} min"})

        elif pass_source == 'library':
            library_template_id = request.form.get('library_template_id', '')
            if library_template_id:
                lib_template = db.get_custom_template(int(library_template_id))
                if lib_template:
                    session_name = lib_template.name
                    session_type = lib_template.session_type
                    duration = lib_template.duration
                    intensity = lib_template.intensity
                    exercises = lib_template.exercises
                    db.increment_template_use(int(library_template_id))
                else:
                    flash('Mallen hittades inte.', 'error')
                    return redirect(url_for('mass_plan'))
            else:
                flash('Välj en mall från träningsbanken.', 'error')
                return redirect(url_for('mass_plan'))

        else:  # custom
            session_name = request.form.get('session_name', 'Eget pass')
            session_type = request.form.get('session_type', 'annat')
            duration = int(request.form.get('duration', 60))
            intensity = request.form.get('intensity', 'medel')
            description = request.form.get('description', '')
            exercises = []

            # Spara till träningsbanken om valt
            if request.form.get('save_to_library') == '1':
                db.add_custom_template(
                    coach_id=user.id,
                    coach_name=user.name,
                    name=session_name,
                    session_type=session_type,
                    duration=duration,
                    intensity=intensity,
                    description=description,
                    exercises=exercises,
                    is_public=True
                )

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
                            f"mass_{pass_source}",
                            session_name,
                            session_type,
                            duration,
                            intensity,
                            exercises,
                            coach_notes
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
                           builtin_templates=SESSION_TEMPLATES,
                           custom_templates=custom_templates,
                           today=date.today())


# ============================================================
# SHARED ROUTES
# ============================================================

@app.route('/exercises')
@login_required
def exercise_list():
    """Visa övningsbanken med möjlighet att bygga pass."""
    user = get_current_user()

    # Gruppera övningar efter kategori
    exercises_by_category = {}
    for ex in EXERCISES.values():
        if ex.category not in exercises_by_category:
            exercises_by_category[ex.category] = []
        exercises_by_category[ex.category].append(ex)

    return render_template('exercises.html',
                           user=user,
                           exercises=EXERCISES,
                           exercises_by_category=exercises_by_category,
                           sessions=SESSION_TEMPLATES)


@app.route('/connect-coach', methods=['GET', 'POST'])
@login_required
def connect_coach():
    """Idrottare kopplar sig till en coach."""
    user = get_current_user()

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
# AI CHAT ROUTES
# ============================================================

@app.route('/athlete/<int:athlete_id>/chat', methods=['GET', 'POST'])
@coach_required
def athlete_ai_chat(athlete_id: int):
    """AI-chatt för en specifik idrottare."""
    user = get_current_user()
    athlete = db.get_athlete(athlete_id)

    if not athlete:
        flash('Idrottare hittades inte.', 'error')
        return redirect(url_for('dashboard'))

    # Beräkna idrottarens status
    readiness = calculate_readiness(athlete)
    logs = athlete.logs[-30:] if athlete.logs else []
    injuries = athlete.get_active_injuries()

    # Beräkna ålder
    current_year = date.today().year
    age = current_year - athlete.birth_year if athlete.birth_year else None

    # Bygg athlete_data för AI
    athlete_data = {
        "name": athlete.name,
        "age": age,
        "discipline": athlete.discipline,
        "level": "ungdom",  # Kan utökas
        "acwr": readiness.acwr,
        "weekly_load": readiness.acute_load,
        "readiness": readiness.level,
        "injuries": [
            {"body_part": inj.body_part, "severity": inj.severity}
            for inj in injuries
        ],
        "recent_logs": [log.to_dict() for log in logs[-7:]]
    }

    # Hantera POST (nytt meddelande)
    if request.method == 'POST':
        message = request.form.get('message', '').strip()
        if message:
            # Skicka till AI
            result = ai_chat.chat(athlete_id, message, athlete_data)
            # Resultatet sparas automatiskt i chatthistoriken

    # Hämta chatthistorik
    chat_history = ai_chat.get_chat_history(athlete_id)

    # Kolla om API är konfigurerat
    api_configured = ai_chat.client is not None

    return render_template('ai_chat.html',
                           user=user,
                           athlete=athlete,
                           acwr=readiness.acwr,
                           weekly_load=readiness.acute_load,
                           injuries=injuries,
                           chat_history=chat_history,
                           api_configured=api_configured)


@app.route('/athlete/<int:athlete_id>/chat/clear')
@coach_required
def ai_chat_clear(athlete_id: int):
    """Rensa chatthistoriken för en idrottare."""
    ai_chat.clear_chat_history(athlete_id)
    flash('Chatthistoriken har rensats.', 'success')
    return redirect(url_for('athlete_ai_chat', athlete_id=athlete_id))


# ============================================================
# STRAVA INTEGRATION ROUTES
# ============================================================

@app.route('/strava/connect')
@login_required
def strava_connect():
    """Starta Strava OAuth-flöde."""
    user = get_current_user()

    # Kolla om redan kopplad
    if auth_db.is_strava_connected(user.id):
        flash('Du har redan kopplat Strava!', 'info')
        return redirect(url_for('strava_settings'))

    # Kolla om Strava är konfigurerat
    if not strava_is_configured():
        flash('Strava-integration är inte konfigurerad. Lägg till API-nycklar i .env', 'error')
        return redirect(url_for('dashboard'))

    # Generera authorization URL
    callback_url = url_for('strava_callback', _external=True)
    # Använd user_id som state för säkerhet
    state = f"user_{user.id}"
    auth_url = strava_auth_url(callback_url, state)

    return redirect(auth_url)


@app.route('/strava/callback')
@login_required
def strava_callback():
    """Hantera callback från Strava efter användaren godkänt."""
    user = get_current_user()

    # Kolla efter fel från Strava
    error = request.args.get('error')
    if error:
        flash(f'Strava-koppling avbröts: {error}', 'error')
        return redirect(url_for('strava_settings'))

    # Hämta authorization code
    code = request.args.get('code')
    state = request.args.get('state')

    if not code:
        flash('Ingen authorization code mottagen från Strava.', 'error')
        return redirect(url_for('strava_settings'))

    # Verifiera state (säkerhetskontroll)
    expected_state = f"user_{user.id}"
    if state != expected_state:
        flash('Ogiltig state-parameter. Försök igen.', 'error')
        return redirect(url_for('strava_settings'))

    # Byt code mot tokens
    callback_url = url_for('strava_callback', _external=True)
    tokens = exchange_code_for_tokens(code, callback_url)

    if not tokens:
        flash('Kunde inte slutföra Strava-koppling. Försök igen.', 'error')
        return redirect(url_for('strava_settings'))

    # Spara tokens för användaren
    auth_db.connect_strava(
        user_id=user.id,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_at=tokens.expires_at,
        athlete_id=tokens.athlete_id,
        athlete_name=tokens.athlete_name
    )

    flash(f'Strava kopplat! Inloggad som {tokens.athlete_name}', 'success')
    return redirect(url_for('strava_settings'))


@app.route('/strava/disconnect', methods=['POST'])
@login_required
def strava_disconnect():
    """Koppla bort Strava."""
    user = get_current_user()
    auth_db.disconnect_strava(user.id)
    flash('Strava har kopplats bort.', 'success')
    return redirect(url_for('strava_settings'))


@app.route('/strava/settings')
@login_required
def strava_settings():
    """Visa Strava-inställningar och importera aktiviteter."""
    user = get_current_user()
    athlete = db.get_athlete_by_user(user.id)

    strava_info = auth_db.get_strava_tokens(user.id)
    is_connected = strava_info is not None
    is_configured = strava_is_configured()

    activities = []
    if is_connected:
        # Kolla om token behöver förnyas
        import time
        if strava_info['expires_at'] and strava_info['expires_at'] < time.time():
            new_tokens = refresh_access_token(strava_info['refresh_token'])
            if new_tokens:
                auth_db.update_strava_tokens(
                    user.id,
                    new_tokens.access_token,
                    new_tokens.refresh_token,
                    new_tokens.expires_at
                )
                strava_info['access_token'] = new_tokens.access_token

        # Hämta senaste aktiviteter
        try:
            activities = get_recent_activities(strava_info['access_token'], days=14)
        except Exception as e:
            flash(f'Kunde inte hämta aktiviteter: {e}', 'error')

    return render_template('strava_settings.html',
                           user=user,
                           athlete=athlete,
                           is_connected=is_connected,
                           is_configured=is_configured,
                           strava_info=strava_info,
                           activities=activities)


@app.route('/strava/import', methods=['POST'])
@login_required
def strava_import():
    """Importera valda aktiviteter från Strava."""
    user = get_current_user()
    athlete = db.get_athlete_by_user(user.id)

    if not athlete:
        flash('Ingen idrottsprofil hittades.', 'error')
        return redirect(url_for('strava_settings'))

    strava_info = auth_db.get_strava_tokens(user.id)
    if not strava_info:
        flash('Strava är inte kopplat.', 'error')
        return redirect(url_for('strava_settings'))

    # Hämta valda aktivitets-IDs
    selected_ids = request.form.getlist('activity_ids')
    if not selected_ids:
        flash('Inga aktiviteter valda.', 'warning')
        return redirect(url_for('strava_settings'))

    # Hämta aktiviteter och importera
    activities = get_recent_activities(strava_info['access_token'], days=30)
    imported = 0

    for activity in activities:
        if str(activity.id) in selected_ids:
            log_data = strava_activity_to_log_data(activity)

            # Hämta RPE från formuläret om användaren angett det
            rpe_key = f'rpe_{activity.id}'
            if rpe_key in request.form:
                try:
                    log_data['rpe'] = int(request.form[rpe_key])
                except ValueError:
                    log_data['rpe'] = 5  # Default

            # Lägg till loggen
            db.add_log(
                athlete.id,
                log_data['date'],
                log_data['session_type'],
                log_data['duration'],
                log_data['rpe'] or 5,
                log_data['comment']
            )
            imported += 1

    if imported > 0:
        invalidate_cache(athlete.id)
        flash(f'{imported} aktivitet(er) importerade från Strava!', 'success')
    else:
        flash('Inga aktiviteter importerades.', 'warning')

    return redirect(url_for('dashboard'))


# ============================================================
# API ROUTES
# ============================================================

@app.route('/api/athlete/<int:athlete_id>/summary')
@login_required
def api_athlete_summary(athlete_id: int):
    """API endpoint för veckosammanfattning (JSON)."""
    user = get_current_user()
    athlete = db.get_athlete(athlete_id)

    if not athlete:
        return jsonify({'error': 'Athlete not found'}), 404

    # Kontrollera behörighet
    if user.is_athlete() and athlete.user_id != user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    summary = generate_week_summary(athlete)
    readiness = calculate_readiness(athlete)

    return jsonify({
        'athlete': athlete.to_dict(),
        'summary': summary,
        'readiness': {
            'score': readiness.score,
            'level': readiness.level,
            'acute_load': readiness.acute_load,
            'chronic_load': readiness.chronic_load,
            'acwr': readiness.acwr,
            'message': readiness.message,
            'recommendation': readiness.recommendation
        }
    })


@app.route('/api/athlete/<int:athlete_id>/trend')
@login_required
def api_athlete_trend(athlete_id: int):
    """API endpoint för trenddata (JSON)."""
    user = get_current_user()
    athlete = db.get_athlete(athlete_id)

    if not athlete:
        return jsonify({'error': 'Athlete not found'}), 404

    trend = get_week_trend(athlete)
    return jsonify(trend)


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


# ============================================================
# AGENT ROUTES (OpenClaw-inspirerad agent)
# ============================================================

@app.route('/agent')
@coach_required
def agent_dashboard():
    """AI Agent Dashboard - OpenClaw-inspirerad."""
    user = get_current_user()
    skills = get_available_skills()
    recent_runs = load_memory("agent_runs", limit=10)

    # Vänd på listan så senaste är först
    recent_runs = [
        {"timestamp": r["timestamp"].split("T")[0], "goal": r["data"]["goal"], "summary": r["data"]["summary"]}
        for r in reversed(recent_runs)
    ]

    return render_template('agent_dashboard.html',
                           user=user,
                           skills=skills,
                           recent_runs=recent_runs)


@app.route('/agent/run', methods=['POST'])
@coach_required
def agent_run():
    """Kör agenten med ett mål."""
    data = request.get_json()
    goal = data.get('goal', '')
    athlete_id = data.get('athlete_id')

    context = {}
    if athlete_id:
        context['athlete_id'] = athlete_id

    result = run_agent(goal, context)

    return jsonify(result)


@app.route('/athlete/<int:athlete_id>/agent')
@login_required
def athlete_agent(athlete_id: int):
    """Agent-vy för en specifik idrottare."""
    user = get_current_user()
    athlete = db.get_athlete(athlete_id)

    if not athlete:
        flash('Idrottaren hittades inte.', 'error')
        return redirect(url_for('dashboard'))

    skills = get_available_skills()

    return render_template('agent_dashboard.html',
                           user=user,
                           skills=skills,
                           athlete_id=athlete_id,
                           athlete_name=athlete.name,
                           recent_runs=[])


# ============================================================
# RUN
# ============================================================

if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000

    print('=' * 50)
    print('🏃 Träningsplattform - Prototyp')
    print('=' * 50)
    print(f'Öppna i webbläsaren: http://localhost:{port}')
    print('')
    print('Demo-konton:')
    print('  Coach:     coach@demo.se / demo123')
    print('  Idrottare: emma@demo.se / demo123')
    print('')
    print('Tryck Ctrl+C för att avsluta')
    print('=' * 50)
    app.run(debug=True, port=port)
