"""
Blog post generation module.

Handles creation of blog posts and related items: labels, properties, restrictions, versions.
"""

import asyncio
import random
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .base import ConfluenceAPIClient

if TYPE_CHECKING:
    from .checkpoint import CheckpointManager


class BlogPostGenerator(ConfluenceAPIClient):
    """Generates Confluence blog posts and related items."""

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
        settling_delay: float = 0.0,
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
            settling_delay,
        )
        self.prefix = prefix
        self.checkpoint = checkpoint
        self.run_id = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        # Track created items
        self.created_blogposts: list[dict[str, str]] = []

    def set_run_id(self, run_id: str) -> None:
        """Set the run ID (should match the main generator's run ID)."""
        self.run_id = run_id

    # ========== BLOGPOST OPERATIONS ==========

    def create_blogpost(
        self,
        space_id: str,
        title: str,
    ) -> dict[str, str] | None:
        """Create a single blog post.

        Args:
            space_id: Space ID to create the blog post in
            title: Blog post title

        Returns:
            Dict with 'id', 'title', 'spaceId' or None on failure
        """
        body_content = f"<p>{self.generate_random_text(10, 30)}</p>"

        blogpost_data: dict[str, Any] = {
            "spaceId": space_id,
            "title": title,
            "status": "current",
            "body": {
                "representation": "storage",
                "value": body_content,
            },
        }

        if self.dry_run:
            self.logger.info(f"DRY RUN: Would create blog post '{title}' in space {space_id}")
            return {"id": f"dry-run-{space_id}-{title}", "title": title, "spaceId": space_id}

        response = self._api_call("POST", "blogposts", data=blogpost_data)
        if response:
            result = response.json()
            blogpost = {
                "id": result.get("id"),
                "title": result.get("title"),
                "spaceId": result.get("spaceId"),
            }
            self.logger.info(f"Created blog post: {title}")
            return blogpost

        self.logger.warning(f"Failed to create blog post '{title}'")
        return None

    def create_blogposts(
        self,
        spaces: list[dict[str, str]],
        count: int,
    ) -> list[dict[str, str]]:
        """Create multiple blog posts distributed across spaces.

        Args:
            spaces: List of space dicts with 'key' and 'id'
            count: Total number of blog posts to create

        Returns:
            List of blog post dicts with 'id', 'title', 'spaceId'
        """
        if not spaces:
            return []

        self.logger.info(f"Creating {count} blog posts...")

        created_blogposts: list[dict[str, str]] = []

        for i in range(count):
            space = spaces[i % len(spaces)]
            space_id = space["id"]
            title = f"{self.prefix} Blog Post {i + 1}"

            blogpost = self.create_blogpost(space_id, title)
            if blogpost:
                created_blogposts.append(blogpost)

            if self.request_delay > 0:
                time.sleep(self.request_delay)

        self.created_blogposts = created_blogposts
        return created_blogposts

    # ========== BLOGPOST LABELS ==========

    def add_blogpost_label(self, blogpost_id: str, label: str) -> bool:
        """Add a label to a blog post.

        Note: Uses legacy REST API as v2 returns 405 for content labels.

        Args:
            blogpost_id: The blog post ID
            label: Label to add

        Returns:
            True if successful
        """
        clean_label = label.lower().replace(" ", "-")
        label_data = [{"prefix": "global", "name": clean_label}]

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would add label '{clean_label}' to blog post {blogpost_id}")
            return True

        base_url = f"{self.confluence_url}/rest/api"
        response = self._api_call("POST", f"content/{blogpost_id}/label", data=label_data, base_url=base_url)
        if response:
            self.logger.debug(f"Added label '{clean_label}' to blog post {blogpost_id}")
            return True
        return False

    def add_blogpost_labels(self, blogpost_ids: list[str], count: int) -> int:
        """Add labels distributed across blog posts.

        Args:
            blogpost_ids: List of blog post IDs
            count: Total number of labels to add

        Returns:
            Number of labels added
        """
        if not blogpost_ids:
            return 0

        self.logger.info(f"Adding {count} blog post labels...")

        label_types = [
            "announcement",
            "update",
            "news",
            "release",
            "recap",
            "milestone",
            "spotlight",
            "digest",
        ]

        created = 0
        for i in range(count):
            blogpost_id = blogpost_ids[i % len(blogpost_ids)]
            label_type = label_types[i % len(label_types)]
            label = f"{self.prefix.lower()}-{label_type}-{i + 1}"

            if self.add_blogpost_label(blogpost_id, label):
                created += 1

            if (i + 1) % 50 == 0:
                self.logger.info(f"Added {created}/{count} blog post labels")
                if self.request_delay > 0:
                    time.sleep(self.request_delay)

        self.logger.info(f"Blog post labels complete: {created} added")
        return created

    # ========== BLOGPOST PROPERTIES ==========

    def set_blogpost_property(self, blogpost_id: str, key: str, value: dict) -> bool:
        """Set a blog post property.

        Args:
            blogpost_id: The blog post ID
            key: Property key
            value: Property value (JSON-serializable dict)

        Returns:
            True if successful
        """
        property_data = {"key": key, "value": value}

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would set property '{key}' on blog post {blogpost_id}")
            return True

        response = self._api_call("POST", f"blogposts/{blogpost_id}/properties", data=property_data)
        if response:
            self.logger.debug(f"Set property '{key}' on blog post {blogpost_id}")
            return True
        return False

    def set_blogpost_properties(self, blogpost_ids: list[str], count: int) -> int:
        """Set properties distributed across blog posts.

        Args:
            blogpost_ids: List of blog post IDs
            count: Total number of properties to set

        Returns:
            Number of properties set
        """
        if not blogpost_ids:
            return 0

        self.logger.info(f"Setting {count} blog post properties...")

        created = 0
        for i in range(count):
            blogpost_id = blogpost_ids[i % len(blogpost_ids)]
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

            if self.set_blogpost_property(blogpost_id, property_key, property_value):
                created += 1

            if (i + 1) % 50 == 0:
                self.logger.info(f"Set {created}/{count} blog post properties")
                if self.request_delay > 0:
                    time.sleep(self.request_delay)

        self.logger.info(f"Blog post properties complete: {created} set")
        return created

    # ========== BLOGPOST RESTRICTIONS ==========

    def add_blogpost_restriction(
        self,
        blogpost_id: str,
        user_account_id: str,
        operation: str,
        current_user_id: str | None = None,
    ) -> bool:
        """Add a restriction to a blog post.

        Uses the legacy REST API as v2 doesn't support setting restrictions directly.
        The current user must be included in the restriction user list to avoid
        self-lockout (Confluence returns 400 otherwise).

        Args:
            blogpost_id: The blog post ID
            user_account_id: User account ID
            operation: 'read' or 'update'
            current_user_id: Current user's account ID (included to prevent self-lockout)

        Returns:
            True if successful
        """
        users = [{"type": "known", "accountId": user_account_id}]
        if current_user_id and current_user_id != user_account_id:
            users.append({"type": "known", "accountId": current_user_id})

        restriction_data = [
            {
                "operation": operation,
                "restrictions": {
                    "user": users,
                },
            }
        ]

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would add '{operation}' restriction to blog post {blogpost_id}")
            return True

        base_url = f"{self.confluence_url}/rest/api"
        response = self._api_call("PUT", f"content/{blogpost_id}/restriction", data=restriction_data, base_url=base_url)
        if response:
            self.logger.debug(f"Added '{operation}' restriction to blog post {blogpost_id}")
            return True
        return False

    def add_blogpost_restrictions(
        self,
        blogpost_ids: list[str],
        user_account_ids: list[str],
        count: int,
    ) -> int:
        """Add restrictions distributed across blog posts and users.

        Args:
            blogpost_ids: List of blog post IDs
            user_account_ids: List of user account IDs
            count: Total number of restrictions to add

        Returns:
            Number of restrictions added
        """
        if not blogpost_ids or not user_account_ids:
            return 0

        self.logger.info(f"Adding {count} blog post restrictions...")

        # Fetch current user to include in restrictions (prevents self-lockout)
        current_user_id = self.get_current_user_account_id()
        if current_user_id is None:
            self.logger.error(
                "Unable to determine current user account ID; skipping blogpost "
                "restrictions to avoid potential self-lockout."
            )
            return 0

        operations = ["read", "update"]

        created = 0
        restriction_index = 0

        for blogpost_id in blogpost_ids:
            for user_id in user_account_ids:
                for operation in operations:
                    if restriction_index >= count:
                        break

                    if self.add_blogpost_restriction(blogpost_id, user_id, operation, current_user_id):
                        created += 1

                    restriction_index += 1

                    if restriction_index % 100 == 0:
                        self.logger.info(f"Added {created}/{count} blog post restrictions")
                        if self.request_delay > 0:
                            time.sleep(self.request_delay)

                if restriction_index >= count:
                    break
            if restriction_index >= count:
                break

        self.logger.info(f"Blog post restrictions complete: {created} added")
        return created

    # ========== BLOGPOST VERSIONS ==========

    def create_blogpost_version(self, blogpost_id: str, title: str) -> bool:
        """Create a new version of a blog post by updating its content.

        Gets the current version number, then updates with incremented version.
        Retries on 409 conflict with version re-read.

        Args:
            blogpost_id: The blog post ID
            title: The blog post title (required for update)

        Returns:
            True if successful
        """
        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would create new version of blog post {blogpost_id}")
            return True

        # Get current blog post to find version number
        response = self._api_call("GET", f"blogposts/{blogpost_id}", params={"body-format": "storage"})
        if not response:
            self.logger.warning(f"Failed to get blog post {blogpost_id} for versioning")
            return False

        blogpost_data = response.json()
        current_version = blogpost_data.get("version", {}).get("number", 1)

        max_conflict_retries = 5
        for retry in range(max_conflict_retries):
            new_body = f"<p>{self.generate_random_text(10, 30)}</p>"
            update_data = {
                "id": blogpost_id,
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

            response = self._api_call("PUT", f"blogposts/{blogpost_id}", data=update_data)
            if response:
                self.logger.debug(f"Created version {current_version + 1} of blog post {blogpost_id}")
                return True

            # On failure, re-read version and retry
            if retry < max_conflict_retries - 1:
                time.sleep(min(2**retry, 8))
                fresh = self._api_call("GET", f"blogposts/{blogpost_id}", params={"body-format": "storage"})
                if fresh:
                    current_version = fresh.json().get("version", {}).get("number", current_version)

        self.logger.warning(f"Failed to create version of blog post {blogpost_id} after {max_conflict_retries} retries")
        return False

    def create_blogpost_versions(
        self,
        blogposts: list[dict[str, str]],
        count: int,
    ) -> int:
        """Create multiple blog post versions distributed across blog posts.

        Args:
            blogposts: List of blog post dicts with 'id' and 'title'
            count: Total number of versions to create

        Returns:
            Number of versions created
        """
        if not blogposts:
            return 0

        self.logger.info(f"Creating {count} blog post versions...")

        created = 0
        for i in range(count):
            blogpost = blogposts[i % len(blogposts)]

            if self.create_blogpost_version(blogpost["id"], blogpost["title"]):
                created += 1

            if (i + 1) % 50 == 0:
                self.logger.info(f"Created {created}/{count} blog post versions")
                if self.request_delay > 0:
                    time.sleep(self.request_delay)

        self.logger.info(f"Blog post versions complete: {created} created")
        return created

    # ========== ASYNC METHODS ==========

    async def create_blogpost_async(
        self,
        space_id: str,
        title: str,
    ) -> dict[str, str] | None:
        """Create a single blog post asynchronously.

        Args:
            space_id: Space ID to create the blog post in
            title: Blog post title

        Returns:
            Dict with 'id', 'title', 'spaceId' or None on failure
        """
        body_content = f"<p>{self.generate_random_text(10, 30)}</p>"

        blogpost_data: dict[str, Any] = {
            "spaceId": space_id,
            "title": title,
            "status": "current",
            "body": {
                "representation": "storage",
                "value": body_content,
            },
        }

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would create blog post '{title}' in space {space_id}")
            return {"id": f"dry-run-{space_id}-{title}", "title": title, "spaceId": space_id}

        success, result = await self._api_call_async("POST", "blogposts", data=blogpost_data)
        if success and result:
            blogpost = {
                "id": result.get("id"),
                "title": result.get("title"),
                "spaceId": result.get("spaceId"),
            }
            self.logger.info(f"Created blog post: {title}")
            return blogpost

        self.logger.warning(f"Failed to create blog post '{title}'")
        return None

    async def create_blogposts_async(
        self,
        spaces: list[dict[str, str]],
        count: int,
    ) -> list[dict[str, str]]:
        """Create multiple blog posts asynchronously with batching.

        Blog posts have no hierarchy dependencies, so they can be created
        in parallel batches for better throughput.

        Args:
            spaces: List of space dicts with 'key' and 'id'
            count: Total number of blog posts to create

        Returns:
            List of blog post dicts
        """
        if not spaces:
            return []

        self.logger.info(f"Creating {count} blog posts (async, concurrency: {self.concurrency})...")

        created_blogposts: list[dict[str, str]] = []
        batch_size = self.concurrency * 4

        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)

            tasks = []
            for i in range(batch_start, batch_end):
                space = spaces[i % len(spaces)]
                space_id = space["id"]
                title = f"{self.prefix} Blog Post {i + 1}"
                tasks.append(self.create_blogpost_async(space_id, title))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, dict):
                    created_blogposts.append(result)
                elif isinstance(result, Exception):
                    self._record_error()
                    self.logger.error(f"Blog post creation failed with exception: {result}")

            self.logger.info(f"Created {len(created_blogposts)}/{count} blog posts")

        self.created_blogposts = created_blogposts
        return created_blogposts

    async def add_blogpost_label_async(self, blogpost_id: str, label: str) -> bool:
        """Add a label to a blog post asynchronously.

        Note: Uses legacy REST API as v2 returns 405 for content labels.

        Args:
            blogpost_id: The blog post ID
            label: Label to add

        Returns:
            True if successful
        """
        clean_label = label.lower().replace(" ", "-")
        label_data = [{"prefix": "global", "name": clean_label}]

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would add label '{clean_label}' to blog post {blogpost_id}")
            return True

        base_url = f"{self.confluence_url}/rest/api"
        success, _ = await self._api_call_async(
            "POST", f"content/{blogpost_id}/label", data=label_data, base_url=base_url
        )
        return success

    async def add_blogpost_labels_async(self, blogpost_ids: list[str], count: int) -> int:
        """Add labels to blog posts asynchronously with batching.

        Args:
            blogpost_ids: List of blog post IDs
            count: Total number of labels to add

        Returns:
            Number of labels added
        """
        if not blogpost_ids:
            return 0

        self.logger.info(f"Adding {count} blog post labels (async, concurrency: {self.concurrency})...")

        label_types = [
            "announcement",
            "update",
            "news",
            "release",
            "recap",
            "milestone",
            "spotlight",
            "digest",
        ]

        created = 0
        batch_size = self.concurrency * 4

        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)

            tasks = []
            for i in range(batch_start, batch_end):
                blogpost_id = blogpost_ids[i % len(blogpost_ids)]
                label_type = label_types[i % len(label_types)]
                label = f"{self.prefix.lower()}-{label_type}-{i + 1}"
                tasks.append(self.add_blogpost_label_async(blogpost_id, label))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if result is True:
                    created += 1

            self.logger.info(f"Added {created}/{count} blog post labels")

        self.logger.info(f"Blog post labels complete: {created} added")
        return created

    async def set_blogpost_property_async(
        self,
        blogpost_id: str,
        key: str,
        value: dict,
    ) -> bool:
        """Set a blog post property asynchronously.

        Args:
            blogpost_id: The blog post ID
            key: Property key
            value: Property value

        Returns:
            True if successful
        """
        property_data = {"key": key, "value": value}

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would set property '{key}' on blog post {blogpost_id}")
            return True

        success, _ = await self._api_call_async("POST", f"blogposts/{blogpost_id}/properties", data=property_data)
        return success

    async def set_blogpost_properties_async(self, blogpost_ids: list[str], count: int) -> int:
        """Set properties on blog posts asynchronously with batching.

        Args:
            blogpost_ids: List of blog post IDs
            count: Total number of properties to set

        Returns:
            Number of properties set
        """
        if not blogpost_ids:
            return 0

        self.logger.info(f"Setting {count} blog post properties (async, concurrency: {self.concurrency})...")

        created = 0
        batch_size = self.concurrency * 4

        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)

            tasks = []
            for i in range(batch_start, batch_end):
                blogpost_id = blogpost_ids[i % len(blogpost_ids)]
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

                tasks.append(self.set_blogpost_property_async(blogpost_id, property_key, property_value))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if result is True:
                    created += 1

            self.logger.info(f"Set {created}/{count} blog post properties")

        self.logger.info(f"Blog post properties complete: {created} set")
        return created

    async def add_blogpost_restriction_async(
        self,
        blogpost_id: str,
        user_account_id: str,
        operation: str,
        current_user_id: str | None = None,
    ) -> bool:
        """Add a restriction to a blog post asynchronously.

        The current user must be included in the restriction user list to avoid
        self-lockout (Confluence returns 400 otherwise).

        Args:
            blogpost_id: The blog post ID
            user_account_id: User account ID
            operation: 'read' or 'update'
            current_user_id: Current user's account ID (included to prevent self-lockout)

        Returns:
            True if successful
        """
        users = [{"type": "known", "accountId": user_account_id}]
        if current_user_id and current_user_id != user_account_id:
            users.append({"type": "known", "accountId": current_user_id})

        restriction_data = [
            {
                "operation": operation,
                "restrictions": {
                    "user": users,
                },
            }
        ]

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would add '{operation}' restriction to blog post {blogpost_id}")
            return True

        base_url = f"{self.confluence_url}/rest/api"
        success, _ = await self._api_call_async(
            "PUT", f"content/{blogpost_id}/restriction", data=restriction_data, base_url=base_url
        )
        return success

    async def add_blogpost_restrictions_async(
        self,
        blogpost_ids: list[str],
        user_account_ids: list[str],
        count: int,
    ) -> int:
        """Add restrictions to blog posts asynchronously with batching.

        Args:
            blogpost_ids: List of blog post IDs
            user_account_ids: List of user account IDs
            count: Total number of restrictions to add

        Returns:
            Number of restrictions added
        """
        if not blogpost_ids or not user_account_ids:
            return 0

        self.logger.info(f"Adding {count} blog post restrictions (async, concurrency: {self.concurrency})...")

        # Fetch current user to include in restrictions (prevents self-lockout).
        # Run the synchronous call in a thread to avoid blocking the event loop.
        current_user_id = await asyncio.to_thread(self.get_current_user_account_id)
        if current_user_id is None:
            self.logger.error(
                "Unable to determine current user account ID; skipping async blogpost "
                "restrictions to avoid potential self-lockout."
            )
            return 0

        operations = ["read", "update"]

        # Pre-compute all restriction specs up to count
        restriction_specs = []
        for blogpost_id in blogpost_ids:
            for user_id in user_account_ids:
                for operation in operations:
                    if len(restriction_specs) >= count:
                        break
                    restriction_specs.append((blogpost_id, user_id, operation))
                if len(restriction_specs) >= count:
                    break
            if len(restriction_specs) >= count:
                break

        created = 0
        batch_size = self.concurrency * 4

        for batch_start in range(0, len(restriction_specs), batch_size):
            batch_end = min(batch_start + batch_size, len(restriction_specs))
            batch = restriction_specs[batch_start:batch_end]

            tasks = [
                self.add_blogpost_restriction_async(blogpost_id, user_id, operation, current_user_id)
                for blogpost_id, user_id, operation in batch
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result, (blogpost_id, user_id, operation) in zip(results, batch, strict=True):
                if result is True:
                    created += 1
                elif isinstance(result, Exception):
                    self._record_error()
                    self.logger.error(
                        "Blogpost restriction task failed for blogpost_id=%s user_id=%s operation=%s",
                        blogpost_id,
                        user_id,
                        operation,
                        exc_info=result,
                    )

            self.logger.info(f"Added {created}/{count} blog post restrictions")

        self.logger.info(f"Blog post restrictions complete: {created} added")
        return created

    async def create_blogpost_version_async(
        self,
        blogpost_id: str,
        title: str,
    ) -> bool:
        """Create a new version of a blog post asynchronously.

        Args:
            blogpost_id: The blog post ID
            title: The blog post title

        Returns:
            True if successful
        """
        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would create new version of blog post {blogpost_id}")
            return True

        # Get current blog post version
        success, blogpost_data = await self._api_call_async(
            "GET", f"blogposts/{blogpost_id}", params={"body-format": "storage"}
        )
        if not success or not blogpost_data:
            self.logger.warning(f"Failed to get blog post {blogpost_id} for versioning")
            return False

        current_version = blogpost_data.get("version", {}).get("number", 1)

        new_body = f"<p>{self.generate_random_text(10, 30)}</p>"
        update_data = {
            "id": blogpost_id,
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

        success, _ = await self._api_call_async("PUT", f"blogposts/{blogpost_id}", data=update_data)
        if success:
            self.logger.debug(f"Created version {current_version + 1} of blog post {blogpost_id}")
        return success

    async def create_blogpost_versions_async(
        self,
        blogposts: list[dict[str, str]],
        count: int,
    ) -> int:
        """Create multiple blog post versions asynchronously.

        Versions for the same blog post must be sequential (each needs the
        current version number), so we group versions by blog post and process
        each blog post's versions sequentially. Different blog posts are
        processed in parallel.

        To avoid 409 conflicts from Confluence's eventual consistency, each
        blog post's current version is fetched once, then incremented locally
        for subsequent versions rather than re-reading from the API.

        Args:
            blogposts: List of blog post dicts with 'id' and 'title'
            count: Total number of versions to create

        Returns:
            Number of versions created
        """
        if not blogposts:
            return 0

        self.logger.info(f"Creating {count} blog post versions (async, concurrency: {self.concurrency})...")

        # Distribute versions round-robin across blog posts
        versions_per_blogpost: dict[str, int] = {}
        for i in range(count):
            blogpost = blogposts[i % len(blogposts)]
            bid = blogpost["id"]
            versions_per_blogpost[bid] = versions_per_blogpost.get(bid, 0) + 1

        # Build a lookup for blog post titles
        blogpost_titles = {bp["id"]: bp["title"] for bp in blogposts}

        created = 0

        async def _create_versions_for_blogpost(blogpost_id: str, num_versions: int) -> int:
            """Create versions for a single blog post sequentially.

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
            if self.settling_delay > 0:
                await asyncio.sleep(self.settling_delay)

            # Get current version number once
            success, bp_data = await self._api_call_async(
                "GET", f"blogposts/{blogpost_id}", params={"body-format": "storage"}
            )
            if not success or not bp_data:
                self.logger.warning(f"Failed to get blog post {blogpost_id} for versioning")
                return 0

            current_version = bp_data.get("version", {}).get("number", 1)
            title = blogpost_titles[blogpost_id]
            bp_created = 0

            for _ in range(num_versions):
                max_conflict_retries = 5
                for retry in range(max_conflict_retries):
                    next_version = current_version + 1
                    new_body = f"<p>{self.generate_random_text(10, 30)}</p>"
                    update_data = {
                        "id": blogpost_id,
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
                        "PUT", f"blogposts/{blogpost_id}", data=update_data, suppress_errors=(409,)
                    )
                    if success:
                        current_version = next_version
                        bp_created += 1
                        break

                    # On failure, wait with exponential backoff then re-read
                    if retry < max_conflict_retries - 1:
                        delay = min(2**retry, 8)  # 1s, 2s, 4s, 8s
                        await asyncio.sleep(delay)
                        ok, fresh = await self._api_call_async(
                            "GET", f"blogposts/{blogpost_id}", params={"body-format": "storage"}
                        )
                        if ok and fresh:
                            current_version = fresh.get("version", {}).get("number", current_version)
                    else:
                        self.logger.warning(
                            f"Failed to create version of blog post {blogpost_id} after {max_conflict_retries} retries"
                        )

            return bp_created

        # Process blog posts in parallel batches, but versions within a blog post sequentially
        blogpost_ids = list(versions_per_blogpost.keys())
        for batch_start in range(0, len(blogpost_ids), self.concurrency):
            batch = blogpost_ids[batch_start : batch_start + self.concurrency]

            tasks = [_create_versions_for_blogpost(bid, versions_per_blogpost[bid]) for bid in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, int):
                    created += result

            self.logger.info(f"Created {created}/{count} blog post versions")

        self.logger.info(f"Blog post versions complete: {created} created")
        return created
