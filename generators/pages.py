"""
Page generation module.

Handles creation of pages and related items: labels, properties, restrictions, versions.
"""

import asyncio
import random
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .base import ConfluenceAPIClient

if TYPE_CHECKING:
    from .checkpoint import CheckpointManager


class PageGenerator(ConfluenceAPIClient):
    """Generates Confluence pages and related items."""

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
        self.created_pages: list[dict[str, str]] = []

    def set_run_id(self, run_id: str) -> None:
        """Set the run ID (should match the main generator's run ID)."""
        self.run_id = run_id

    # ========== PAGE OPERATIONS ==========

    def create_page(
        self,
        space_id: str,
        title: str,
        parent_id: str | None = None,
    ) -> dict[str, str] | None:
        """Create a single page.

        Args:
            space_id: Space ID to create the page in
            title: Page title
            parent_id: Optional parent page ID for hierarchy

        Returns:
            Dict with 'id', 'title', 'spaceId' (and 'parentId' if set) or None on failure
        """
        body_content = f"<p>{self.generate_random_text(10, 30)}</p>"

        page_data: dict[str, Any] = {
            "spaceId": space_id,
            "title": title,
            "status": "current",
            "body": {
                "representation": "storage",
                "value": body_content,
            },
        }

        if parent_id:
            page_data["parentId"] = parent_id

        if self.dry_run:
            self.logger.info(f"DRY RUN: Would create page '{title}' in space {space_id}")
            result = {"id": f"dry-run-{space_id}-{title}", "title": title, "spaceId": space_id}
            if parent_id:
                result["parentId"] = parent_id
            return result

        response = self._api_call("POST", "pages", data=page_data)
        if response:
            result = response.json()
            page = {
                "id": result.get("id"),
                "title": result.get("title"),
                "spaceId": result.get("spaceId"),
            }
            if parent_id:
                page["parentId"] = parent_id
            self.logger.info(f"Created page: {title}")
            return page

        self.logger.warning(f"Failed to create page '{title}'")
        return None

    def create_pages(
        self,
        spaces: list[dict[str, str]],
        count: int,
    ) -> list[dict[str, str]]:
        """Create multiple pages distributed across spaces with hierarchy.

        Pages are created with a parent-child hierarchy:
        - ~60% root pages (no parent)
        - ~30% level 1 children (parent is a root page)
        - ~10% level 2+ children (parent is a level 1 page)

        Args:
            spaces: List of space dicts with 'key' and 'id'
            count: Total number of pages to create

        Returns:
            List of page dicts with 'id', 'title', 'spaceId'
        """
        if not spaces:
            return []

        self.logger.info(f"Creating {count} pages...")

        created_pages: list[dict[str, str]] = []
        # Track pages per space for hierarchy
        space_pages: dict[str, list[dict[str, str]]] = {s["id"]: [] for s in spaces}

        for i in range(count):
            space = spaces[i % len(spaces)]
            space_id = space["id"]
            title = f"{self.prefix} Page {i + 1}"

            # Determine parent based on hierarchy distribution
            parent_id = None
            existing = space_pages[space_id]

            if existing:
                roll = random.random()
                if roll < 0.6:
                    # Root page (no parent)
                    parent_id = None
                elif roll < 0.9:
                    # Level 1 child - parent is a root page
                    root_pages = [p for p in existing if p.get("parentId") is None]
                    if root_pages:
                        parent_id = random.choice(root_pages)["id"]
                else:
                    # Level 2+ child - parent is any existing page
                    parent_id = random.choice(existing)["id"]

            page = self.create_page(space_id, title, parent_id=parent_id)
            if page:
                created_pages.append(page)
                space_pages[space_id].append(page)

            time.sleep(0.1)

        self.created_pages = created_pages
        return created_pages

    # ========== PAGE LABELS ==========

    def add_page_label(self, page_id: str, label: str) -> bool:
        """Add a label to a page.

        Note: Uses legacy REST API as v2 returns 405 for page labels.

        Args:
            page_id: The page ID
            label: Label to add

        Returns:
            True if successful
        """
        clean_label = label.lower().replace(" ", "-")
        label_data = [{"prefix": "global", "name": clean_label}]

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would add label '{clean_label}' to page {page_id}")
            return True

        base_url = f"{self.confluence_url}/rest/api"
        response = self._api_call("POST", f"content/{page_id}/label", data=label_data, base_url=base_url)
        if response:
            self.logger.debug(f"Added label '{clean_label}' to page {page_id}")
            return True
        return False

    def add_page_labels(self, page_ids: list[str], count: int) -> int:
        """Add labels distributed across pages.

        Args:
            page_ids: List of page IDs
            count: Total number of labels to add

        Returns:
            Number of labels added
        """
        if not page_ids:
            return 0

        self.logger.info(f"Adding {count} page labels...")

        label_types = [
            "documentation",
            "howto",
            "reference",
            "tutorial",
            "draft",
            "review",
            "approved",
            "archived",
        ]

        created = 0
        for i in range(count):
            page_id = page_ids[i % len(page_ids)]
            label_type = label_types[i % len(label_types)]
            label = f"{self.prefix.lower()}-{label_type}-{i + 1}"

            if self.add_page_label(page_id, label):
                created += 1

            if (i + 1) % 50 == 0:
                self.logger.info(f"Added {created}/{count} page labels")
                time.sleep(0.2)

        self.logger.info(f"Page labels complete: {created} added")
        return created

    # ========== PAGE PROPERTIES ==========

    def set_page_property(self, page_id: str, key: str, value: dict) -> bool:
        """Set a page property.

        Args:
            page_id: The page ID
            key: Property key
            value: Property value (JSON-serializable dict)

        Returns:
            True if successful
        """
        property_data = {"key": key, "value": value}

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would set property '{key}' on page {page_id}")
            return True

        response = self._api_call("POST", f"pages/{page_id}/properties", data=property_data)
        if response:
            self.logger.debug(f"Set property '{key}' on page {page_id}")
            return True
        return False

    def set_page_properties(self, page_ids: list[str], count: int) -> int:
        """Set properties distributed across pages.

        Args:
            page_ids: List of page IDs
            count: Total number of properties to set

        Returns:
            Number of properties set
        """
        if not page_ids:
            return 0

        self.logger.info(f"Setting {count} page properties...")

        created = 0
        for i in range(count):
            page_id = page_ids[i % len(page_ids)]
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

            if self.set_page_property(page_id, property_key, property_value):
                created += 1

            if (i + 1) % 50 == 0:
                self.logger.info(f"Set {created}/{count} page properties")
                time.sleep(0.2)

        self.logger.info(f"Page properties complete: {created} set")
        return created

    # ========== PAGE RESTRICTIONS ==========

    def add_page_restriction(
        self,
        page_id: str,
        user_account_id: str,
        operation: str,
    ) -> bool:
        """Add a restriction to a page.

        Uses the legacy REST API as v2 doesn't support setting restrictions directly.

        Args:
            page_id: The page ID
            user_account_id: User account ID
            operation: 'read' or 'update'

        Returns:
            True if successful
        """
        restriction_data = [
            {
                "operation": operation,
                "restrictions": {
                    "user": [{"type": "known", "accountId": user_account_id}],
                },
            }
        ]

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would add '{operation}' restriction to page {page_id}")
            return True

        base_url = f"{self.confluence_url}/rest/api"
        response = self._api_call("PUT", f"content/{page_id}/restriction", data=restriction_data, base_url=base_url)
        if response:
            self.logger.debug(f"Added '{operation}' restriction to page {page_id}")
            return True
        return False

    def add_page_restrictions(
        self,
        page_ids: list[str],
        user_account_ids: list[str],
        count: int,
    ) -> int:
        """Add restrictions distributed across pages and users.

        Args:
            page_ids: List of page IDs
            user_account_ids: List of user account IDs
            count: Total number of restrictions to add

        Returns:
            Number of restrictions added
        """
        if not page_ids or not user_account_ids:
            return 0

        self.logger.info(f"Adding {count} page restrictions...")

        operations = ["read", "update"]

        created = 0
        restriction_index = 0

        for page_id in page_ids:
            for user_id in user_account_ids:
                for operation in operations:
                    if restriction_index >= count:
                        break

                    if self.add_page_restriction(page_id, user_id, operation):
                        created += 1

                    restriction_index += 1

                    if restriction_index % 100 == 0:
                        self.logger.info(f"Added {created}/{count} page restrictions")
                        time.sleep(0.2)

                if restriction_index >= count:
                    break
            if restriction_index >= count:
                break

        self.logger.info(f"Page restrictions complete: {created} added")
        return created

    # ========== PAGE VERSIONS ==========

    def create_page_version(self, page_id: str, title: str) -> bool:
        """Create a new version of a page by updating its content.

        Gets the current version number, then updates with incremented version.

        Args:
            page_id: The page ID
            title: The page title (required for update)

        Returns:
            True if successful
        """
        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would create new version of page {page_id}")
            return True

        # Get current page to find version number
        response = self._api_call("GET", f"pages/{page_id}", params={"body-format": "storage"})
        if not response:
            self.logger.warning(f"Failed to get page {page_id} for versioning")
            return False

        page_data = response.json()
        current_version = page_data.get("version", {}).get("number", 1)

        # Update with new content and incremented version
        new_body = f"<p>{self.generate_random_text(10, 30)}</p>"
        update_data = {
            "id": page_id,
            "status": "current",
            "title": title,
            "body": {
                "representation": "storage",
                "value": new_body,
            },
            "version": {
                "number": current_version + 1,
                "message": f"Auto-generated version {current_version + 1}",
            },
        }

        response = self._api_call("PUT", f"pages/{page_id}", data=update_data)
        if response:
            self.logger.debug(f"Created version {current_version + 1} of page {page_id}")
            return True
        return False

    def create_page_versions(
        self,
        pages: list[dict[str, str]],
        count: int,
    ) -> int:
        """Create multiple page versions distributed across pages.

        Args:
            pages: List of page dicts with 'id' and 'title'
            count: Total number of versions to create

        Returns:
            Number of versions created
        """
        if not pages:
            return 0

        self.logger.info(f"Creating {count} page versions...")

        created = 0
        for i in range(count):
            page = pages[i % len(pages)]

            if self.create_page_version(page["id"], page["title"]):
                created += 1

            if (i + 1) % 50 == 0:
                self.logger.info(f"Created {created}/{count} page versions")
                time.sleep(0.2)

        self.logger.info(f"Page versions complete: {created} created")
        return created

    # ========== ASYNC METHODS ==========

    async def create_page_async(
        self,
        space_id: str,
        title: str,
        parent_id: str | None = None,
    ) -> dict[str, str] | None:
        """Create a single page asynchronously.

        Args:
            space_id: Space ID to create the page in
            title: Page title
            parent_id: Optional parent page ID

        Returns:
            Dict with 'id', 'title', 'spaceId' or None on failure
        """
        body_content = f"<p>{self.generate_random_text(10, 30)}</p>"

        page_data: dict[str, Any] = {
            "spaceId": space_id,
            "title": title,
            "status": "current",
            "body": {
                "representation": "storage",
                "value": body_content,
            },
        }

        if parent_id:
            page_data["parentId"] = parent_id

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would create page '{title}' in space {space_id}")
            result = {"id": f"dry-run-{space_id}-{title}", "title": title, "spaceId": space_id}
            if parent_id:
                result["parentId"] = parent_id
            return result

        success, result = await self._api_call_async("POST", "pages", data=page_data)
        if success and result:
            page = {
                "id": result.get("id"),
                "title": result.get("title"),
                "spaceId": result.get("spaceId"),
            }
            if parent_id:
                page["parentId"] = parent_id
            self.logger.info(f"Created page: {title}")
            return page

        self.logger.warning(f"Failed to create page '{title}'")
        return None

    async def create_pages_async(
        self,
        spaces: list[dict[str, str]],
        count: int,
    ) -> list[dict[str, str]]:
        """Create multiple pages asynchronously with hierarchy.

        Pages are created sequentially per space to build proper hierarchy,
        but multiple spaces can be processed concurrently.

        Args:
            spaces: List of space dicts with 'key' and 'id'
            count: Total number of pages to create

        Returns:
            List of page dicts
        """
        if not spaces:
            return []

        self.logger.info(f"Creating {count} pages (async)...")

        created_pages: list[dict[str, str]] = []
        space_pages: dict[str, list[dict[str, str]]] = {s["id"]: [] for s in spaces}

        # Pages need to be created sequentially within a space for hierarchy
        for i in range(count):
            space = spaces[i % len(spaces)]
            space_id = space["id"]
            title = f"{self.prefix} Page {i + 1}"

            parent_id = None
            existing = space_pages[space_id]

            if existing:
                roll = random.random()
                if roll < 0.6:
                    parent_id = None
                elif roll < 0.9:
                    root_pages = [p for p in existing if p.get("parentId") is None]
                    if root_pages:
                        parent_id = random.choice(root_pages)["id"]
                else:
                    parent_id = random.choice(existing)["id"]

            page = await self.create_page_async(space_id, title, parent_id=parent_id)
            if page:
                created_pages.append(page)
                space_pages[space_id].append(page)

        self.created_pages = created_pages
        return created_pages

    async def add_page_label_async(self, page_id: str, label: str) -> bool:
        """Add a label to a page asynchronously.

        Note: Uses legacy REST API as v2 returns 405 for page labels.

        Args:
            page_id: The page ID
            label: Label to add

        Returns:
            True if successful
        """
        clean_label = label.lower().replace(" ", "-")
        label_data = [{"prefix": "global", "name": clean_label}]

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would add label '{clean_label}' to page {page_id}")
            return True

        base_url = f"{self.confluence_url}/rest/api"
        success, _ = await self._api_call_async("POST", f"content/{page_id}/label", data=label_data, base_url=base_url)
        return success

    async def add_page_labels_async(self, page_ids: list[str], count: int) -> int:
        """Add labels to pages asynchronously with batching.

        Args:
            page_ids: List of page IDs
            count: Total number of labels to add

        Returns:
            Number of labels added
        """
        if not page_ids:
            return 0

        self.logger.info(f"Adding {count} page labels (async, concurrency: {self.concurrency})...")

        label_types = [
            "documentation",
            "howto",
            "reference",
            "tutorial",
            "draft",
            "review",
            "approved",
            "archived",
        ]

        created = 0
        batch_size = self.concurrency * 2

        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)

            tasks = []
            for i in range(batch_start, batch_end):
                page_id = page_ids[i % len(page_ids)]
                label_type = label_types[i % len(label_types)]
                label = f"{self.prefix.lower()}-{label_type}-{i + 1}"
                tasks.append(self.add_page_label_async(page_id, label))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if result is True:
                    created += 1

            self.logger.info(f"Added {created}/{count} page labels")

        self.logger.info(f"Page labels complete: {created} added")
        return created

    async def set_page_property_async(
        self,
        page_id: str,
        key: str,
        value: dict,
    ) -> bool:
        """Set a page property asynchronously.

        Args:
            page_id: The page ID
            key: Property key
            value: Property value

        Returns:
            True if successful
        """
        property_data = {"key": key, "value": value}

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would set property '{key}' on page {page_id}")
            return True

        success, _ = await self._api_call_async("POST", f"pages/{page_id}/properties", data=property_data)
        return success

    async def set_page_properties_async(self, page_ids: list[str], count: int) -> int:
        """Set properties on pages asynchronously with batching.

        Args:
            page_ids: List of page IDs
            count: Total number of properties to set

        Returns:
            Number of properties set
        """
        if not page_ids:
            return 0

        self.logger.info(f"Setting {count} page properties (async, concurrency: {self.concurrency})...")

        created = 0
        batch_size = self.concurrency * 2

        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)

            tasks = []
            for i in range(batch_start, batch_end):
                page_id = page_ids[i % len(page_ids)]
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

                tasks.append(self.set_page_property_async(page_id, property_key, property_value))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if result is True:
                    created += 1

            self.logger.info(f"Set {created}/{count} page properties")

        self.logger.info(f"Page properties complete: {created} set")
        return created

    async def add_page_restriction_async(
        self,
        page_id: str,
        user_account_id: str,
        operation: str,
    ) -> bool:
        """Add a restriction to a page asynchronously.

        Args:
            page_id: The page ID
            user_account_id: User account ID
            operation: 'read' or 'update'

        Returns:
            True if successful
        """
        restriction_data = [
            {
                "operation": operation,
                "restrictions": {
                    "user": [{"type": "known", "accountId": user_account_id}],
                },
            }
        ]

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would add '{operation}' restriction to page {page_id}")
            return True

        base_url = f"{self.confluence_url}/rest/api"
        success, _ = await self._api_call_async(
            "PUT", f"content/{page_id}/restriction", data=restriction_data, base_url=base_url
        )
        return success

    async def add_page_restrictions_async(
        self,
        page_ids: list[str],
        user_account_ids: list[str],
        count: int,
    ) -> int:
        """Add restrictions to pages asynchronously with batching.

        Args:
            page_ids: List of page IDs
            user_account_ids: List of user account IDs
            count: Total number of restrictions to add

        Returns:
            Number of restrictions added
        """
        if not page_ids or not user_account_ids:
            return 0

        self.logger.info(f"Adding {count} page restrictions (async, concurrency: {self.concurrency})...")

        operations = ["read", "update"]

        # Pre-compute all restriction specs up to count
        restriction_specs = []
        for page_id in page_ids:
            for user_id in user_account_ids:
                for operation in operations:
                    if len(restriction_specs) >= count:
                        break
                    restriction_specs.append((page_id, user_id, operation))
                if len(restriction_specs) >= count:
                    break
            if len(restriction_specs) >= count:
                break

        created = 0
        batch_size = self.concurrency * 2

        for batch_start in range(0, len(restriction_specs), batch_size):
            batch_end = min(batch_start + batch_size, len(restriction_specs))
            batch = restriction_specs[batch_start:batch_end]

            tasks = [
                self.add_page_restriction_async(page_id, user_id, operation) for page_id, user_id, operation in batch
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if result is True:
                    created += 1

            self.logger.info(f"Added {created}/{count} page restrictions")

        self.logger.info(f"Page restrictions complete: {created} added")
        return created

    async def create_page_version_async(
        self,
        page_id: str,
        title: str,
    ) -> bool:
        """Create a new version of a page asynchronously.

        Args:
            page_id: The page ID
            title: The page title

        Returns:
            True if successful
        """
        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would create new version of page {page_id}")
            return True

        # Get current page version
        success, page_data = await self._api_call_async("GET", f"pages/{page_id}", params={"body-format": "storage"})
        if not success or not page_data:
            self.logger.warning(f"Failed to get page {page_id} for versioning")
            return False

        current_version = page_data.get("version", {}).get("number", 1)

        new_body = f"<p>{self.generate_random_text(10, 30)}</p>"
        update_data = {
            "id": page_id,
            "status": "current",
            "title": title,
            "body": {
                "representation": "storage",
                "value": new_body,
            },
            "version": {
                "number": current_version + 1,
                "message": f"Auto-generated version {current_version + 1}",
            },
        }

        success, _ = await self._api_call_async("PUT", f"pages/{page_id}", data=update_data)
        if success:
            self.logger.debug(f"Created version {current_version + 1} of page {page_id}")
        return success

    async def create_page_versions_async(
        self,
        pages: list[dict[str, str]],
        count: int,
    ) -> int:
        """Create multiple page versions asynchronously.

        Versions for the same page must be sequential (each needs the current
        version number), so we group versions by page and process each page's
        versions sequentially. Different pages are processed in parallel.

        To avoid 409 conflicts from Confluence's eventual consistency, each
        page's current version is fetched once, then incremented locally for
        subsequent versions rather than re-reading from the API.

        Args:
            pages: List of page dicts with 'id' and 'title'
            count: Total number of versions to create

        Returns:
            Number of versions created
        """
        if not pages:
            return 0

        self.logger.info(f"Creating {count} page versions (async, concurrency: {self.concurrency})...")

        # Distribute versions round-robin across pages
        versions_per_page: dict[str, int] = {}
        for i in range(count):
            page = pages[i % len(pages)]
            pid = page["id"]
            versions_per_page[pid] = versions_per_page.get(pid, 0) + 1

        # Build a lookup for page titles
        page_titles = {p["id"]: p["title"] for p in pages}

        created = 0

        async def _create_versions_for_page(page_id: str, num_versions: int) -> int:
            """Create versions for a single page sequentially.

            Fetches the current version once, then tracks the version number
            locally. On 409 CONFLICT (Hibernate optimistic lock from a
            concurrent write like property updates), re-reads the version
            and retries.
            """
            if self.dry_run:
                return num_versions

            # Brief settling delay to let Confluence finish background
            # processing (search indexing, property HIBERNATEVERSION updates)
            # before we start reading version numbers
            await asyncio.sleep(1.0)

            # Get current version number once
            success, page_data = await self._api_call_async(
                "GET", f"pages/{page_id}", params={"body-format": "storage"}
            )
            if not success or not page_data:
                self.logger.warning(f"Failed to get page {page_id} for versioning")
                return 0

            current_version = page_data.get("version", {}).get("number", 1)
            title = page_titles[page_id]
            page_created = 0

            for _ in range(num_versions):
                max_conflict_retries = 5
                for retry in range(max_conflict_retries):
                    next_version = current_version + 1
                    new_body = f"<p>{self.generate_random_text(10, 30)}</p>"
                    update_data = {
                        "id": page_id,
                        "status": "current",
                        "title": title,
                        "body": {
                            "representation": "storage",
                            "value": new_body,
                        },
                        "version": {
                            "number": next_version,
                            "message": f"Auto-generated version {next_version}",
                        },
                    }

                    success, _ = await self._api_call_async(
                        "PUT", f"pages/{page_id}", data=update_data, suppress_errors=(409,)
                    )
                    if success:
                        current_version = next_version
                        page_created += 1
                        break

                    # On failure, wait with exponential backoff then re-read
                    if retry < max_conflict_retries - 1:
                        delay = min(2**retry, 8)  # 1s, 2s, 4s, 8s
                        await asyncio.sleep(delay)
                        ok, fresh = await self._api_call_async(
                            "GET", f"pages/{page_id}", params={"body-format": "storage"}
                        )
                        if ok and fresh:
                            current_version = fresh.get("version", {}).get("number", current_version)
                    else:
                        self.logger.warning(
                            f"Failed to create version of page {page_id} after {max_conflict_retries} retries"
                        )

            return page_created

        # Process pages in parallel batches, but versions within a page sequentially
        page_ids = list(versions_per_page.keys())
        for batch_start in range(0, len(page_ids), self.concurrency):
            batch = page_ids[batch_start : batch_start + self.concurrency]

            tasks = [_create_versions_for_page(pid, versions_per_page[pid]) for pid in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, int):
                    created += result

            self.logger.info(f"Created {created}/{count} page versions")

        self.logger.info(f"Page versions complete: {created} created")
        return created
