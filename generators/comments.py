"""
Comment generation module.

Handles creation of inline comments, footer comments, and their versions.
"""

import asyncio
import re
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .base import ConfluenceAPIClient

if TYPE_CHECKING:
    from .checkpoint import CheckpointManager


class CommentGenerator(ConfluenceAPIClient):
    """Generates Confluence comments (inline and footer) and their versions."""

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
        self.created_footer_comments: list[dict[str, str]] = []
        self.created_inline_comments: list[dict[str, str]] = []

        # Cache page body text to avoid repeated GETs for inline comments
        self._page_text_cache: dict[str, str] = {}
        # Per-page locks to prevent duplicate fetches in async mode
        self._page_text_locks: dict[str, asyncio.Lock] = {}

    def set_run_id(self, run_id: str) -> None:
        """Set the run ID (should match the main generator's run ID)."""
        self.run_id = run_id

    @staticmethod
    def _extract_text_selection(body_html: str) -> str | None:
        """Extract a word from page body HTML to use as inline comment anchor.

        The Confluence inline comment API requires textSelection to match actual
        text in the page. We strip HTML tags and pick the first word that's
        4+ characters (to avoid matching common short words across versions).

        Returns:
            A word from the page body, or None if no suitable text found
        """
        text = re.sub(r"<[^>]+>", " ", body_html)
        words = text.split()
        for word in words:
            clean = re.sub(r"[^a-zA-Z]", "", word)
            if len(clean) >= 4:
                return clean
        return None

    def _get_page_text_selection(self, page_id: str) -> str | None:
        """Get a text selection for a page, using cache when available."""
        if page_id in self._page_text_cache:
            return self._page_text_cache[page_id]

        response = self._api_call("GET", f"pages/{page_id}", params={"body-format": "storage"})
        if not response:
            return None

        body = response.json().get("body", {}).get("storage", {}).get("value", "")
        selection = self._extract_text_selection(body)
        if selection:
            self._page_text_cache[page_id] = selection
        return selection

    async def _get_page_text_selection_async(self, page_id: str) -> str | None:
        """Get a text selection for a page asynchronously, using cache when available.

        Uses per-page locks to prevent duplicate fetches when multiple tasks
        request the same page concurrently.
        """
        if page_id in self._page_text_cache:
            return self._page_text_cache[page_id]

        # Get or create a lock for this page to prevent duplicate fetches
        if page_id not in self._page_text_locks:
            self._page_text_locks[page_id] = asyncio.Lock()

        async with self._page_text_locks[page_id]:
            # Re-check cache after acquiring lock (another task may have populated it)
            if page_id in self._page_text_cache:
                return self._page_text_cache[page_id]

            success, data = await self._api_call_async("GET", f"pages/{page_id}", params={"body-format": "storage"})
            if not success or not data:
                return None

            body = data.get("body", {}).get("storage", {}).get("value", "")
            selection = self._extract_text_selection(body)
            if selection:
                self._page_text_cache[page_id] = selection
            return selection

    # ========== FOOTER COMMENT OPERATIONS ==========

    def create_footer_comment(
        self,
        page_id: str,
        index: int,
    ) -> dict[str, str] | None:
        """Create a single footer comment on a page.

        Args:
            page_id: Page ID to create the comment on
            index: Comment index (for logging)

        Returns:
            Dict with 'id' and 'pageId' or None on failure
        """
        body_content = f"<p>{self.generate_random_text(5, 15)}</p>"

        comment_data: dict[str, Any] = {
            "pageId": page_id,
            "body": {
                "representation": "storage",
                "value": body_content,
            },
        }

        if self.dry_run:
            self.logger.info(f"DRY RUN: Would create footer comment {index} on page {page_id}")
            return {"id": f"dry-run-footer-{page_id}-{index}", "pageId": page_id}

        response = self._api_call("POST", "footer-comments", data=comment_data)
        if response:
            result = response.json()
            comment = {
                "id": result.get("id"),
                "pageId": page_id,
            }
            self.logger.debug(f"Created footer comment {index} on page {page_id}")
            return comment

        self.logger.warning(f"Failed to create footer comment {index} on page {page_id}")
        return None

    def create_footer_comments(
        self,
        page_ids: list[str],
        count: int,
    ) -> list[dict[str, str]]:
        """Create multiple footer comments distributed across pages.

        Args:
            page_ids: List of page IDs
            count: Total number of footer comments to create

        Returns:
            List of comment dicts with 'id' and 'pageId'
        """
        if not page_ids:
            return []

        self.logger.info(f"Creating {count} footer comments...")

        created_comments: list[dict[str, str]] = []

        for i in range(count):
            page_id = page_ids[i % len(page_ids)]

            comment = self.create_footer_comment(page_id, i + 1)
            if comment:
                created_comments.append(comment)

            time.sleep(0.1)

        self.created_footer_comments = created_comments
        return created_comments

    # ========== INLINE COMMENT OPERATIONS ==========

    def create_inline_comment(
        self,
        page_id: str,
        index: int,
    ) -> dict[str, str] | None:
        """Create a single inline comment on a page.

        Fetches the page body to find real text for the inline anchor.
        The textSelection must match actual text in the page.

        Args:
            page_id: Page ID to create the comment on
            index: Comment index (for logging)

        Returns:
            Dict with 'id' and 'pageId' or None on failure
        """
        if self.dry_run:
            self.logger.info(f"DRY RUN: Would create inline comment {index} on page {page_id}")
            return {"id": f"dry-run-inline-{page_id}-{index}", "pageId": page_id}

        # Fetch page body to get real text for the inline anchor
        text_selection = self._get_page_text_selection(page_id)
        if not text_selection:
            self.logger.warning(f"Failed to get page text for inline comment on page {page_id}")
            return None

        body_content = f"<p>{self.generate_random_text(5, 15)}</p>"

        comment_data: dict[str, Any] = {
            "pageId": page_id,
            "body": {
                "representation": "storage",
                "value": body_content,
            },
            "inlineCommentProperties": {
                "textSelection": text_selection,
                "textSelectionMatchCount": 1,
                "textSelectionMatchIndex": 0,
            },
        }

        response = self._api_call("POST", "inline-comments", data=comment_data)
        if response:
            result = response.json()
            comment = {
                "id": result.get("id"),
                "pageId": page_id,
            }
            self.logger.debug(f"Created inline comment {index} on page {page_id}")
            return comment

        self.logger.warning(f"Failed to create inline comment {index} on page {page_id}")
        return None

    def create_inline_comments(
        self,
        page_ids: list[str],
        count: int,
    ) -> list[dict[str, str]]:
        """Create multiple inline comments distributed across pages.

        Args:
            page_ids: List of page IDs
            count: Total number of inline comments to create

        Returns:
            List of comment dicts with 'id' and 'pageId'
        """
        if not page_ids:
            return []

        self.logger.info(f"Creating {count} inline comments...")

        created_comments: list[dict[str, str]] = []

        for i in range(count):
            page_id = page_ids[i % len(page_ids)]

            comment = self.create_inline_comment(page_id, i + 1)
            if comment:
                created_comments.append(comment)

            time.sleep(0.1)

        self.created_inline_comments = created_comments
        return created_comments

    # ========== COMMENT VERSIONS ==========

    def create_comment_version(self, comment_id: str, comment_type: str) -> bool:
        """Create a new version of a comment by updating its content.

        Gets the current version number, then updates with incremented version.
        Retries on 409 conflict with version re-read.

        Args:
            comment_id: The comment ID
            comment_type: 'footer' or 'inline' (selects endpoint)

        Returns:
            True if successful
        """
        endpoint_prefix = f"{comment_type}-comments"

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would create new version of {comment_type} comment {comment_id}")
            return True

        # Get current comment to find version number
        response = self._api_call("GET", f"{endpoint_prefix}/{comment_id}", params={"body-format": "storage"})
        if not response:
            self.logger.warning(f"Failed to get {comment_type} comment {comment_id} for versioning")
            return False

        comment_data = response.json()
        current_version = comment_data.get("version", {}).get("number", 1)

        max_conflict_retries = 5
        for retry in range(max_conflict_retries):
            new_body = f"<p>{self.generate_random_text(5, 15)}</p>"
            update_data = {
                "version": {
                    "number": current_version + 1,
                    "message": f"Auto-generated version {current_version + 1}",
                },
                "body": {
                    "representation": "storage",
                    "value": new_body,
                },
            }

            response = self._api_call("PUT", f"{endpoint_prefix}/{comment_id}", data=update_data)
            if response:
                self.logger.debug(f"Created version {current_version + 1} of {comment_type} comment {comment_id}")
                return True

            # On failure, re-read version and retry
            if retry < max_conflict_retries - 1:
                time.sleep(min(2**retry, 8))
                fresh = self._api_call("GET", f"{endpoint_prefix}/{comment_id}", params={"body-format": "storage"})
                if fresh:
                    current_version = fresh.json().get("version", {}).get("number", current_version)

        self.logger.warning(
            f"Failed to create version of {comment_type} comment {comment_id} after {max_conflict_retries} retries"
        )
        return False

    def create_comment_versions(
        self,
        comments: list[dict[str, str]],
        count: int,
        comment_type: str,
    ) -> int:
        """Create multiple comment versions distributed across comments.

        Args:
            comments: List of comment dicts with 'id' and 'pageId'
            count: Total number of versions to create
            comment_type: 'footer' or 'inline'

        Returns:
            Number of versions created
        """
        if not comments:
            return 0

        self.logger.info(f"Creating {count} {comment_type} comment versions...")

        created = 0
        for i in range(count):
            comment = comments[i % len(comments)]

            if self.create_comment_version(comment["id"], comment_type):
                created += 1

            if (i + 1) % 50 == 0:
                self.logger.info(f"Created {created}/{count} {comment_type} comment versions")
                time.sleep(0.2)

        self.logger.info(f"{comment_type.capitalize()} comment versions complete: {created} created")
        return created

    # ========== ASYNC METHODS ==========

    async def create_footer_comment_async(
        self,
        page_id: str,
        index: int,
    ) -> dict[str, str] | None:
        """Create a single footer comment asynchronously.

        Args:
            page_id: Page ID to create the comment on
            index: Comment index (for logging)

        Returns:
            Dict with 'id' and 'pageId' or None on failure
        """
        body_content = f"<p>{self.generate_random_text(5, 15)}</p>"

        comment_data: dict[str, Any] = {
            "pageId": page_id,
            "body": {
                "representation": "storage",
                "value": body_content,
            },
        }

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would create footer comment {index} on page {page_id}")
            return {"id": f"dry-run-footer-{page_id}-{index}", "pageId": page_id}

        success, result = await self._api_call_async("POST", "footer-comments", data=comment_data)
        if success and result:
            comment = {
                "id": result.get("id"),
                "pageId": page_id,
            }
            self.logger.debug(f"Created footer comment {index} on page {page_id}")
            return comment

        self.logger.warning(f"Failed to create footer comment {index} on page {page_id}")
        return None

    async def create_footer_comments_async(
        self,
        page_ids: list[str],
        count: int,
    ) -> list[dict[str, str]]:
        """Create multiple footer comments asynchronously with batching.

        Args:
            page_ids: List of page IDs
            count: Total number of footer comments to create

        Returns:
            List of comment dicts
        """
        if not page_ids:
            return []

        self.logger.info(f"Creating {count} footer comments (async, concurrency: {self.concurrency})...")

        created_comments: list[dict[str, str]] = []
        batch_size = self.concurrency * 2

        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)

            tasks = []
            for i in range(batch_start, batch_end):
                page_id = page_ids[i % len(page_ids)]
                tasks.append(self.create_footer_comment_async(page_id, i + 1))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, dict):
                    created_comments.append(result)
                elif isinstance(result, Exception):
                    self._record_error()
                    self.logger.error(f"Footer comment creation failed with exception: {result}")

            self.logger.info(f"Created {len(created_comments)}/{count} footer comments")

        self.created_footer_comments = created_comments
        return created_comments

    async def create_inline_comment_async(
        self,
        page_id: str,
        index: int,
    ) -> dict[str, str] | None:
        """Create a single inline comment asynchronously.

        Fetches the page body to find real text for the inline anchor.
        The textSelection must match actual text in the page.

        Args:
            page_id: Page ID to create the comment on
            index: Comment index (for logging)

        Returns:
            Dict with 'id' and 'pageId' or None on failure
        """
        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would create inline comment {index} on page {page_id}")
            return {"id": f"dry-run-inline-{page_id}-{index}", "pageId": page_id}

        # Fetch page body to get real text for the inline anchor
        text_selection = await self._get_page_text_selection_async(page_id)
        if not text_selection:
            self.logger.warning(f"Failed to get page text for inline comment on page {page_id}")
            return None

        body_content = f"<p>{self.generate_random_text(5, 15)}</p>"

        comment_data: dict[str, Any] = {
            "pageId": page_id,
            "body": {
                "representation": "storage",
                "value": body_content,
            },
            "inlineCommentProperties": {
                "textSelection": text_selection,
                "textSelectionMatchCount": 1,
                "textSelectionMatchIndex": 0,
            },
        }

        success, result = await self._api_call_async("POST", "inline-comments", data=comment_data)
        if success and result:
            comment = {
                "id": result.get("id"),
                "pageId": page_id,
            }
            self.logger.debug(f"Created inline comment {index} on page {page_id}")
            return comment

        self.logger.warning(f"Failed to create inline comment {index} on page {page_id}")
        return None

    async def create_inline_comments_async(
        self,
        page_ids: list[str],
        count: int,
    ) -> list[dict[str, str]]:
        """Create multiple inline comments asynchronously with batching.

        Args:
            page_ids: List of page IDs
            count: Total number of inline comments to create

        Returns:
            List of comment dicts
        """
        if not page_ids:
            return []

        self.logger.info(f"Creating {count} inline comments (async, concurrency: {self.concurrency})...")

        created_comments: list[dict[str, str]] = []
        batch_size = self.concurrency * 2

        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)

            tasks = []
            for i in range(batch_start, batch_end):
                page_id = page_ids[i % len(page_ids)]
                tasks.append(self.create_inline_comment_async(page_id, i + 1))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, dict):
                    created_comments.append(result)
                elif isinstance(result, Exception):
                    self._record_error()
                    self.logger.error(f"Inline comment creation failed with exception: {result}")

            self.logger.info(f"Created {len(created_comments)}/{count} inline comments")

        self.created_inline_comments = created_comments
        return created_comments

    async def create_comment_version_async(
        self,
        comment_id: str,
        comment_type: str,
    ) -> bool:
        """Create a new version of a comment asynchronously.

        Args:
            comment_id: The comment ID
            comment_type: 'footer' or 'inline'

        Returns:
            True if successful
        """
        endpoint_prefix = f"{comment_type}-comments"

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would create new version of {comment_type} comment {comment_id}")
            return True

        max_conflict_retries = 5

        for retry in range(max_conflict_retries):
            # Get current comment version
            success, comment_data = await self._api_call_async(
                "GET", f"{endpoint_prefix}/{comment_id}", params={"body-format": "storage"}
            )
            if not success or not comment_data:
                self.logger.warning(f"Failed to get {comment_type} comment {comment_id} for versioning")
                return False

            current_version = comment_data.get("version", {}).get("number", 1)

            new_body = f"<p>{self.generate_random_text(5, 15)}</p>"
            update_data = {
                "version": {
                    "number": current_version + 1,
                    "message": f"Auto-generated version {current_version + 1}",
                },
                "body": {
                    "representation": "storage",
                    "value": new_body,
                },
            }

            success, _ = await self._api_call_async(
                "PUT",
                f"{endpoint_prefix}/{comment_id}",
                data=update_data,
                suppress_errors=(409,),
            )
            if success:
                self.logger.debug(f"Created version {current_version + 1} of {comment_type} comment {comment_id}")
                return True

            # On failure, wait with exponential backoff then retry
            if retry < max_conflict_retries - 1:
                delay = min(2**retry, 8)
                self.logger.debug(
                    f"Retrying version creation for {comment_type} comment {comment_id} "
                    f"(attempt {retry + 1}/{max_conflict_retries}, sleep {delay}s)"
                )
                await asyncio.sleep(delay)

        self.logger.warning(
            f"Failed to create version of {comment_type} comment {comment_id} after {max_conflict_retries} retries"
        )
        return False

    async def create_comment_versions_async(
        self,
        comments: list[dict[str, str]],
        count: int,
        comment_type: str,
    ) -> int:
        """Create multiple comment versions asynchronously.

        Versions for the same comment must be sequential (each needs the
        current version number), so we group versions by comment and process
        each comment's versions sequentially. Different comments are
        processed in parallel.

        Args:
            comments: List of comment dicts with 'id' and 'pageId'
            count: Total number of versions to create
            comment_type: 'footer' or 'inline'

        Returns:
            Number of versions created
        """
        if not comments:
            return 0

        self.logger.info(
            f"Creating {count} {comment_type} comment versions (async, concurrency: {self.concurrency})..."
        )

        endpoint_prefix = f"{comment_type}-comments"

        # Distribute versions round-robin across comments
        versions_per_comment: dict[str, int] = {}
        for i in range(count):
            comment = comments[i % len(comments)]
            cid = comment["id"]
            versions_per_comment[cid] = versions_per_comment.get(cid, 0) + 1

        created = 0

        async def _create_versions_for_comment(comment_id: str, num_versions: int) -> int:
            """Create versions for a single comment sequentially.

            Fetches the current version once, then tracks the version number
            locally. On 409 CONFLICT, re-reads the version and retries.
            """
            if self.dry_run:
                return num_versions

            # Brief settling delay
            await asyncio.sleep(1.0)

            # Get current version number once
            success, c_data = await self._api_call_async(
                "GET", f"{endpoint_prefix}/{comment_id}", params={"body-format": "storage"}
            )
            if not success or not c_data:
                self.logger.warning(f"Failed to get {comment_type} comment {comment_id} for versioning")
                return 0

            current_version = c_data.get("version", {}).get("number", 1)
            c_created = 0

            for _ in range(num_versions):
                max_conflict_retries = 5
                for retry in range(max_conflict_retries):
                    next_version = current_version + 1
                    new_body = f"<p>{self.generate_random_text(5, 15)}</p>"
                    update_data = {
                        "version": {
                            "number": next_version,
                            "message": f"Auto-generated version {next_version}",
                        },
                        "body": {
                            "representation": "storage",
                            "value": new_body,
                        },
                    }

                    success, _ = await self._api_call_async(
                        "PUT",
                        f"{endpoint_prefix}/{comment_id}",
                        data=update_data,
                        suppress_errors=(409,),
                    )
                    if success:
                        current_version = next_version
                        c_created += 1
                        break

                    # On failure, wait with exponential backoff then re-read
                    if retry < max_conflict_retries - 1:
                        delay = min(2**retry, 8)
                        await asyncio.sleep(delay)
                        ok, fresh = await self._api_call_async(
                            "GET",
                            f"{endpoint_prefix}/{comment_id}",
                            params={"body-format": "storage"},
                        )
                        if ok and fresh:
                            current_version = fresh.get("version", {}).get("number", current_version)
                    else:
                        self.logger.warning(
                            f"Failed to create version of {comment_type} comment {comment_id} "
                            f"after {max_conflict_retries} retries"
                        )

            return c_created

        # Process comments in parallel batches, but versions within a comment sequentially
        comment_ids = list(versions_per_comment.keys())
        for batch_start in range(0, len(comment_ids), self.concurrency):
            batch = comment_ids[batch_start : batch_start + self.concurrency]

            tasks = [_create_versions_for_comment(cid, versions_per_comment[cid]) for cid in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, int):
                    created += result
                elif isinstance(result, Exception):
                    self.logger.error(f"Error creating {comment_type} comment versions: {result}")
                    self._record_error()

            self.logger.info(f"Created {created}/{count} {comment_type} comment versions")

        self.logger.info(f"{comment_type.capitalize()} comment versions complete: {created} created")
        return created
