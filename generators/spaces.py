"""
Space generation module.

Handles creation of spaces and related items: labels, properties, permissions, look and feel.
"""

import asyncio
import random
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .base import ConfluenceAPIClient

if TYPE_CHECKING:
    from .checkpoint import CheckpointManager


class SpaceGenerator(ConfluenceAPIClient):
    """Generates Confluence spaces and related items."""

    def __init__(
        self,
        confluence_url: str,
        email: str,
        api_token: str,
        prefix: str,
        dry_run: bool = False,
        concurrency: int = 5,
        benchmark: Any | None = None,
        request_delay: float = 0.0,
        checkpoint: "CheckpointManager | None" = None,
    ):
        super().__init__(
            confluence_url,
            email,
            api_token,
            dry_run,
            concurrency,
            benchmark,
            request_delay,
        )
        self.prefix = prefix
        self.checkpoint = checkpoint
        self.run_id = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        # Track created items
        self.created_spaces: list[dict[str, str]] = []

    def set_run_id(self, run_id: str) -> None:
        """Set the run ID (should match the main generator's run ID)."""
        self.run_id = run_id

    # ========== SPACE OPERATIONS ==========

    def get_space(self, space_key: str) -> dict[str, str] | None:
        """Fetch a space's info by key.

        Args:
            space_key: The space key to look up

        Returns:
            Dict with 'key', 'id', 'name' or None if not found
        """
        if self.dry_run:
            return {"key": space_key, "id": f"dry-run-{space_key}", "name": f"Dry Run {space_key}"}

        # v2 API requires filtering by key, not using key in URL path
        response = self._api_call("GET", "spaces", params={"keys": space_key})
        if response:
            data = response.json()
            results = data.get("results", [])
            if results:
                result = results[0]
                return {
                    "key": result.get("key"),
                    "id": result.get("id"),
                    "name": result.get("name"),
                }
        return None

    def create_space(self, key: str, name: str, description: str = "") -> dict[str, str] | None:
        """Create a single space.

        Args:
            key: Space key (uppercase alphanumeric)
            name: Space display name
            description: Optional space description

        Returns:
            Dict with 'key', 'id', 'name' or None on failure
        """
        space_data = {
            "key": key,
            "name": name,
            "description": {
                "representation": "plain",
                "value": description or self.generate_random_text(5, 15),
            },
        }

        if self.dry_run:
            self.logger.info(f"DRY RUN: Would create space {key}")
            return {"key": key, "id": f"dry-run-{key}", "name": name}

        response = self._api_call("POST", "spaces", data=space_data)
        if response:
            result = response.json()
            space = {
                "key": result.get("key"),
                "id": result.get("id"),
                "name": result.get("name"),
            }
            self.logger.info(f"Created space: {key}")
            return space

        # Check if space already exists
        existing = self.get_space(key)
        if existing:
            self.logger.info(f"Space {key} already exists, reusing it")
            return existing

        self.logger.warning(f"Failed to create space {key}")
        return None

    def create_spaces(self, count: int) -> list[dict[str, str]]:
        """Create multiple spaces.

        Args:
            count: Number of spaces to create

        Returns:
            List of space dicts with 'key', 'id', 'name'
        """
        self.logger.info(f"Creating {count} spaces...")

        created_spaces = []

        for i in range(count):
            # Space keys are uppercase, max 255 chars
            # Use prefix (max 6 chars) + sequential number
            space_key = f"{self.prefix[:6].upper()}{i + 1}"
            space_name = f"{self.prefix} Test Space {i + 1}"

            space = self.create_space(space_key, space_name)
            if space:
                created_spaces.append(space)

            # Small delay to avoid rate limiting
            time.sleep(0.3)

        self.created_spaces = created_spaces
        return created_spaces

    # ========== SPACE LABELS ==========

    def add_space_label(self, space_key: str, label: str) -> bool:
        """Add a label to a space.

        Note: Uses legacy REST API as v2 doesn't support space labels.

        Args:
            space_key: The space key (not ID)
            label: Label to add (alphanumeric and hyphens only)

        Returns:
            True if successful
        """
        # Labels must be lowercase alphanumeric with hyphens
        clean_label = label.lower().replace(" ", "-")

        # Legacy API expects array of label objects
        label_data = [{"prefix": "global", "name": clean_label}]

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would add label '{clean_label}' to space {space_key}")
            return True

        base_url = f"{self.confluence_url}/rest/api"
        response = self._api_call("POST", f"space/{space_key}/label", data=label_data, base_url=base_url)
        if response:
            self.logger.debug(f"Added label '{clean_label}' to space {space_key}")
            return True
        return False

    def add_space_labels(self, space_keys: list[str], count: int) -> int:
        """Add labels distributed across spaces.

        Args:
            space_keys: List of space keys
            count: Total number of labels to add

        Returns:
            Number of labels added
        """
        if not space_keys:
            return 0

        self.logger.info(f"Adding {count} space labels...")

        label_types = [
            "project",
            "documentation",
            "archive",
            "public",
            "private",
            "team",
            "department",
            "internal",
        ]

        created = 0
        for i in range(count):
            space_key = space_keys[i % len(space_keys)]
            label_type = label_types[i % len(label_types)]
            label = f"{self.prefix.lower()}-{label_type}-{i + 1}"

            if self.add_space_label(space_key, label):
                created += 1

            if (i + 1) % 50 == 0:
                self.logger.info(f"Added {created}/{count} space labels")
                time.sleep(0.2)

        self.logger.info(f"Space labels complete: {created} added")
        return created

    # ========== SPACE CATEGORIES ==========
    #
    # Note: Space labels are deprecated in Confluence Cloud, replaced by categories.
    # However, we still create labels for backup compatibility (existing backups contain labels).
    # Categories are created alongside labels in the same ratio.
    #

    def add_space_category(self, space_key: str, category_name: str) -> bool:
        """Add a category to a space.

        Categories replaced labels in Confluence Cloud for organizing spaces.
        Uses the legacy REST API for content labels with category prefix.

        Note: Confluence Cloud "categories" are implemented as labels with a
        special prefix in the legacy API. The v2 API doesn't have a dedicated
        categories endpoint.

        Args:
            space_key: The space key (not ID)
            category_name: Category name to add

        Returns:
            True if successful
        """
        # Categories are implemented as labels with "team" prefix in legacy API
        # This makes them appear in the space directory categorization
        clean_name = category_name.lower().replace(" ", "-")
        category_data = [{"prefix": "team", "name": clean_name}]

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would add category '{clean_name}' to space {space_key}")
            return True

        base_url = f"{self.confluence_url}/rest/api"
        response = self._api_call("POST", f"space/{space_key}/label", data=category_data, base_url=base_url)
        if response:
            self.logger.debug(f"Added category '{clean_name}' to space {space_key}")
            return True
        return False

    def add_space_categories(self, space_keys: list[str], count: int) -> int:
        """Add categories distributed across spaces.

        Args:
            space_keys: List of space keys
            count: Total number of categories to add

        Returns:
            Number of categories added
        """
        if not space_keys:
            return 0

        self.logger.info(f"Adding {count} space categories...")

        category_types = [
            "Project",
            "Documentation",
            "Archive",
            "Public",
            "Private",
            "Team",
            "Department",
            "Internal",
        ]

        created = 0
        for i in range(count):
            space_key = space_keys[i % len(space_keys)]
            category_type = category_types[i % len(category_types)]
            category_name = f"{self.prefix}-{category_type}-{i + 1}"

            if self.add_space_category(space_key, category_name):
                created += 1

            if (i + 1) % 50 == 0:
                self.logger.info(f"Added {created}/{count} space categories")
                time.sleep(0.2)

        self.logger.info(f"Space categories complete: {created} added")
        return created

    async def add_space_category_async(self, space_key: str, category_name: str) -> bool:
        """Add a category to a space asynchronously.

        Args:
            space_key: The space key (not ID)
            category_name: Category name to add

        Returns:
            True if successful
        """
        clean_name = category_name.lower().replace(" ", "-")
        category_data = [{"prefix": "team", "name": clean_name}]

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would add category '{clean_name}' to space {space_key}")
            return True

        base_url = f"{self.confluence_url}/rest/api"
        success, _ = await self._api_call_async(
            "POST", f"space/{space_key}/label", data=category_data, base_url=base_url
        )
        return success

    async def add_space_categories_async(self, space_keys: list[str], count: int) -> int:
        """Add categories to spaces asynchronously with batching.

        Args:
            space_keys: List of space keys
            count: Total number of categories to add

        Returns:
            Number of categories added
        """
        if not space_keys:
            return 0

        self.logger.info(f"Adding {count} space categories (async, concurrency: {self.concurrency})...")

        category_types = [
            "Project",
            "Documentation",
            "Archive",
            "Public",
            "Private",
            "Team",
            "Department",
            "Internal",
        ]

        created = 0
        batch_size = self.concurrency * 2

        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)

            tasks = []
            for i in range(batch_start, batch_end):
                space_key = space_keys[i % len(space_keys)]
                category_type = category_types[i % len(category_types)]
                category_name = f"{self.prefix}-{category_type}-{i + 1}"
                tasks.append(self.add_space_category_async(space_key, category_name))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if result is True:
                    created += 1

            self.logger.info(f"Added {created}/{count} space categories")

        self.logger.info(f"Space categories complete: {created} added")
        return created

    # ========== SPACE PROPERTIES ==========

    def set_space_property(self, space_id: str, key: str, value: dict) -> bool:
        """Set a space property.

        Args:
            space_id: The space ID
            key: Property key
            value: Property value (JSON-serializable dict)

        Returns:
            True if successful
        """
        property_data = {"key": key, "value": value}

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would set property '{key}' on space {space_id}")
            return True

        response = self._api_call("POST", f"spaces/{space_id}/properties", data=property_data)
        if response:
            self.logger.debug(f"Set property '{key}' on space {space_id}")
            return True
        return False

    def set_space_properties(self, space_ids: list[str], count: int) -> int:
        """Set properties distributed across spaces.

        Args:
            space_ids: List of space IDs
            count: Total number of properties to set

        Returns:
            Number of properties set
        """
        if not space_ids:
            return 0

        self.logger.info(f"Setting {count} space properties...")

        created = 0
        for i in range(count):
            space_id = space_ids[i % len(space_ids)]
            property_key = f"{self.prefix.lower()}_property_{i + 1}"

            property_value = {
                "generatedBy": "confluence-test-data-generator",
                "runId": self.run_id,
                "timestamp": datetime.now().isoformat(),
                "index": i + 1,
                "category": random.choice(["config", "metadata", "settings", "cache"]),
                "data": {
                    "enabled": random.choice([True, False]),
                    "threshold": random.randint(1, 100),
                    "mode": random.choice(["auto", "manual", "scheduled"]),
                    "description": self.generate_random_text(5, 15),
                },
            }

            if self.set_space_property(space_id, property_key, property_value):
                created += 1

            if (i + 1) % 50 == 0:
                self.logger.info(f"Set {created}/{count} space properties")
                time.sleep(0.2)

        self.logger.info(f"Space properties complete: {created} set")
        return created

    # ========== SPACE PERMISSIONS ==========

    # "View only" is a system role that isn't available on standard spaces
    EXCLUDED_SPACE_ROLES = {"View only"}

    def get_space_roles(self) -> list[dict]:
        """Fetch available space roles from Confluence.

        Excludes roles that aren't assignable on standard spaces (e.g. "View only").

        Returns:
            List of role dicts with 'id' and 'name' keys, or defaults for dry run.
        """
        if self.dry_run:
            return [
                {"id": "dry-run-role-1", "name": "Collaborator"},
                {"id": "dry-run-role-2", "name": "Viewer"},
                {"id": "dry-run-role-3", "name": "Manager"},
                {"id": "dry-run-role-4", "name": "Admin"},
            ]

        response = self._api_call("GET", "space-roles")
        if response:
            roles = response.json().get("results", [])
            return [r for r in roles if r.get("name") not in self.EXCLUDED_SPACE_ROLES]
        return []

    def add_space_role_assignment(
        self,
        space_id: str,
        role_id: str,
        principal_id: str,
    ) -> bool:
        """Assign a role to a user in a space.

        Uses the v2 role-assignment API. Confluence Cloud sites in RBAC mode
        require role assignments instead of direct permission grants.

        Args:
            space_id: The space ID (not key)
            role_id: The role UUID from get_space_roles()
            principal_id: User account ID

        Returns:
            True if successful
        """
        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would assign role {role_id} to user in space {space_id}")
            return True

        assignment_data = [
            {
                "roleId": role_id,
                "principal": {
                    "principalType": "USER",
                    "principalId": principal_id,
                },
            }
        ]

        response = self._api_call("POST", f"spaces/{space_id}/role-assignments", data=assignment_data)
        if response:
            self.logger.debug(f"Assigned role to user in space {space_id}")
            return True
        return False

    def add_space_permissions(
        self,
        space_ids: list[str],
        user_account_ids: list[str],
        count: int,
    ) -> int:
        """Add role assignments distributed across spaces and users.

        Each role assignment grants multiple underlying permissions. Uses the
        v2 role-assignment API which works with Confluence Cloud RBAC mode.

        Args:
            space_ids: List of space IDs
            user_account_ids: List of user account IDs
            count: Total number of role assignments to add

        Returns:
            Number of role assignments added
        """
        if not space_ids or not user_account_ids:
            return 0

        roles = self.get_space_roles()
        if not roles:
            self.logger.warning("No space roles found — skipping space permissions")
            return 0

        role_ids = [r["id"] for r in roles]
        self.logger.info(f"Adding {count} space role assignments ({len(roles)} roles available)...")

        created = 0
        assignment_index = 0

        for space_id in space_ids:
            for user_id in user_account_ids:
                for role_id in role_ids:
                    if assignment_index >= count:
                        break

                    if self.add_space_role_assignment(space_id, role_id, user_id):
                        created += 1

                    assignment_index += 1

                    if assignment_index % 100 == 0:
                        self.logger.info(f"Added {created}/{count} space role assignments")
                        if self.request_delay > 0:
                            time.sleep(self.request_delay)

                if assignment_index >= count:
                    break
            if assignment_index >= count:
                break

        self.logger.info(f"Space role assignments complete: {created} added")
        return created

    # ========== SPACE LOOK AND FEEL ==========

    def set_space_look_and_feel(
        self,
        space_key: str,
        settings: dict | None = None,
    ) -> bool:
        """Set space look and feel settings.

        Uses the legacy REST API endpoint as this isn't available in v2.

        Args:
            space_key: The space key (not ID)
            settings: Optional custom settings dict. If None, uses defaults.

        Returns:
            True if successful
        """
        if settings is None:
            # Generate random look and feel settings
            settings = {
                "spaceKey": space_key,
                "headings": {
                    "color": f"#{random.randint(0, 0xFFFFFF):06x}",
                },
                "links": {
                    "color": f"#{random.randint(0, 0xFFFFFF):06x}",
                },
                "menus": {
                    "hoverOrFocus": {
                        "backgroundColor": f"#{random.randint(0, 0xFFFFFF):06x}",
                    },
                    "color": f"#{random.randint(0, 0xFFFFFF):06x}",
                },
                "header": {
                    "backgroundColor": f"#{random.randint(0, 0xFFFFFF):06x}",
                    "button": {
                        "backgroundColor": f"#{random.randint(0, 0xFFFFFF):06x}",
                        "color": f"#{random.randint(0, 0xFFFFFF):06x}",
                    },
                },
                "content": {
                    "screen": {
                        "background": f"#{random.randint(0, 0xFFFFFF):06x}",
                    },
                },
                "bordersAndDividers": {
                    "color": f"#{random.randint(0, 0xFFFFFF):06x}",
                },
            }

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would set look and feel for space {space_key}")
            return True

        # Look and feel uses the legacy REST API
        base_url = f"{self.confluence_url}/rest/api"
        response = self._api_call(
            "PUT",
            "settings/lookandfeel/custom",
            data=settings,
            base_url=base_url,
            params={"spaceKey": space_key},
        )

        if response:
            self.logger.debug(f"Set look and feel for space {space_key}")
            return True
        return False

    def set_space_look_and_feel_multiple(
        self,
        space_keys: list[str],
        count: int,
    ) -> int:
        """Set look and feel for multiple spaces.

        Args:
            space_keys: List of space keys
            count: Number of spaces to configure (may be less than len(space_keys))

        Returns:
            Number of spaces configured
        """
        if not space_keys:
            return 0

        self.logger.info(f"Setting look and feel for {count} spaces...")

        created = 0
        for i in range(min(count, len(space_keys))):
            space_key = space_keys[i]

            if self.set_space_look_and_feel(space_key):
                created += 1

            if (i + 1) % 10 == 0:
                self.logger.info(f"Configured {created}/{count} space look and feel settings")
                time.sleep(0.3)

        self.logger.info(f"Space look and feel complete: {created} configured")
        return created

    # ========== ASYNC METHODS ==========

    async def create_space_async(
        self,
        key: str,
        name: str,
        description: str = "",
    ) -> dict[str, str] | None:
        """Create a single space asynchronously.

        Args:
            key: Space key (uppercase alphanumeric)
            name: Space display name
            description: Optional space description

        Returns:
            Dict with 'key', 'id', 'name' or None on failure
        """
        space_data = {
            "key": key,
            "name": name,
            "description": {
                "representation": "plain",
                "value": description or self.generate_random_text(5, 15),
            },
        }

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would create space {key}")
            return {"key": key, "id": f"dry-run-{key}", "name": name}

        success, result = await self._api_call_async("POST", "spaces", data=space_data)
        if success and result:
            space = {
                "key": result.get("key"),
                "id": result.get("id"),
                "name": result.get("name"),
            }
            self.logger.info(f"Created space: {key}")
            return space

        self.logger.warning(f"Failed to create space {key}")
        return None

    async def create_spaces_async(self, count: int) -> list[dict[str, str]]:
        """Create multiple spaces asynchronously.

        Note: Spaces are created sequentially to avoid key conflicts and
        because the count is typically low.

        Args:
            count: Number of spaces to create

        Returns:
            List of space dicts with 'key', 'id', 'name'
        """
        self.logger.info(f"Creating {count} spaces (async)...")

        created_spaces = []

        for i in range(count):
            space_key = f"{self.prefix[:6].upper()}{i + 1}"
            space_name = f"{self.prefix} Test Space {i + 1}"

            space = await self.create_space_async(space_key, space_name)
            if space:
                created_spaces.append(space)

        self.created_spaces = created_spaces
        return created_spaces

    async def add_space_label_async(self, space_key: str, label: str) -> bool:
        """Add a label to a space asynchronously.

        Note: Uses legacy REST API as v2 doesn't support space labels.

        Args:
            space_key: The space key (not ID)
            label: Label to add

        Returns:
            True if successful
        """
        clean_label = label.lower().replace(" ", "-")
        label_data = [{"prefix": "global", "name": clean_label}]

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would add label '{clean_label}' to space {space_key}")
            return True

        base_url = f"{self.confluence_url}/rest/api"
        success, _ = await self._api_call_async("POST", f"space/{space_key}/label", data=label_data, base_url=base_url)
        return success

    async def add_space_labels_async(self, space_keys: list[str], count: int) -> int:
        """Add labels to spaces asynchronously with batching.

        Args:
            space_keys: List of space keys
            count: Total number of labels to add

        Returns:
            Number of labels added
        """
        if not space_keys:
            return 0

        self.logger.info(f"Adding {count} space labels (async, concurrency: {self.concurrency})...")

        label_types = [
            "project",
            "documentation",
            "archive",
            "public",
            "private",
            "team",
            "department",
            "internal",
        ]

        created = 0
        batch_size = self.concurrency * 2

        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)

            tasks = []
            for i in range(batch_start, batch_end):
                space_key = space_keys[i % len(space_keys)]
                label_type = label_types[i % len(label_types)]
                label = f"{self.prefix.lower()}-{label_type}-{i + 1}"
                tasks.append(self.add_space_label_async(space_key, label))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if result is True:
                    created += 1

            self.logger.info(f"Added {created}/{count} space labels")

        self.logger.info(f"Space labels complete: {created} added")
        return created

    async def set_space_property_async(
        self,
        space_id: str,
        key: str,
        value: dict,
    ) -> bool:
        """Set a space property asynchronously.

        Args:
            space_id: The space ID
            key: Property key
            value: Property value

        Returns:
            True if successful
        """
        property_data = {"key": key, "value": value}

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would set property '{key}' on space {space_id}")
            return True

        success, _ = await self._api_call_async("POST", f"spaces/{space_id}/properties", data=property_data)
        return success

    async def set_space_properties_async(self, space_ids: list[str], count: int) -> int:
        """Set properties on spaces asynchronously with batching.

        Args:
            space_ids: List of space IDs
            count: Total number of properties to set

        Returns:
            Number of properties set
        """
        if not space_ids:
            return 0

        self.logger.info(f"Setting {count} space properties (async, concurrency: {self.concurrency})...")

        created = 0
        batch_size = self.concurrency * 2

        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)

            tasks = []
            for i in range(batch_start, batch_end):
                space_id = space_ids[i % len(space_ids)]
                property_key = f"{self.prefix.lower()}_property_{i + 1}"

                property_value = {
                    "generatedBy": "confluence-test-data-generator",
                    "runId": self.run_id,
                    "timestamp": datetime.now().isoformat(),
                    "index": i + 1,
                    "category": random.choice(["config", "metadata", "settings", "cache"]),
                    "data": {
                        "enabled": random.choice([True, False]),
                        "threshold": random.randint(1, 100),
                        "mode": random.choice(["auto", "manual", "scheduled"]),
                        "description": self.generate_random_text(5, 15),
                    },
                }

                tasks.append(self.set_space_property_async(space_id, property_key, property_value))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if result is True:
                    created += 1

            self.logger.info(f"Set {created}/{count} space properties")

        self.logger.info(f"Space properties complete: {created} set")
        return created

    async def add_space_role_assignment_async(
        self,
        space_id: str,
        role_id: str,
        principal_id: str,
    ) -> bool:
        """Assign a role to a user in a space asynchronously.

        Uses the v2 role-assignment API. Confluence Cloud sites in RBAC mode
        require role assignments instead of direct permission grants.

        Args:
            space_id: The space ID (not key)
            role_id: The role UUID from get_space_roles()
            principal_id: User account ID

        Returns:
            True if successful
        """
        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would assign role {role_id} to user in space {space_id}")
            return True

        assignment_data = [
            {
                "roleId": role_id,
                "principal": {
                    "principalType": "USER",
                    "principalId": principal_id,
                },
            }
        ]

        success, _ = await self._api_call_async("POST", f"spaces/{space_id}/role-assignments", data=assignment_data)
        return success

    async def add_space_permissions_async(
        self,
        space_ids: list[str],
        user_account_ids: list[str],
        count: int,
    ) -> int:
        """Add role assignments to spaces asynchronously with batching.

        Each role assignment grants multiple underlying permissions. Uses the
        v2 role-assignment API which works with Confluence Cloud RBAC mode.

        Args:
            space_ids: List of space IDs
            user_account_ids: List of user account IDs
            count: Total number of role assignments to add

        Returns:
            Number of role assignments added
        """
        if not space_ids or not user_account_ids:
            return 0

        roles = self.get_space_roles()
        if not roles:
            self.logger.warning("No space roles found — skipping space permissions")
            return 0

        role_ids = [r["id"] for r in roles]
        self.logger.info(
            f"Adding {count} space role assignments (async, concurrency: {self.concurrency}, {len(roles)} roles)..."
        )

        # Pre-compute all assignment combinations up to count
        assignment_specs = []
        for space_id in space_ids:
            for user_id in user_account_ids:
                for role_id in role_ids:
                    if len(assignment_specs) >= count:
                        break
                    assignment_specs.append((space_id, role_id, user_id))
                if len(assignment_specs) >= count:
                    break
            if len(assignment_specs) >= count:
                break

        created = 0
        batch_size = self.concurrency * 2

        for batch_start in range(0, len(assignment_specs), batch_size):
            batch = assignment_specs[batch_start : batch_start + batch_size]
            tasks = [
                self.add_space_role_assignment_async(space_id, role_id, user_id) for space_id, role_id, user_id in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if result is True:
                    created += 1
                elif isinstance(result, Exception):
                    self._record_error()
                    self.logger.error(f"Role assignment task failed: {result}")

            self.logger.info(f"Added {created}/{count} space role assignments")

        self.logger.info(f"Space role assignments complete: {created} added")
        return created
