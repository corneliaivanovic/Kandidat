"""
Autentisering och användarsystem.
Hanterar inloggning, registrering och roller (coach/idrottare).
"""

from dataclasses import dataclass, field
from typing import Optional
import hashlib
import secrets
import string


@dataclass
class User:
    """En användare i systemet."""
    id: int
    email: str
    password_hash: str
    name: str
    role: str  # "coach" eller "athlete"
    coach_code: Optional[str] = None  # Endast för coaches
    connected_coach_id: Optional[int] = None  # Endast för athletes

    # Strava-integration
    strava_access_token: Optional[str] = None
    strava_refresh_token: Optional[str] = None
    strava_expires_at: Optional[int] = None
    strava_athlete_id: Optional[int] = None
    strava_athlete_name: Optional[str] = None

    def check_password(self, password: str) -> bool:
        """Verifiera lösenord."""
        return self.password_hash == self._hash_password(password)

    @staticmethod
    def _hash_password(password: str) -> str:
        """Hasha lösenord (enkel version för prototyp)."""
        return hashlib.sha256(password.encode()).hexdigest()

    def is_coach(self) -> bool:
        return self.role == "coach"

    def is_athlete(self) -> bool:
        return self.role == "athlete"

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "coach_code": self.coach_code
        }


class AuthStore:
    """Hantering av användare och autentisering."""

    def __init__(self):
        self.users: dict[int, User] = {}
        self.users_by_email: dict[str, User] = {}
        self.next_user_id = 1
        self._load_demo_users()

    def _generate_coach_code(self) -> str:
        """Generera en unik coach-kod (t.ex. ANNA-7X3K)."""
        chars = string.ascii_uppercase + string.digits
        code = ''.join(secrets.choice(chars) for _ in range(4))
        return code

    def _load_demo_users(self):
        """Skapa demo-användare för test."""
        # Demo coach
        coach = self.register(
            email="coach@demo.se",
            password="demo123",
            name="Demo Coach",
            role="coach"
        )

        # Demo idrottare (kopplade till coach)
        athletes_data = [
            ("emma@demo.se", "Emma Lindström"),
            ("oscar@demo.se", "Oscar Bergman"),
            ("maja@demo.se", "Maja Eriksson"),
        ]

        for email, name in athletes_data:
            athlete = self.register(
                email=email,
                password="demo123",
                name=name,
                role="athlete"
            )
            # Koppla till demo-coach
            if athlete and coach:
                self.connect_athlete_to_coach(athlete.id, coach.coach_code)

    def register(self, email: str, password: str, name: str, role: str) -> Optional[User]:
        """Registrera en ny användare."""
        # Kolla om email redan finns
        if email.lower() in self.users_by_email:
            return None

        # Skapa coach-kod om det är en coach
        coach_code = None
        if role == "coach":
            coach_code = self._generate_coach_code()
            # Se till att koden är unik
            while any(u.coach_code == coach_code for u in self.users.values()):
                coach_code = self._generate_coach_code()

        user = User(
            id=self.next_user_id,
            email=email.lower(),
            password_hash=User._hash_password(password),
            name=name,
            role=role,
            coach_code=coach_code
        )

        self.users[user.id] = user
        self.users_by_email[user.email] = user
        self.next_user_id += 1

        return user

    def login(self, email: str, password: str) -> Optional[User]:
        """Logga in en användare."""
        user = self.users_by_email.get(email.lower())
        if user and user.check_password(password):
            return user
        return None

    def get_user(self, user_id: int) -> Optional[User]:
        """Hämta användare via ID."""
        return self.users.get(user_id)

    def get_coach_by_code(self, code: str) -> Optional[User]:
        """Hitta en coach via deras coach-kod."""
        code = code.upper().strip()
        for user in self.users.values():
            if user.is_coach() and user.coach_code == code:
                return user
        return None

    def connect_athlete_to_coach(self, athlete_id: int, coach_code: str) -> bool:
        """Koppla en idrottare till en coach via coach-kod."""
        athlete = self.get_user(athlete_id)
        coach = self.get_coach_by_code(coach_code)

        if not athlete or not coach:
            return False

        if not athlete.is_athlete() or not coach.is_coach():
            return False

        athlete.connected_coach_id = coach.id
        return True

    def get_athletes_for_coach(self, coach_id: int) -> list[User]:
        """Hämta alla idrottare kopplade till en coach."""
        return [
            user for user in self.users.values()
            if user.is_athlete() and user.connected_coach_id == coach_id
        ]

    def get_coach_for_athlete(self, athlete_id: int) -> Optional[User]:
        """Hämta coachen för en idrottare."""
        athlete = self.get_user(athlete_id)
        if not athlete or not athlete.connected_coach_id:
            return None
        return self.get_user(athlete.connected_coach_id)

    # ============================================================
    # STRAVA INTEGRATION
    # ============================================================

    def connect_strava(self, user_id: int, access_token: str, refresh_token: str,
                       expires_at: int, athlete_id: int, athlete_name: str) -> bool:
        """Spara Strava-koppling för en användare."""
        user = self.get_user(user_id)
        if not user:
            return False

        user.strava_access_token = access_token
        user.strava_refresh_token = refresh_token
        user.strava_expires_at = expires_at
        user.strava_athlete_id = athlete_id
        user.strava_athlete_name = athlete_name
        return True

    def disconnect_strava(self, user_id: int) -> bool:
        """Ta bort Strava-koppling för en användare."""
        user = self.get_user(user_id)
        if not user:
            return False

        user.strava_access_token = None
        user.strava_refresh_token = None
        user.strava_expires_at = None
        user.strava_athlete_id = None
        user.strava_athlete_name = None
        return True

    def update_strava_tokens(self, user_id: int, access_token: str,
                             refresh_token: str, expires_at: int) -> bool:
        """Uppdatera Strava-tokens efter refresh."""
        user = self.get_user(user_id)
        if not user:
            return False

        user.strava_access_token = access_token
        user.strava_refresh_token = refresh_token
        user.strava_expires_at = expires_at
        return True

    def get_strava_tokens(self, user_id: int) -> Optional[dict]:
        """Hämta Strava-tokens för en användare."""
        user = self.get_user(user_id)
        if not user or not user.strava_access_token:
            return None

        return {
            'access_token': user.strava_access_token,
            'refresh_token': user.strava_refresh_token,
            'expires_at': user.strava_expires_at,
            'athlete_id': user.strava_athlete_id,
            'athlete_name': user.strava_athlete_name
        }

    def is_strava_connected(self, user_id: int) -> bool:
        """Kolla om användaren har kopplat Strava."""
        user = self.get_user(user_id)
        return user is not None and user.strava_access_token is not None


# Global auth store instance
auth_db = AuthStore()
