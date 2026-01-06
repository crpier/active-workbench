---
tags: []
---

# Active Workbench - Implementation Plan

**Created:** 2026-01-04
**Goal:** Build a practical knowledge management system focused on active work, not comprehensive knowledge archival

---

## Core Philosophy

> "Capture the messy process, compile when needed, write when ready"

**This is NOT**:
- A second brain with comprehensive linking and tagging
- A knowledge graph requiring constant curation
- A system that demands perfect categorization

**This IS**:
- A working memory extension for active projects
- A chronological capture system (daybook)
- A compilation tool (project logs)
- A writing workspace (ideas → drafts → published)

**Success = Daily Use, Not Feature Completion**

---

## Architecture Overview

### The Flow

```
Voice Capture (Pixel Watch)
    ↓
Google Assistant (transcription)
    ↓
Android App (minimal)
    ↓
Backend Service (FastAPI on VPS)
    ↓
Individual Note in limbo/
    ↓
Weekly Triage (Mobile or Desktop)
    ↓
Move to Daybook with [tags]
    ↓
Manual Compilation (wb compile)
    ↓
Project Logs / Writing Drafts
```

### Technology Stack

**Backend:**
- Python 3.12+ with `uv` package manager
- FastAPI for HTTP API
- Writes markdown files directly to vault
- Hosted on VPS (always accessible)
- Git auto-commit and push for sync

**Android App:**
- Kotlin + Jetpack Compose (minimal UI)
- Receives voice notes from Google Assistant
- POSTs to VPS backend
- ~200 lines of code total

**Frontend (Phase 2):**
- SolidJS + TanStack Start
- Mobile-first responsive design
- Tailwind CSS
- Simple, focused on triage workflow

**CLI Tool:**
- Python script (`wb`)
- Click framework for commands
- Lives in `~/bin/wb` or installed via pip

**Storage:**
- Vault: Standard markdown files
- Config: `~/.config/workbench/config.yaml`
- Git repository for sync

### Repository Structure

```
~/projects/workbench/
├── cli/
│   ├── src/
│   │   └── wb/
│   │       ├── __init__.py
│   │       ├── cli.py          # Click command definitions
│   │       ├── commands/       # Individual commands
│   │       │   ├── daybook.py
│   │       │   ├── projects.py
│   │       │   ├── writing.py
│   │       │   └── utils.py
│   │       ├── config.py       # Configuration management
│   │       └── vault.py        # Vault operations
│   ├── pyproject.toml
│   └── README.md
│
├── backend/
│   ├── src/
│   │   ├── api/           # FastAPI routes
│   │   ├── services/      # Note creation, vault writer
│   │   └── models/        # Data models
│   ├── pyproject.toml
│   └── README.md
│
├── frontend/              # Phase 2
│   ├── src/
│   │   ├── routes/        # TanStack Start routes
│   │   ├── components/    # SolidJS components
│   │   └── lib/           # Utilities
│   └── package.json
│
└── android/               # Phase 1
    └── app/src/main/kotlin/
        └── com/workbench/capture/

~/vault/                   # Your actual vault
├── daybook/
├── projects/
├── writing/
├── limbo/
└── templates/
```

---

## Phase 0: CLI + Manual Workflow (Week 1-2)

**Goal:** Start using the system daily with zero automation

### What You'll Build

#### 1. The `wb` CLI Tool (Python)

**Core Commands:**

```bash
wb today              # Open today's daybook
wb yesterday          # Open yesterday's daybook
wb new <project>      # Create new project
wb list               # Show active projects
wb compile <project>  # Extract [project] entries to log
wb solve [project]    # Mark as solved (interactive)
wb block [project]    # Move to hiatus (interactive)
wb resume <project>   # Move from hiatus to ongoing
wb write <title>      # Create/open writing draft
wb ideas              # Open writing ideas
wb publish <title>    # Move draft to published
wb inbox              # Open limbo/Inbox.md
wb triage             # Open limbo/ directory
wb search <term>      # Grep across daybook
wb status             # Show dashboard
```

**Project Structure:**

```
cli/
├── src/
│   └── wb/
│       ├── __init__.py
│       ├── cli.py              # Main CLI entry point
│       ├── config.py           # Configuration management
│       ├── vault.py            # Vault path operations
│       └── commands/
│           ├── __init__.py
│           ├── daybook.py      # today, yesterday commands
│           ├── projects.py     # new, list, compile, solve, block
│           ├── writing.py      # write, ideas, publish
│           └── search.py       # search, triage, inbox
├── pyproject.toml
└── README.md
```

**Dependencies:**

```toml
[project]
name = "wb"
version = "0.1.0"
description = "Workbench CLI for knowledge management"
requires-python = ">=3.12"
dependencies = [
    "click>=8.1.0",
    "pyyaml>=6.0",
    "rich>=13.0.0",  # For nice terminal output
]

[project.scripts]
wb = "wb.cli:main"
```

**Full implementation code provided in appendix below**

#### 2. Templates

Create initial templates in `~/vault/templates/`:

**`daybook.md`:**
```markdown
---
tags: []
---

# YYYY-MM-DD

## Standup
- **Yesterday**:
- **Today**:
- **Blockers**:

## Priority Tasks
- [ ]

## Engineering Log (UTC)
- HH:MM

## Code Reviews / PRs
- [ ]

## Notes & Links
-
```

**`project.md`:**
```markdown
# Project Name

**Started:** YYYY-MM-DD
**Status:** ongoing
**Goal:**
**Last updated:** YYYY-MM-DD

---

## Compiled Log

(No entries yet)

---

## Key Insights

```

#### 3. Initial Setup

```bash
# Create workbench project directory
mkdir -p ~/projects/workbench/cli
cd ~/projects/workbench/cli

# Initialize Python project with uv
uv init
# Create src/wb/ structure and implement commands

# Install in development mode
uv pip install -e .

# Initialize vault structure
wb --init  # Creates directories and templates
```

### Usage Workflow: Week 1

**Day 1: Setup**

```bash
# Install wb
cd ~/projects/workbench/cli
uv pip install -e .

# Initialize vault
wb --init

# Create first daybook
wb today

# Write first entry:
# 10:30 [setup-workbench]
# Setting up the workbench system. Created CLI tool and templates.
```

**Day 2-7: Daily Practice**

**Morning:**
```bash
wb today
# Fill in standup section
# Log work as you go
```

**Throughout day:**
```markdown
## Engineering Log (UTC)
- 10:30 [learn-keyboard]
  Started learning keyboard. Finger positioning is confusing.

- 14:00 [fix-auth-bug]
  Production bug. Users getting logged out. Investigating.

- 16:00 [essay-python-typing]
  Interesting insight about NewType vs TypeAlias. Should write about this.
```

**End of day:**
- Mark completed tasks
- Note what to do tomorrow
- Close daybook

**Sunday (Week 1):**
```bash
# Create projects for the week's tagged entries
wb new learn-keyboard
wb new fix-auth-bug
wb new essay-python-typing

# Compile logs
wb compile learn-keyboard
wb compile fix-auth-bug
wb compile essay-python-typing

# Review compiled logs
# See the full story of each project
```

### Success Metrics: Phase 0

**Week 1:**
- ✅ Opened daybook 5+ days
- ✅ Created 2-3 projects
- ✅ Tagged entries with [project-name]
- ✅ Comfortable with wb commands

**Week 2:**
- ✅ Daily daybook is automatic (no friction)
- ✅ Compiled at least 2 projects
- ✅ Sunday review workflow established
- ✅ System feels useful, not burdensome

**Ready for Phase 1 when:**
- Daybook habit is solid (daily use)
- You understand your project workflow
- You're frustrated by manual capture (ready for voice notes)

---

## Phase 1: Voice Capture Backend (Week 3-4)

**Goal:** Capture voice notes from watch → individual notes in limbo

### What You'll Build

#### 1. Backend Service

**Project Structure:**

```
backend/
├── src/
│   ├── api/
│   │   ├── __init__.py
│   │   └── capture.py      # Voice note endpoint
│   ├── services/
│   │   ├── __init__.py
│   │   ├── vault_writer.py # Write to limbo/
│   │   └── git_sync.py     # Auto-commit and push
│   ├── models/
│   │   ├── __init__.py
│   │   └── capture.py      # Request/response models
│   ├── config.py           # Load config.yaml
│   └── main.py             # FastAPI app
├── pyproject.toml
└── README.md
```

**Dependencies:**

```toml
[project]
name = "workbench-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "pydantic>=2.5.0",
    "pyyaml>=6.0",
]
```

**Key implementation code provided in appendix below**

#### 2. Android App (Minimal)

**`MainActivity.kt`:**

```kotlin
package com.workbench.capture

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import android.widget.Toast

class MainActivity : ComponentActivity() {
    private val apiClient = ApiClient()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        when (intent?.action) {
            Intent.ACTION_SEND -> {
                val text = intent.getStringExtra(Intent.EXTRA_TEXT)
                if (text != null) {
                    lifecycleScope.launch {
                        captureNote(text)
                    }
                }
            }
        }
    }

    private suspend fun captureNote(text: String) {
        try {
            val response = apiClient.captureNote(text)
            if (response.isSuccessful) {
                Toast.makeText(this, "Note captured!", Toast.LENGTH_SHORT).show()
                finish()
            } else {
                Toast.makeText(this, "Failed to capture note", Toast.LENGTH_SHORT).show()
            }
        } catch (e: Exception) {
            Toast.makeText(this, "Error: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }
}
```

#### 3. VPS Deployment

**Systemd Service:**

```ini
[Unit]
Description=Workbench Backend
After=network.target

[Service]
Type=simple
User=vault
WorkingDirectory=/home/vault/workbench/backend
ExecStart=/home/vault/.local/bin/uv run uvicorn src.main:app --host 0.0.0.0 --port 8765
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Usage Workflow: Phase 1

**Voice Note Capture:**
1. Tap watch: "Hey Google, take a note"
2. Say: "Keyboard practice tip keep wrists elevated"
3. Select "Workbench" from picker
4. See "Note captured!" toast

**What happens:**
- Individual note created: `limbo/2026-01-04-143022-keyboard-practice-tip.md`
- Git auto-commits and pushes
- Desktop pulls to sync

**Sunday Triage:**

```bash
# Pull latest notes
cd ~/vault && git pull

# Open limbo directory
wb triage

# For each note:
# 1. Read content
# 2. Copy to daybook with [tag]
# 3. Delete from limbo

wb compile learn-keyboard  # Update project log
```

### Success Metrics: Phase 1

**Week 3:**
- ✅ Backend running on VPS
- ✅ Android app installed and configured
- ✅ Captured 3+ voice notes
- ✅ Individual notes appearing in limbo/

**Week 4:**
- ✅ Voice capture feels natural (< 10 seconds)
- ✅ Weekly triage workflow established
- ✅ Git sync working reliably

---

## Phase 2: Minimal Mobile Triage UI (Week 5-8)

**Goal:** Process limbo notes on tablet via web interface

### What You'll Build

**Technology:**
- SolidJS + TanStack Start
- Tailwind CSS
- Mobile-first responsive design

**Features:**
- List limbo notes
- Move to daybook with [tag]
- Delete notes
- Simple, focused UI

**Routes:**
- `/triage` - Main triage interface
- `/api/notes` - List limbo notes
- `/api/move` - Move note to daybook
- `/api/delete` - Delete note

### Implementation

**`src/routes/triage.tsx`:**

```tsx
import { createSignal, For, Show } from "solid-js";
import { createAsync } from "@solidjs/router";
import { NoteCard } from "~/components/NoteCard";

export default function Triage() {
  const notes = createAsync(() => fetchLimboNotes());

  return (
    <div class="max-w-2xl mx-auto p-4">
      <header class="mb-6">
        <h1 class="text-3xl font-bold">Triage</h1>
        <p class="text-gray-600">
          {notes()?.length || 0} notes to process
        </p>
      </header>

      <For each={notes()}>
        {(note) => (
          <NoteCard note={note} />
        )}
      </For>

      <Show when={notes()?.length === 0}>
        <p class="text-center py-12 text-xl text-gray-500">
          All caught up! 🎉
        </p>
      </Show>
    </div>
  );
}
```

**Backend API Endpoints:**

```python
@router.get("/api/triage/notes")
async def list_limbo_notes():
    """List all notes in limbo/"""
    # Implementation: scan limbo/ directory, return note metadata
    pass

@router.post("/api/triage/move")
async def move_to_daybook(request: MoveToDaybookRequest):
    """Move note from limbo to today's daybook with tag"""
    # Implementation: read note, append to daybook, delete from limbo
    pass

@router.delete("/api/triage/notes/{note_id}")
async def delete_note(note_id: str):
    """Delete note from limbo"""
    # Implementation: delete file from limbo/
    pass
```

### Usage Workflow: Phase 2

**Sunday Morning Triage:**
1. Wake up, grab tablet
2. Open: `https://vault.yourdomain.com/triage`
3. For each note:
   - Read → Add tag → Move to daybook
   - Or delete
4. Done when "0 notes remaining"

### Success Metrics: Phase 2

**Week 5-6:**
- ✅ Frontend running locally
- ✅ Can view/move/delete notes
- ✅ Mobile UI feels natural

**Week 7-8:**
- ✅ Deployed to VPS
- ✅ Sunday triage on tablet
- ✅ Processing 10+ notes/week via UI

---

## Phase 3: Iteration & Refinement (Ongoing)

**Goal:** Improve based on real usage

### Potential Enhancements

**Add features when:**
1. Pain point felt 3+ times
2. Manual workflow is genuinely tedious
3. Feature solves real problem
4. Simple implementation (< 2 weeks)

**Possible additions:**
- AI-assisted compilation
- Better search interface
- Writing support tools
- Weekly review dashboard
- Push notifications

---

## Summary

### What You Get

**Phase 0 (Weeks 1-2):**
- Daily daybook habit
- Python CLI tool
- Manual compilation
- Understanding of needs

**Phase 1 (Weeks 3-4):**
- Voice capture → limbo
- Backend on VPS
- Android app
- Git auto-sync

**Phase 2 (Weeks 5-8):**
- Mobile triage UI
- Process notes on tablet
- Complete workflow

**End State:**
A practical system that captures thoughts, organizes via triage, compiles into logs, and supports writing—all feeling lightweight and natural.

---

## Appendix: Full Implementation Code

### CLI Tool Implementation

See separate implementation files for:
- `config.py` - Configuration management
- `vault.py` - Vault operations
- `commands/daybook.py` - Daybook commands
- `commands/projects.py` - Project management
- `commands/writing.py` - Writing workflow
- `cli.py` - Main entry point

### Backend Implementation

See separate implementation files for:
- `services/vault_writer.py` - Note creation
- `services/git_sync.py` - Git automation
- `api/capture.py` - Capture endpoint
- `main.py` - FastAPI app

(Full code examples provided in earlier sections)
