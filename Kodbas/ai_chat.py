"""
AI-chatt för träningsplanering.
Använder Claude API för att ge personliga rekommendationer baserat på idrottarens data.
Med guardrails och RAG från övningsbanken.
"""

import os
from datetime import date, timedelta
from typing import Optional
from dataclasses import dataclass, field
from pathlib import Path

# Ladda miljövariabler från .env-fil
def load_env_file():
    """Ladda .env-fil manuellt för att säkerställa att det fungerar."""
    env_paths = [
        Path(__file__).parent / '.env',
        Path('.env'),
    ]

    for env_path in env_paths:
        if env_path.exists():
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if '=' in line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        os.environ[key] = value
            break

load_env_file()

# Försök importera anthropic - om det inte finns, använder vi mock
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except Exception:
    ANTHROPIC_AVAILABLE = False


@dataclass
class ChatMessage:
    """Ett meddelande i chatten."""
    id: int
    athlete_id: int
    role: str  # "user" (coach) eller "assistant" (AI)
    content: str
    timestamp: str
    metadata: dict = field(default_factory=dict)  # För att spara "varför"-info


class AIChat:
    """
    AI-chatt med guardrails för träningsplanering.
    Integrerar med övningsbanken (RAG) och idrottardata.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.client = None

        if self.api_key and ANTHROPIC_AVAILABLE:
            self.client = anthropic.Anthropic(api_key=self.api_key)

        # Chatthistorik per idrottare
        self.chat_histories: dict[int, list[ChatMessage]] = {}
        self.message_counter = 0

        # Guardrails - regler som AI:n måste följa
        self.guardrails = {
            "max_weekly_high_intensity": 3,  # Max 3 hårda pass per vecka
            "min_recovery_hours": 48,  # Minst 48h mellan hårda pass
            "injury_keywords": ["skada", "ont", "smärta", "inflammation"],
            "forbidden_advice": ["medicin", "läkemedel", "diagnos", "behandling"],
        }

    def _build_system_prompt(self, athlete_data: dict, exercises_context: str) -> str:
        """
        Bygg system-prompt med idrottarkontext och guardrails.
        Detta är RAG - vi injicerar relevant data i prompten.
        """

        injuries_text = "Inga aktiva skador"
        if athlete_data.get("injuries"):
            injuries_text = ", ".join([
                f"{inj['body_part']} ({inj['severity']})"
                for inj in athlete_data["injuries"]
            ])

        recent_sessions = "Ingen träningshistorik"
        if athlete_data.get("recent_logs"):
            sessions = []
            for log in athlete_data["recent_logs"][-5:]:
                sessions.append(f"- {log['date']}: {log['session_type']} ({log['duration_minutes']}min, RPE {log['rpe']})")
            recent_sessions = "\n".join(sessions)

        return f"""Du är en AI-assistent för friidrottsträning. Du hjälper coacher med träningsplanering.

## IDROTTARENS DATA
- Namn: {athlete_data.get('name', 'Okänd')}
- Ålder: {athlete_data.get('age', 'Okänd')}
- Disciplin: {athlete_data.get('discipline', 'Okänd')}
- Nivå: {athlete_data.get('level', 'Okänd')}

## BELASTNINGSDATA
- ACWR (Acute:Chronic Workload Ratio): {athlete_data.get('acwr', 'Ej beräknad')}
- Veckobelastning: {athlete_data.get('weekly_load', 0)} (session-RPE)
- Träningsberedskap: {athlete_data.get('readiness', 'Okänd')}

## AKTIVA SKADOR
{injuries_text}

## SENASTE TRÄNINGSPASS
{recent_sessions}

## TILLGÄNGLIGA ÖVNINGAR FRÅN TRÄNINGSBANKEN
{exercises_context}

## DINA REGLER (GUARDRAILS) - FÖLJ ALLTID DESSA:
1. Max {self.guardrails['max_weekly_high_intensity']} högintensiva pass per vecka
2. Minst {self.guardrails['min_recovery_hours']} timmar mellan hårda pass
3. Om ACWR > 1.5: Föreslå ALLTID lättare träning eller vila
4. Om ACWR < 0.8: Kan föreslå ökad belastning gradvis
5. Vid aktiva skador: Undvik övningar som belastar skadade områden
6. GE ALDRIG medicinsk rådgivning - hänvisa till sjukvård vid behov
7. Förklara ALLTID varför du ger ett visst råd

## DITT SVAR
- Svara på svenska
- Var konkret och praktisk
- Inkludera alltid en kort förklaring av ditt resonemang
- Om du föreslår övningar, välj från träningsbanken ovan när möjligt
- Formatera svaret tydligt med punktlistor vid behov"""

    def _get_exercises_context(self, discipline: str) -> str:
        """
        Hämta relevanta övningar från övningsbanken (RAG).
        Filtrerar baserat på disciplin.
        """
        from exercise_bank import EXERCISES

        relevant_exercises = []
        for ex_id, exercise in EXERCISES.items():
            if discipline in exercise.disciplines or "mångkamp" in exercise.disciplines:
                relevant_exercises.append(
                    f"- {exercise.name} ({exercise.category}, {exercise.intensity} intensitet, {exercise.duration_minutes}min)"
                )

        if not relevant_exercises:
            return "Alla standardövningar tillgängliga"

        return "\n".join(relevant_exercises[:15])  # Max 15 övningar för att spara tokens

    def _apply_guardrails(self, response: str, athlete_data: dict) -> tuple[str, list[str]]:
        """
        Applicera guardrails på AI:ns svar.
        Returnerar (modifierat svar, lista med varningar).
        """
        warnings = []

        # Kolla om AI försöker ge medicinsk rådgivning
        for forbidden in self.guardrails["forbidden_advice"]:
            if forbidden.lower() in response.lower():
                warnings.append(f"⚠️ Obs: För medicinsk rådgivning, kontakta sjukvård.")

        # Kolla ACWR
        acwr = athlete_data.get("acwr", 1.0)
        if acwr and acwr > 1.5:
            if "hög" in response.lower() and "intensitet" in response.lower():
                warnings.append("⚠️ ACWR är hög (>1.5). Överväg att minska intensiteten.")

        # Kolla skador
        if athlete_data.get("injuries"):
            injured_parts = [inj["body_part"].lower() for inj in athlete_data["injuries"]]
            for part in injured_parts:
                if part in response.lower():
                    warnings.append(f"⚠️ Observera aktiv skada på {part}.")

        return response, warnings

    def _log_decision(self, athlete_id: int, user_message: str, ai_response: str,
                      athlete_data: dict, warnings: list[str]) -> dict:
        """
        Logga AI-beslut för spårbarhet och utvärdering.
        """
        return {
            "timestamp": date.today().isoformat(),
            "athlete_id": athlete_id,
            "input": {
                "user_message": user_message[:100],  # Trunkera för lagring
                "acwr": athlete_data.get("acwr"),
                "injuries": bool(athlete_data.get("injuries")),
                "discipline": athlete_data.get("discipline"),
            },
            "output": {
                "response_length": len(ai_response),
                "warnings_triggered": warnings,
            }
        }

    def chat(self, athlete_id: int, user_message: str, athlete_data: dict) -> dict:
        """
        Skicka ett meddelande och få svar från AI.

        Returns:
            dict med:
            - response: AI:ns svar
            - warnings: Lista med varningar från guardrails
            - reasoning: Kort förklaring av beslut
            - decision_log: Loggdata för utvärdering
        """

        # Initiera chatthistorik om den inte finns
        if athlete_id not in self.chat_histories:
            self.chat_histories[athlete_id] = []

        # Hämta övningskontext (RAG)
        exercises_context = self._get_exercises_context(
            athlete_data.get("discipline", "mångkamp")
        )

        # Bygg system-prompt
        system_prompt = self._build_system_prompt(athlete_data, exercises_context)

        # Bygg meddelandehistorik för API
        messages = []
        for msg in self.chat_histories[athlete_id][-10:]:  # Max 10 tidigare meddelanden
            messages.append({
                "role": msg.role,
                "content": msg.content
            })
        messages.append({"role": "user", "content": user_message})

        # Anropa API eller använd mock
        if self.client:
            try:
                response = self.client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=1024,
                    system=system_prompt,
                    messages=messages
                )
                ai_response = response.content[0].text
            except Exception as e:
                ai_response = f"⚠️ Kunde inte ansluta till AI: {str(e)}\n\nKontrollera din API-nyckel."
        else:
            # Mock-svar när API inte är tillgängligt
            ai_response = self._generate_mock_response(user_message, athlete_data)

        # Applicera guardrails
        ai_response, warnings = self._apply_guardrails(ai_response, athlete_data)

        # Logga beslut
        decision_log = self._log_decision(
            athlete_id, user_message, ai_response, athlete_data, warnings
        )

        # Spara meddelanden i historik
        self.message_counter += 1
        user_msg = ChatMessage(
            id=self.message_counter,
            athlete_id=athlete_id,
            role="user",
            content=user_message,
            timestamp=date.today().isoformat()
        )
        self.chat_histories[athlete_id].append(user_msg)

        self.message_counter += 1
        assistant_msg = ChatMessage(
            id=self.message_counter,
            athlete_id=athlete_id,
            role="assistant",
            content=ai_response,
            timestamp=date.today().isoformat(),
            metadata={"warnings": warnings, "decision_log": decision_log}
        )
        self.chat_histories[athlete_id].append(assistant_msg)

        return {
            "response": ai_response,
            "warnings": warnings,
            "reasoning": self._extract_reasoning(ai_response),
            "decision_log": decision_log
        }

    def _generate_mock_response(self, user_message: str, athlete_data: dict) -> str:
        """
        Generera ett regelbaserat mock-svar när API inte är tillgängligt.
        Visar hur systemet fungerar utan att kosta pengar.
        """
        name = athlete_data.get("name", "idrottaren")
        acwr = athlete_data.get("acwr", 1.0)
        discipline = athlete_data.get("discipline", "friidrott")
        injuries = athlete_data.get("injuries", [])

        # Analysera meddelandet för att ge relevant svar
        message_lower = user_message.lower()

        if "träna" in message_lower or "pass" in message_lower or "vecka" in message_lower:
            # Träningsrekommendation
            if acwr and acwr > 1.5:
                intensity_rec = "lätt till medel"
                reason = f"ACWR är {acwr:.2f} vilket är över 1.5 - kroppen behöver återhämtning"
            elif acwr and acwr < 0.8:
                intensity_rec = "medel till hög"
                reason = f"ACWR är {acwr:.2f} vilket är under 0.8 - det finns utrymme att öka belastningen"
            else:
                intensity_rec = "medel"
                reason = f"ACWR är {acwr:.2f} vilket är i den optimala zonen (0.8-1.3)"

            injury_note = ""
            if injuries:
                injury_parts = [inj["body_part"] for inj in injuries]
                injury_note = f"\n\n⚠️ **Observera skador:** {', '.join(injury_parts)}. Undvik övningar som belastar dessa områden."

            return f"""## Träningsrekommendation för {name}

**Rekommenderad intensitet:** {intensity_rec}

**Motivering:** {reason}

**Förslag för {discipline}:**
- Uppvärmning: 10-15 min lätt jogging + dynamisk stretching
- Huvudpass: Anpassa efter dagens fokus
- Nedvarvning: 10 min lätt löpning + stretching
{injury_note}

---
*💡 Detta är ett regelbaserat förslag. Med API-nyckel får du mer personliga rekommendationer.*"""

        elif "skada" in message_lower or "ont" in message_lower:
            return f"""## Angående skador

Jag ser att du undrar om skaderelaterade frågor.

**Aktiva skador för {name}:**
{chr(10).join([f"- {inj['body_part']} ({inj['severity']})" for inj in injuries]) if injuries else "- Inga registrerade skador"}

**Generella råd:**
- Undvik övningar som provocerar smärta
- Gradvis återgång till full belastning
- Vid osäkerhet: konsultera sjukvårdspersonal

⚠️ *Jag kan inte ge medicinsk rådgivning. För bedömning av skador, kontakta legitimerad vårdpersonal.*

---
*💡 Med API-nyckel kan jag ge mer detaljerade anpassningar.*"""

        elif "kost" in message_lower or "mat" in message_lower or "äta" in message_lower:
            return f"""## Kostråd

**Generella riktlinjer för {discipline}:**
- Ät 2-3 timmar innan träning
- Drick tillräckligt med vatten
- Återhämtningsmåltid inom 30-60 min efter träning
- Balanserad kost med protein, kolhydrater och fett

**Inför tävling:**
- Kolhydratladda 2-3 dagar innan
- Undvik nya livsmedel på tävlingsdagen
- Lätt måltid 3-4 timmar före start

---
*💡 Med API-nyckel kan jag ge mer personliga kostråd baserat på träningsdata.*"""

        else:
            return f"""## AI-assistent för {name}

Jag hjälper gärna med:
- 📅 **Träningsplanering** - "Vad bör {name} träna denna vecka?"
- 🏃 **Passförslag** - "Föreslå ett teknikpass för {discipline}"
- 🤕 **Skadeanpassning** - "Hur tränar vi runt fotledsskadan?"
- 🍎 **Kostråd** - "Vad bör hen äta inför tävling?"
- 📊 **Belastningsanalys** - "Är träningsbelastningen rimlig?"

**Nuvarande status:**
- ACWR: {acwr:.2f if acwr else 'Ej beräknad'}
- Skador: {len(injuries)} aktiva

Ställ din fråga så hjälper jag dig!

---
*💡 OBS: API-nyckel saknas. Du ser regelbaserade svar. Med API-nyckel får du AI-genererade personliga svar.*"""

    def _extract_reasoning(self, response: str) -> str:
        """Extrahera resonemang/motivering från svaret."""
        # Försök hitta motivering i svaret
        if "motivering:" in response.lower():
            parts = response.lower().split("motivering:")
            if len(parts) > 1:
                return parts[1].split("\n")[0].strip()[:200]

        if "därför" in response.lower():
            return "Se förklaring i svaret ovan."

        return "Baserat på idrottarens data och träningshistorik."

    def get_chat_history(self, athlete_id: int) -> list[dict]:
        """Hämta chatthistorik för en idrottare."""
        if athlete_id not in self.chat_histories:
            return []

        return [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp,
                "warnings": msg.metadata.get("warnings", [])
            }
            for msg in self.chat_histories[athlete_id]
        ]

    def clear_chat_history(self, athlete_id: int):
        """Rensa chatthistorik för en idrottare."""
        if athlete_id in self.chat_histories:
            self.chat_histories[athlete_id] = []


# Global instans
ai_chat = AIChat()
