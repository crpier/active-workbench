# Active Workbench Expo App

Shared web/mobile UI for article workflows.

## Commands

```bash
npm install
npm run web
npm run android
npm run typecheck
npm run test
npm run build:web
```

## Share Intents (Android)

The app is configured with `expo-share-intent` plugin for `text/*` Android shares.
Use a dev build (not Expo Go) for intent testing.

Share reliability notes:
- Incoming share intents are written to a persisted local queue (`AsyncStorage`).
- The queue auto-flushes on startup, when app returns to foreground, and on a periodic timer while open.
- Failed submissions are retried with exponential backoff.

## Backend URL

Configure backend URL from the in-app **Settings** screen.
For local emulator usage use `http://10.0.2.2:8000`.
