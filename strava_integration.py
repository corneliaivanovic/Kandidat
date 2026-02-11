"""
Strava Integration - OAuth 2.0 flöde för att hämta träningsdata från Strava.

Användaren godkänner åtkomst via Stravas login, och vi kan sedan
hämta deras aktiviteter automatiskt.
"""

import os
import requests
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# KONFIGURATION
# ============================================================

# Dessa värden får ni när ni registrerar er app hos Strava
# https://www.strava.com/settings/api
STRAVA_CLIENT_ID = os.getenv('STRAVA_CLIENT_ID', '')
STRAVA_CLIENT_SECRET = os.getenv('STRAVA_CLIENT_SECRET', '')

# URLs för OAuth-flödet
STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"

# Vilken data vi vill ha tillgång till
# read = läsa aktiviteter, profile:read_all = läsa profil
STRAVA_SCOPE = "read,activity:read_all,profile:read_all"


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class StravaTokens:
    """Tokens för en användares Strava-koppling."""
    access_token: str
    refresh_token: str
    expires_at: int  # Unix timestamp
    athlete_id: int
    athlete_name: str

    def is_expired(self) -> bool:
        """Kolla om access_token har gått ut."""
        return datetime.now().timestamp() >= self.expires_at


@dataclass
class StravaActivity:
    """En aktivitet från Strava."""
    id: int
    name: str
    type: str  # Run, Ride, Swim, etc.
    start_date: datetime
    distance: float  # meter
    moving_time: int  # sekunder
    elapsed_time: int  # sekunder
    average_heartrate: Optional[float] = None
    max_heartrate: Optional[float] = None
    suffer_score: Optional[float] = None  # Stravas "relative effort"
    description: Optional[str] = None

    @property
    def duration_minutes(self) -> int:
        """Returnera duration i minuter."""
        return self.moving_time // 60

    @property
    def distance_km(self) -> float:
        """Returnera distans i km."""
        return self.distance / 1000


# ============================================================
# OAUTH FUNKTIONER
# ============================================================

def get_authorization_url(redirect_uri: str, state: str = None) -> str:
    """
    Generera URL dit användaren ska skickas för att godkänna åtkomst.

    Args:
        redirect_uri: URL dit Strava skickar tillbaka användaren
        state: Valfri säkerhetsparameter (rekommenderas)

    Returns:
        URL som användaren ska besöka
    """
    params = {
        'client_id': STRAVA_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': STRAVA_SCOPE,
        'approval_prompt': 'auto'  # 'force' för att alltid visa godkännande-dialog
    }

    if state:
        params['state'] = state

    query = '&'.join(f"{k}={v}" for k, v in params.items())
    return f"{STRAVA_AUTH_URL}?{query}"


def exchange_code_for_tokens(code: str, redirect_uri: str) -> Optional[StravaTokens]:
    """
    Byt authorization code mot access tokens.

    Detta anropas efter att användaren godkänt och Strava
    skickat tillbaka dem med en 'code' parameter.

    Args:
        code: Authorization code från Strava
        redirect_uri: Samma redirect_uri som användes i authorization

    Returns:
        StravaTokens om lyckad, None annars
    """
    data = {
        'client_id': STRAVA_CLIENT_ID,
        'client_secret': STRAVA_CLIENT_SECRET,
        'code': code,
        'grant_type': 'authorization_code'
    }

    try:
        response = requests.post(STRAVA_TOKEN_URL, data=data)
        response.raise_for_status()
        result = response.json()

        athlete = result.get('athlete', {})

        return StravaTokens(
            access_token=result['access_token'],
            refresh_token=result['refresh_token'],
            expires_at=result['expires_at'],
            athlete_id=athlete.get('id', 0),
            athlete_name=f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip()
        )

    except requests.RequestException as e:
        print(f"Fel vid token-utbyte: {e}")
        return None


def refresh_access_token(refresh_token: str) -> Optional[StravaTokens]:
    """
    Förnya access_token med refresh_token.

    Access tokens går ut efter ~6 timmar, så vi behöver
    förnya dem regelbundet.

    Args:
        refresh_token: Refresh token från tidigare authorization

    Returns:
        Nya StravaTokens om lyckad, None annars
    """
    data = {
        'client_id': STRAVA_CLIENT_ID,
        'client_secret': STRAVA_CLIENT_SECRET,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token'
    }

    try:
        response = requests.post(STRAVA_TOKEN_URL, data=data)
        response.raise_for_status()
        result = response.json()

        return StravaTokens(
            access_token=result['access_token'],
            refresh_token=result['refresh_token'],
            expires_at=result['expires_at'],
            athlete_id=0,  # Returneras inte vid refresh
            athlete_name=""
        )

    except requests.RequestException as e:
        print(f"Fel vid token-förnyelse: {e}")
        return None


# ============================================================
# API FUNKTIONER - HÄMTA DATA
# ============================================================

def get_athlete_profile(access_token: str) -> Optional[dict]:
    """Hämta användarens Strava-profil."""
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = requests.get(f"{STRAVA_API_BASE}/athlete", headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Fel vid hämtning av profil: {e}")
        return None


def get_activities(access_token: str, after: datetime = None,
                   before: datetime = None, per_page: int = 30) -> list[StravaActivity]:
    """
    Hämta användarens aktiviteter från Strava.

    Args:
        access_token: Giltig access token
        after: Hämta aktiviteter efter detta datum
        before: Hämta aktiviteter före detta datum
        per_page: Antal aktiviteter per sida (max 200)

    Returns:
        Lista med StravaActivity-objekt
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"per_page": min(per_page, 200)}

    if after:
        params["after"] = int(after.timestamp())
    if before:
        params["before"] = int(before.timestamp())

    try:
        response = requests.get(
            f"{STRAVA_API_BASE}/athlete/activities",
            headers=headers,
            params=params
        )
        response.raise_for_status()
        data = response.json()

        activities = []
        for item in data:
            activities.append(StravaActivity(
                id=item['id'],
                name=item['name'],
                type=item['type'],
                start_date=datetime.fromisoformat(item['start_date_local'].replace('Z', '+00:00')),
                distance=item.get('distance', 0),
                moving_time=item.get('moving_time', 0),
                elapsed_time=item.get('elapsed_time', 0),
                average_heartrate=item.get('average_heartrate'),
                max_heartrate=item.get('max_heartrate'),
                suffer_score=item.get('suffer_score'),
                description=item.get('description')
            ))

        return activities

    except requests.RequestException as e:
        print(f"Fel vid hämtning av aktiviteter: {e}")
        return []


def get_activity_detail(access_token: str, activity_id: int) -> Optional[dict]:
    """Hämta detaljerad info om en specifik aktivitet."""
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = requests.get(
            f"{STRAVA_API_BASE}/activities/{activity_id}",
            headers=headers
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Fel vid hämtning av aktivitet {activity_id}: {e}")
        return None


# ============================================================
# MAPPNING TILL ERT SYSTEM
# ============================================================

def map_strava_type_to_session_type(strava_type: str) -> str:
    """
    Mappa Stravas aktivitetstyp till era session types.
    """
    mapping = {
        'Run': 'löpning',
        'TrailRun': 'löpning',
        'VirtualRun': 'löpning',
        'Walk': 'promenad',
        'Hike': 'promenad',
        'Ride': 'cykel',
        'VirtualRide': 'cykel',
        'Swim': 'simning',
        'WeightTraining': 'styrka',
        'Workout': 'styrka',
        'Yoga': 'rörlighet',
        'CrossFit': 'kombinerat'
    }
    return mapping.get(strava_type, 'annat')


def estimate_rpe_from_heartrate(activity: StravaActivity, max_hr: int = 200) -> Optional[int]:
    """
    Uppskatta RPE baserat på genomsnittlig hjärtfrekvens.

    Detta är en grov uppskattning - användaren bör justera manuellt.

    RPE-zoner baserat på % av max HR:
    - <60%: RPE 1-3 (lätt)
    - 60-70%: RPE 4-5 (medel)
    - 70-80%: RPE 6-7 (ganska hård)
    - 80-90%: RPE 8-9 (hård)
    - >90%: RPE 10 (maximal)
    """
    if not activity.average_heartrate:
        return None

    hr_percent = (activity.average_heartrate / max_hr) * 100

    if hr_percent < 60:
        return 3
    elif hr_percent < 70:
        return 5
    elif hr_percent < 80:
        return 6
    elif hr_percent < 90:
        return 8
    else:
        return 9


def strava_activity_to_log_data(activity: StravaActivity) -> dict:
    """
    Konvertera en Strava-aktivitet till data för TrainingLog.

    Returns:
        Dict med fält som matchar add_log()-funktionen
    """
    estimated_rpe = estimate_rpe_from_heartrate(activity)

    return {
        'date': activity.start_date.date(),
        'session_type': map_strava_type_to_session_type(activity.type),
        'duration': activity.duration_minutes,
        'rpe': estimated_rpe,  # None om vi inte kan uppskatta - användaren fyller i
        'comment': f"Importerad från Strava: {activity.name}",
        'strava_id': activity.id,
        'distance_km': activity.distance_km,
        'original_type': activity.type
    }


# ============================================================
# HJÄLPFUNKTIONER
# ============================================================

def is_configured() -> bool:
    """Kolla om Strava-integration är konfigurerad."""
    return bool(STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET)


def get_recent_activities(access_token: str, days: int = 14) -> list[StravaActivity]:
    """Hämta aktiviteter från de senaste N dagarna."""
    after = datetime.now() - timedelta(days=days)
    return get_activities(access_token, after=after)


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    print("=== Strava Integration ===\n")

    if is_configured():
        print(f"✓ Konfigurerad med Client ID: {STRAVA_CLIENT_ID[:8]}...")

        # Visa authorization URL
        redirect = "http://127.0.0.1:5000/strava/callback"
        auth_url = get_authorization_url(redirect, state="test123")
        print(f"\nAuthorization URL:\n{auth_url}")
    else:
        print("✗ Inte konfigurerad")
        print("\nLägg till i .env:")
        print("  STRAVA_CLIENT_ID=din_client_id")
        print("  STRAVA_CLIENT_SECRET=din_client_secret")
