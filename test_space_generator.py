#!/usr/bin/env python3
"""
Test script for SpaceGenerator.

Simple CLI to test space generation against a Confluence Cloud instance.
"""

import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from generators.spaces import SpaceGenerator


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Test the SpaceGenerator against Confluence Cloud",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List available users (to get user IDs for permissions)
  python test_space_generator.py --list-users
  python test_space_generator.py --list-users 20

  # List members of a specific group (including invited users)
  python test_space_generator.py --list-group-members confluence-users-sitename

  # Dry run - preview what would be created
  python test_space_generator.py --dry-run --spaces 2

  # Create 1 space with labels and properties
  python test_space_generator.py --spaces 1 --labels 3 --properties 2

  # Create spaces with permissions for existing users
  python test_space_generator.py --spaces 1 --permissions 5 --user-ids user1,user2

  # Test async mode
  python test_space_generator.py --spaces 2 --labels 5 --async
        """,
    )

    parser.add_argument(
        "--url",
        default=os.environ.get("CONFLUENCE_URL"),
        help="Confluence URL (default: CONFLUENCE_URL env var)",
    )
    parser.add_argument(
        "--email",
        default=os.environ.get("CONFLUENCE_EMAIL"),
        help="Confluence email (default: CONFLUENCE_EMAIL env var)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("CONFLUENCE_API_TOKEN"),
        help="API token (default: CONFLUENCE_API_TOKEN env var)",
    )
    parser.add_argument(
        "--prefix",
        default="SPCTEST",
        help="Prefix for space keys (default: SPCTEST)",
    )
    parser.add_argument(
        "--spaces",
        type=int,
        default=1,
        help="Number of spaces to create (default: 1)",
    )
    parser.add_argument(
        "--labels",
        type=int,
        default=0,
        help="Number of labels to add (default: 0)",
    )
    parser.add_argument(
        "--properties",
        type=int,
        default=0,
        help="Number of properties to set (default: 0)",
    )
    parser.add_argument(
        "--permissions",
        type=int,
        default=0,
        help="Number of permissions to add (default: 0)",
    )
    parser.add_argument(
        "--user-ids",
        help="Comma-separated user account IDs for permissions",
    )
    parser.add_argument(
        "--look-and-feel",
        action="store_true",
        help="Set custom look and feel on spaces",
    )
    parser.add_argument(
        "--list-users",
        type=int,
        nargs="?",
        const=10,
        metavar="N",
        help="List user account IDs and exit (default: 10 users)",
    )
    parser.add_argument(
        "--list-group-members",
        metavar="GROUP",
        help="List members of a group (e.g., confluence-users-sitename)",
    )
    parser.add_argument(
        "--async",
        dest="use_async",
        action="store_true",
        help="Use async methods",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without making API calls",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    return parser.parse_args()


def run_sync(generator: SpaceGenerator, args: argparse.Namespace) -> None:
    """Run space generation synchronously."""
    # Create spaces
    print(f"\n{'=' * 50}")
    print(f"Creating {args.spaces} space(s)...")
    print(f"{'=' * 50}")

    spaces = generator.create_spaces(args.spaces)
    print(f"Created {len(spaces)} space(s)")

    if not spaces:
        print("No spaces created, skipping additional operations")
        return

    for space in spaces:
        print(f"  - {space['key']} (id: {space['id']})")

    space_ids = [s["id"] for s in spaces]
    space_keys = [s["key"] for s in spaces]

    # Add labels (uses space keys, not IDs) and categories (same count)
    # Note: Labels are deprecated in Confluence Cloud, replaced by categories.
    # We create both: labels for backup compatibility, categories for current functionality.
    if args.labels > 0:
        print(f"\n{'=' * 50}")
        print(f"Adding {args.labels} label(s) [deprecated, for backup compatibility]...")
        print(f"{'=' * 50}")

        label_count = generator.add_space_labels(space_keys, args.labels)
        print(f"Added {label_count} label(s)")

        print(f"\n{'=' * 50}")
        print(f"Adding {args.labels} categor(ies) [team-prefixed labels for space directory]...")
        print(f"{'=' * 50}")

        category_count = generator.add_space_categories(space_keys, args.labels)
        print(f"Added {category_count} categor(ies)")

    # Set properties
    if args.properties > 0:
        print(f"\n{'=' * 50}")
        print(f"Setting {args.properties} propert(ies)...")
        print(f"{'=' * 50}")

        count = generator.set_space_properties(space_ids, args.properties)
        print(f"Set {count} propert(ies)")

    # Add permissions
    if args.permissions > 0 and args.user_ids:
        print(f"\n{'=' * 50}")
        print(f"Adding {args.permissions} permission(s)...")
        print(f"{'=' * 50}")

        user_ids = [u.strip() for u in args.user_ids.split(",")]
        count = generator.add_space_permissions(space_ids, user_ids, args.permissions)
        print(f"Added {count} permission(s)")
    elif args.permissions > 0:
        print("\nSkipping permissions - no --user-ids provided")

    # Set look and feel
    if args.look_and_feel:
        print(f"\n{'=' * 50}")
        print("Setting look and feel...")
        print(f"{'=' * 50}")

        count = generator.set_space_look_and_feel_multiple(space_keys, len(space_keys))
        print(f"Configured {count} space(s)")


async def run_async(generator: SpaceGenerator, args: argparse.Namespace) -> None:
    """Run space generation asynchronously."""
    try:
        # Create spaces
        print(f"\n{'=' * 50}")
        print(f"Creating {args.spaces} space(s) (async)...")
        print(f"{'=' * 50}")

        spaces = await generator.create_spaces_async(args.spaces)
        print(f"Created {len(spaces)} space(s)")

        if not spaces:
            print("No spaces created, skipping additional operations")
            return

        for space in spaces:
            print(f"  - {space['key']} (id: {space['id']})")

        space_ids = [s["id"] for s in spaces]
        space_keys = [s["key"] for s in spaces]

        # Add labels (uses space keys, not IDs) and categories (same count)
        if args.labels > 0:
            print(f"\n{'=' * 50}")
            print(f"Adding {args.labels} label(s) (async) [deprecated, for backup compatibility]...")
            print(f"{'=' * 50}")

            label_count = await generator.add_space_labels_async(space_keys, args.labels)
            print(f"Added {label_count} label(s)")

            print(f"\n{'=' * 50}")
            print(f"Adding {args.labels} categor(ies) (async) [team-prefixed labels for space directory]...")
            print(f"{'=' * 50}")

            category_count = await generator.add_space_categories_async(space_keys, args.labels)
            print(f"Added {category_count} categor(ies)")

        # Set properties
        if args.properties > 0:
            print(f"\n{'=' * 50}")
            print(f"Setting {args.properties} propert(ies) (async)...")
            print(f"{'=' * 50}")

            count = await generator.set_space_properties_async(space_ids, args.properties)
            print(f"Set {count} propert(ies)")

        # Add permissions
        if args.permissions > 0 and args.user_ids:
            print(f"\n{'=' * 50}")
            print(f"Adding {args.permissions} permission(s) (async)...")
            print(f"{'=' * 50}")

            user_ids = [u.strip() for u in args.user_ids.split(",")]
            count = await generator.add_space_permissions_async(space_ids, user_ids, args.permissions)
            print(f"Added {count} permission(s)")
        elif args.permissions > 0:
            print("\nSkipping permissions - no --user-ids provided")

    finally:
        await generator._close_async_session()


def main() -> None:
    """Main entry point."""
    load_dotenv()
    args = parse_args()

    # Validate required args
    if not args.url:
        print("Error: --url or CONFLUENCE_URL environment variable required", file=sys.stderr)
        sys.exit(1)
    if not args.email:
        print("Error: --email or CONFLUENCE_EMAIL environment variable required", file=sys.stderr)
        sys.exit(1)
    if not args.token:
        print("Error: --token or CONFLUENCE_API_TOKEN environment variable required", file=sys.stderr)
        sys.exit(1)

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    # Print config
    print("\nSpace Generator Test")
    print("=" * 50)
    print(f"URL:        {args.url}")
    print(f"Email:      {args.email}")
    print(f"Token:      {'*' * 12} (configured)")
    print(f"Prefix:     {args.prefix}")
    print(f"Dry Run:    {args.dry_run}")
    print(f"Async Mode: {args.use_async}")

    # Handle --list-users
    if args.list_users is not None:
        import requests

        # Use Atlassian Admin API to list users (same as user generator)
        # Extract base URL (remove /wiki if present)
        base_url = args.url.rstrip("/")
        if base_url.endswith("/wiki"):
            base_url = base_url[:-5]

        print(f"\nFetching up to {args.list_users} users...")
        print("=" * 50)

        session = requests.Session()
        users = []

        import time

        for attempt in range(3):
            try:
                # Use the users/search endpoint which works for listing
                response = session.get(
                    f"{base_url}/rest/api/3/users/search",
                    params={"maxResults": args.list_users},
                    auth=(args.email, args.token),
                    headers={"Accept": "application/json"},
                    timeout=30,
                )

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 5))
                    print(f"Rate limited, waiting {retry_after}s...")
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()

                for user in response.json():
                    account_id = user.get("accountId")
                    display_name = user.get("displayName", "Unknown")
                    account_type = user.get("accountType", "unknown")

                    # Skip app users and inactive users
                    if account_type == "atlassian" and account_id:
                        users.append({"id": account_id, "name": display_name})
                break

            except requests.RequestException as e:
                if attempt == 2:
                    print(f"Error fetching users: {e}")
                    return
                time.sleep(2**attempt)

        if users:
            print(f"Found {len(users)} user(s):\n")
            for user in users:
                print(f"  {user['id']}  ({user['name']})")

            user_ids = [u["id"] for u in users[:3]]
            print(f'\nUse with: --user-ids "{",".join(user_ids)}"')
        else:
            print("No users found")

        return

    # Handle --list-group-members
    if args.list_group_members:
        import time

        import requests

        base_url = args.url.rstrip("/")
        if base_url.endswith("/wiki"):
            base_url = base_url[:-5]

        group_name = args.list_group_members
        print(f"\nFetching members of group '{group_name}'...")
        print("=" * 50)

        session = requests.Session()
        users = []

        for attempt in range(3):
            try:
                response = session.get(
                    f"{base_url}/rest/api/3/group/member",
                    params={"groupname": group_name, "maxResults": 100},
                    auth=(args.email, args.token),
                    headers={"Accept": "application/json"},
                    timeout=30,
                )

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 5))
                    print(f"Rate limited, waiting {retry_after}s...")
                    time.sleep(retry_after)
                    continue

                if response.status_code == 404:
                    print(f"Group '{group_name}' not found")
                    return

                response.raise_for_status()

                data = response.json()
                for user in data.get("values", []):
                    account_id = user.get("accountId")
                    display_name = user.get("displayName", "Unknown")
                    if account_id:
                        users.append({"id": account_id, "name": display_name})
                break

            except requests.RequestException as e:
                if attempt == 2:
                    print(f"Error fetching group members: {e}")
                    return
                time.sleep(2**attempt)

        if users:
            print(f"Found {len(users)} member(s):\n")
            for user in users:
                print(f"  {user['id']}  ({user['name']})")

            user_ids = [u["id"] for u in users[:5]]
            print(f'\nUse with: --user-ids "{",".join(user_ids)}"')
        else:
            print("No members found in group")

        return

    # Create generator
    generator = SpaceGenerator(
        confluence_url=args.url,
        email=args.email,
        api_token=args.token,
        prefix=args.prefix,
        dry_run=args.dry_run,
    )

    # Run
    if args.use_async:
        asyncio.run(run_async(generator, args))
    else:
        run_sync(generator, args)

    print(f"\n{'=' * 50}")
    print("Done!")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
