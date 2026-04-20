"""
Autentisering och användarsystem.
Hanterar inloggning, registrering och roller (coach/idrottare).
"""

from dataclasses import dataclass, field
from typing import Optional
import hashlib
import secrets
import string

from database import get_connection, init_db


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
        init_db()
        self._load_demo_users()

    def _row_to_user(self, row) -> Optional[User]:
        if not row:
            return None
        return User(
            id=row["id"],
            email=row["email"],
            password_hash=row["password_hash"],
            name=row["name"],
            role=row["role"],
            coach_code=row["coach_code"],
            connected_coach_id=row["connected_coach_id"],
        )

    def _generate_coach_code(self) -> str:
        """Generera en unik coach-kod (t.ex. ANNA-7X3K)."""
        chars = string.ascii_uppercase + string.digits
        code = ''.join(secrets.choice(chars) for _ in range(4))
        return code

    def _load_demo_users(self):
        """Skapa demo-användare för test."""
        if self.login("coach@demo.se", "demo123"):
            return

        # Demo coach
        coach = self.register(
            email="coach@demo.se",
            password="demo123",
            name="Demo Coach",
            role="coach"
        )

        # Demo idrottare (kopplade till coach)
        # Ordningen matchar user_ids i app.py init_demo_data
        athletes_data = [
            ("ebba@demo.se", "Ebba 3"),              # user_id 2 - demo för Garmin-tempomodell
            ("hugo@demo.se", "Hugo Kündig"),         # user_id 3 - demo för tävlingsresultat
            ("daniel@demo.se", "Daniel"),            # user_id 4 - demo för Garmin-tempomodell
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
        if self.get_user_by_email(email):
            return None

        # Skapa coach-kod om det är en coach
        coach_code = None
        if role == "coach":
            coach_code = self._generate_coach_code()
            # Se till att koden är unik
            while self.get_coach_by_code(coach_code):
                coach_code = self._generate_coach_code()

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (email, password_hash, name, role, coach_code, connected_coach_id)
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (email.lower(), User._hash_password(password), name, role, coach_code),
        )
        user_id = cur.lastrowid
        conn.commit()
        conn.close()
        return self.get_user(user_id)

    def login(self, email: str, password: str) -> Optional[User]:
        """Logga in en användare."""
        user = self.get_user_by_email(email)
        if user and user.check_password(password):
            return user
        return None

    def get_user(self, user_id: int) -> Optional[User]:
        """Hämta användare via ID."""
        conn = get_connection()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        return self._row_to_user(row)

    def get_user_by_email(self, email: str) -> Optional[User]:
        conn = get_connection()
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
        conn.close()
        return self._row_to_user(row)

    def delete_user(self, user_id: int) -> bool:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
        deleted = cur.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def get_coach_by_code(self, code: str) -> Optional[User]:
        """Hitta en coach via deras coach-kod."""
        code = code.upper().strip()
        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM users WHERE role = 'coach' AND coach_code = ?",
            (code,),
        ).fetchone()
        conn.close()
        return self._row_to_user(row)

    def connect_athlete_to_coach(self, athlete_id: int, coach_code: str) -> bool:
        """Koppla en idrottare till en coach via coach-kod."""
        athlete = self.get_user(athlete_id)
        coach = self.get_coach_by_code(coach_code)

        if not athlete or not coach:
            return False

        if not athlete.is_athlete() or not coach.is_coach():
            return False

        conn = get_connection()
        conn.execute(
            "UPDATE users SET connected_coach_id = ? WHERE id = ?",
            (coach.id, athlete.id),
        )
        conn.commit()
        conn.close()
        return True

    def get_athletes_for_coach(self, coach_id: int) -> list[User]:
        """Hämta alla idrottare kopplade till en coach."""
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM users WHERE role = 'athlete' AND connected_coach_id = ? ORDER BY name",
            (coach_id,),
        ).fetchall()
        conn.close()
        return [self._row_to_user(row) for row in rows]

    def get_coach_for_athlete(self, athlete_id: int) -> Optional[User]:
        """Hämta coachen för en idrottare."""
        athlete = self.get_user(athlete_id)
        if not athlete or not athlete.connected_coach_id:
            return None
        return self.get_user(athlete.connected_coach_id)


# Global auth store instance
auth_db = AuthStore()
