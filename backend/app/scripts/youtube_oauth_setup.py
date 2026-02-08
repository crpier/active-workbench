from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from backend.app.config import load_settings
from backend.app.services.youtube_service import (
    YouTubeService,
    YouTubeServiceError,
    resolve_oauth_paths,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap YouTube OAuth for Active Workbench.",
    )
    parser.add_argument(
        "--client-secret",
        type=Path,
        default=None,
        help="Path to downloaded Google OAuth client secret JSON.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="How many recent videos to fetch for verification.",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Optional search query to filter recent videos.",
    )
    return parser.parse_args()


def copy_client_secret_if_needed(source_path: Path, destination_path: Path) -> None:
    source = source_path.expanduser().resolve()
    if not source.exists():
        raise YouTubeServiceError(f"Client secret file does not exist: {source}")

    destination = destination_path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    if source == destination:
        return

    shutil.copy2(source, destination)


def main() -> None:
    args = _parse_args()
    settings = load_settings()

    token_path, secret_path = resolve_oauth_paths(settings.data_dir)
    if args.client_secret is not None:
        copy_client_secret_if_needed(args.client_secret, secret_path)
        print(f"Client secret ready at: {secret_path}")
    else:
        print(f"Expecting client secret at: {secret_path}")

    service = YouTubeService(mode="oauth", data_dir=settings.data_dir)

    videos = service.list_recent(limit=max(1, min(10, args.limit)), query=args.query)

    print(f"OAuth success. Token path: {token_path}")
    print("Recent videos:")
    for index, video in enumerate(videos, start=1):
        print(f"{index}. {video.title} [{video.video_id}] {video.published_at}")


if __name__ == "__main__":
    main()
