# Android Share App (v1)

This is a minimal Android app scaffold that handles `ACTION_SEND` text shares,
extracts the first `http/https` URL, and calls:

- `POST /mobile/v1/share/article`

## What It Implements

- Share intent handler activity: `ShareReceiverActivity`
- URL extraction from shared text
- Retrofit client + repository for the mobile share endpoint
- Persistent local queue (`SharedPreferences` JSON store)
- Background sync + retry with exponential backoff (`WorkManager`)
- In-app recent history view in `MainActivity`
- Manual "Sync now" trigger from app UI
- Embedded OpenCode chat via WebView (`ChatActivity`)

## Project Location

- `mobile/android-share/`

## Configure Backend Base URL

The app uses `BuildConfig.WORKBENCH_BASE_URL` as default, and you can override it in app UI:

- Debug default: `http://10.0.2.2:8000/` (Android emulator -> host machine)
- Release placeholder: `https://your-api-host.example/`

Adjust in:

- `mobile/android-share/app/build.gradle.kts`

## Configure Mobile API Key (for secure share endpoint)

If backend sets `ACTIVE_WORKBENCH_MOBILE_API_KEY`, the Android app must send:

- `Authorization: Bearer <key>`

You can set it either:

- in app settings (`Mobile API key (Bearer)` field), or
- as build default in `WORKBENCH_MOBILE_API_KEY` (`app/build.gradle.kts`)

Mobile API key is stored with `EncryptedSharedPreferences` when available.

## Configure OpenCode Web URL

The app uses `BuildConfig.OPENCODE_WEB_URL` as default, and you can override it in app UI:

- Debug default: `http://10.0.2.2:4096/` (Android emulator -> host machine)
- Release placeholder: `https://your-opencode-host.example/`

To run OpenCode Web on host machine with fixed port:

```bash
opencode web --hostname=127.0.0.1 --port=4096
```

Then in app, tap **Open Chat**.

You can update URLs and mobile API key from the app home screen and tap **Save endpoints**.

## Manual Test

1. Start Active Workbench backend (same machine).
2. Install/run this Android app on emulator or device.
3. In another app (e.g. X/Twitter, browser), share text containing a URL.
4. Choose `Workbench Share` in Android share sheet.
5. Confirm share is queued in the in-app result screen.
6. Open app launcher icon to view recent share history and sync status.

## Notes

- Debug builds allow cleartext HTTP for local testing.
- Release builds disable cleartext traffic; use HTTPS endpoints.
- Chat traffic goes to OpenCode Web URL; article-share sync goes only to Active Workbench backend URL.
