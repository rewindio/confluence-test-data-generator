#!/usr/bin/env python3
"""
Confluence User and Group Generator

Creates test users and groups in Confluence Cloud instances.
Users are created with email addresses in the format: prefix+sandboxN@domain

This leverages Gmail's "+" alias feature - all emails go to the same inbox.
"""

import argparse
import logging
import os
import sys
import time

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class ConfluenceUserGenerator:
    """Generates test users and groups for Confluence Cloud.

    Uses the Atlassian Admin API to invite users and manage groups.
    Requires site-admin or org-admin permissions.

    Note: Users are invited to the Atlassian organization. Confluence access
    must be granted separately through the admin console, as the user invite
    API only supports Jira product assignments.
    """

    def __init__(
        self,
        confluence_url: str,
        email: str,
        api_token: str,
        dry_run: bool = False,
        email_suffix: str = "confluence",
        confluence_users_group: str | None = None,
    ):
        self.confluence_url = confluence_url.rstrip("/")
        # Handle /wiki suffix - remove it for user management (uses admin API)
        if self.confluence_url.endswith("/wiki"):
            self.confluence_url = self.confluence_url[:-5]
        self.email = email
        self.api_token = api_token
        self.dry_run = dry_run
        self.email_suffix = email_suffix

        # Extract site name for default group naming
        # Atlassian Cloud groups include site name: confluence-users-{site-name}
        self.site_name = self._extract_site_name()
        self.confluence_users_group = confluence_users_group or f"confluence-users-{self.site_name}"

        self.session = self._create_session()
        self.logger = logging.getLogger(__name__)

        # Track created items
        self.created_users: list[dict] = []
        self.created_groups: list[dict] = []
        self.existing_users: list[dict] = []
        self.existing_groups: list[dict] = []

    def _extract_site_name(self) -> str:
        """Extract the site name from the Confluence URL.

        Atlassian Cloud URLs are in the format: https://{site-name}.atlassian.net
        Default groups include the site name: confluence-users-{site-name}

        Returns:
            The site name extracted from the URL
        """
        # Parse URL like https://mycompany.atlassian.net
        from urllib.parse import urlparse

        parsed = urlparse(self.confluence_url)
        hostname = parsed.netloc or parsed.path

        # Extract site name from hostname (e.g., "mycompany" from "mycompany.atlassian.net")
        # Use endswith() to prevent URL substring attacks (e.g., evil.atlassian.net.attacker.com)
        if hostname.endswith(".atlassian.net"):
            return hostname.removesuffix(".atlassian.net")

        # Fallback: use full hostname without dots
        return hostname.replace(".", "-")

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()

        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _parse_retry_after(self, header_value: str | None, default: float = 30.0) -> float:
        """Parse the Retry-After header value.

        Handles both numeric seconds and HTTP date formats per RFC 7231.

        Args:
            header_value: The Retry-After header value
            default: Default value if parsing fails

        Returns:
            Number of seconds to wait
        """
        if not header_value:
            return default
        try:
            return float(header_value)
        except ValueError:
            # Could be an HTTP date format, fall back to default
            self.logger.debug(f"Could not parse Retry-After header '{header_value}', using default {default}s")
            return default

    def _make_request_with_retries(
        self,
        method: str,
        url: str,
        data: dict | None = None,
        params: dict | None = None,
        max_retries: int = 5,
        max_rate_limit_retries: int = 10,
        api_name: str = "API",
    ) -> requests.Response | None:
        """Make an HTTP request with retry and rate limit handling.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL to request
            data: JSON data to send
            params: Query parameters
            max_retries: Maximum retry attempts for errors
            max_rate_limit_retries: Maximum retries for rate limiting (429)
            api_name: Name of API for logging

        Returns:
            Response object on success, None on client errors (4xx)
        """
        rate_limit_retries = 0

        for attempt in range(max_retries):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    json=data,
                    params=params,
                    auth=(self.email, self.api_token),
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                    timeout=30,
                )

                if response.status_code == 429:
                    rate_limit_retries += 1
                    if rate_limit_retries > max_rate_limit_retries:
                        self.logger.error(f"Exceeded max rate limit retries ({max_rate_limit_retries})")
                        return None
                    retry_after = self._parse_retry_after(response.headers.get("Retry-After"))
                    self.logger.warning(f"Rate limited. Waiting {retry_after}s... (retry {rate_limit_retries}/{max_rate_limit_retries})")
                    time.sleep(retry_after)
                    continue

                # 4xx errors are client errors - don't retry, return None
                if 400 <= response.status_code < 500:
                    self.logger.debug(f"Client error {response.status_code}: {response.text[:200]}")
                    return None

                response.raise_for_status()
                return response

            except requests.exceptions.RequestException as e:
                self.logger.error(f"{api_name} call failed (attempt {attempt + 1}/{max_retries}): {e}")
                if hasattr(e, "response") and e.response is not None:
                    try:
                        error_detail = e.response.text
                        self.logger.error(f"Response body: {error_detail}")
                    except Exception as log_err:
                        self.logger.debug(f"Failed to read error response body: {log_err}")
                # Only retry on network/server errors, not client errors
                if attempt < max_retries - 1:
                    time.sleep(2**attempt)
                else:
                    raise

        return None

    def _api_call(
        self,
        method: str,
        endpoint: str,
        data: dict | None = None,
        params: dict | None = None,
        max_retries: int = 5,
        api_version: str = "v1",
    ) -> requests.Response | None:
        """Make a Confluence API call with rate limit handling.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (relative to base URL)
            data: JSON data to send
            params: Query parameters
            max_retries: Maximum retry attempts
            api_version: API version ("v1" for /rest/api, "v2" for /api/v2)

        Returns:
            Response object on success, None on client errors (4xx)
        """
        if api_version == "v2":
            url = f"{self.confluence_url}/wiki/api/v2/{endpoint}"
        else:
            url = f"{self.confluence_url}/wiki/rest/api/{endpoint}"

        if self.dry_run:
            self.logger.info(f"DRY RUN: {method} {endpoint}")
            if data:
                self.logger.debug(f"  Data: {data}")
            return None

        return self._make_request_with_retries(
            method=method,
            url=url,
            data=data,
            params=params,
            max_retries=max_retries,
            api_name="Confluence API",
        )

    def _admin_api_call(
        self,
        method: str,
        endpoint: str,
        data: dict | None = None,
        params: dict | None = None,
        max_retries: int = 5,
    ) -> requests.Response | None:
        """Make an Atlassian Admin API call for user management.

        The Atlassian Admin API is used to invite users to Cloud sites.
        Uses the same base URL without /wiki prefix.

        Returns:
            Response object on success, None on client errors (4xx)
        """
        url = f"{self.confluence_url}/rest/api/3/{endpoint}"

        if self.dry_run:
            self.logger.info(f"DRY RUN: {method} {endpoint}")
            if data:
                self.logger.debug(f"  Data: {data}")
            return None

        return self._make_request_with_retries(
            method=method,
            url=url,
            data=data,
            params=params,
            max_retries=max_retries,
            api_name="Admin API",
        )

    def parse_email(self, base_email: str) -> tuple[str, str]:
        """Parse email into prefix and domain parts.

        Args:
            base_email: Base email address (e.g., user@example.com or user+tag@example.com)

        Returns:
            Tuple of (prefix, domain)

        Raises:
            ValueError: If email format is invalid
        """
        if "@" not in base_email:
            raise ValueError(f"Invalid email format: {base_email}")

        # Handle existing + in email
        local_part, domain = base_email.rsplit("@", 1)

        # Validate both parts are non-empty
        local_part = local_part.strip()
        domain = domain.strip()
        if not local_part or not domain:
            raise ValueError(f"Invalid email format: {base_email}")

        if "+" in local_part:
            prefix = local_part.split("+", 1)[0]
        else:
            prefix = local_part

        return prefix, domain

    def generate_sandbox_email(self, base_email: str, index: int) -> str:
        """Generate a sandbox email address using Gmail's + alias feature.

        Args:
            base_email: Base email (e.g., user@example.com)
            index: User index number

        Returns:
            Sandbox email (e.g., user+confluence1@example.com)
        """
        prefix, domain = self.parse_email(base_email)
        return f"{prefix}+{self.email_suffix}{index}@{domain}"

    def check_user_exists(self, email: str) -> dict | None:
        """Check if a user already exists in Confluence.

        Uses the Atlassian admin API to search for users by email.

        Args:
            email: User's email address

        Returns:
            User dict if found, None otherwise
        """
        if self.dry_run:
            return None

        self.logger.debug(f"Checking if user exists: {email}")

        # Use admin API user search (same as Jira)
        response = self._admin_api_call("GET", "user/search", params={"query": email})
        if response:
            users = response.json()
            self.logger.debug(f"User search returned {len(users)} results")
            for user in users:
                if user.get("emailAddress", "").lower() == email.lower():
                    return user

        return None

    def create_user(self, email: str, display_name: str) -> dict | None:
        """Create/invite a single user in Confluence Cloud.

        Uses POST /rest/api/3/user to invite users (same as Jira admin API).
        Requires site-admin or user-access-admin permissions.

        Args:
            email: User's email address
            display_name: Display name for the user

        Returns:
            User dict if created/exists, None on failure
        """
        self.logger.info(f"Processing user: {email} ({display_name})")
        self.logger.debug("Checking if user already exists...")

        if self.dry_run:
            self.logger.info(f"DRY RUN: Would check/invite user {email}")
            self.created_users.append({"email": email, "displayName": display_name, "status": "dry_run"})
            return {"email": email, "displayName": display_name}

        # Check if user already exists
        existing_user = self.check_user_exists(email)
        if existing_user:
            account_id = existing_user.get("accountId", existing_user.get("publicName", "Unknown"))
            self.logger.info(f"User {email} already exists (accountId: {account_id})")
            self.existing_users.append(
                {
                    "email": email,
                    "displayName": existing_user.get("displayName", display_name),
                    "accountId": account_id,
                    "status": "exists",
                }
            )
            return existing_user

        # Invite the user via Admin API (POST /rest/api/3/user)
        # Note: The /rest/api/3/user endpoint only accepts Jira product names.
        # We use an empty products array and add users to confluence-users group for access.
        user_data = {
            "emailAddress": email,
            "displayName": display_name,
            "products": [],  # Empty - Confluence access granted via group membership
        }

        response = self._admin_api_call("POST", "user", data=user_data)

        if response:
            user = response.json()
            account_id = user.get("accountId")
            self.logger.info(f"Invited user: {email} (accountId: {account_id})")

            # Add user to confluence-users group to grant Confluence access
            if account_id:
                if self.add_user_to_group(account_id, self.confluence_users_group):
                    self.logger.info(f"Added {email} to {self.confluence_users_group} group")
                else:
                    self.logger.warning(f"Failed to add {email} to {self.confluence_users_group} group")

            self.created_users.append(
                {"email": email, "displayName": display_name, "accountId": account_id, "status": "invited"}
            )
            return user

        # If API call failed, log it
        self.logger.warning(f"Failed to invite user {email}")
        self.created_users.append({"email": email, "displayName": display_name, "status": "failed"})

        return None

    def check_group_exists(self, group_name: str) -> dict | None:
        """Check if a group already exists in Confluence.

        Args:
            group_name: Name of the group

        Returns:
            Group dict if found, None otherwise
        """
        if self.dry_run:
            return None

        # Try Confluence group endpoint
        response = self._api_call("GET", "group", params={"groupName": group_name})
        if response and response.status_code == 200:
            return response.json()

        # Also try listing groups and searching
        response = self._api_call("GET", "group", params={"limit": 100})
        if response:
            data = response.json()
            groups = data.get("results", [])
            for group in groups:
                if group.get("name", "").lower() == group_name.lower():
                    return group

        return None

    def create_group(self, group_name: str) -> dict | None:
        """Create a group in Confluence.

        Args:
            group_name: Name of the group to create

        Returns:
            Group dict if created/exists, None on failure
        """
        self.logger.info(f"Processing group: {group_name}")

        if self.dry_run:
            self.logger.info(f"DRY RUN: Would check/create group {group_name}")
            self.created_groups.append({"name": group_name, "status": "dry_run"})
            return {"name": group_name}

        # Check if group exists
        existing_group = self.check_group_exists(group_name)
        if existing_group:
            self.logger.info(f"Group {group_name} already exists")
            self.existing_groups.append({"name": group_name, "id": existing_group.get("id"), "status": "exists"})
            return existing_group

        # Create the group via Confluence API
        group_data = {"name": group_name}
        response = self._api_call("POST", "group", data=group_data)

        if response:
            group = response.json()
            self.logger.info(f"Created group: {group_name}")
            self.created_groups.append({"name": group_name, "id": group.get("id"), "status": "created"})
            return group

        return None

    def add_user_to_group(self, account_id: str, group_name: str) -> bool:
        """Add a user to a Confluence group.

        Uses the Atlassian Admin API (same as Jira) to add users to groups.

        Args:
            account_id: User's Atlassian account ID
            group_name: Name of the group

        Returns:
            True if successful, False otherwise
        """
        self.logger.info(f"Adding user {account_id} to group {group_name}")

        if self.dry_run:
            self.logger.info(f"DRY RUN: Would add user to group {group_name}")
            return True

        data = {"accountId": account_id}
        response = self._admin_api_call("POST", "group/user", data=data, params={"groupname": group_name})

        if response:
            self.logger.info(f"Added user to group {group_name}")
            return True

        return False

    def generate_users(self, base_email: str, count: int, prefix: str = "Sandbox") -> list[dict]:
        """Generate multiple sandbox users.

        Args:
            base_email: Base email for generating sandbox addresses
            count: Number of users to create
            prefix: Display name prefix (default: "Sandbox")

        Returns:
            List of created user dicts
        """
        self.logger.info(f"Generating {count} sandbox users from {base_email}")

        users = []
        for i in range(1, count + 1):
            email = self.generate_sandbox_email(base_email, i)
            display_name = f"{prefix} User {i}"

            user = self.create_user(email, display_name)
            if user:
                users.append(user)

            time.sleep(0.3)  # Small delay between users

        return users

    def generate_groups(self, group_names: list[str]) -> list[dict]:
        """Generate multiple groups.

        Args:
            group_names: List of group names to create

        Returns:
            List of created group dicts
        """
        self.logger.info(f"Generating {len(group_names)} groups")

        groups = []
        for name in group_names:
            group = self.create_group(name)
            if group:
                groups.append(group)

            time.sleep(0.3)

        return groups

    def generate_all(
        self, base_email: str, user_count: int, group_names: list[str] | None = None, user_prefix: str = "Sandbox"
    ) -> None:
        """Generate users and optionally groups.

        Args:
            base_email: Base email for generating sandbox addresses
            user_count: Number of users to create
            group_names: Optional list of group names to create
            user_prefix: Display name prefix (default: "Sandbox")
        """
        self.logger.info("=" * 60)
        self.logger.info("Starting Confluence user/group generation")
        self.logger.info(f"Base email: {base_email}")
        self.logger.info(f"User count: {user_count}")
        self.logger.info(f"Email suffix: {self.email_suffix}")
        self.logger.info(f"Confluence users group: {self.confluence_users_group}")
        self.logger.info(f"Groups: {group_names or 'None'}")
        self.logger.info(f"Dry run: {self.dry_run}")
        self.logger.info("=" * 60)

        # Generate email list for reference
        self.logger.info("\nPlanned user emails:")
        for i in range(1, user_count + 1):
            email = self.generate_sandbox_email(base_email, i)
            self.logger.info(f"  {i}. {email}")

        # Create groups first
        if group_names:
            self.logger.info(f"\nCreating {len(group_names)} groups...")
            self.generate_groups(group_names)

        # Create users
        self.logger.info(f"\nCreating {user_count} users...")
        self.generate_users(base_email, user_count, user_prefix)

        # Summary
        self.logger.info("\n" + "=" * 60)
        self.logger.info("Generation complete!")
        self.logger.info("=" * 60)

        # Groups summary
        if self.existing_groups:
            self.logger.info(f"\nGroups already existing: {len(self.existing_groups)}")
            for group in self.existing_groups:
                self.logger.info(f"  - {group.get('name')} (id: {group.get('id')})")

        created_groups = [g for g in self.created_groups if g.get("status") == "created"]
        if created_groups:
            self.logger.info(f"\nGroups created: {len(created_groups)}")
            for group in created_groups:
                self.logger.info(f"  - {group.get('name')}")

        # Users summary
        if self.existing_users:
            self.logger.info(f"\nUsers already existing: {len(self.existing_users)}")
            for user in self.existing_users:
                self.logger.info(f"  - {user.get('email')} (accountId: {user.get('accountId')})")

        invited_users = [u for u in self.created_users if u.get("status") == "invited"]
        if invited_users:
            self.logger.info(f"\nUsers invited: {len(invited_users)}")
            for user in invited_users:
                self.logger.info(f"  - {user.get('email')} (accountId: {user.get('accountId')})")

        failed_users = [u for u in self.created_users if u.get("status") == "failed"]
        if failed_users:
            self.logger.info(f"\nUsers failed to invite: {len(failed_users)}")
            for user in failed_users:
                self.logger.info(f"  - {user.get('email')}")

        # Final tally
        self.logger.info("\nSummary:")
        self.logger.info(
            f"  Users:  {len(self.existing_users)} existing, {len(invited_users)} invited, {len(failed_users)} failed"
        )
        self.logger.info(f"  Groups: {len(self.existing_groups)} existing, {len(created_groups)} created")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate test users and groups for Confluence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate 5 sandbox users
  %(prog)s --url https://mycompany.atlassian.net \\
           --email admin@mycompany.com \\
           --base-email user@example.com \\
           --users 5

  # Generate users and groups
  %(prog)s --url https://mycompany.atlassian.net \\
           --email admin@mycompany.com \\
           --base-email user@example.com \\
           --users 10 \\
           --groups "Test Group 1" "Test Group 2"

  # Dry run to see what would be created
  %(prog)s --url https://mycompany.atlassian.net \\
           --email admin@mycompany.com \\
           --base-email user@example.com \\
           --users 5 \\
           --dry-run

  # Use custom suffix to avoid collision with Jira sandbox users
  %(prog)s --url https://mycompany.atlassian.net \\
           --email admin@mycompany.com \\
           --base-email user@example.com \\
           --users 5 \\
           --suffix conftest

Generated emails will be in format (default suffix is 'confluence'):
  user+confluence1@example.com
  user+confluence2@example.com
  ...
        """,
    )

    parser.add_argument("--url", required=True, help="Confluence URL (e.g., https://mycompany.atlassian.net)")
    parser.add_argument("--email", required=True, help="Your Confluence admin email")
    parser.add_argument("--token", help="Confluence API token (or set CONFLUENCE_API_TOKEN env var)")
    parser.add_argument("--base-email", required=True, help="Base email for sandbox users (e.g., user@example.com)")
    parser.add_argument("--users", type=int, required=True, help="Number of sandbox users to create")
    parser.add_argument("--groups", nargs="+", help="Group names to create")
    parser.add_argument("--user-prefix", default="Sandbox", help="Display name prefix for users (default: Sandbox)")
    parser.add_argument(
        "--suffix",
        default="confluence",
        help="Email suffix for sandbox users (default: confluence). E.g., user+confluence1@example.com",
    )
    parser.add_argument(
        "--confluence-users-group",
        help="Confluence users group name for granting access. Auto-detected from URL if not specified "
        "(e.g., confluence-users-mycompany for mycompany.atlassian.net)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be created without creating it")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Load environment variables from .env file
    load_dotenv()

    # Get API token
    api_token = args.token or os.environ.get("CONFLUENCE_API_TOKEN")
    if not api_token:
        print("Error: Confluence API token required. Use --token or set CONFLUENCE_API_TOKEN", file=sys.stderr)
        sys.exit(1)

    # Validate user count is positive
    if args.users <= 0:
        print("Error: --users must be a positive integer", file=sys.stderr)
        sys.exit(1)

    try:
        generator = ConfluenceUserGenerator(
            confluence_url=args.url,
            email=args.email,
            api_token=api_token,
            dry_run=args.dry_run,
            email_suffix=args.suffix,
            confluence_users_group=args.confluence_users_group,
        )

        generator.generate_all(
            base_email=args.base_email, user_count=args.users, group_names=args.groups, user_prefix=args.user_prefix
        )

    except KeyboardInterrupt:
        print("\n\nInterrupted by user", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
