from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.request import Request, urlopen

DEFAULT_COOKIES_FROM_BROWSER = os.getenv(
    "ACTIVE_WORKBENCH_YOUTUBE_COOKIES_FROM_BROWSER",
    "chromium+gnomekeyring:Default",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read YouTube Watch Later with yt-dlp and push a snapshot to the Active Workbench API."
        ),
    )
    parser.add_argument(
        "--cookies",
        type=Path,
        help="Path to browser-exported YouTube cookies for yt-dlp (overrides browser mode).",
    )
    parser.add_argument(
        "--cookies-from-browser",
        type=str,
        default=DEFAULT_COOKIES_FROM_BROWSER,
        help=(
            "Browser/profile spec for yt-dlp --cookies-from-browser. "
            f"Default: {DEFAULT_COOKIES_FROM_BROWSER!r}."
        ),
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=os.getenv("ACTIVE_WORKBENCH_API_BASE_URL", "http://127.0.0.1:8000"),
        help="Active Workbench API base URL.",
    )
    parser.add_argument(
        "--api-token",
        type=str,
        default=os.getenv("ACTIVE_WORKBENCH_API_TOKEN"),
        help="Optional bearer token forwarded as Authorization header.",
    )
    parser.add_argument(
        "--source-client",
        type=str,
        default=socket.gethostname(),
        help="Identifier recorded with the pushed snapshot.",
    )
    parser.add_argument(
        "--generated-at-utc",
        type=str,
        default=datetime.now(UTC).isoformat(),
        help="Snapshot generation timestamp (UTC ISO-8601).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print snapshot payload preview without pushing it.",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow pushing an empty snapshot (normally blocked to avoid accidental wipes).",
    )
    return parser.parse_args()


def _collect_watch_later_videos(
    *,
    cookies_path: Path | None,
    cookies_from_browser: str,
) -> list[dict[str, Any]]:
    if cookies_path is not None:
        if not cookies_path.exists():
            raise RuntimeError(f"Cookie file does not exist: {cookies_path}")
        command = [
            "yt-dlp",
            "--flat-playlist",
            "--dump-single-json",
            "--cookies",
            str(cookies_path),
            "https://www.youtube.com/playlist?list=WL",
        ]
    else:
        browser_spec = cookies_from_browser.strip()
        if not browser_spec:
            raise RuntimeError(
                "No cookie source configured. Provide --cookies or --cookies-from-browser."
            )
        command = [
            "uvx",
            "--with",
            "secretstorage",
            "yt-dlp",
            "--flat-playlist",
            "--dump-single-json",
            "--cookies-from-browser",
            browser_spec,
            "https://www.youtube.com/playlist?list=WL",
        ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise RuntimeError(f"yt-dlp failed ({completed.returncode}): {stderr}")
    stdout = completed.stdout.strip()
    if not stdout:
        return []

    payload_raw = cast(object, json.loads(stdout))
    if not isinstance(payload_raw, dict):
        return []
    payload = cast(dict[str, object], payload_raw)
    entries_raw = payload.get("entries")
    if not isinstance(entries_raw, list):
        return []
    entries = cast(list[object], entries_raw)

    videos: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(entries, start=1):
        if not isinstance(raw_entry, dict):
            continue
        entry = cast(dict[str, object], raw_entry)
        raw_video_id = entry.get("id")
        if not isinstance(raw_video_id, str) or not raw_video_id.strip():
            continue
        video_id = raw_video_id.strip()
        title = entry.get("title")
        channel_title = entry.get("channel") or entry.get("uploader")
        videos.append(
            {
                "video_id": video_id,
                "title": title if isinstance(title, str) else None,
                "channel_title": channel_title if isinstance(channel_title, str) else None,
                "snapshot_position": index,
            }
        )
    return videos


def _push_snapshot(
    *,
    base_url: str,
    api_token: str | None,
    source_client: str,
    generated_at_utc: str,
    videos: list[dict[str, Any]],
    allow_empty_snapshot: bool,
) -> dict[str, Any]:
    endpoint = f"{base_url.rstrip('/')}/youtube/watch-later/snapshot"
    payload = {
        "generated_at_utc": generated_at_utc,
        "source_client": source_client,
        "videos": videos,
        "allow_empty_snapshot": allow_empty_snapshot,
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if isinstance(api_token, str) and api_token.strip():
        headers["Authorization"] = f"Bearer {api_token.strip()}"
    request = Request(endpoint, data=body, headers=headers, method="POST")
    with urlopen(request) as response:
        raw = response.read().decode("utf-8")
    parsed_raw = cast(object, json.loads(raw))
    if not isinstance(parsed_raw, dict):
        raise RuntimeError("Unexpected snapshot push response")
    return cast(dict[str, Any], parsed_raw)


def main() -> None:
    args = _parse_args()
    cookies_path = args.cookies.expanduser().resolve() if args.cookies is not None else None
    videos = _collect_watch_later_videos(
        cookies_path=cookies_path,
        cookies_from_browser=args.cookies_from_browser,
    )
    print(f"Collected {len(videos)} watch-later videos from yt-dlp.")

    payload_preview = {
        "generated_at_utc": args.generated_at_utc,
        "source_client": args.source_client,
        "videos_count": len(videos),
    }
    print(json.dumps(payload_preview, indent=2))
    if args.dry_run:
        return

    response = _push_snapshot(
        base_url=args.base_url,
        api_token=args.api_token,
        source_client=args.source_client,
        generated_at_utc=args.generated_at_utc,
        videos=videos,
        allow_empty_snapshot=args.allow_empty,
    )
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
