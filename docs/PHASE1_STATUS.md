# Phase 1: Voice Capture Backend - STATUS

## ✅ Completed

### Backend Service
- [x] FastAPI application created
- [x] VaultWriter service (creates individual notes in limbo/)
- [x] GitSync service (auto-commit and push)
- [x] Capture endpoint (`/api/capture`)
- [x] Health check endpoint (`/api/health`)
- [x] Configuration system
- [x] Logging
- [x] CORS middleware
- [x] Background tasks for git sync

**Location**: `~/Projects/active-workbench/backend/`

**Test Results**:
```bash
# Health check: ✅
curl http://localhost:8765/api/health
# Returns: {"status":"ok","service":"workbench-backend","version":"0.1.0"}

# Capture test: ✅
curl -X POST http://localhost:8765/api/capture \
  -H "Content-Type: application/json" \
  -d '{"text": "Test voice note about keyboard practice keep wrists elevated"}'
# Returns: {"status":"captured","note_id":"...","note_path":"limbo/..."}

# Note created: ✅
# File: limbo/2026-01-04-202527-test-voice-note-about-keyboard-practice-keep-wrist.md
# Contains proper frontmatter and content
```

### Deployment Files
- [x] Systemd service file (`workbench.service`)
- [x] Deployment guide (`DEPLOYMENT.md`)
- [x] Local test script (`test_local.sh`)

## 🚧 Next Steps

### Android App (Minimal)
**Goal**: Capture voice notes from Google Assistant and send to backend

**What to Build**:
1. Kotlin Android app
2. Receives `ACTION_SEND` intent from Google Assistant
3. POSTs to backend endpoint
4. Shows "Note captured!" toast
5. ~200 lines of code

**Project Location**: `~/Projects/active-workbench/android/`

**Files Needed**:
- `app/src/main/kotlin/com/workbench/capture/MainActivity.kt`
- `app/src/main/kotlin/com/workbench/capture/ApiClient.kt`
- `app/src/main/AndroidManifest.xml`
- `app/build.gradle.kts`

**Key Dependencies**:
- `io.ktor:ktor-client-android` - HTTP client
- `org.jetbrains.kotlinx:kotlinx-serialization-json` - JSON serialization

**Intent Filter** (for receiving voice notes):
```xml
<intent-filter>
    <action android:name="android.intent.action.SEND" />
    <category android:name="android.intent.category.DEFAULT" />
    <data android:mimeType="text/plain" />
</intent-filter>
```

**Workflow**:
1. User: "Hey Google, take a note"
2. User: Says note content
3. Google Assistant shows picker
4. User selects "Workbench"
5. App receives text via `ACTION_SEND`
6. App POSTs to `https://vault.yourdomain.com:8765/api/capture`
7. Shows toast: "Note captured!"
8. Done

### VPS Deployment
**When to do**: After Android app is built and tested

**Steps**:
1. Follow `DEPLOYMENT.md`
2. Setup VPS with systemd service
3. Configure domain/SSL (optional but recommended)
4. Test from Android app
5. Setup git auto-sync

## 📊 Current State

**Working**:
- ✅ CLI tool (`wb`) for local workflow
- ✅ Backend API for voice capture
- ✅ Individual note creation in limbo/
- ✅ Git auto-commit (if vault is git repo)
- ✅ Local testing

**Ready for**:
- 🔨 Android app development
- 🔨 VPS deployment

**Then you'll have**:
- Voice notes from watch → Backend → Limbo
- Weekly triage (desktop or mobile)
- Compilation into project logs
- Writing workflow

## 🧪 Testing the Backend

### Local Testing
```bash
# Run test script
~/Projects/active-workbench/backend/test_local.sh

# Or manually:
cd ~/Projects/active-workbench/backend
.venv/bin/uvicorn src.main:app --reload --host 0.0.0.0 --port 8765

# In another terminal:
curl http://localhost:8765/api/health
curl -X POST http://localhost:8765/api/capture \
  -H "Content-Type: application/json" \
  -d '{"text": "Your test note here"}'

# Check result:
ls ~/vault/limbo/
```

### What to Expect
- Note file created in `~/vault/limbo/`
- Filename: `YYYY-MM-DD-HHMMSS-first-50-chars.md`
- Frontmatter with tags, captured time, source, status
- Content after frontmatter

## 🎯 Next Session Plan

1. **Create Android project structure**
2. **Implement MainActivity** (receive voice notes)
3. **Implement ApiClient** (POST to backend)
4. **Test locally** (Android Studio emulator or device)
5. **Configure backend URL** (point to VPS when ready)
6. **Test end-to-end** (watch → Android → backend → limbo)

Then Phase 1 is complete! 🎉
