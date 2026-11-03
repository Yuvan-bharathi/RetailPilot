# Setting up Claude Code in Antigravity

Antigravity is a VS Code-based editor, so Claude Code runs there either as the extension or as the CLI in the
integrated terminal. Official guide: https://code.claude.com/docs/en/vs-code.md

## 1. Prerequisites on your machine
- Git, Docker Desktop (for PostgreSQL + Redis), Node.js 20+, Python 3.12, `uv` (https://docs.astral.sh/uv/)
- A Claude account with Claude Code access (Pro/Max/Team/Enterprise) or an Anthropic API key

## 2. Install Claude Code
Option A — extension (recommended)
1. In Antigravity open the Extensions view (Ctrl+Shift+X / Cmd+Shift+X), search **"Claude Code"** (publisher Anthropic), Install.
2. If it does not appear, install it from the Open VSX registry: https://open-vsx.org/extension/Anthropic/claude-code
3. Open the Claude Code panel and sign in through the browser.

Option B — CLI in the integrated terminal (if the extension cannot be installed)
- macOS / Linux / WSL: `curl -fsSL https://claude.ai/install.sh | bash`
- Windows: follow the Windows instructions on https://code.claude.com/docs (setup page)
- Then in Antigravity's terminal, inside the project folder: `claude` → sign in.
Check with `claude --version`.

## 3. Put the starter kit in a repository
```
unzip RetailPilot_AI_Claude_Code_Starter_Kit.zip
cd retailpilot-ai
git init && git add . && git commit -m "docs: frozen design v2.2, diagrams v3, Claude Code instructions"
```
Open the `retailpilot-ai` folder in Antigravity (File → Open Folder). Claude Code loads `CLAUDE.md` from the
project root automatically at the start of every session; run `/memory` to confirm it is loaded.

## 4. Start development
1. Open `PROMPTS.md`, copy the Phase 0 prompt into Claude Code. Read its summary and answer its questions.
2. For each phase: new session (`/clear`) → plan mode → approve plan → implement → run checks → review diff → commit.
   (In the terminal, Shift+Tab cycles permission modes including plan mode; the extension has a plan review view.)
3. Keep permission prompts on for shell commands until the project is stable; allow-list safe commands
   (pytest, ruff, npm run lint) as you go.

## 5. Tips that matter for this project
- Do not let two AI agents edit the same files at once: if you also use Antigravity's built-in agent,
  give it a different task or branch.
- One phase per branch (`git switch -c phase-3-tools`) makes review and rollback easy.
- When Claude makes a mistake that should never repeat, add one short bullet to CLAUDE.md
  (keep CLAUDE.md short — long files reduce how well it is followed; details stay in docs/).
- Never paste real client data or secrets into prompts; use `.env` (git-ignored) and synthetic data.
