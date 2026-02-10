"""
Attachment generation module.

Handles creation of attachments and related items: labels, versions.
Uses multipart form data uploads (legacy v1 API) since v2 doesn't support
attachment uploads directly.
"""

import asyncio
import random
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

import aiohttp
import requests

from .base import ConfluenceAPIClient

if TYPE_CHECKING:
    from .checkpoint import CheckpointManager


class AttachmentGenerator(ConfluenceAPIClient):
    """Generates Confluence attachments with small synthetic files.

    Attachments are uploaded via the legacy REST API (v1) using multipart
    form data. A pool of pre-generated files is reused to minimize CPU
    overhead at scale.
    """

    # File pool configuration
    _FILE_POOL_SIZE = 20
    _FILE_TYPES = [
        ("txt", "text/plain"),
        ("json", "application/json"),
        ("csv", "text/csv"),
        ("log", "text/plain"),
    ]

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
        self.created_attachments: list[dict[str, str]] = []

        # Pre-generate file pool
        self._file_pool: list[tuple[str, bytes, str]] = []
        self._init_file_pool()

        # Async upload session (separate from JSON session, no Content-Type header)
        self._async_upload_session: aiohttp.ClientSession | None = None

    def set_run_id(self, run_id: str) -> None:
        """Set the run ID (should match the main generator's run ID)."""
        self.run_id = run_id

    def _init_file_pool(self) -> None:
        """Pre-generate a pool of small files for reuse during uploads."""
        for i in range(self._FILE_POOL_SIZE):
            ext, content_type = self._FILE_TYPES[i % len(self._FILE_TYPES)]
            size = random.randint(1024, 5120)  # 1-5 KB
            content = self._generate_file_content(ext, size)
            filename = f"{self.prefix.lower()}_file_{i + 1}.{ext}"
            self._file_pool.append((filename, content, content_type))

    def _generate_file_content(self, ext: str, size: int) -> bytes:
        """Generate synthetic file content based on file type.

        Args:
            ext: File extension (txt, json, csv, log)
            size: Target size in bytes

        Returns:
            Generated file content as bytes
        """
        if ext == "json":
            lines = ["{\n", '  "generator": "confluence-test-data-generator",\n']
            lines.append(f'  "runId": "{self.run_id}",\n')
            lines.append(f'  "timestamp": "{datetime.now().isoformat()}",\n')
            lines.append('  "data": [\n')
            current_size = sum(len(line.encode()) for line in lines)
            while current_size < size - 20:
                line = f'    "{self.generate_random_text(3, 8)}",\n'
                lines.append(line)
                current_size += len(line.encode())
            lines.append('    "end"\n  ]\n}')
            return "".join(lines).encode()

        if ext == "csv":
            lines = ["id,name,description,value\n"]
            current_size = len(lines[0].encode())
            row_num = 1
            while current_size < size:
                text = self.generate_random_text(3, 8)
                line = f"{row_num},{text},{self.generate_random_text(5, 12)},{random.randint(1, 1000)}\n"
                lines.append(line)
                current_size += len(line.encode())
                row_num += 1
            return "".join(lines).encode()

        # txt and log
        lines = []
        current_size = 0
        while current_size < size:
            line = f"{self.generate_random_text(5, 15)}\n"
            lines.append(line)
            current_size += len(line.encode())
        return "".join(lines).encode()

    def _get_random_file(self) -> tuple[str, bytes, str]:
        """Get a random file from the pool with a unique filename suffix.

        Returns:
            Tuple of (filename, content, content_type) with randomized filename
        """
        base_filename, content, content_type = random.choice(self._file_pool)
        # Add random suffix to avoid filename collisions on same page
        name, ext = base_filename.rsplit(".", 1)
        unique_filename = f"{name}_{random.randint(10000, 99999)}.{ext}"
        return unique_filename, content, content_type

    # ========== ATTACHMENT UPLOAD ==========

    def upload_attachment(
        self,
        page_id: str,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> dict[str, str] | None:
        """Upload an attachment to a page.

        Uses the legacy REST API with multipart form data.

        Args:
            page_id: Page or blogpost ID to attach to
            filename: Attachment filename
            content: File content as bytes
            content_type: MIME content type

        Returns:
            Dict with 'id', 'title' or None on failure
        """
        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would upload attachment '{filename}' to content {page_id}")
            return {"id": f"dry-run-att-{page_id}-{filename}", "title": filename}

        url = f"{self.confluence_url}/rest/api/content/{page_id}/child/attachment"

        for attempt in range(3):
            try:
                self._record_request()
                response = self.session.request(
                    method="POST",
                    url=url,
                    files={"file": (filename, content, content_type)},
                    auth=(self.email, self.api_token),
                    headers={
                        "X-Atlassian-Token": "no-check",
                    },
                    timeout=30,
                )

                self._handle_rate_limit(response)

                if response.status_code == 429:
                    continue

                if response.status_code >= 400:
                    error_text = response.text
                    if "already exists" in error_text.lower():
                        self.logger.debug(f"Attachment already exists: {filename} on {page_id}")
                        return None

                    if 500 <= response.status_code < 600 and attempt < 2:
                        # Server error - retry with backoff
                        self.logger.debug(
                            f"Upload got {response.status_code} for {filename}, retrying (attempt {attempt + 1}/3)"
                        )
                        time.sleep(2**attempt)
                        continue

                    # Non-retryable error or retries exhausted
                    self._record_error()
                    self.logger.error(f"Upload failed ({response.status_code}): {filename} -> {page_id}")
                    self.logger.error(f"Response: {self._truncate_error_response(error_text)}")
                    return None

                result = response.json()
                results = result.get("results", [result])
                if results:
                    att = results[0]
                    self.logger.debug(f"Uploaded attachment: {filename} -> {page_id}")
                    return {"id": att.get("id"), "title": att.get("title", filename)}

            except requests.exceptions.RequestException as e:
                self._record_error()
                self.logger.error(f"Upload failed (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(2**attempt)

        return None

    def create_attachments(
        self,
        page_ids: list[str],
        count: int,
    ) -> list[dict[str, str]]:
        """Create attachments distributed across pages.

        Args:
            page_ids: List of page/content IDs to attach to
            count: Total number of attachments to create

        Returns:
            List of attachment dicts with 'id', 'title', 'pageId'
        """
        if not page_ids:
            return []

        self.logger.info(f"Creating {count} attachments...")

        created_attachments: list[dict[str, str]] = []

        for i in range(count):
            page_id = page_ids[i % len(page_ids)]
            filename, content, content_type = self._get_random_file()

            att = self.upload_attachment(page_id, filename, content, content_type)
            if att:
                att["pageId"] = page_id
                created_attachments.append(att)

            if (i + 1) % 50 == 0:
                self.logger.info(f"Created {len(created_attachments)}/{count} attachments")
                if self.request_delay > 0:
                    time.sleep(self.request_delay)

        self.created_attachments = created_attachments
        return created_attachments

    # ========== ATTACHMENT LABELS ==========

    def add_attachment_label(self, attachment_id: str, label: str) -> bool:
        """Add a label to an attachment.

        Uses legacy REST API (same endpoint as page/blogpost labels).

        Args:
            attachment_id: The attachment ID
            label: Label to add

        Returns:
            True if successful
        """
        clean_label = label.lower().replace(" ", "-")
        label_data = [{"prefix": "global", "name": clean_label}]

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would add label '{clean_label}' to attachment {attachment_id}")
            return True

        base_url = f"{self.confluence_url}/rest/api"
        response = self._api_call("POST", f"content/{attachment_id}/label", data=label_data, base_url=base_url)
        if response:
            self.logger.debug(f"Added label '{clean_label}' to attachment {attachment_id}")
            return True
        return False

    def add_attachment_labels(self, attachment_ids: list[str], count: int) -> int:
        """Add labels distributed across attachments.

        Args:
            attachment_ids: List of attachment IDs
            count: Total number of labels to add

        Returns:
            Number of labels added
        """
        if not attachment_ids:
            return 0

        self.logger.info(f"Adding {count} attachment labels...")

        label_types = [
            "document",
            "image",
            "spreadsheet",
            "archive",
            "backup",
            "export",
            "report",
            "template",
        ]

        created = 0
        for i in range(count):
            attachment_id = attachment_ids[i % len(attachment_ids)]
            label_type = label_types[i % len(label_types)]
            label = f"{self.prefix.lower()}-{label_type}-{i + 1}"

            if self.add_attachment_label(attachment_id, label):
                created += 1

            if (i + 1) % 50 == 0:
                self.logger.info(f"Added {created}/{count} attachment labels")
                if self.request_delay > 0:
                    time.sleep(self.request_delay)

        self.logger.info(f"Attachment labels complete: {created} added")
        return created

    # ========== ATTACHMENT VERSIONS ==========

    def create_attachment_version(
        self,
        page_id: str,
        attachment_id: str,
        filename: str,
    ) -> bool:
        """Create a new version of an attachment by re-uploading.

        Confluence creates a new version when uploading a file with the same
        filename to the same content.

        Args:
            page_id: The page ID the attachment belongs to
            attachment_id: The attachment ID
            filename: The original filename (must match for versioning)

        Returns:
            True if successful
        """
        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would create new version of attachment {attachment_id}")
            return True

        # Generate new content for the version
        ext = filename.rsplit(".", 1)[-1] if "." in filename else "txt"
        new_content = self._generate_file_content(ext, random.randint(1024, 5120))

        url = f"{self.confluence_url}/rest/api/content/{page_id}/child/attachment/{attachment_id}/data"

        for attempt in range(3):
            try:
                self._record_request()
                response = self.session.request(
                    method="POST",
                    url=url,
                    files={"file": (filename, new_content, "application/octet-stream")},
                    auth=(self.email, self.api_token),
                    headers={
                        "X-Atlassian-Token": "no-check",
                    },
                    timeout=30,
                )

                self._handle_rate_limit(response)

                if response.status_code == 429:
                    continue

                if response.status_code < 300:
                    self.logger.debug(f"Created new version of attachment {attachment_id}")
                    return True

                if 500 <= response.status_code < 600 and attempt < 2:
                    # Server error - retry with backoff
                    self.logger.debug(
                        f"Attachment version got {response.status_code}, retrying "
                        f"(attempt {attempt + 1}/3): {attachment_id}"
                    )
                    time.sleep(2**attempt)
                    continue

                # Non-retryable error or retries exhausted
                self._record_error()
                error_text = response.text
                self.logger.error(f"Attachment version failed ({response.status_code}): {attachment_id}")
                self.logger.error(f"Response: {self._truncate_error_response(error_text)}")
                return False

            except requests.exceptions.RequestException as e:
                self._record_error()
                self.logger.error(f"Attachment version failed (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    time.sleep(2**attempt)

        return False

    def create_attachment_versions(
        self,
        attachments: list[dict[str, str]],
        count: int,
    ) -> int:
        """Create multiple attachment versions distributed across attachments.

        Args:
            attachments: List of attachment dicts with 'id', 'title', 'pageId'
            count: Total number of versions to create

        Returns:
            Number of versions created
        """
        if not attachments:
            return 0

        self.logger.info(f"Creating {count} attachment versions...")

        created = 0
        for i in range(count):
            att = attachments[i % len(attachments)]

            if self.create_attachment_version(att["pageId"], att["id"], att["title"]):
                created += 1

            if (i + 1) % 50 == 0:
                self.logger.info(f"Created {created}/{count} attachment versions")
                if self.request_delay > 0:
                    time.sleep(self.request_delay)

        self.logger.info(f"Attachment versions complete: {created} created")
        return created

    # ========== ASYNC METHODS ==========

    async def _get_async_upload_session(self) -> aiohttp.ClientSession:
        """Get or create async session for multipart uploads.

        This is separate from the JSON session because uploads need
        different headers (no Content-Type, plus X-Atlassian-Token).
        """
        if self._async_upload_session is None or self._async_upload_session.closed:
            auth = aiohttp.BasicAuth(self.email, self.api_token)
            timeout = aiohttp.ClientTimeout(total=60)

            connector = aiohttp.TCPConnector(
                limit=100, limit_per_host=50, ttl_dns_cache=300, enable_cleanup_closed=True
            )

            self._async_upload_session = aiohttp.ClientSession(
                auth=auth,
                connector=connector,
                timeout=timeout,
                headers={
                    "X-Atlassian-Token": "no-check",
                },
            )
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.concurrency)
        return self._async_upload_session

    async def _close_async_session(self):
        """Close both async sessions (JSON and upload)."""
        await super()._close_async_session()
        if self._async_upload_session and not self._async_upload_session.closed:
            await self._async_upload_session.close()

    async def _upload_async(
        self,
        url: str,
        filename: str,
        content: bytes,
        content_type: str,
        max_retries: int = 3,
    ) -> tuple[bool, dict | None]:
        """Upload a file via multipart form data asynchronously.

        Args:
            url: Full upload URL
            filename: Attachment filename
            content: File content bytes
            content_type: MIME type
            max_retries: Max retry attempts

        Returns:
            (success, response_json) tuple
        """
        if self.dry_run:
            return (True, None)

        session = await self._get_async_upload_session()

        async with self._semaphore:
            for attempt in range(max_retries):
                await self._wait_for_cooldown()
                await self._apply_request_delay()

                try:
                    self._record_request()

                    data = aiohttp.FormData()
                    data.add_field(
                        "file",
                        content,
                        filename=filename,
                        content_type=content_type,
                    )

                    async with session.post(url, data=data) as response:
                        delay = await self._handle_rate_limit_async(response.status, dict(response.headers))

                        if response.status == 429:
                            await asyncio.sleep(delay)
                            continue

                        if response.status >= 400:
                            error_text = await response.text()
                            if "already exists" in error_text.lower():
                                self.logger.debug(f"Attachment already exists: {filename}")
                            elif response.status < 500:
                                # Client error - not retryable
                                self._record_error()
                                self.logger.error(f"Upload failed ({response.status}): {filename}")
                                self.logger.error(f"Response: {self._truncate_error_response(error_text)}")
                            elif attempt < max_retries - 1:
                                # Server error with retries remaining - log at debug
                                self.logger.debug(
                                    f"Upload got {response.status} for {filename}, retrying "
                                    f"(attempt {attempt + 1}/{max_retries})"
                                )
                                await asyncio.sleep(2**attempt)
                                continue
                            else:
                                # Server error, all retries exhausted
                                self._record_error()
                                self.logger.error(
                                    f"Upload failed ({response.status}) after {max_retries} attempts: {filename}"
                                )
                                self.logger.error(f"Response: {self._truncate_error_response(error_text)}")
                            return (False, None)

                        result = await response.json()
                        return (True, result)

                except aiohttp.ClientError as e:
                    if attempt < max_retries - 1:
                        self.logger.debug(
                            f"Upload connection error for {filename}, retrying "
                            f"(attempt {attempt + 1}/{max_retries}): {e}"
                        )
                        await asyncio.sleep(2**attempt)
                    else:
                        self._record_error()
                        self.logger.error(f"Upload failed after {max_retries} attempts: {filename}: {e}")
                        return (False, None)

        return (False, None)

    async def upload_attachment_async(
        self,
        page_id: str,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> dict[str, str] | None:
        """Upload an attachment asynchronously.

        Args:
            page_id: Page or blogpost ID
            filename: Attachment filename
            content: File content bytes
            content_type: MIME type

        Returns:
            Dict with 'id', 'title' or None on failure
        """
        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would upload attachment '{filename}' to content {page_id}")
            return {"id": f"dry-run-att-{page_id}-{filename}", "title": filename}

        url = f"{self.confluence_url}/rest/api/content/{page_id}/child/attachment"

        success, result = await self._upload_async(url, filename, content, content_type)
        if success and result:
            results = result.get("results", [result])
            if results:
                att = results[0]
                self.logger.debug(f"Uploaded attachment: {filename} -> {page_id}")
                return {"id": att.get("id"), "title": att.get("title", filename)}

        # _upload_async already logs details (including "already exists" at DEBUG)
        self.logger.debug(f"Failed to upload attachment '{filename}' to {page_id}")
        return None

    async def create_attachments_async(
        self,
        page_ids: list[str],
        count: int,
    ) -> list[dict[str, str]]:
        """Create attachments asynchronously distributed across pages.

        Args:
            page_ids: List of page/content IDs
            count: Total number of attachments to create

        Returns:
            List of attachment dicts with 'id', 'title', 'pageId'
        """
        if not page_ids:
            return []

        self.logger.info(f"Creating {count} attachments (async, concurrency: {self.concurrency})...")

        created_attachments: list[dict[str, str]] = []
        batch_size = self.concurrency * 4

        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)

            tasks = []
            batch_page_ids = []
            for i in range(batch_start, batch_end):
                page_id = page_ids[i % len(page_ids)]
                filename, content, content_type = self._get_random_file()
                tasks.append(self.upload_attachment_async(page_id, filename, content, content_type))
                batch_page_ids.append(page_id)

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for j, result in enumerate(results):
                if isinstance(result, dict):
                    result["pageId"] = batch_page_ids[j]
                    created_attachments.append(result)
                elif isinstance(result, Exception):
                    self._record_error()
                    self.logger.error(f"Attachment upload failed with exception: {result}")

            self.logger.info(f"Created {len(created_attachments)}/{count} attachments")

        self.created_attachments = created_attachments
        return created_attachments

    async def add_attachment_label_async(self, attachment_id: str, label: str) -> bool:
        """Add a label to an attachment asynchronously.

        Args:
            attachment_id: The attachment ID
            label: Label to add

        Returns:
            True if successful
        """
        clean_label = label.lower().replace(" ", "-")
        label_data = [{"prefix": "global", "name": clean_label}]

        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would add label '{clean_label}' to attachment {attachment_id}")
            return True

        base_url = f"{self.confluence_url}/rest/api"
        success, _ = await self._api_call_async(
            "POST", f"content/{attachment_id}/label", data=label_data, base_url=base_url
        )
        return success

    async def add_attachment_labels_async(self, attachment_ids: list[str], count: int) -> int:
        """Add labels to attachments asynchronously with batching.

        Args:
            attachment_ids: List of attachment IDs
            count: Total number of labels to add

        Returns:
            Number of labels added
        """
        if not attachment_ids:
            return 0

        self.logger.info(f"Adding {count} attachment labels (async, concurrency: {self.concurrency})...")

        label_types = [
            "document",
            "image",
            "spreadsheet",
            "archive",
            "backup",
            "export",
            "report",
            "template",
        ]

        created = 0
        batch_size = self.concurrency * 4

        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)

            tasks = []
            for i in range(batch_start, batch_end):
                attachment_id = attachment_ids[i % len(attachment_ids)]
                label_type = label_types[i % len(label_types)]
                label = f"{self.prefix.lower()}-{label_type}-{i + 1}"
                tasks.append(self.add_attachment_label_async(attachment_id, label))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if result is True:
                    created += 1
                elif isinstance(result, Exception):
                    self._record_error()
                    self.logger.error(f"Attachment label failed with exception: {result}")

            self.logger.info(f"Added {created}/{count} attachment labels")

        self.logger.info(f"Attachment labels complete: {created} added")
        return created

    async def create_attachment_version_async(
        self,
        page_id: str,
        attachment_id: str,
        filename: str,
    ) -> bool:
        """Create a new version of an attachment asynchronously.

        Args:
            page_id: The page ID the attachment belongs to
            attachment_id: The attachment ID
            filename: The original filename

        Returns:
            True if successful
        """
        if self.dry_run:
            self.logger.debug(f"DRY RUN: Would create new version of attachment {attachment_id}")
            return True

        ext = filename.rsplit(".", 1)[-1] if "." in filename else "txt"
        new_content = self._generate_file_content(ext, random.randint(1024, 5120))

        url = f"{self.confluence_url}/rest/api/content/{page_id}/child/attachment/{attachment_id}/data"

        success, _ = await self._upload_async(url, filename, new_content, "application/octet-stream")
        if success:
            self.logger.debug(f"Created new version of attachment {attachment_id}")
        return success

    async def create_attachment_versions_async(
        self,
        attachments: list[dict[str, str]],
        count: int,
    ) -> int:
        """Create multiple attachment versions asynchronously.

        Args:
            attachments: List of attachment dicts with 'id', 'title', 'pageId'
            count: Total number of versions to create

        Returns:
            Number of versions created
        """
        if not attachments:
            return 0

        self.logger.info(f"Creating {count} attachment versions (async, concurrency: {self.concurrency})...")

        created = 0
        batch_size = self.concurrency * 4

        for batch_start in range(0, count, batch_size):
            batch_end = min(batch_start + batch_size, count)

            tasks = []
            for i in range(batch_start, batch_end):
                att = attachments[i % len(attachments)]
                tasks.append(self.create_attachment_version_async(att["pageId"], att["id"], att["title"]))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if result is True:
                    created += 1
                elif isinstance(result, Exception):
                    self._record_error()
                    self.logger.error(f"Attachment version failed with exception: {result}")

            self.logger.info(f"Created {created}/{count} attachment versions")

        self.logger.info(f"Attachment versions complete: {created} created")
        return created
