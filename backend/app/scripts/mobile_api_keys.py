from __future__ import annotations

import argparse

from backend.app.config import load_settings
from backend.app.repositories.database import Database
from backend.app.repositories.mobile_api_key_repository import MobileApiKeyRepository


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manage per-device mobile API keys for Active Workbench.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Create a new device API key.")
    create_parser.add_argument(
        "--device-name",
        required=True,
        help="Human-readable device name (for example: pixel-test-01).",
    )

    revoke_parser = subparsers.add_parser("revoke", help="Revoke an existing device API key.")
    revoke_parser.add_argument(
        "--key-id",
        required=True,
        help="Device key id (mkey_...).",
    )

    list_parser = subparsers.add_parser("list", help="List device API keys.")
    list_parser.add_argument(
        "--all",
        action="store_true",
        help="Include revoked keys.",
    )

    return parser.parse_args()


def _print_key_list(repository: MobileApiKeyRepository, *, include_revoked: bool) -> None:
    keys = repository.list_keys(include_revoked=include_revoked)
    if not keys:
        print("No mobile API keys found.")
        return

    print("key_id\tdevice_name\tcreated_at\trevoked_at\tlast_used_at\tlast_seen_ip")
    for key in keys:
        print(
            "\t".join(
                [
                    key.key_id,
                    key.device_name,
                    key.created_at,
                    key.revoked_at or "-",
                    key.last_used_at or "-",
                    key.last_seen_ip or "-",
                ]
            )
        )


def main() -> None:
    args = _parse_args()
    settings = load_settings(validate_oauth_secrets=False)
    database = Database(settings.db_path)
    database.initialize()
    repository = MobileApiKeyRepository(database)

    if args.command == "create":
        record, token = repository.create_key(args.device_name)
        print(f"Created mobile API key: {record.key_id}")
        print(f"Device name: {record.device_name}")
        print(f"Token (save now, only shown once): {token}")
        print(f"Authorization header: Bearer {token}")
        return

    if args.command == "revoke":
        revoked = repository.revoke_key(args.key_id)
        if revoked:
            print(f"Revoked mobile API key: {args.key_id}")
        else:
            print(f"No active mobile API key found for: {args.key_id}")
        return

    if args.command == "list":
        _print_key_list(repository, include_revoked=args.all)
        return

    raise RuntimeError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    main()
