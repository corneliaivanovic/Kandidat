"""
RAG-modul (Retrieval Augmented Generation) för träningsplattformen.

Laddar utbildningsmaterial från PDF-extraherade textfiler,
delar upp i chunks, söker med TF-IDF, och använder Claude API
för att generera kunskapsbaserade träningspass.

Kunskapskällor (väljs per genereringstillfälle):
- Löptränare utbildningsmaterial (2025)       ← primär källa för löpning
- Friidrottens allmänna träningslära (2017)
- Träning i uppbyggnadsstadiet - Medel- och långdistans
"""

import os
import re
import json
from pathlib import Path
from typing import Optional
from datetime import date as _date
from collections import Counter

import numpy as np
import anthropic


# ============================================================
# KONFIGURATION
# ============================================================

KNOWLEDGE_BASE_DIR = os.path.join(os.path.dirname(__file__), "knowledge_base")

CHUNK_SIZE    = 800
CHUNK_OVERLAP = 150
TOP_K         = 5

# Dokument som kan väljas i UI — nyckel används som form-värde
DOCUMENT_REGISTRY = {
    "loptranare": {
        "filename":    "loptranare_2025.txt",
        "title":       "Löptränare (2025)",
        "description": "Specifik löpträning, 80/20-regeln, periodisering, intensitetszoner",
    },
    "friidrottslara": {
        "filename":    "friidrottens_tranlara.txt",
        "title":       "Friidrottens träningslära (2017)",
        "description": "Allmän träningsteori, belastningsprinciper, friidrott",
    },
    "uppbyggnad": {
        "filename":    "uppbyggnad_medel_lang.txt",
        "title":       "Träning i uppbyggnadsstadiet",
        "description": "Medel- och långdistans i uppbyggnadsfasen",
    },
}

# Standardval: alla tre dokument
DEFAULT_DOCUMENTS = list(DOCUMENT_REGISTRY.keys())

DISCIPLINE_DEFAULT_DOCUMENTS = {
    "sprint": ["loptranare", "friidrottslara"],
    "medel": ["loptranare", "friidrottslara", "uppbyggnad"],
    "distans": ["loptranare", "friidrottslara", "uppbyggnad"],
}

SEARCH_PROFILES = {
    "week": {
        "veckostruktur": [
            "{discipline} {phase} träningsplanering veckoschema",
            "{discipline} mikrocykel veckostruktur löpning",
        ],
        "nyckelpass": [
            "{discipline} intervallträning uthållighet nyckelpass",
            "{discipline} kvalitetspass tävlingsfart tröskel vo2",
        ],
        "återhämtning": [
            "återhämtning vilodag hard easy polariserad löpning",
            "{phase} återhämtning lätt distanslöpning zon 1 zon 2",
        ],
        "teknik": [
            "{discipline} löpteknik löpskola stegfrekvens avslappning",
        ],
        "periodisering": [
            "{phase} intensitetszoner 80 20 tröskelträning",
        ],
    },
    "month": {
        "periodisering": [
            "{discipline} {phase} periodisering månadsplanering",
            "{discipline} veckoschema progression mesocykel",
        ],
        "nyckelpass": [
            "{phase} intervallträning tröskelträning nyckelpass",
            "{discipline} specifika nyckelpass tävlingsförberedelse",
        ],
        "återhämtning": [
            "återhämtning 80 20 intensitetszoner polariserad löpning",
            "hard easy principen mikroperiodisering friidrott",
        ],
        "teknik": [
            "{discipline} löpteknik teknikpass löpning",
        ],
    },
}

# Mappning filnamn → titeln som sparas i metadata
SOURCE_METADATA = {
    doc["filename"]: {"title": doc["title"], "key": key}
    for key, doc in DOCUMENT_REGISTRY.items()
}

# ============================================================
# GUARDRAIL-KONSTANTER  (grundade i löptränare-PDF:en)
# ============================================================

# Guardrail 1 — 80/20-regeln (Seiler, loptranare_2025 ~rad 1226)
MAX_HARD_RATIO = 0.20          # Max 20 % av passen får vara hårda

# Guardrail 3 — Fasspecifikt max antal hårda pass per vecka
PHASE_MAX_HARD = {
    "grundträning": 1,   # Aerob bas — minimal intensitet
    "uppbyggnad":   2,   # Bygge — max 2 hårda
    "tävling":      2,   # Specifik fart — max 2 hårda, lägre volym
    "återhämtning": 0,   # Noll hårda pass
}

# Guardrail 3 — Vecka 4 alltid återhämtningsvecka med 50–70 % volym
# (loptranare_2025 rad 1178: "Var fjärde vecka: återhämtningsvecka med 50–70 % volym")
RECOVERY_WEEK_VOLUME_FACTOR = 0.60   # 60 % — mitt i 50–70 %-spannet

# Guardrail 5 — Åldersanpassning (loptranare_2025 rad 940–970)
# Tre nivåer baserade direkt på PDF:ens indelning:
#   Barn ca 6–12 år:      lek/teknik, max 3 pass/v, inga hårda pass
#   Ungdomar ca 13–17 år: strukturerad men variation, max 1 hårt pass, teknik obligatoriskt
#   Vuxna 18+:            normala regler gäller

CHILD_MAX_AGE  = 12   # Barn: 12 år eller yngre
YOUTH_MAX_AGE  = 17   # Ungdomar: 13–17 år

# Guardrail 2 — Pass-roller (minst 2 olika roller per vecka)
SESSION_ROLES = ["kvalitet", "volym", "återhämtning", "teknik"]


def _ideal_hard_cap(total_sessions: int) -> int:
    """Basnivå för 80/20-principen, avrundad till en praktisk veckogräns."""
    if total_sessions <= 0:
        return 0
    return max(1, int(round(total_sessions * MAX_HARD_RATIO)))


def _effective_hard_cap(total_sessions: int, phase: str, birth_year: int = 2000) -> tuple[int, int]:
    """
    Returnera (tillåtet_max, ideal_max) för hårda pass.

    80/20 behålls som princip via ideal_max, men små veckor och vissa faser
    får begränsad flexibilitet för att undvika onödiga fallback-planer.
    """
    age_group = _get_age_group(birth_year)
    phase_cap = PHASE_MAX_HARD.get(phase, 2)

    if age_group == "barn":
        return 0, 0
    if age_group == "ungdom":
        phase_cap = min(phase_cap, 1)

    ideal_cap = _ideal_hard_cap(total_sessions)
    phase_flex = 0
    if phase in {"uppbyggnad", "tävling"} and total_sessions >= 5:
        phase_flex = 1

    effective_cap = min(phase_cap, ideal_cap + phase_flex)
    if phase != "återhämtning" and total_sessions > 0:
        effective_cap = max(1, effective_cap)

    return effective_cap, ideal_cap


def _get_age_group(birth_year: int) -> str:
    """
    Räknar ut åldersgrupp baserat på årets datum.
    Returnerar 'barn', 'ungdom' eller 'vuxen'.
    Fungerar korrekt oavsett vilket år koden körs.
    """
    age = _date.today().year - birth_year
    if age <= CHILD_MAX_AGE:
        return "barn"
    elif age <= YOUTH_MAX_AGE:
        return "ungdom"
    else:
        return "vuxen"


# ============================================================
# CHUNKING
# ============================================================

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Dela upp text i överlappande chunks vid meningsgränser."""
    text = re.sub(r'--- Sida \d+ ---', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end < len(text):
            bp = text.rfind('.', start + chunk_size // 2, end)
            if bp == -1:
                bp = text.rfind('\n', start + chunk_size // 2, end)
            if bp > start:
                end = bp + 1
        chunk = text[start:end].strip()
        if len(chunk) > 50:
            chunks.append(chunk)
        start = end - overlap

    return chunks


def get_default_doc_keys_for_discipline(discipline: str) -> list[str]:
    """Returnera standarddokument för en löpdisciplin."""
    return list(DISCIPLINE_DEFAULT_DOCUMENTS.get(discipline, DEFAULT_DOCUMENTS))


def resolve_allowed_doc_keys(allowed_doc_keys: Optional[list[str]], discipline: str) -> list[str]:
    """
    Normalisera dokumenturvalet.
    Om användaren inte gjort ett tydligt val används disciplinens standardurval.
    """
    if not allowed_doc_keys:
        return get_default_doc_keys_for_discipline(discipline)

    normalized = [k for k in allowed_doc_keys if k in DOCUMENT_REGISTRY]
    if not normalized:
        return get_default_doc_keys_for_discipline(discipline)

    # Legacy-default: gamla idrottare har ofta "alla dokument" sparat som standardval.
    if set(normalized) == set(DEFAULT_DOCUMENTS):
        return get_default_doc_keys_for_discipline(discipline)

    return normalized


def load_knowledge_base() -> tuple[list[str], list[dict]]:
    """Ladda alla textfiler från knowledge_base-mappen."""
    all_chunks, all_metadata = [], []

    if not os.path.exists(KNOWLEDGE_BASE_DIR):
        print(f"⚠️ Knowledge base directory not found: {KNOWLEDGE_BASE_DIR}")
        return [], []

    for key, doc in DOCUMENT_REGISTRY.items():
        filename = doc["filename"]
        filepath = os.path.join(KNOWLEDGE_BASE_DIR, filename)
        if not os.path.exists(filepath):
            print(f"⚠️ Knowledge base file saknas för '{key}': {filepath}")
            continue

        with open(filepath, 'r', encoding='utf-8') as f:
            text = f.read()

        source_info = SOURCE_METADATA.get(filename, {"title": filename, "key": filename})
        chunks = chunk_text(text)
        for i, chunk in enumerate(chunks):
            all_chunks.append(chunk)
            all_metadata.append({
                "source":      source_info["title"],
                "source_key":  source_info["key"],
                "filename":    filename,
                "chunk_index": i,
                "total_chunks": len(chunks),
            })

    print(f"📚 Kunskapsbas laddad: {len(all_chunks)} chunks från {len(set(m['filename'] for m in all_metadata))} dokument")
    return all_chunks, all_metadata


# ============================================================
# EMBEDDINGS-SÖKNING MED DOKUMENTFILTER
# ============================================================

class KnowledgeRetriever:
    """Embeddings-baserad semantisk sökning med valfritt dokumentfilter."""

    EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self):
        self.chunks      = []
        self.metadata    = []
        self.model       = None
        self.embeddings  = None   # numpy-array (n_chunks, dim)
        self._initialized = False

    def initialize(self):
        if self._initialized:
            return
        self.chunks, self.metadata = load_knowledge_base()
        if not self.chunks:
            self._initialized = True
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            print("⚠️ sentence-transformers saknas. Installera med: pip install sentence-transformers")
            self._initialized = True
            return

        print(f"🧠 Laddar embeddingsmodell '{self.EMBEDDING_MODEL}'...")
        self.model = SentenceTransformer(self.EMBEDDING_MODEL)
        print(f"   Genererar embeddings för {len(self.chunks)} chunks...")
        self.embeddings = self.model.encode(
            self.chunks,
            show_progress_bar=False,
            batch_size=64,
            convert_to_numpy=True,
        )
        # Normalisera en gång (gör cosine similarity till en enkel matrisgångersättning)
        norms = np.linalg.norm(self.embeddings, axis=1, keepdims=True) + 1e-10
        self.embeddings = self.embeddings / norms
        self._initialized = True
        print(f"✅ Embeddings-index byggt: {self.embeddings.shape[0]} chunks, dim {self.embeddings.shape[1]}")

    def search(self, query: str, top_k: int = TOP_K,
               allowed_doc_keys: list[str] = None) -> list[dict]:
        """
        Sök i kunskapsbasen med semantisk likhet (cosine similarity via embeddings).

        Args:
            query:            Sökfråga
            top_k:            Max antal resultat
            allowed_doc_keys: Lista med dokumentnycklar att inkludera,
                              t.ex. ["loptranare"]. None = alla dokument.
        """
        if not self._initialized:
            self.initialize()
        if not self.chunks or self.model is None or self.embeddings is None:
            return []

        # Koda frågan och normalisera
        q_emb  = self.model.encode([query], convert_to_numpy=True)
        q_norm = q_emb / (np.linalg.norm(q_emb, axis=1, keepdims=True) + 1e-10)

        # Cosine similarity = skalärprodukt (chunks är redan normaliserade)
        similarities = (self.embeddings @ q_norm.T).flatten()

        # Hämta fler än top_k för att klara bortfiltrering vid dokumentfilter
        candidate_indices = similarities.argsort()[-(top_k * 4):][::-1]

        results = []
        for idx in candidate_indices:
            if similarities[idx] <= 0.0:
                continue
            meta = self.metadata[idx]
            # Filtrera på dokumentnyckel om angiven
            if allowed_doc_keys is not None and meta["source_key"] not in allowed_doc_keys:
                continue
            results.append({
                "text":        self.chunks[idx],
                "score":       float(similarities[idx]),
                "source":      meta["source"],
                "source_key":  meta["source_key"],
                "chunk_index": meta["chunk_index"],
            })
            if len(results) >= top_k:
                break

        return results


# ============================================================
# HÅRDA REGLER — GUARDRAILS
# ============================================================

def review_week_plan(sessions: list[dict], phase: str = "uppbyggnad",
                     birth_year: int = 2000) -> dict:
    """
    Kontrollera ett veckoschema och skilj på blockerande fel och mjuka varningar.
    """
    blocking_errors = []
    soft_warnings = []
    normalized_sessions = sessions or []
    if not normalized_sessions:
        return {
            "blocking_errors": ["⚠️ Inga pass genererades"],
            "soft_warnings": [],
            "normalized_sessions": [],
            "summary": {"hard_count": 0, "total_sessions": 0, "age_group": _get_age_group(birth_year)},
        }

    difficulties = [s.get("difficulty", "medium") for s in normalized_sessions]
    roles = [s.get("role", "volym") for s in normalized_sessions]
    hard_count = difficulties.count("hard")
    total = len(normalized_sessions)
    unique_names = {s.get("name", "").strip().lower() for s in normalized_sessions if s.get("name")}
    age_group = _get_age_group(birth_year)
    effective_hard_cap, ideal_hard_cap = _effective_hard_cap(total, phase, birth_year)

    if total > 0 and hard_count > ideal_hard_cap:
        soft_warnings.append(
            f"⚠️ G1 80/20: {hard_count}/{total} pass är hårda ({hard_count/total:.0%}). "
            f"Det accepteras tillfälligt i fas '{phase}', men ligger över idealnivån på {ideal_hard_cap}."
        )

    unique_roles = set(roles)
    if len(unique_roles) < 2:
        soft_warnings.append(
            f"⚠️ G2 Variation: Bara {unique_roles} — behöver minst 2 olika passroller"
        )

    phase_max = PHASE_MAX_HARD.get(phase, 2)
    if hard_count > phase_max:
        blocking_errors.append(
            f"⚠️ G3 Fastak: {hard_count} hårda pass men fas '{phase}' tillåter max {phase_max}"
        )

    volume_profile = _summarize_month_intensity_balance([{"sessions": normalized_sessions}])
    week_medium_ratio = volume_profile["ratios"]["medium"]
    if week_medium_ratio > 0.40:
        soft_warnings.append(
            f"⚠️ G4 Mellanzon: veckan innehåller {week_medium_ratio:.0%} medelintensiv volym, vilket är högt"
        )
    elif week_medium_ratio > 0.28:
        soft_warnings.append(
            f"⚠️ G4 Mellanzon: veckan innehåller {week_medium_ratio:.0%} medelintensiv volym; håll mer av arbetet lågintensivt"
        )

    if age_group == "barn":
        if hard_count > 0:
            blocking_errors.append(
                f"⚠️ G5 Barn: {hard_count} hårda pass — barn ska ha noll hårda pass"
            )
        if "teknik" not in roles:
            blocking_errors.append("⚠️ G5 Barn: Saknar teknikpass — obligatoriskt för barn")
        if len(normalized_sessions) > 3:
            blocking_errors.append(f"⚠️ G5 Barn: {len(normalized_sessions)} pass — barn bör ha max 3 pass/vecka")
    elif age_group == "ungdom":
        if hard_count > 1:
            blocking_errors.append(
                f"⚠️ G5 Ungdom: {hard_count} hårda pass — max 1 för ungdomar (13–17 år)"
            )
        if "teknik" not in roles:
            blocking_errors.append("⚠️ G5 Ungdom: Saknar teknikpass — obligatoriskt för ungdomar")

    # G6: Nyckelpass — gäller ej återhämtningsveckor (de har inga hårda pass)
    if phase != "återhämtning":
        key_sessions = [s for s in normalized_sessions if s.get("is_key_session", False)]
        if len(key_sessions) != 1:
            blocking_errors.append("⚠️ G6 Nyckelpass: Det måste finnas exakt ett nyckelpass")

    is_recovery_phase = phase == "återhämtning"

    for i, s in enumerate(normalized_sessions):
        difficulty = s.get("difficulty")
        desc = (s.get("description") or "").lower()
        if not desc:
            if is_recovery_phase and difficulty != "hard":
                soft_warnings.append(f"⚠️ Pass {i+1} ({s.get('name','?')}): Saknar beskrivning")
            else:
                blocking_errors.append(f"⚠️ Pass {i+1} ({s.get('name','?')}): Saknar beskrivning")
            continue

        if "syfte:" not in desc:
            if not is_recovery_phase or difficulty == "hard":
                soft_warnings.append(f"⚠️ Pass {i+1} ({s.get('name','?')}): Saknar tydligt syfte")
        if "uppvärmning" not in desc:
            if difficulty == "hard":
                blocking_errors.append(f"⚠️ G7 Pass {i+1} ({s.get('name','?')}): Saknar uppvärmning")
            elif not is_recovery_phase:
                soft_warnings.append(f"⚠️ Pass {i+1} ({s.get('name','?')}): Saknar uppvärmning")
        if "nedvarvning" not in desc and "nedjogg" not in desc:
            if difficulty == "hard":
                blocking_errors.append(f"⚠️ G7 Pass {i+1} ({s.get('name','?')}): Saknar nedvarvning")
            elif not is_recovery_phase:
                soft_warnings.append(f"⚠️ Pass {i+1} ({s.get('name','?')}): Saknar nedvarvning")
        if "vila" not in desc and difficulty in {"hard", "medium"} and not (is_recovery_phase and difficulty == "medium"):
            soft_warnings.append(f"⚠️ Pass {i+1} ({s.get('name','?')}): Saknar tydlig vila/intensitetsstyrning")

    for i in range(len(difficulties) - 1):
        if difficulties[i] == "hard" and difficulties[i + 1] != "easy":
            blocking_errors.append(
                f"⚠️ G8 Hard–easy: Pass {i+1} är hårt men pass {i+2} är '{difficulties[i+1]}'"
            )

    if len(unique_names) < max(1, total - 1):
        soft_warnings.append("⚠️ Flera pass har samma eller nästan samma namn")

    return {
        "blocking_errors": blocking_errors,
        "soft_warnings": soft_warnings,
        "normalized_sessions": normalized_sessions,
            "summary": {
            "hard_count": hard_count,
            "total_sessions": total,
            "age_group": age_group,
            "role_counts": dict(Counter(roles)),
            "effective_hard_cap": effective_hard_cap,
            "ideal_hard_cap": ideal_hard_cap,
            "week_medium_ratio": week_medium_ratio,
        },
    }


def validate_week_plan(sessions: list[dict], phase: str = "uppbyggnad",
                       birth_year: int = 2000) -> list[str]:
    """Bakåtkompatibel wrapper som returnerar alla varningar/fel som en lista."""
    review = review_week_plan(sessions, phase=phase, birth_year=birth_year)
    return review["blocking_errors"] + review["soft_warnings"]


def apply_hard_rules_to_structure(days_per_week: int, phase: str,
                                  birth_year: int = 2000) -> list[dict]:
    """
    Skapa en garanterat regelenlig veckostruktur.
    Alla 8 guardrails är inbyggda i strukturen.

    Returns:
        Lista med {day, difficulty, role, is_key_session}
    """
    age_group = _get_age_group(birth_year)
    phase_max = PHASE_MAX_HARD.get(phase, 2)

    # Guardrail 5: Åldersanpassning av max hårda pass
    if age_group == "barn":
        phase_max = 0   # Barn: noll hårda pass
    elif age_group == "ungdom":
        phase_max = min(phase_max, 1)  # Ungdomar: max 1 hårt pass

    # Basmönster per antal dagar
    # Guardrail 8: hårt → lätt alltid (inte hårt → medium)
    # Guardrail 2: minst 2 roller (kvalitet + volym/återhämtning)
    # Guardrail 6: första hårda = nyckelpass
    base_structures = {
        3: [
            {"day": "Måndag",   "difficulty": "easy",   "role": "volym"},
            {"day": "Onsdag",   "difficulty": "hard",   "role": "kvalitet",     "is_key_session": True},
            {"day": "Fredag",   "difficulty": "easy",   "role": "återhämtning"},
        ],
        4: [
            {"day": "Måndag",   "difficulty": "hard",   "role": "kvalitet",     "is_key_session": True},
            {"day": "Tisdag",   "difficulty": "easy",   "role": "återhämtning"},  # G8: lätt efter hårt
            {"day": "Torsdag",  "difficulty": "medium", "role": "volym"},
            {"day": "Lördag",   "difficulty": "hard",   "role": "kvalitet"},
        ],
        5: [
            {"day": "Måndag",   "difficulty": "hard",   "role": "kvalitet",     "is_key_session": True},
            {"day": "Tisdag",   "difficulty": "easy",   "role": "återhämtning"},  # G8
            {"day": "Onsdag",   "difficulty": "medium", "role": "volym"},
            {"day": "Fredag",   "difficulty": "hard",   "role": "kvalitet"},
            {"day": "Lördag",   "difficulty": "easy",   "role": "återhämtning"},  # G8
        ],
        6: [
            {"day": "Måndag",   "difficulty": "hard",   "role": "kvalitet",     "is_key_session": True},
            {"day": "Tisdag",   "difficulty": "easy",   "role": "återhämtning"},  # G8
            {"day": "Onsdag",   "difficulty": "medium", "role": "volym"},
            {"day": "Torsdag",  "difficulty": "easy",   "role": "återhämtning"},
            {"day": "Fredag",   "difficulty": "hard",   "role": "kvalitet"},
            {"day": "Lördag",   "difficulty": "easy",   "role": "volym"},          # G8: lätt efter hårt
        ],
    }

    structure = [dict(s) for s in base_structures.get(days_per_week, base_structures[4])]

    # Guardrail 3: Fasspecifikt tak — om fas tillåter 0–1 hårda, skriv om
    hard_slots = [s for s in structure if s["difficulty"] == "hard"]
    effective_hard_cap, _ = _effective_hard_cap(len(structure), phase, birth_year)

    if phase_max == 0:
        # Återhämtning: alla hard → easy
        for s in structure:
            if s["difficulty"] == "hard":
                s["difficulty"] = "easy"
                s["role"] = "återhämtning"
            s.pop("is_key_session", None)

    elif len(hard_slots) > effective_hard_cap:
        # Behåll första hårda pass upp till tillåtet tak, skriv om resten
        first_hard_found = False
        kept_hard = 0
        for s in structure:
            if s["difficulty"] == "hard":
                if kept_hard < effective_hard_cap:
                    kept_hard += 1
                    first_hard_found = True
                    s["is_key_session"] = kept_hard == 1
                else:
                    s["difficulty"] = "medium"
                    s["role"] = "volym"
                    s.pop("is_key_session", None)

    # Guardrail 5: Åldersanpassning av passroller
    if age_group == "barn":
        # Barn: alla pass → teknik/lek, max 3 pass totalt
        for s in structure[:3]:
            s["difficulty"] = "easy"
            s["role"] = "teknik"
            s.pop("is_key_session", None)
        structure = structure[:3]  # Max 3 pass för barn
    elif age_group == "ungdom":
        # Ungdomar: ett teknikpass ersätter ett medelpass
        for s in structure:
            if s["difficulty"] == "medium" and s.get("role") != "teknik":
                s["role"] = "teknik"
                break

    # Guardrail 3 (vecka 4): Återhämtningsvecka reducerar antalet pass med ~40 %
    # Kallas med phase=="återhämtning" — redan hanterat ovan (0 hårda)
    # Volymreduktionen (50–70 %) skickas som instruktion i promtpen

    # Sätt is_key_session=False som default om inte satt
    for s in structure:
        s.setdefault("is_key_session", False)

    return structure


# ============================================================
# CLAUDE API
# ============================================================

def get_claude_client() -> Optional[anthropic.Anthropic]:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    api_key  = os.environ.get('ANTHROPIC_API_KEY')

    if not api_key and os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if line.startswith('ANTHROPIC_API_KEY='):
                    api_key = line.strip().split('=', 1)[1]
                    os.environ['ANTHROPIC_API_KEY'] = api_key
                    break

    if not api_key:
        print("⚠️ ANTHROPIC_API_KEY saknas i .env")
        return None

    import httpx
    return anthropic.Anthropic(api_key=api_key, http_client=httpx.Client(verify=False))


def _humanize_api_failure(reason: str) -> str:
    """Översätt tekniska AI-/API-fel till begriplig svenska."""
    text = (reason or "").strip()
    lower = text.lower()

    if "api-nyckel" in lower and "saknas" in lower:
        return "AI-generering kunde inte användas eftersom API-nyckeln saknas."
    if "invalid x-api-key" in lower or "authentication_error" in lower or "401" in lower:
        return "AI-generering kunde inte användas eftersom API-nyckeln är ogiltig."
    if "credit balance is too low" in lower or "credits" in lower or "billing" in lower:
        return "AI-generering kunde inte användas eftersom Anthropic-krediter saknas."
    if "timed out" in lower or "timeout" in lower:
        return "AI-generering kunde inte användas eftersom API-anropet tog för lång tid."
    if "connection" in lower or "network" in lower or "dns" in lower:
        return "AI-generering kunde inte användas på grund av nätverksfel."
    if "ai-svaret kunde inte tolkas" in lower or "kunde inte parsa" in lower:
        return text or "AI-generering misslyckades eftersom svaret från modellen inte kunde tolkas."
    if "kvalitetssäkras" in lower and "vecka" in text.lower():
        return text
    if "blocking_errors" in lower:
        return "AI-genereringen stoppades eftersom planen bröt mot blockerande kvalitetsregler."
    if "guardrails" in lower:
        return text or "AI-genereringen stoppades eftersom planen bröt mot viktiga guardrails."
    if "kvalitetssäkras" in lower:
        return text or "AI-genereringen stoppades eftersom planen inte kunde kvalitetssäkras."
    if "claude-klient saknas" in lower:
        return "AI-generering kunde inte användas eftersom API-nyckeln saknas."

    return text or "AI-generering kunde inte användas."


def _compact_ai_response_snippet(text: str, pos: int, radius: int = 220) -> str:
    """Returnera ett kort utdrag runt JSON-felet utan att dumpa hela AI-svaret."""
    raw = text or ""
    if not raw:
        return "tomt AI-svar"

    safe_pos = max(0, min(pos or 0, len(raw)))
    start = max(0, safe_pos - radius)
    end = min(len(raw), safe_pos + radius)
    snippet = raw[start:end].replace("\n", "\\n")
    snippet = re.sub(r"\s{2,}", " ", snippet).strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(raw):
        snippet += "..."
    return snippet


def _format_json_decode_failure(error: json.JSONDecodeError, text: str, plan_label: str) -> str:
    """
    Bygg ett felsvar som är användbart vid felsökning av Claude/RAG-output.
    Hålls på en rad eftersom meddelandet också visas i flash och coach_notes.
    """
    snippet = _compact_ai_response_snippet(text, error.pos)
    first_chars = (text or "").lstrip()[:30].replace("\n", "\\n")
    first_chars = first_chars or "tomt svar"
    return (
        f"AI-svaret kunde inte tolkas som JSON för {plan_label}. "
        f"JSON-fel: {error.msg} vid rad {error.lineno}, kolumn {error.colno}, tecken {error.pos}. "
        f"Svaret börjar med: '{first_chars}'. "
        f"Utdrag nära felet: '{snippet}'"
    )


def _summarize_guardrail_errors(errors: list[str], max_items: int = 2) -> str:
    """Gör blockerande guardrail-fel läsbara i UI:t utan att bli för långa."""
    cleaned = []
    for error in errors or []:
        text = re.sub(r"^⚠️\s*", "", str(error)).strip()
        if text:
            cleaned.append(text)
    if not cleaned:
        return ""
    if len(cleaned) <= max_items:
        return "; ".join(cleaned)
    remaining = len(cleaned) - max_items
    return f"{'; '.join(cleaned[:max_items])}; samt {remaining} till"


def _estimate_session_distribution(session: dict) -> dict:
    from ai_schedule import estimate_intensity_distribution

    return estimate_intensity_distribution(
        session_name=session.get("name", ""),
        session_type=session.get("type", ""),
        planned_duration=session.get("duration_min", 0),
        planned_intensity=session.get("intensity", "medel"),
        description=session.get("description", ""),
    )


def _summarize_month_intensity_balance(month_plan: list[dict]) -> dict:
    totals = {"low": 0, "medium": 0, "high": 0}
    weekly_totals = []

    for week in month_plan or []:
        week_totals = {"low": 0, "medium": 0, "high": 0}
        for session in week.get("sessions", []) or []:
            distribution = session.get("estimated_distribution") or _estimate_session_distribution(session)
            session["estimated_distribution"] = distribution
            week_totals["low"] += distribution["low"]
            week_totals["medium"] += distribution["medium"]
            week_totals["high"] += distribution["high"]
        weekly_totals.append({
            "week_number": week.get("week_number"),
            "week_theme": week.get("week_theme", ""),
            "total": sum(week_totals.values()),
            **week_totals,
        })
        for key in totals:
            totals[key] += week_totals[key]

    total_minutes = sum(totals.values())
    ratios = {
        key: (totals[key] / total_minutes if total_minutes else 0.0)
        for key in totals
    }
    return {
        "totals": totals,
        "ratios": ratios,
        "weekly_totals": weekly_totals,
        "total_minutes": total_minutes,
    }


def review_month_plan(month_plan: list[dict], phase: str = "uppbyggnad",
                      birth_year: int = 2000) -> dict:
    blocking_errors = []
    soft_warnings = []
    summary = _summarize_month_intensity_balance(month_plan)
    ratios = summary["ratios"]

    low_floor = {
        "grundträning": 0.68,
        "uppbyggnad": 0.58,
        "tävling": 0.52,
        "återhämtning": 0.80,
    }.get(phase, 0.60)
    high_ceiling = {
        "grundträning": 0.16,
        "uppbyggnad": 0.24,
        "tävling": 0.26,
        "återhämtning": 0.05,
    }.get(phase, 0.22)

    if ratios["low"] < low_floor:
        blocking_errors.append(
            f"⚠️ M1 Lågintensiv dominans: lågintensiv volym är {ratios['low']:.0%}, bör vara minst {low_floor:.0%} i fas '{phase}'"
        )
    if ratios["high"] > high_ceiling:
        blocking_errors.append(
            f"⚠️ M2 Högintensiv volym: högintensiv volym är {ratios['high']:.0%}, bör vara högst {high_ceiling:.0%} i fas '{phase}'"
        )
    if ratios["medium"] > 0.35:
        blocking_errors.append(
            f"⚠️ M3 Mellanzon: medelintensiv volym är {ratios['medium']:.0%}, vilket är för högt"
        )
    elif ratios["medium"] > 0.25:
        soft_warnings.append(
            f"⚠️ M3 Mellanzon: medelintensiv volym är {ratios['medium']:.0%}; håll mellanzonen mer återhållen"
        )
    if ratios["low"] <= (ratios["medium"] + ratios["high"]):
        blocking_errors.append(
            "⚠️ M4 Basbalans: lågintensiv volym dominerar inte perioden tydligt"
        )

    weekly_totals = summary["weekly_totals"]
    for index, week in enumerate(weekly_totals):
        theme = (week.get("week_theme") or "").lower()
        if "återhämt" not in theme:
            continue
        prev_total = weekly_totals[index - 1]["total"] if index > 0 else 0
        current_total = week["total"]
        if prev_total and current_total > prev_total * 0.75:
            blocking_errors.append(
                f"⚠️ M5 Återhämtningsvecka: vecka {week.get('week_number')} sänker inte volymen tillräckligt mot föregående vecka"
            )
        if current_total and (week["high"] / current_total) > 0.08:
            blocking_errors.append(
                f"⚠️ M5 Återhämtningsvecka: vecka {week.get('week_number')} innehåller för mycket högintensiv volym"
            )

    summary["age_group"] = _get_age_group(birth_year)
    return {
        "blocking_errors": blocking_errors,
        "soft_warnings": soft_warnings,
        "summary": summary,
    }


def _rebalance_month_plan_intensity(month_plan: list[dict], phase: str = "uppbyggnad") -> list[dict]:
    rebalanced = []
    for week in month_plan or []:
        theme = (week.get("week_theme") or "").lower()
        sessions = [dict(session) for session in (week.get("sessions") or [])]

        if "återhämt" in theme:
            for session in sessions:
                distribution = _estimate_session_distribution(session)
                if session.get("intensity") in {"hög", "medel"}:
                    session["intensity"] = "låg"
                    session["difficulty"] = "easy"
                    session["role"] = "återhämtning"
                    session["duration_min"] = max(20, int(round((session.get("duration_min", 0) or 30) * 0.8)))
                session["estimated_distribution"] = _estimate_session_distribution(session)
            rebalanced.append({
                **week,
                "sessions": sessions,
            })
            continue

        # Dämpa extra hög belastning först, sedan mellanzon om den blir för dominant.
        hard_seen = 0
        for session in sessions:
            if session.get("difficulty") == "hard":
                hard_seen += 1
                if phase == "grundträning" and hard_seen > 1:
                    session["difficulty"] = "medium"
                    session["intensity"] = "medel"
                    session["role"] = "volym"
            session["estimated_distribution"] = _estimate_session_distribution(session)

        week_summary = _summarize_month_intensity_balance([{"sessions": sessions}])
        if week_summary["ratios"]["medium"] > 0.35:
            medium_adjusted = False
            for session in reversed(sessions):
                if session.get("intensity") == "medel":
                    session["intensity"] = "låg"
                    session["difficulty"] = "easy"
                    session["role"] = "volym" if session.get("role") == "teknik" else "återhämtning"
                    session["estimated_distribution"] = _estimate_session_distribution(session)
                    medium_adjusted = True
                    break
            if not medium_adjusted:
                for session in sessions:
                    session["estimated_distribution"] = _estimate_session_distribution(session)

        rebalanced.append({
            **week,
            "sessions": sessions,
        })

    return rebalanced


# ============================================================
# HJÄLPFUNKTIONER FÖR PROMPTS
# ============================================================

def _format_athlete_context(athlete_info: dict) -> str:
    """
    Bygg en läsbar textsträng om idrottaren för Claude-prompten.
    Inkluderar tävlingsresultat om de finns, så att AI:n kan anpassa
    träningen efter faktisk prestationsnivå (t.ex. personbästa på 100m).
    """
    if not athlete_info:
        return ""

    parts = []
    if athlete_info.get("age"):
        parts.append(f"Ålder: {athlete_info['age']} år")
    if athlete_info.get("birth_year"):
        parts.append(f"Födelseår: {athlete_info['birth_year']}")
    if athlete_info.get("discipline"):
        parts.append(f"Grenprofil: {athlete_info['discipline']}")
    if athlete_info.get("running_focus"):
        parts.append(f"Löpgren: {athlete_info['running_focus']}")
    if athlete_info.get("training_phase"):
        parts.append(f"Fas: {athlete_info['training_phase']}")
    if athlete_info.get("training_days_per_week"):
        parts.append(f"Träningsdagar/vecka: {athlete_info['training_days_per_week']}")
    if athlete_info.get("club"):
        parts.append(f"Klubb: {athlete_info['club']}")
    if athlete_info.get("experience_level"):
        parts.append(f"Erfarenhetsläge: {athlete_info['experience_level']}")
    if athlete_info.get("training_experience_level"):
        parts.append(f"Angiven träningsvana: {athlete_info['training_experience_level']}")
    if athlete_info.get("performance_level"):
        parts.append(f"Prestationsnivå: {athlete_info['performance_level']}")

    base = ("Idrottarens profil: " + ", ".join(parts) + "\n") if parts else ""

    optional_lines = []
    field_labels = {
        "weekly_training_amount": "Nuvarande träningsmängd",
        "primary_goal": "Huvudmål",
        "injury_constraints": "Skador/begränsningar",
        "best_5k_time": "Bästa 5 km-tid",
        "best_alt_distance": "Alternativ tävlingsdistans",
        "best_alt_time": "Tid på alternativ distans",
        "easy_pace": "Ungefärligt lugnt tempo",
        "threshold_pace": "Ungefärligt tröskeltempo",
        "training_surface": "Vanlig träningsmiljö",
        "response_notes": "Övrig respons/kommentar",
        "best_60m_time": "Bästa 60 m-tid",
        "best_100m_time": "Bästa 100 m-tid",
        "best_200m_time": "Bästa 200 m-tid",
        "primary_sprint_event": "Huvudsprintdistans",
    }
    for field, label in field_labels.items():
        if athlete_info.get(field):
            optional_lines.append(f"{label}: {athlete_info[field]}")
    if athlete_info.get("has_external_training_data"):
        optional_lines.append("Extern träningsdata finns tillgänglig från användaren")
    pace_model = athlete_info.get("pace_model") or {}
    if pace_model.get("source_label"):
        optional_lines.append(f"Härledd fartmodell baserad på: {pace_model['source_label']}")
    if pace_model.get("easy_text"):
        optional_lines.append(f"Beräknat lugnt tempo: {pace_model['easy_text']}")
    if pace_model.get("threshold_text"):
        optional_lines.append(f"Beräknat tröskeltempo: {pace_model['threshold_text']}")
    if pace_model.get("speed_endurance_text"):
        optional_lines.append(f"Beräknad snabbhetsuthållighetsfart: {pace_model['speed_endurance_text']}")
    if optional_lines:
        base += "AI-underlag för individanpassning:\n" + "\n".join(f"  {line}" for line in optional_lines) + "\n"

    # Lägg till tävlingsresultat om de finns
    comp = athlete_info.get("competition_results")
    if comp and comp.get("personal_bests"):
        pb_lines = []
        for event, pb in comp["personal_bests"].items():
            pb_lines.append(f"  {event}: {pb['result']} ({pb['date']})")
        base += "Personbästa (tävlingsresultat):\n" + "\n".join(pb_lines) + "\n"

        recent = comp.get("recent_results", [])
        if recent:
            base += "Senaste tävlingar:\n"
            for r in recent[:3]:
                base += f"  {r['date']} — {r['event']}: {r['result']} ({r['venue']})\n"

        base += (
            "OBS: Anpassa träningsintensitet och mål utifrån dessa resultat. "
            "Personbästa anger idrottarens nuvarande prestandanivå.\n"
        )

    return base


# ============================================================
# GUARDRAIL-TEXT TILL PROMPTS
# ============================================================

def _build_guardrail_prompt(phase: str, days_per_week: int,
                             birth_year: int = 2000,
                             is_recovery_week: bool = False) -> str:
    """Bygger den guardrail-sektion som injiceras i varje Claude-prompt."""
    age_group = _get_age_group(birth_year)
    phase_max = PHASE_MAX_HARD.get(phase, 2)
    if age_group == "barn":
        phase_max = 0
    elif age_group == "ungdom":
        phase_max = min(phase_max, 1)

    lines = [
        "HÅRDA REGLER — DESSA FÅR ALDRIG BRYTAS:",
        "G0 (Enbart löpning): Alla pass MÅSTE vara löpningsbaserade. "
        "Styrketräning, gym och tyngdlyftning är FÖRBJUDET. "
        "Tillåtna passtyper: snabbhet, uthållighet, teknik, återhämtning.",
        "G1 (80/20 som periodprincip): Hela 4-veckorsperioden ska domineras av lågintensiv volym. "
        "Sikta på ungefär 80 % lågintensivt och cirka 20 % i högre intensitet över hela mesocykeln, inte som exakt matematik i varje vecka.",
        f"G2 (Variation): Varje vecka måste innehålla minst 2 olika passtyper "
        f"(t.ex. kvalitet + volym + återhämtning).",
        f"G3 (Fas '{phase}'): Max {phase_max} hårt pass per vecka i denna fas.",
        "G4 (Mellanzon): Undvik att lägga för stor del av träningen i mellanzon. "
        "Medelintensiva pass får finnas men ska inte dominera perioden eller ersätta lågintensiv bas.",
    ]

    if is_recovery_week:
        lines.append(
            f"G3 (Återhämtningsvecka): ENDAST lätta pass. "
            f"Volym ska vara 50–70 % av normalvecka. "
            f"Max {max(2, days_per_week - 2)} pass denna vecka."
        )

    lines += [
        "G5 (Progression): Höj inte både volym och intensitet samtidigt vecka-till-vecka.",
    ]

    if age_group == "barn":
        lines.append(
            f"G5 (Barn, född {birth_year}): NOLL hårda pass. Max 3 pass/vecka. "
            f"Enbart lek, teknik och koordination. Fokus på rörelseglädje, INTE prestation."
        )
    elif age_group == "ungdom":
        lines.append(
            f"G6 (Ungdom, född {birth_year}): Max 1 hårt pass per vecka. "
            f"Minst ett teknikpass MÅSTE ingå. Variation och teknik prioriteras."
        )

    lines += [
        "G7 (Nyckelpass): Utse exakt ETT nyckelpass per vecka — det viktigaste passet. "
        "Övriga pass stödjer återhämtning inför/efter nyckelpasset.",
        "G8 (Passstruktur): Alla hårda pass MÅSTE innehålla: "
        "Uppvärmning (minst 15 min), Huvudpass, Nedvarvning (minst 10 min).",
        "G9 (Hard–easy): Ett hårt pass MÅSTE alltid följas av ett lätt pass eller vilodag. "
        "Aldrig hårt → medium direkt dagen efter.",
    ]

    return "\n".join(lines)


def _build_coachlike_prompt_block(discipline: str, athlete_info: dict) -> str:
    age_group = _get_age_group(int((athlete_info or {}).get("birth_year", 2000)))
    experience = (athlete_info or {}).get("experience_level", "van")
    performance = (athlete_info or {}).get("performance_level", "utvecklande")

    audience_line = (
        "Skriv pedagogiskt, enkelt och tekniknära."
        if age_group in {"barn", "ungdom"} else
        "Skriv tydligt, precist och coachlikt med prestationsfokus."
    )

    return "\n".join([
        "COACHKVALITET — PASSEN MÅSTE KÄNNAS SOM EN TRÄNARES PLANERING:",
        f"- Idrottarens erfarenhetsläge: {experience}. Prestationsnivå: {performance}.",
        f"- Anpassa språk och dosering för målgruppen. {audience_line}",
        "- Varje pass måste innehålla 'Syfte:', 'Uppvärmning:', 'Huvudpass:' och 'Nedvarvning:'.",
        "- Beskriv varför passet ligger just den dagen i relation till nyckelpasset.",
        "- Ange tydlig intensitetsstyrning via zon, tävlingsfart, tröskel eller procent där det passar.",
        "- Om individdata om fart finns ska du ge ungefärligt tempo eller tempointervall som passar just idrottaren.",
        "- För medel/distans: skriv alltid fart i min/km, aldrig som sekunder per rep eller repfart.",
        "- Om fartunderlag saknas ska du använda försiktiga fartintervall, zoner eller känsla i stället för falsk precision.",
        "- Medium-pass ska vara kontrollerade och får inte kännas som dolda hårda pass.",
        "- Lätta pass ska vara verkligt återhämtande och stödja nästa kvalitetspass.",
        f"- För disciplinen {discipline} ska passen vara grenspecifika och inte generisk allmänlöpning.",
    ])


def _build_search_queries(plan_type: str, discipline: str, phase: str) -> list[tuple[str, str]]:
    profile = SEARCH_PROFILES[plan_type]
    queries = []
    for theme, templates in profile.items():
        for template in templates:
            queries.append((theme, template.format(discipline=discipline, phase=phase)))
    return queries


def _collect_retrieval_context(
    retriever: "KnowledgeRetriever",
    plan_type: str,
    discipline: str,
    phase: str,
    allowed_doc_keys: list[str],
    max_chunks: int,
) -> tuple[str, list[dict]]:
    """
    Samla och diversifiera chunks så att prompten får flera perspektiv.
    """
    queries = _build_search_queries(plan_type, discipline, phase)
    chosen = []
    seen_texts = set()
    source_counts = Counter()
    theme_counts = Counter()

    for theme, query in queries:
        results = retriever.search(query, top_k=4, allowed_doc_keys=allowed_doc_keys)
        for result in results:
            text = result["text"]
            source_key = result["source_key"]
            if text in seen_texts:
                continue
            if source_counts[source_key] >= 3:
                continue
            if theme_counts[theme] >= 2:
                continue
            enriched = dict(result)
            enriched["theme"] = theme
            chosen.append(enriched)
            seen_texts.add(text)
            source_counts[source_key] += 1
            theme_counts[theme] += 1
            if len(chosen) >= max_chunks:
                break
        if len(chosen) >= max_chunks:
            break

    context_text = "\n\n---\n\n".join(
        f"[Källa: {c['source']} | Tema: {c['theme']}]\n{c['text']}" for c in chosen
    )
    return context_text, chosen


def _build_plan_metadata(status: str, used_chunks: list[dict], review: dict,
                         week_theme: Optional[str] = None, overview: str = "") -> dict:
    return {
        "status": status,
        "sources": sorted({c["source"] for c in used_chunks}),
        "source_keys": sorted({c["source_key"] for c in used_chunks}),
        "review": review,
        "week_theme": week_theme or "",
        "overview": overview.strip(),
    }


def _build_failed_plan_result(reason: str, used_chunks: Optional[list[dict]] = None) -> dict:
    human_reason = _humanize_api_failure(reason)
    metadata = _build_plan_metadata(
        status="RAG-fel",
        used_chunks=used_chunks or [],
        review={
            "blocking_errors": [human_reason],
            "soft_warnings": [],
            "normalized_sessions": [],
            "summary": {},
        },
        overview=f"Ett säkert reservupplägg användes eftersom RAG inte kunde användas fullt ut. Orsak: {human_reason}",
    )
    metadata["coach_notes"] = _coach_notes_from_metadata(metadata)
    return {
        "plan": None,
        "metadata": metadata,
        "error": human_reason,
    }


def _coach_notes_from_metadata(metadata: dict, key_session_name: str = "") -> str:
    source_text = ", ".join(metadata.get("sources", [])) if metadata.get("sources") else "Inga externa källor"
    week_theme = metadata.get("week_theme")
    overview = metadata.get("overview") or "Veckan är byggd kring ett tydligt nyckelpass och återhämtning före/efter kvalitet."
    key_line = f"Nyckelpass: {key_session_name}" if key_session_name else "Nyckelpass: se veckans markerade kvalitetspass"
    theme_line = f"Veckofokus: {week_theme}" if week_theme else "Veckofokus: coachlik löpveckostruktur"
    return "\n".join([
        f"Planstatus: {metadata.get('status', 'ok')}",
        theme_line,
        key_line,
        f"Källor: {source_text}",
        f"Coachförklaring: {overview}",
    ])


def _repair_sessions_to_structure(sessions: list[dict], structure: list[dict]) -> list[dict]:
    repaired = []
    for i, base in enumerate(structure):
        src = dict(sessions[i]) if i < len(sessions) else {}
        src["day_name"] = base["day"]
        src["difficulty"] = base["difficulty"]
        src["role"] = base.get("role", "volym")
        src["is_key_session"] = base.get("is_key_session", False)
        src.setdefault("name", "AI-pass")
        src.setdefault("type", "uthållighet")
        src.setdefault("duration_min", 50 if base["difficulty"] != "easy" else 35)
        src.setdefault("intensity", "medel" if base["difficulty"] == "medium" else ("hög" if base["difficulty"] == "hard" else "låg"))
        desc = src.get("description", "")
        if "Syfte:" not in desc:
            purpose = (
                "Syfte: Veckans nyckelpass för att utveckla specifik kapacitet."
                if src["is_key_session"] else
                "Syfte: Stödja veckans huvudpass med rätt dos och återhämtning."
            )
            src["description"] = f"{purpose}\n{desc}".strip()
        if "Uppvärmning:" not in src["description"]:
            src["description"] += "\nUppvärmning: 10-15 min lugn jogg + rörlighet."
        if "Huvudpass:" not in src["description"]:
            src["description"] += "\nHuvudpass: Kontrollerad löpning enligt passets syfte."
        if "Nedvarvning:" not in src["description"] and "Nedjogg:" not in src["description"]:
            src["description"] += "\nNedvarvning: 10 min lugn jogg och lätt rörlighet."
        repaired.append(src)
    return repaired


# ============================================================
# HELA VECKANS PLAN I ETT CLAUDE-ANROP
# ============================================================

def generate_week_plan_rag(
    discipline:       str,
    phase:            str,
    days_per_week:    int,
    retriever:        KnowledgeRetriever,
    athlete_info:     dict = None,
    allowed_doc_keys: list[str] = None,
) -> Optional[dict]:
    """
    Generera ett komplett veckoschema i ETT Claude-anrop med RAG-kontext.

    Args:
        allowed_doc_keys: Vilka dokument som RAG-sökningen ska använda,
                          t.ex. ["loptranare"]. None = alla.
    """
    client = get_claude_client()
    if not client:
        return _build_failed_plan_result("Anthropic API-nyckel saknas")

    allowed_doc_keys = resolve_allowed_doc_keys(allowed_doc_keys, discipline)

    birth_year = int((athlete_info or {}).get("birth_year", 2000))

    context_text, used_chunks = _collect_retrieval_context(
        retriever=retriever,
        plan_type="week",
        discipline=discipline,
        phase=phase,
        allowed_doc_keys=allowed_doc_keys,
        max_chunks=8,
    )

    structure = apply_hard_rules_to_structure(days_per_week, phase, birth_year)

    sessions_spec = "\n".join(
        f"{i+1}. {s['day']}: {s['difficulty'].upper()} pass "
        f"(roll: {s['role']})"
        f"{' ← NYCKELPASS' if s['is_key_session'] else ''}"
        for i, s in enumerate(structure)
    )

    athlete_context = _format_athlete_context(athlete_info)

    guardrails = _build_guardrail_prompt(phase, days_per_week, birth_year)
    coachlike = _build_coachlike_prompt_block(discipline, athlete_info or {})

    prompt = f"""Du är en erfaren friidrottstränare med gedigen utbildning i löpträning.
Skapa ett veckoschema baserat på utbildningsmaterialet nedan.

UTBILDNINGSMATERIAL:
{context_text if context_text else "Använd din allmänna träningskunskap."}

ATLETPROFIL:
- Gren: {discipline}
- Träningsfas: {phase}
- Träningsdagar: {days_per_week}
{athlete_context}

VECKOSTRUKTUR (MÅSTE följas exakt):
{sessions_spec}

{guardrails}

{coachlike}

Skapa ett sammanhängande schema. Tänk som en coach — nyckelpasset är veckans tyngdpunkt,
övriga pass anpassas för att idrottaren ska kunna prestera maximalt på nyckelpasset.

Svara ENBART med giltig JSON-array:
[
  {{
    "day_name": "Måndag",
    "difficulty": "hard",
    "role": "kvalitet",
    "is_key_session": true,
    "name": "Passnamn (max 4 ord)",
    "type": "snabbhet/uthållighet/teknik/återhämtning",
    "duration_min": 70,
    "intensity": "hög/medel/låg",
    "description": "Uppvärmning: 15 min lugnt tempo + löpskola.\\nHuvudpass: 6x800m i tävlingsfart, 2 min vila.\\nNedvarvning: 10 min lugnt + stretching."
  }}
]

KRITISKA regler för description-fältet:
- ALLTID använd denna struktur exakt: Syfte: ... \\nUppvärmning: ... \\nHuvudpass: ... \\nNedvarvning: ...
- ALDRIG asterisker (**) eller andra markdown-symboler
- Använd \\n för radbrytning mellan sektionerna
- Hårda pass: Uppvärmning (≥15 min) + Huvudpass + Nedvarvning (≥10 min)
- Lätta pass: Uppvärmning och Huvudpass måste ingå
- Uppvärmning ska vara konkret: joggdelar ska anges i min/km när tempo kan uppskattas; dynamisk rörlighet/löpskola/stegringar ska ange exakt vad som görs, antal repetitioner och känsla/progressionsgrad
- Nedvarvning ska vara konkret: lugn jogg/promenad ska anges i min/km när tempo kan uppskattas, plus stretch/rörlighet och mycket lätt känsla
- Använd inte % av maxpuls för vanlig uppvärmningsjogg eller nedvarvningsjogg; använd min/km eller zon/känsla om tempo saknas
- För stegringslopp/upptrappning/progressiva lopp räcker känsla/progression, t.ex. "börja kontrollerat och öka från lugnt till snabbt men avslappnat, inte max"
- Om du använder ord som löpskola, stegringslopp, uppbyggnad, progressivt eller dynamisk rörlighet ska du kort förklara vad idrottaren ska göra
- Specifika distanser, tider, viloperioder MÅSTE anges
- Skriv på svenska"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = re.sub(r'^```(?:json)?\n?', '', text)
            text = re.sub(r'\n?```$', '', text)

        sessions = json.loads(text)
        sessions = _repair_sessions_to_structure(sessions, structure)

        review = review_week_plan(sessions, phase=phase, birth_year=birth_year)
        for w in review["blocking_errors"] + review["soft_warnings"]:
            print(w)
        status = "RAG-genererad"
        if review["blocking_errors"]:
            repaired_sessions = _repair_sessions_to_structure(review["normalized_sessions"], structure)
            repaired_review = review_week_plan(repaired_sessions, phase=phase, birth_year=birth_year)
            if repaired_review["blocking_errors"]:
                print("⚠️ Veckoplan kunde inte kvalitetssäkras efter reparation")
                failure_summary = _summarize_guardrail_errors(repaired_review["blocking_errors"])
                return _build_failed_plan_result(
                    (
                        "Veckoplanen bröt mot blockerande guardrails även efter reparation"
                        + (f": {failure_summary}" if failure_summary else "")
                    ),
                    used_chunks=used_chunks,
                )
            sessions = repaired_sessions
            review = repaired_review
            status = "RAG-reparerad"

        key_session_name = next((s.get("name", "") for s in sessions if s.get("is_key_session")), "")
        overview = (
            f"Veckan byggs runt nyckelpasset '{key_session_name}' med lättare pass före/efter för att skydda kvaliteten."
            if key_session_name else
            "Veckan är periodiserad med ett tydligt kvalitetspass och återhämtning runt omkring."
        )
        metadata = _build_plan_metadata(status, used_chunks, review, overview=overview)
        metadata["coach_notes"] = _coach_notes_from_metadata(metadata, key_session_name=key_session_name)

        return {
            "plan": sessions,
            "metadata": metadata,
        }

    except json.JSONDecodeError as e:
        failure_reason = _format_json_decode_failure(e, text, "veckoplan")
        print(f"⚠️ {failure_reason}")
        return _build_failed_plan_result(failure_reason, used_chunks=used_chunks)
    except anthropic.APIError as e:
        print(f"⚠️ Claude API-fel: {e}")
        return _build_failed_plan_result(f"Claude API-fel: {e}", used_chunks=used_chunks)
    except Exception as e:
        print(f"⚠️ Oväntat fel: {e}")
        return _build_failed_plan_result(f"Oväntat fel i veckoplanering: {e}", used_chunks=used_chunks)


# ============================================================
# MÅNADSPLAN I ETT CLAUDE-ANROP
# ============================================================

MONTH_PROGRESSION = {
    "grundträning":  ["bas",         "bygge",         "bygge",         "återhämtning"],
    "uppbyggnad":    ["bygge",        "intensitet",    "intensitet",    "återhämtning"],
    "tävling":       ["aktivering",   "tävlingsvecka", "nedtrappning",  "återhämtning"],
    "återhämtning":  ["lätt",         "lätt",          "lätt",          "lätt"],
}

RECOVERY_WEEK_THEMES = {"återhämtning", "lätt", "nedtrappning"}


def generate_month_plan_rag(
    discipline:       str,
    phase:            str,
    days_per_week:    int,
    retriever:        KnowledgeRetriever,
    athlete_info:     dict = None,
    allowed_doc_keys: list[str] = None,
) -> Optional[dict]:
    """
    Generera en komplett månadsplan (4 veckor) i ETT Claude-anrop.

    Args:
        allowed_doc_keys: Dokumentfilter för RAG-sökning. None = alla.
    """
    client = get_claude_client()
    if not client:
        return _build_failed_plan_result("Anthropic API-nyckel saknas")

    allowed_doc_keys = resolve_allowed_doc_keys(allowed_doc_keys, discipline)

    birth_year = int((athlete_info or {}).get("birth_year", 2000))

    context_text, used_chunks = _collect_retrieval_context(
        retriever=retriever,
        plan_type="month",
        discipline=discipline,
        phase=phase,
        allowed_doc_keys=allowed_doc_keys,
        max_chunks=10,
    )

    week_themes = MONTH_PROGRESSION.get(phase, MONTH_PROGRESSION["grundträning"])

    # Bygg strukturer för alla 4 veckor
    week_structures = []
    for week_num, theme in enumerate(week_themes, 1):
        is_recovery = theme in RECOVERY_WEEK_THEMES
        week_phase  = "återhämtning" if is_recovery else phase

        # Guardrail 3 (vecka 4): reducera antal pass med ~40 %
        effective_days = days_per_week
        if is_recovery:
            effective_days = max(2, round(days_per_week * RECOVERY_WEEK_VOLUME_FACTOR))

        structure = apply_hard_rules_to_structure(effective_days, week_phase, birth_year)
        week_structures.append({
            "week":        week_num,
            "theme":       theme,
            "is_recovery": is_recovery,
            "sessions":    structure,
        })

    # Bygg spec för prompten
    weeks_spec = ""
    for w in week_structures:
        weeks_spec += f"\nVECKA {w['week']} — Tema: {w['theme']}"
        if w["is_recovery"]:
            weeks_spec += f" (ÅTERHÄMTNING — 50–70 % av normalvolym, max {len(w['sessions'])} pass)"
        weeks_spec += "\n"
        for s in w["sessions"]:
            key_tag = " ← NYCKELPASS" if s["is_key_session"] else ""
            weeks_spec += (
                f"  {s['day']}: {s['difficulty'].upper()} "
                f"(roll: {s['role']}){key_tag}\n"
            )

    athlete_context = _format_athlete_context(athlete_info)

    guardrails = _build_guardrail_prompt(phase, days_per_week, birth_year)
    coachlike = _build_coachlike_prompt_block(discipline, athlete_info or {})

    prompt = f"""Du är en erfaren friidrottstränare med gedigen utbildning i periodisering och löpträning.
Skapa en månadsplan (4 veckor, klassisk mesocykel) baserat på utbildningsmaterialet nedan.

UTBILDNINGSMATERIAL:
{context_text if context_text else "Använd din allmänna träningskunskap."}

ATLETPROFIL:
- Gren: {discipline}
- Träningsfas: {phase}
- Träningsdagar per vecka (normalvecka): {days_per_week}
{athlete_context}

MÅNADSSTRUKTUR (MÅSTE följas exakt):
{weeks_spec}

{guardrails}

{coachlike}

Progressionsregel (Guardrail 4):
- Vecka 1 → 2: Öka ANTINGEN volym ELLER intensitet, inte båda
- Vecka 2 → 3: Fortsätt progression på samma axel
- Vecka 4: ALLTID återhämtning — 50–70 % av vecka 3:s volym

Tänk som en coach med gedigen utbildning:
- Nyckelpasset är veckans tyngdpunkt — övriga pass stödjer det
- Hard–easy: hårt pass → lätt/vila dagen efter, alltid
- Hårda pass ALLTID med uppvärmning (≥15 min) och nedvarvning (≥10 min)

Svara ENBART med giltig JSON:
[
  {{
    "week_number": 1,
    "week_theme": "bas",
    "sessions": [
      {{
        "day_name": "Måndag",
        "difficulty": "hard",
        "role": "kvalitet",
        "is_key_session": true,
        "name": "Passnamn (max 4 ord)",
        "type": "snabbhet/uthållighet/teknik/återhämtning",
        "duration_min": 70,
        "intensity": "hög/medel/låg",
        "description": "Uppvärmning: 15 min lugnt + löpskola.\\nHuvudpass: 5x1000m i tröskelfart, 90 sek vila.\\nNedvarvning: 10 min lugnt + stretching."
      }}
    ]
  }}
]

KRITISKA regler för description-fältet:
- ALLTID använd denna struktur exakt: Syfte: ... \\nUppvärmning: ... \\nHuvudpass: ... \\nNedvarvning: ...
- ALDRIG asterisker (**) eller andra markdown-symboler
- Använd \\n för radbrytning mellan sektionerna
- Uppvärmning ska vara konkret: joggdelar ska anges i min/km när tempo kan uppskattas; dynamisk rörlighet/löpskola/stegringar ska ange exakt vad som görs, antal repetitioner och känsla/progressionsgrad
- Nedvarvning ska vara konkret: lugn jogg/promenad ska anges i min/km när tempo kan uppskattas, plus stretch/rörlighet och mycket lätt känsla
- Använd inte % av maxpuls för vanlig uppvärmningsjogg eller nedvarvningsjogg; använd min/km eller zon/känsla om tempo saknas
- För stegringslopp/upptrappning/progressiva lopp räcker känsla/progression, t.ex. "börja kontrollerat och öka från lugnt till snabbt men avslappnat, inte max"
- Om du använder ord som löpskola, stegringslopp, uppbyggnad, progressivt eller dynamisk rörlighet ska du kort förklara vad idrottaren ska göra
- Specifika distanser, tider, viloperioder i varje pass
- Tydlig progression vecka 1 → 3, tydlig nedtrappning vecka 4
- Skriv på svenska"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=6000,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = re.sub(r'^```(?:json)?\n?', '', text)
            text = re.sub(r'\n?```$', '', text)

        month_plan = json.loads(text)
        month_review_rows = []
        repaired_month_plan = []
        month_repaired = False

        for index, week in enumerate(month_plan):
            w_num = week.get("week_number", "?")
            w_theme = week.get("week_theme", "?")
            is_rec  = w_theme in RECOVERY_WEEK_THEMES
            w_phase = "återhämtning" if is_rec else phase
            structure = week_structures[index]["sessions"] if index < len(week_structures) else []
            sessions = _repair_sessions_to_structure(week.get("sessions", []), structure)
            review = review_week_plan(sessions, phase=w_phase, birth_year=birth_year)
            if review["blocking_errors"]:
                repaired_sessions = _repair_sessions_to_structure(review["normalized_sessions"], structure)
                repaired_review = review_week_plan(repaired_sessions, phase=w_phase, birth_year=birth_year)
                if repaired_review["blocking_errors"]:
                    print(f"⚠️ Vecka {w_num} ({w_theme}) kunde inte kvalitetssäkras")
                    failure_summary = _summarize_guardrail_errors(repaired_review["blocking_errors"])
                    return _build_failed_plan_result(
                        (
                            f"Vecka {w_num} ({w_theme}) bröt mot blockerande guardrails även efter reparation"
                            + (f": {failure_summary}" if failure_summary else "")
                        ),
                        used_chunks=used_chunks,
                    )
                sessions = repaired_sessions
                review = repaired_review
                month_repaired = True
            month_review_rows.append((w_num, w_theme, review))
            repaired_month_plan.append({
                "week_number": week.get("week_number", index + 1),
                "week_theme": w_theme,
                "sessions": sessions,
            })

        month_review = review_month_plan(repaired_month_plan, phase=phase, birth_year=birth_year)
        if month_review["blocking_errors"]:
            rebalanced_month = _rebalance_month_plan_intensity(repaired_month_plan, phase=phase)
            rebalanced_month_review = review_month_plan(rebalanced_month, phase=phase, birth_year=birth_year)
            if rebalanced_month_review["blocking_errors"]:
                failure_summary = _summarize_guardrail_errors(rebalanced_month_review["blocking_errors"])
                return _build_failed_plan_result(
                    (
                        "Månadsplanen bröt mot periodiseringsregler även efter intensitetsreparation"
                        + (f": {failure_summary}" if failure_summary else "")
                    ),
                    used_chunks=used_chunks,
                )
            repaired_month_plan = rebalanced_month
            month_review = rebalanced_month_review
            month_repaired = True

        total_sessions = sum(len(w.get("sessions", [])) for w in repaired_month_plan)
        print(f"✅ Månadsplan: {total_sessions} pass fördelade på 4 veckor")
        overview = "Mesocykeln byggs med progressionsveckor följt av återhämtningsvecka och tydliga nyckelpass."
        metadata = _build_plan_metadata("RAG-reparerad" if month_repaired else "RAG-genererad", used_chunks, {
            "blocking_errors": [f"Vecka {w}: {err}" for w, _, rev in month_review_rows for err in rev["blocking_errors"]],
            "soft_warnings": [f"Vecka {w}: {warn}" for w, _, rev in month_review_rows for warn in rev["soft_warnings"]] + month_review["soft_warnings"],
            "normalized_sessions": repaired_month_plan,
            "summary": {"weeks": len(repaired_month_plan), "month_balance": month_review["summary"]},
        }, overview=overview)
        metadata["coach_notes"] = _coach_notes_from_metadata(metadata)
        return {
            "plan": repaired_month_plan,
            "metadata": metadata,
        }

    except json.JSONDecodeError as e:
        failure_reason = _format_json_decode_failure(e, text, "månadsplan")
        print(f"⚠️ {failure_reason}")
        return _build_failed_plan_result(failure_reason, used_chunks=used_chunks)
    except anthropic.APIError as e:
        print(f"⚠️ Claude API-fel: {e}")
        return _build_failed_plan_result(f"Claude API-fel: {e}", used_chunks=used_chunks)
    except Exception as e:
        print(f"⚠️ Oväntat fel: {e}")
        return _build_failed_plan_result(f"Oväntat fel i månadsplanering: {e}", used_chunks=used_chunks)


# ============================================================
# GLOBAL RETRIEVER
# ============================================================

_retriever = None

def get_retriever() -> KnowledgeRetriever:
    global _retriever
    if _retriever is None:
        _retriever = KnowledgeRetriever()
        _retriever.initialize()
    return _retriever


def get_document_options() -> list[dict]:
    """Returnerar lista med dokumentalternativ för UI-visning."""
    return [
        {"key": key, "title": doc["title"], "description": doc["description"]}
        for key, doc in DOCUMENT_REGISTRY.items()
    ]
