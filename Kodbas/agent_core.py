"""
Agent Core - OpenClaw-inspirerad agent-arkitektur för träningsplattformen.

Arkitektur:
- Agent Loop: Plan → Act → Verify → Repeat
- Skills: Modulära förmågor agenten kan använda
- Memory: Persistent kontext (JSONL-filer)
- Tools: Faktiska handlingar (notifications, dataändringar)

Inspirerad av OpenClaw's "Brain, Hands, Memory"-arkitektur.
"""

import os
import json
import hashlib
from datetime import datetime, date, timedelta
from dataclasses import dataclass, asdict
from typing import Optional, Callable
from enum import Enum

# Ladda API-nyckel
from dotenv import load_dotenv
load_dotenv()

try:
    from anthropic import Anthropic
    client = Anthropic()
    API_AVAILABLE = True
except Exception:
    client = None
    API_AVAILABLE = False


# ============================================================
# MEMORY SYSTEM - Persistent kontext (som OpenClaw's JSONL)
# ============================================================

MEMORY_DIR = os.path.join(os.path.dirname(__file__), '.agent_memory')

def ensure_memory_dir():
    """Skapa memory-katalog om den inte finns."""
    if not os.path.exists(MEMORY_DIR):
        os.makedirs(MEMORY_DIR)

def save_memory(key: str, data: dict):
    """Spara data till agent-minnet."""
    ensure_memory_dir()
    filepath = os.path.join(MEMORY_DIR, f"{key}.jsonl")
    with open(filepath, 'a') as f:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def load_memory(key: str, limit: int = 50) -> list[dict]:
    """Läs senaste entries från agent-minnet."""
    ensure_memory_dir()
    filepath = os.path.join(MEMORY_DIR, f"{key}.jsonl")
    if not os.path.exists(filepath):
        return []

    entries = []
    with open(filepath, 'r') as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))

    return entries[-limit:]  # Returnera senaste entries

def clear_memory(key: str):
    """Rensa ett specifikt minne."""
    filepath = os.path.join(MEMORY_DIR, f"{key}.jsonl")
    if os.path.exists(filepath):
        os.remove(filepath)


# ============================================================
# SKILL SYSTEM - Modulära förmågor (som OpenClaw's Skills)
# ============================================================

@dataclass
class SkillResult:
    """Resultat från en skill-exekvering."""
    success: bool
    message: str
    data: Optional[dict] = None
    action_taken: Optional[str] = None

class Skill:
    """Basklass för agent-skills."""

    name: str = "base_skill"
    description: str = "Basskill"

    def can_execute(self, context: dict) -> bool:
        """Kontrollera om skillen kan köras givet kontexten."""
        return True

    def execute(self, context: dict) -> SkillResult:
        """Kör skillen."""
        raise NotImplementedError


class CheckACWRSkill(Skill):
    """Skill: Kontrollera ACWR för alla idrottare och flagga riskfall."""

    name = "check_acwr"
    description = "Analyserar alla idrottares ACWR och identifierar överträningsrisk"

    def execute(self, context: dict) -> SkillResult:
        from models import db
        from readiness import calculate_readiness

        alerts = []
        athletes = db.get_all_athletes()

        for athlete in athletes:
            readiness = calculate_readiness(athlete)

            if readiness.acwr and readiness.acwr > 1.5:
                alerts.append({
                    "athlete_id": athlete.id,
                    "athlete_name": athlete.name,
                    "acwr": readiness.acwr,
                    "level": "kritisk" if readiness.acwr > 1.8 else "varning",
                    "message": f"{athlete.name} har ACWR {readiness.acwr:.2f} - hög skaderisk!"
                })
            elif readiness.level == "röd":
                alerts.append({
                    "athlete_id": athlete.id,
                    "athlete_name": athlete.name,
                    "acwr": readiness.acwr,
                    "level": "varning",
                    "message": f"{athlete.name} är i röd zon - behöver vila"
                })

        # Spara till minnet
        if alerts:
            save_memory("acwr_alerts", {"alerts": alerts, "checked_at": datetime.now().isoformat()})

        return SkillResult(
            success=True,
            message=f"Kontrollerade {len(athletes)} idrottare, hittade {len(alerts)} varningar",
            data={"alerts": alerts, "total_checked": len(athletes)}
        )


class CheckInactiveAthletesSkill(Skill):
    """Skill: Hitta idrottare som inte loggat på länge."""

    name = "check_inactive"
    description = "Identifierar idrottare som inte loggat träning på över 3 dagar"

    def execute(self, context: dict) -> SkillResult:
        from models import db

        inactive = []
        athletes = db.get_all_athletes()

        for athlete in athletes:
            days = athlete.get_days_since_last_log()
            if days >= 3:
                inactive.append({
                    "athlete_id": athlete.id,
                    "athlete_name": athlete.name,
                    "days_since_log": days,
                    "message": f"{athlete.name} har inte loggat på {days} dagar"
                })

        if inactive:
            save_memory("inactive_alerts", {"inactive": inactive})

        return SkillResult(
            success=True,
            message=f"Hittade {len(inactive)} inaktiva idrottare",
            data={"inactive": inactive}
        )


class GenerateWeekPlanSkill(Skill):
    """Skill: Generera veckoplan för en idrottare med AI."""

    name = "generate_week_plan"
    description = "Skapar ett AI-genererat veckoplaneringsförslag för en idrottare"

    def execute(self, context: dict) -> SkillResult:
        athlete_id = context.get("athlete_id")
        if not athlete_id:
            return SkillResult(success=False, message="Ingen athlete_id angiven")

        from models import db
        from readiness import calculate_readiness

        athlete = db.get_athlete(athlete_id)
        if not athlete:
            return SkillResult(success=False, message="Idrottare hittades inte")

        readiness = calculate_readiness(athlete)
        logs = athlete.get_logs_last_n_days(14)
        injuries = athlete.get_active_injuries()

        # Bygg prompt för AI
        prompt = f"""Du är en friidrottsexpert. Skapa ett veckoplaneringsförslag för:

Idrottare: {athlete.name}
Gren: {athlete.discipline}
Ålder: {date.today().year - athlete.birth_year} år
ACWR: {readiness.acwr:.2f if readiness.acwr else 'Ej beräknat'}
Status: {readiness.level}
Aktiva skador: {', '.join([f"{i.body_part} ({i.status})" for i in injuries]) if injuries else 'Inga'}

Senaste 14 dagars träning:
{chr(10).join([f"- {log.date}: {log.session_type}, {log.duration}min, RPE {log.rpe}" for log in logs[-7:]])}

Ge ett konkret veckoschema (mån-sön) med:
- Typ av pass
- Ungefärlig duration
- Intensitet (låg/medel/hög)
- Kort motivering

Svara på svenska i JSON-format:
{{"monday": {{"type": "...", "duration": X, "intensity": "...", "note": "..."}}, ...}}
"""

        if not API_AVAILABLE:
            return SkillResult(
                success=False,
                message="API ej tillgänglig",
                data={"error": "no_api"}
            )

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}]
            )

            plan_text = response.content[0].text

            # Försök parsa JSON från svaret
            import re
            json_match = re.search(r'\{[\s\S]*\}', plan_text)
            if json_match:
                plan_data = json.loads(json_match.group())
            else:
                plan_data = {"raw_response": plan_text}

            # Spara till minnet
            save_memory(f"week_plan_{athlete_id}", {
                "athlete_id": athlete_id,
                "plan": plan_data,
                "generated_at": datetime.now().isoformat()
            })

            return SkillResult(
                success=True,
                message=f"Veckoplan genererad för {athlete.name}",
                data={"plan": plan_data, "athlete_name": athlete.name}
            )

        except Exception as e:
            return SkillResult(success=False, message=f"Fel vid AI-anrop: {str(e)}")


class AnalyzeProgressSkill(Skill):
    """Skill: Analysera en idrottares progression över tid."""

    name = "analyze_progress"
    description = "Analyserar träningsprogressionen och identifierar trender"

    def execute(self, context: dict) -> SkillResult:
        athlete_id = context.get("athlete_id")
        if not athlete_id:
            return SkillResult(success=False, message="Ingen athlete_id angiven")

        from models import db

        athlete = db.get_athlete(athlete_id)
        if not athlete:
            return SkillResult(success=False, message="Idrottare hittades inte")

        logs = athlete.get_logs_last_n_days(30)

        if len(logs) < 5:
            return SkillResult(
                success=True,
                message="För lite data för analys",
                data={"status": "insufficient_data"}
            )

        # Beräkna trender
        weekly_loads = {}
        for log in logs:
            week = log.date.isocalendar()[1]
            if week not in weekly_loads:
                weekly_loads[week] = []
            weekly_loads[week].append(log.load)

        weekly_totals = {w: sum(loads) for w, loads in weekly_loads.items()}
        weeks = sorted(weekly_totals.keys())

        trend = "stabil"
        if len(weeks) >= 2:
            recent = weekly_totals[weeks[-1]]
            previous = weekly_totals[weeks[-2]]
            change = (recent - previous) / previous * 100 if previous > 0 else 0

            if change > 15:
                trend = "ökande"
            elif change < -15:
                trend = "minskande"

        analysis = {
            "athlete_name": athlete.name,
            "total_sessions": len(logs),
            "weekly_totals": weekly_totals,
            "trend": trend,
            "avg_rpe": sum(log.rpe for log in logs) / len(logs),
            "avg_duration": sum(log.duration for log in logs) / len(logs)
        }

        return SkillResult(
            success=True,
            message=f"Analys klar för {athlete.name}: trend är {trend}",
            data=analysis
        )


# ============================================================
# SKILL REGISTRY - Alla tillgängliga skills
# ============================================================

SKILLS = {
    "check_acwr": CheckACWRSkill(),
    "check_inactive": CheckInactiveAthletesSkill(),
    "generate_week_plan": GenerateWeekPlanSkill(),
    "analyze_progress": AnalyzeProgressSkill(),
}


# ============================================================
# AGENT LOOP - Hjärtat i agenten (Plan → Act → Verify → Repeat)
# ============================================================

@dataclass
class AgentTask:
    """En uppgift för agenten att utföra."""
    id: str
    description: str
    skill_name: str
    context: dict
    status: str = "pending"  # pending, running, completed, failed
    result: Optional[SkillResult] = None
    created_at: str = None
    completed_at: str = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


class AgentLoop:
    """
    OpenClaw-inspirerad agent-loop.

    Cykeln:
    1. PLAN - Ta emot mål, bryt ner i tasks
    2. ACT - Kör relevant skill
    3. VERIFY - Kontrollera resultat
    4. REPEAT - Fortsätt eller avsluta
    """

    def __init__(self):
        self.tasks: list[AgentTask] = []
        self.execution_log: list[dict] = []
        self.max_iterations = 10

    def plan(self, goal: str, context: dict = None) -> list[AgentTask]:
        """
        PLAN-fasen: Analysera målet och skapa tasks.

        I en fullständig implementation skulle LLM:en bestämma
        vilka skills som behövs. Här gör vi en enklare mappning.
        """
        context = context or {}
        tasks = []

        # Enkel mappning av mål till skills
        goal_lower = goal.lower()

        if "acwr" in goal_lower or "belastning" in goal_lower or "överträning" in goal_lower:
            tasks.append(AgentTask(
                id=f"task_{len(self.tasks)}",
                description="Kontrollera ACWR för alla idrottare",
                skill_name="check_acwr",
                context=context
            ))

        if "inaktiv" in goal_lower or "loggat" in goal_lower:
            tasks.append(AgentTask(
                id=f"task_{len(self.tasks) + len(tasks)}",
                description="Hitta inaktiva idrottare",
                skill_name="check_inactive",
                context=context
            ))

        if "veckoplan" in goal_lower or "planera" in goal_lower:
            tasks.append(AgentTask(
                id=f"task_{len(self.tasks) + len(tasks)}",
                description="Generera veckoplan",
                skill_name="generate_week_plan",
                context=context
            ))

        if "progress" in goal_lower or "utveckling" in goal_lower or "trend" in goal_lower:
            tasks.append(AgentTask(
                id=f"task_{len(self.tasks) + len(tasks)}",
                description="Analysera progression",
                skill_name="analyze_progress",
                context=context
            ))

        # Om inga specifika mål, kör daglig check
        if not tasks and ("daglig" in goal_lower or "check" in goal_lower or "kolla" in goal_lower):
            tasks.append(AgentTask(
                id=f"task_{len(self.tasks)}",
                description="Kontrollera ACWR",
                skill_name="check_acwr",
                context=context
            ))
            tasks.append(AgentTask(
                id=f"task_{len(self.tasks) + 1}",
                description="Hitta inaktiva",
                skill_name="check_inactive",
                context=context
            ))

        self.tasks.extend(tasks)

        # Logga planeringen
        self._log("plan", {
            "goal": goal,
            "tasks_created": len(tasks),
            "task_ids": [t.id for t in tasks]
        })

        return tasks

    def act(self, task: AgentTask) -> SkillResult:
        """
        ACT-fasen: Kör en skill.
        """
        task.status = "running"

        skill = SKILLS.get(task.skill_name)
        if not skill:
            result = SkillResult(
                success=False,
                message=f"Skill '{task.skill_name}' finns inte"
            )
            task.status = "failed"
            task.result = result
            return result

        try:
            result = skill.execute(task.context)
            task.result = result
            task.status = "completed" if result.success else "failed"
            task.completed_at = datetime.now().isoformat()

            self._log("act", {
                "task_id": task.id,
                "skill": task.skill_name,
                "success": result.success,
                "message": result.message
            })

            return result

        except Exception as e:
            result = SkillResult(success=False, message=f"Fel: {str(e)}")
            task.status = "failed"
            task.result = result
            return result

    def verify(self, task: AgentTask) -> bool:
        """
        VERIFY-fasen: Kontrollera om resultatet är OK.
        """
        if not task.result:
            return False

        # Enkel verifiering - lyckades skillen?
        verified = task.result.success

        self._log("verify", {
            "task_id": task.id,
            "verified": verified,
            "result_message": task.result.message
        })

        return verified

    def run(self, goal: str, context: dict = None) -> dict:
        """
        Kör hela agent-loopen för ett mål.

        Returns:
            dict med resultat från alla tasks
        """
        context = context or {}
        results = []

        # 1. PLAN
        tasks = self.plan(goal, context)

        if not tasks:
            return {
                "success": False,
                "message": f"Kunde inte skapa tasks för målet: {goal}",
                "results": []
            }

        # 2-4. ACT → VERIFY → REPEAT
        for iteration, task in enumerate(tasks):
            if iteration >= self.max_iterations:
                break

            # ACT
            result = self.act(task)

            # VERIFY
            verified = self.verify(task)

            results.append({
                "task_id": task.id,
                "description": task.description,
                "skill": task.skill_name,
                "success": result.success,
                "verified": verified,
                "message": result.message,
                "data": result.data
            })

        # Sammanfatta
        successful = sum(1 for r in results if r["success"])

        summary = {
            "success": successful == len(results),
            "message": f"Körde {len(results)} tasks, {successful} lyckades",
            "results": results,
            "execution_log": self.execution_log
        }

        # Spara till minnet
        save_memory("agent_runs", {
            "goal": goal,
            "summary": summary["message"],
            "timestamp": datetime.now().isoformat()
        })

        return summary

    def _log(self, phase: str, data: dict):
        """Logga till execution_log."""
        self.execution_log.append({
            "phase": phase,
            "timestamp": datetime.now().isoformat(),
            **data
        })


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

def run_agent(goal: str, context: dict = None) -> dict:
    """Kör agenten med ett mål."""
    agent = AgentLoop()
    return agent.run(goal, context)


def daily_check() -> dict:
    """Kör daglig automatisk check."""
    return run_agent("Kör daglig check av alla idrottare")


def get_available_skills() -> list[dict]:
    """Lista alla tillgängliga skills."""
    return [
        {"name": skill.name, "description": skill.description}
        for skill in SKILLS.values()
    ]


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    print("=== Agent Core Test ===\n")

    print("Tillgängliga skills:")
    for skill in get_available_skills():
        print(f"  - {skill['name']}: {skill['description']}")

    print("\n--- Kör daglig check ---")
    result = daily_check()
    print(f"Resultat: {result['message']}")

    for r in result['results']:
        print(f"  [{r['skill']}] {r['message']}")
        if r['data']:
            print(f"    Data: {json.dumps(r['data'], indent=2, ensure_ascii=False)[:200]}...")
