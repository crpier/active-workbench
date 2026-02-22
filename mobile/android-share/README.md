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

## Configure OpenCode Web URL

The app uses `BuildConfig.OPENCODE_WEB_URL` as default, and you can override it in app UI:

- Debug default: `http://10.0.2.2:4096/` (Android emulator -> host machine)
- Release placeholder: `https://your-opencode-host.example/`

To run OpenCode Web on host machine with fixed port:

```bash
opencode web --hostname=127.0.0.1 --port=4096
```

Then in app, tap **Open Chat**.

You can update both URLs from the app home screen and tap **Save endpoints**.

## Manual Test

1. Start Active Workbench backend (same machine).
2. Install/run this Android app on emulator or device.
3. In another app (e.g. X/Twitter, browser), share text containing a URL.
4. Choose `Workbench Share` in Android share sheet.
5. Confirm share is queued in the in-app result screen.
6. Open app launcher icon to view recent share history and sync status.

## Notes

- `android:usesCleartextTraffic="true"` is enabled for local HTTP testing.
- For production, move to HTTPS and tighten network security policy.
