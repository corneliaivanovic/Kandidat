const pptxgen = require("pptxgenjs");

let pres = new pptxgen();
pres.layout = 'LAYOUT_16x9';
pres.author = 'Grupp X';
pres.title = 'AI Agent-arkitektur för Träningsplattformen';

// Färgpalett - Midnight Executive
const COLORS = {
  primary: "1E2761",      // Navy
  secondary: "CADCFC",    // Ice blue
  accent: "6366F1",       // Indigo
  white: "FFFFFF",
  dark: "1E293B",
  gray: "64748B",
  lightBg: "F8FAFC",
  success: "22C55E"
};

// ============================================================
// SLIDE 1: Titel
// ============================================================
let slide1 = pres.addSlide();
slide1.background = { color: COLORS.primary };

slide1.addText("AI Agent-arkitektur", {
  x: 0.5, y: 1.8, w: 9, h: 1,
  fontSize: 44, fontFace: "Arial", bold: true,
  color: COLORS.white
});

slide1.addText("Inspirerad av OpenClaw", {
  x: 0.5, y: 2.8, w: 9, h: 0.6,
  fontSize: 28, fontFace: "Arial",
  color: COLORS.secondary
});

slide1.addText("Träningsplattformen - Kandidatarbete VT 2026", {
  x: 0.5, y: 4.5, w: 9, h: 0.5,
  fontSize: 16, fontFace: "Arial",
  color: COLORS.secondary
});

// ============================================================
// SLIDE 2: Vad är OpenClaw?
// ============================================================
let slide2 = pres.addSlide();
slide2.background = { color: COLORS.lightBg };

slide2.addText("Vad är OpenClaw?", {
  x: 0.5, y: 0.3, w: 9, h: 0.8,
  fontSize: 36, fontFace: "Arial", bold: true,
  color: COLORS.dark
});

// Key facts box
slide2.addShape(pres.shapes.RECTANGLE, {
  x: 0.5, y: 1.2, w: 4.3, h: 3.8,
  fill: { color: COLORS.white },
  line: { color: "E2E8F0", width: 1 }
});

slide2.addText("Open-source AI Agent", {
  x: 0.7, y: 1.3, w: 4, h: 0.5,
  fontSize: 18, fontFace: "Arial", bold: true,
  color: COLORS.accent
});

slide2.addText([
  { text: "145,000+ GitHub-stjärnor", options: { bullet: true, breakLine: true } },
  { text: "Viral januari 2026", options: { bullet: true, breakLine: true } },
  { text: "Kör lokalt på din maskin", options: { bullet: true, breakLine: true } },
  { text: "Kan faktiskt GÖRA saker", options: { bullet: true, breakLine: true } },
  { text: "Multi-kanal (WhatsApp, Slack...)", options: { bullet: true } }
], {
  x: 0.7, y: 1.9, w: 4, h: 2.8,
  fontSize: 14, fontFace: "Arial",
  color: COLORS.dark
});

// Vs vårt
slide2.addShape(pres.shapes.RECTANGLE, {
  x: 5.2, y: 1.2, w: 4.3, h: 3.8,
  fill: { color: COLORS.white },
  line: { color: "E2E8F0", width: 1 }
});

slide2.addText("Vår implementation", {
  x: 5.4, y: 1.3, w: 4, h: 0.5,
  fontSize: 18, fontFace: "Arial", bold: true,
  color: COLORS.success
});

slide2.addText([
  { text: "Samma arkitektur-principer", options: { bullet: true, breakLine: true } },
  { text: "Anpassat för träningsdomänen", options: { bullet: true, breakLine: true } },
  { text: "Integrerat i vår Flask-app", options: { bullet: true, breakLine: true } },
  { text: "Skills för ACWR, planering", options: { bullet: true, breakLine: true } },
  { text: "Proof-of-concept", options: { bullet: true } }
], {
  x: 5.4, y: 1.9, w: 4, h: 2.8,
  fontSize: 14, fontFace: "Arial",
  color: COLORS.dark
});

// ============================================================
// SLIDE 3: Agent Loop - Kärnan
// ============================================================
let slide3 = pres.addSlide();
slide3.background = { color: COLORS.lightBg };

slide3.addText("Agent Loop - Kärnan", {
  x: 0.5, y: 0.3, w: 9, h: 0.8,
  fontSize: 36, fontFace: "Arial", bold: true,
  color: COLORS.dark
});

// Flow boxes
const flowY = 1.8;
const boxW = 2;
const boxH = 1.8;
const gap = 0.3;

// PLAN
slide3.addShape(pres.shapes.RECTANGLE, {
  x: 0.5, y: flowY, w: boxW, h: boxH,
  fill: { color: COLORS.accent }
});
slide3.addText("🎯", { x: 0.5, y: flowY + 0.2, w: boxW, h: 0.6, fontSize: 28, align: "center" });
slide3.addText("PLAN", { x: 0.5, y: flowY + 0.7, w: boxW, h: 0.4, fontSize: 18, bold: true, align: "center", color: COLORS.white });
slide3.addText("Bryt ner mål\ni tasks", { x: 0.5, y: flowY + 1.1, w: boxW, h: 0.6, fontSize: 12, align: "center", color: COLORS.secondary });

// Arrow 1
slide3.addText("→", { x: 2.5 + gap/2, y: flowY + 0.6, w: 0.5, h: 0.5, fontSize: 32, color: COLORS.gray });

// ACT
slide3.addShape(pres.shapes.RECTANGLE, {
  x: 3, y: flowY, w: boxW, h: boxH,
  fill: { color: COLORS.accent }
});
slide3.addText("⚡", { x: 3, y: flowY + 0.2, w: boxW, h: 0.6, fontSize: 28, align: "center" });
slide3.addText("ACT", { x: 3, y: flowY + 0.7, w: boxW, h: 0.4, fontSize: 18, bold: true, align: "center", color: COLORS.white });
slide3.addText("Kör relevant\nskill", { x: 3, y: flowY + 1.1, w: boxW, h: 0.6, fontSize: 12, align: "center", color: COLORS.secondary });

// Arrow 2
slide3.addText("→", { x: 5 + gap/2, y: flowY + 0.6, w: 0.5, h: 0.5, fontSize: 32, color: COLORS.gray });

// VERIFY
slide3.addShape(pres.shapes.RECTANGLE, {
  x: 5.5, y: flowY, w: boxW, h: boxH,
  fill: { color: COLORS.accent }
});
slide3.addText("✓", { x: 5.5, y: flowY + 0.2, w: boxW, h: 0.6, fontSize: 28, align: "center" });
slide3.addText("VERIFY", { x: 5.5, y: flowY + 0.7, w: boxW, h: 0.4, fontSize: 18, bold: true, align: "center", color: COLORS.white });
slide3.addText("Kontrollera\nresultat", { x: 5.5, y: flowY + 1.1, w: boxW, h: 0.6, fontSize: 12, align: "center", color: COLORS.secondary });

// Arrow 3
slide3.addText("→", { x: 7.5 + gap/2, y: flowY + 0.6, w: 0.5, h: 0.5, fontSize: 32, color: COLORS.gray });

// REPEAT
slide3.addShape(pres.shapes.RECTANGLE, {
  x: 8, y: flowY, w: boxW, h: boxH,
  fill: { color: COLORS.accent }
});
slide3.addText("🔄", { x: 8, y: flowY + 0.2, w: boxW, h: 0.6, fontSize: 28, align: "center" });
slide3.addText("REPEAT", { x: 8, y: flowY + 0.7, w: boxW, h: 0.4, fontSize: 18, bold: true, align: "center", color: COLORS.white });
slide3.addText("Iterera vid\nbehov", { x: 8, y: flowY + 1.1, w: boxW, h: 0.6, fontSize: 12, align: "center", color: COLORS.secondary });

// Explanation
slide3.addText("Till skillnad från vanlig AI-chat som bara svarar med text, kan en agent faktiskt utföra handlingar och iterera tills målet är uppnått.", {
  x: 0.5, y: 4.2, w: 9, h: 0.8,
  fontSize: 14, fontFace: "Arial", italics: true,
  color: COLORS.gray
});

// ============================================================
// SLIDE 4: Brain, Hands, Memory
// ============================================================
let slide4 = pres.addSlide();
slide4.background = { color: COLORS.lightBg };

slide4.addText("Arkitektur: Brain, Hands, Memory", {
  x: 0.5, y: 0.3, w: 9, h: 0.8,
  fontSize: 36, fontFace: "Arial", bold: true,
  color: COLORS.dark
});

// Three columns
const colW = 2.8;
const colH = 3.2;
const colY = 1.3;

// BRAIN
slide4.addShape(pres.shapes.RECTANGLE, {
  x: 0.7, y: colY, w: colW, h: colH,
  fill: { color: COLORS.white },
  line: { color: COLORS.accent, width: 2 }
});
slide4.addText("🧠 BRAIN", {
  x: 0.7, y: colY + 0.2, w: colW, h: 0.5,
  fontSize: 20, bold: true, align: "center", color: COLORS.accent
});
slide4.addText("LLM (Claude)", {
  x: 0.7, y: colY + 0.7, w: colW, h: 0.4,
  fontSize: 14, align: "center", color: COLORS.dark
});
slide4.addText([
  { text: "Bestämmer vilka skills", options: { bullet: true, breakLine: true } },
  { text: "Planerar sekvensen", options: { bullet: true, breakLine: true } },
  { text: "Tolkar resultat", options: { bullet: true } }
], {
  x: 0.9, y: colY + 1.2, w: colW - 0.4, h: 1.8,
  fontSize: 12, color: COLORS.dark
});

// HANDS
slide4.addShape(pres.shapes.RECTANGLE, {
  x: 3.7, y: colY, w: colW, h: colH,
  fill: { color: COLORS.white },
  line: { color: COLORS.success, width: 2 }
});
slide4.addText("🖐️ HANDS", {
  x: 3.7, y: colY + 0.2, w: colW, h: 0.5,
  fontSize: 20, bold: true, align: "center", color: COLORS.success
});
slide4.addText("Skills (moduler)", {
  x: 3.7, y: colY + 0.7, w: colW, h: 0.4,
  fontSize: 14, align: "center", color: COLORS.dark
});
slide4.addText([
  { text: "check_acwr", options: { bullet: true, breakLine: true } },
  { text: "check_inactive", options: { bullet: true, breakLine: true } },
  { text: "generate_week_plan", options: { bullet: true, breakLine: true } },
  { text: "analyze_progress", options: { bullet: true } }
], {
  x: 3.9, y: colY + 1.2, w: colW - 0.4, h: 1.8,
  fontSize: 12, color: COLORS.dark, fontFace: "Consolas"
});

// MEMORY
slide4.addShape(pres.shapes.RECTANGLE, {
  x: 6.7, y: colY, w: colW, h: colH,
  fill: { color: COLORS.white },
  line: { color: "F59E0B", width: 2 }
});
slide4.addText("💾 MEMORY", {
  x: 6.7, y: colY + 0.2, w: colW, h: 0.5,
  fontSize: 20, bold: true, align: "center", color: "F59E0B"
});
slide4.addText("JSONL-filer", {
  x: 6.7, y: colY + 0.7, w: colW, h: 0.4,
  fontSize: 14, align: "center", color: COLORS.dark
});
slide4.addText([
  { text: "Sparar kontext", options: { bullet: true, breakLine: true } },
  { text: "Historik per idrottare", options: { bullet: true, breakLine: true } },
  { text: "Persisterar mellan sessioner", options: { bullet: true } }
], {
  x: 6.9, y: colY + 1.2, w: colW - 0.4, h: 1.8,
  fontSize: 12, color: COLORS.dark
});

// ============================================================
// SLIDE 5: Våra Skills
// ============================================================
let slide5 = pres.addSlide();
slide5.background = { color: COLORS.lightBg };

slide5.addText("Implementerade Skills", {
  x: 0.5, y: 0.3, w: 9, h: 0.8,
  fontSize: 36, fontFace: "Arial", bold: true,
  color: COLORS.dark
});

// Skills grid 2x2
const skills = [
  { name: "check_acwr", desc: "Kontrollerar alla idrottares ACWR och flaggar överträningsrisk. Varnar när ACWR > 1.5", color: "EF4444" },
  { name: "check_inactive", desc: "Hittar idrottare som inte loggat på 3+ dagar. Proaktiv uppföljning.", color: "F59E0B" },
  { name: "generate_week_plan", desc: "AI-genererar veckoplan baserat på historik, belastning och skador.", color: COLORS.success },
  { name: "analyze_progress", desc: "Analyserar trender över tid - ökande/stabil/minskande belastning.", color: COLORS.accent }
];

const gridX = [0.5, 5];
const gridY = [1.2, 3];

skills.forEach((skill, i) => {
  const x = gridX[i % 2];
  const y = gridY[Math.floor(i / 2)];

  slide5.addShape(pres.shapes.RECTANGLE, {
    x: x, y: y, w: 4.3, h: 1.5,
    fill: { color: COLORS.white },
    line: { color: "E2E8F0", width: 1 }
  });

  // Accent bar
  slide5.addShape(pres.shapes.RECTANGLE, {
    x: x, y: y, w: 0.08, h: 1.5,
    fill: { color: skill.color }
  });

  slide5.addText(skill.name, {
    x: x + 0.2, y: y + 0.15, w: 4, h: 0.4,
    fontSize: 16, bold: true, fontFace: "Consolas",
    color: COLORS.dark
  });

  slide5.addText(skill.desc, {
    x: x + 0.2, y: y + 0.55, w: 4, h: 0.9,
    fontSize: 12, color: COLORS.gray
  });
});

// ============================================================
// SLIDE 6: Skillnad mot vanlig AI
// ============================================================
let slide6 = pres.addSlide();
slide6.background = { color: COLORS.lightBg };

slide6.addText("Agent vs Vanlig AI-chat", {
  x: 0.5, y: 0.3, w: 9, h: 0.8,
  fontSize: 36, fontFace: "Arial", bold: true,
  color: COLORS.dark
});

// Table
slide6.addTable([
  [
    { text: "Aspekt", options: { bold: true, fill: { color: COLORS.primary }, color: COLORS.white } },
    { text: "Vanlig AI (ChatGPT)", options: { bold: true, fill: { color: COLORS.primary }, color: COLORS.white } },
    { text: "AI Agent", options: { bold: true, fill: { color: COLORS.primary }, color: COLORS.white } }
  ],
  ["Initiativ", "Väntar på fråga", "Agerar proaktivt"],
  ["Output", "Endast text", "Text + handlingar"],
  ["Verktyg", "Inga", "Skills, API:er, filer"],
  ["Iteration", "En fråga = ett svar", "Loopar tills klart"],
  ["Minne", "Per session", "Persistent"],
  ["Exempel", "\"ACWR är 1.6\"", "\"ACWR=1.6, justerar planen\""]
], {
  x: 0.5, y: 1.2, w: 9, h: 3.5,
  colW: [2, 3.5, 3.5],
  border: { pt: 0.5, color: "E2E8F0" },
  fontFace: "Arial",
  fontSize: 12,
  color: COLORS.dark,
  valign: "middle"
});

// ============================================================
// SLIDE 7: Kod-exempel
// ============================================================
let slide7 = pres.addSlide();
slide7.background = { color: COLORS.dark };

slide7.addText("Kod: Agent Loop", {
  x: 0.5, y: 0.3, w: 9, h: 0.6,
  fontSize: 28, fontFace: "Arial", bold: true,
  color: COLORS.white
});

const codeText = `class AgentLoop:
    def run(self, goal: str, context: dict):
        # 1. PLAN - Bryt ner målet i tasks
        tasks = self.plan(goal, context)

        for task in tasks:
            # 2. ACT - Kör skill
            result = self.act(task)

            # 3. VERIFY - Kontrollera
            verified = self.verify(task)

            # 4. REPEAT - Fortsätt loopen

        return summary`;

slide7.addText(codeText, {
  x: 0.5, y: 1.0, w: 9, h: 4,
  fontSize: 14, fontFace: "Consolas",
  color: COLORS.secondary,
  valign: "top"
});

// ============================================================
// SLIDE 8: Nästa steg
// ============================================================
let slide8 = pres.addSlide();
slide8.background = { color: COLORS.lightBg };

slide8.addText("Nästa Steg", {
  x: 0.5, y: 0.3, w: 9, h: 0.8,
  fontSize: 36, fontFace: "Arial", bold: true,
  color: COLORS.dark
});

slide8.addText([
  { text: "Möjliga vidareutvecklingar:", options: { bold: true, breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "WhatsApp/Telegram-integration", options: { bullet: true, breakLine: true } },
  { text: "Schemalagda checks (cron-jobb)", options: { bullet: true, breakLine: true } },
  { text: "Fler skills (nutrition, tester, periodisering)", options: { bullet: true, breakLine: true } },
  { text: "Sub-agents för parallella tasks", options: { bullet: true, breakLine: true } },
  { text: "Utökad LLM-planering (låt AI välja skills)", options: { bullet: true } }
], {
  x: 0.5, y: 1.2, w: 5, h: 3.5,
  fontSize: 16, color: COLORS.dark
});

// Key insight box
slide8.addShape(pres.shapes.RECTANGLE, {
  x: 5.8, y: 1.2, w: 3.7, h: 2.5,
  fill: { color: COLORS.accent }
});

slide8.addText("💡 Insikt", {
  x: 6, y: 1.4, w: 3.3, h: 0.5,
  fontSize: 18, bold: true, color: COLORS.white
});

slide8.addText("Vi behöver inte bygga OpenClaw - vi kan använda samma arkitektur-principer i vår domän.", {
  x: 6, y: 1.9, w: 3.3, h: 1.5,
  fontSize: 14, color: COLORS.white
});

// ============================================================
// SLIDE 9: Sammanfattning
// ============================================================
let slide9 = pres.addSlide();
slide9.background = { color: COLORS.primary };

slide9.addText("Sammanfattning", {
  x: 0.5, y: 0.5, w: 9, h: 0.8,
  fontSize: 36, fontFace: "Arial", bold: true,
  color: COLORS.white
});

slide9.addText([
  { text: "Vi har byggt en OpenClaw-inspirerad agent-modul", options: { bullet: true, breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "Agent Loop: Plan → Act → Verify → Repeat", options: { bullet: true, breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "Skills: check_acwr, check_inactive, generate_week_plan, analyze_progress", options: { bullet: true, breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "Memory: JSONL för persistent kontext", options: { bullet: true, breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "Integrerat i vår Flask-app med dashboard", options: { bullet: true } }
], {
  x: 0.5, y: 1.5, w: 9, h: 3.5,
  fontSize: 18, color: COLORS.white
});

slide9.addText("Testa: http://localhost:5000/agent", {
  x: 0.5, y: 4.8, w: 9, h: 0.5,
  fontSize: 16, fontFace: "Consolas",
  color: COLORS.secondary
});

// Save
pres.writeFile({ fileName: "/sessions/affectionate-sweet-cerf/mnt/Idrottsapp - Prototyp/AI_Agent_Presentation.pptx" })
  .then(() => console.log("Presentation skapad!"))
  .catch(err => console.error(err));
