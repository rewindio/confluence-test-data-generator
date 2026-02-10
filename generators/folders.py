"""
Folder generation module.

Handles creation of Confluence folders and folder restrictions using the v2 REST API
for folders and the legacy v1 REST API for restrictions.
"""

import asyncio
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .base import ConfluenceAPIClient

if TYPE_CHECKING:
    from .checkpoint import CheckpointManager


class FolderGenerator(ConfluenceAPIClient):
    """Generates Confluence folders and folder restrictions."""

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
        self.created_folders: list[dict[str, str]] = []

    def set_run_id(self, run_id: str) -> None:
        """Set the run ID (should match the main generator's run ID)."""
        self.run_id = run_id

    # ========== FOLDER OPERATIONS ==========

    def create_folder(
        self,
        space_id: str,
        title: str,
    ) -> dict[str, str] | None:
        """Create a single folder.

        Args:
            space_id: Space ID to create the folder in
            title: Folder title

        Returns:
            Dict with 'id', 'title', 'spaceId' or None on failure
        """
        folder_data = {
            "spaceId": space_id,
            "title": title,
        }

        if self.dry_run:
            self.logger.info(f"DRY RUN: Would create folder '{title}' in space {space_id}")
            return {"id": f"dry-run-folder-{space_id}-{title}", "title": title, "spaceId": space_id}

        response = self._api_call("POST", "folders", data=folder_data)
        if response:
            result = response.json()
            folder = {
                "id": result.get("id"),
                "title": result.get("title"),
                "spaceId": result.get("spaceId", space_id),
            }
            self.logger.info(f"Created folder: {title}")
            return folder

        self.logger.warning(f"Failed to create folder '{title}'")
        return None

    def create_folders(
        self,
        spaces: list[dict[str, str]],
        count: int,
    ) -> list[dict[str, str]]:
        """Create multiple folders distributed across spaces.

        Args:
            spaces: List of space dicts with 'key' and 'id'
            count: Total number of folders to create

        Returns:
            List of folder dicts with 'id', 'title', 'spaceId'
        """
        if not spaces:
            return []

        self.logger.info(f"Creating {count} folders...")

        created_folders: list[dict[str, str]] = []

        for i in range(count):
            space = spaces[i % len(spaces)]
            space_id = space["id"]
            title = f"{self.prefix} Folder {i + 1}"

            folder = self.create_folder(space_id, title)
            if folder:
                created_folders.append(folder)

            if self.request_delay > 0:
                time.sleep(self.request_delay)

        self.created_folders = created_folders
        return created_folders

    # ========== FOLDER RESTRICTIONS ==========

    def add_folder_restriction(
        self,
        folder_id: str,
        user_account_id: str,
        operation: str,
        current_user_id: str | None = None,
    ) -> bool:
        """Add a restriction to a folder.

        Uses the legacy REST API (same endpoint as pages/blogposts).
        The current user must be included in the restriction user list to avoid
        self-lockout (Confluence returns 400 otherwise).

        Args:
            folder_id: The folder ID
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
            self.logger.debug(f"DRY RUN: Would add '{operation}' restriction to folder {folder_id}")
            return True

        base_url = f"{self.confluence_url}/rest/api"
        response = self._api_call("PUT", f"content/{folder_id}/restriction", data=restriction_data, base_url=base_url)
        if response:
            self.logger.debug(f"Added '{operation}' restriction to folder {folder_id}")
            return True
        return False

    def add_folder_restrictions(
        self,
        folder_ids: list[str],
        user_account_ids: list[str],
        count: int,
    ) -> int:
        """Add restrictions distributed across folders and users.

        Args:
            folder_ids: List of folder IDs
            user_account_ids: List of user account IDs
            count: Total number of restrictions to add

        Returns:
            Number of restrictions added
        """
        if not folder_ids or not user_account_ids:
            return 0

        self.logger.info(f"Adding {count} folder restrictions...")

        # Fetch current user to include in restrictions (prevents self-lockout)
        current_user_id = self.get_current_user_account_id()
        if current_user_id is None:
            self.logger.error(
                "Unable to determine current user account ID; skipping folder "
                "restrictions to avoid potential self-lockout."
            )
            return 0

        operations = ["read", "update"]

        created = 0
        restriction_index = 0

        for folder_id in folder_ids:
            for user_id in user_account_ids:
                for operation in operations:
                    if restriction_index >= count:
                        break

                    if self.add_folder_restriction(folder_id, user_id, operation, current_user_id):
                        created += 1

                    restriction_index += 1

                    if restriction_index % 100 == 0:
                        self.logger.info(f"Added {created}/{count} folder restrictions")
                        if self.request_delay > 0:
                            time.sleep(self.request_delay)

                if restriction_index >= count:
                    break
            if restriction_index >= count:
                break

        self.logger.info(f"Folder restrictions complete: {created} added")
        return created

    # ========== ASYNC METHODS ==========

    async def create_folder_async(
        self,
        space_id: str,
        title: str,
    ) -> dict[str, str] | None:
        """Create a single folder asynchronously.

        Args:
            space_id: Space ID to create the folder in
            title: Folder title

        Returns:
            Dict with 'id', 'title', 'spaceId' or None on failure
        """
        folder_data = {
            "spaceId": space_id,
            "title": title,
        }

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would create folder '{title}' in space {space_id}")
            return {"id": f"dry-run-folder-{space_id}-{title}", "title": title, "spaceId": space_id}

        success, result = await self._api_call_async("POST", "folders", data=folder_data)
        if success and result:
            folder = {
                "id": result.get("id"),
                "title": result.get("title"),
                "spaceId": result.get("spaceId", space_id),
            }
            self.logger.info(f"Created folder: {title}")
            return folder

        self.logger.warning(f"Failed to create folder '{title}'")
        return None

    async def create_folders_async(
        self,
        spaces: list[dict[str, str]],
        count: int,
    ) -> list[dict[str, str]]:
        """Create multiple folders asynchronously with batching.

        Args:
            spaces: List of space dicts with 'key' and 'id'
            count: Total number of folders to create

        Returns:
            List of folder dicts
        """
        if not spaces:
            return []

        self.logger.info(f"Creating {count} folders (async, concurrency: {self.concurrency})...")

        created_folders: list[dict[str, str]] = []
        batch_size = self.concurrency * 4

        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)

            tasks = []
            for i in range(batch_start, batch_end):
                space = spaces[i % len(spaces)]
                space_id = space["id"]
                title = f"{self.prefix} Folder {i + 1}"
                tasks.append(self.create_folder_async(space_id, title))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, dict):
                    created_folders.append(result)
                elif isinstance(result, Exception):
                    self._record_error()
                    exc_info = (type(result), result, result.__traceback__)
                    self.logger.error("Folder creation failed with exception", exc_info=exc_info)

            self.logger.info(f"Created {len(created_folders)}/{count} folders")

        self.created_folders = created_folders
        return created_folders

    async def add_folder_restriction_async(
        self,
        folder_id: str,
        user_account_id: str,
        operation: str,
        current_user_id: str | None = None,
    ) -> bool:
        """Add a restriction to a folder asynchronously.

        The current user must be included in the restriction user list to avoid
        self-lockout (Confluence returns 400 otherwise).

        Args:
            folder_id: The folder ID
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
            self.logger.debug(f"DRY RUN: Would add '{operation}' restriction to folder {folder_id}")
            return True

        base_url = f"{self.confluence_url}/rest/api"
        success, _ = await self._api_call_async(
            "PUT", f"content/{folder_id}/restriction", data=restriction_data, base_url=base_url
        )
        return success

    async def add_folder_restrictions_async(
        self,
        folder_ids: list[str],
        user_account_ids: list[str],
        count: int,
    ) -> int:
        """Add restrictions to folders asynchronously with batching.

        Args:
            folder_ids: List of folder IDs
            user_account_ids: List of user account IDs
            count: Total number of restrictions to add

        Returns:
            Number of restrictions added
        """
        if not folder_ids or not user_account_ids:
            return 0

        self.logger.info(f"Adding {count} folder restrictions (async, concurrency: {self.concurrency})...")

        # Fetch current user to include in restrictions (prevents self-lockout).
        # Run the synchronous call in a thread to avoid blocking the event loop.
        current_user_id = await asyncio.to_thread(self.get_current_user_account_id)
        if current_user_id is None:
            self.logger.error(
                "Unable to determine current user account ID; skipping async folder "
                "restrictions to avoid potential self-lockout."
            )
            return 0

        operations = ["read", "update"]

        # Pre-compute all restriction specs up to count
        restriction_specs = []
        for folder_id in folder_ids:
            for user_id in user_account_ids:
                for operation in operations:
                    if len(restriction_specs) >= count:
                        break
                    restriction_specs.append((folder_id, user_id, operation))
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
                self.add_folder_restriction_async(folder_id, user_id, operation, current_user_id)
                for folder_id, user_id, operation in batch
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result, (folder_id, user_id, operation) in zip(results, batch, strict=True):
                if result is True:
                    created += 1
                elif isinstance(result, Exception):
                    self._record_error()
                    self.logger.error(
                        "Folder restriction task failed for folder_id=%s user_id=%s operation=%s",
                        folder_id,
                        user_id,
                        operation,
                        exc_info=(type(result), result, result.__traceback__),
                    )

            self.logger.info(f"Added {created}/{count} folder restrictions")

        self.logger.info(f"Folder restrictions complete: {created} added")
        return created
