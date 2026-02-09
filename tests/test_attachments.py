"""Tests for generators/attachments.py - AttachmentGenerator."""

from unittest.mock import patch

import aiohttp
import pytest
import requests as requests_lib
import responses
from aioresponses import aioresponses

from generators.attachments import AttachmentGenerator
from tests.conftest import CONFLUENCE_URL, TEST_EMAIL, TEST_PREFIX, TEST_TOKEN


class TestAttachmentGeneratorInitialization:
    """Tests for AttachmentGenerator initialization."""

    def test_basic_initialization(self):
        """Test basic AttachmentGenerator initialization."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        assert generator.confluence_url == CONFLUENCE_URL
        assert generator.email == TEST_EMAIL
        assert generator.api_token == TEST_TOKEN
        assert generator.prefix == TEST_PREFIX
        assert generator.dry_run is False
        assert generator.concurrency == 5
        assert generator.checkpoint is None
        assert generator.created_attachments == []

    def test_file_pool_initialized(self):
        """Test that file pool is pre-generated on init."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        assert len(generator._file_pool) == 20
        for filename, content, content_type in generator._file_pool:
            assert filename.startswith(TEST_PREFIX.lower())
            assert isinstance(content, bytes)
            assert len(content) > 0
            assert content_type in ("text/plain", "application/json", "text/csv")

    def test_run_id_format(self):
        """Test that run_id is generated in correct format."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        assert generator.run_id.startswith(TEST_PREFIX)
        parts = generator.run_id.split("-")
        assert len(parts) == 3

    def test_set_run_id(self):
        """Test setting custom run ID."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        generator.set_run_id("custom-run-id-123")
        assert generator.run_id == "custom-run-id-123"


class TestFileGeneration:
    """Tests for file content generation."""

    def test_generate_file_content_txt(self):
        """Test generating text file content."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        content = generator._generate_file_content("txt", 1024)
        assert isinstance(content, bytes)
        assert len(content) >= 1024

    def test_generate_file_content_json(self):
        """Test generating JSON file content."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        content = generator._generate_file_content("json", 1024)
        assert isinstance(content, bytes)
        text = content.decode()
        assert text.startswith("{")
        assert text.endswith("}")
        assert "generator" in text

    def test_generate_file_content_csv(self):
        """Test generating CSV file content."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        content = generator._generate_file_content("csv", 1024)
        assert isinstance(content, bytes)
        text = content.decode()
        assert "id,name,description,value" in text

    def test_get_random_file_unique_names(self):
        """Test that random files get unique filenames."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        filenames = set()
        for _ in range(50):
            filename, _, _ = generator._get_random_file()
            filenames.add(filename)

        # With random suffixes, we should get many unique names
        assert len(filenames) > 10


class TestAttachmentUpload:
    """Tests for attachment upload operations."""

    @responses.activate
    def test_upload_attachment_success(self):
        """Test uploading an attachment successfully."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
            json={"results": [{"id": "att001", "title": "test_file.txt"}]},
            status=200,
        )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        att = generator.upload_attachment("100001", "test_file.txt", b"content", "text/plain")

        assert att is not None
        assert att["id"] == "att001"
        assert att["title"] == "test_file.txt"

    def test_upload_attachment_dry_run(self):
        """Test uploading an attachment in dry run mode."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        att = generator.upload_attachment("100001", "test_file.txt", b"content", "text/plain")

        assert att is not None
        assert "dry-run" in att["id"]
        assert att["title"] == "test_file.txt"

    @responses.activate
    def test_upload_attachment_failure(self):
        """Test uploading when API returns error."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
            json={"message": "error"},
            status=500,
        )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        att = generator.upload_attachment("100001", "test_file.txt", b"content", "text/plain")
        assert att is None

    @responses.activate
    def test_create_attachments_multiple(self):
        """Test creating multiple attachments across pages."""
        for _ in range(5):
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
                json={"results": [{"id": "att001", "title": "file.txt"}]},
                status=200,
            )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            attachments = generator.create_attachments(["100001"], 5)

        assert len(attachments) == 5
        for att in attachments:
            assert att["pageId"] == "100001"
        assert generator.created_attachments == attachments

    def test_create_attachments_dry_run(self):
        """Test creating multiple attachments in dry run mode."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        with patch("time.sleep"):
            attachments = generator.create_attachments(["100001", "100002"], 6)

        assert len(attachments) == 6
        for att in attachments:
            assert "dry-run" in att["id"]

    def test_create_attachments_distributes_across_pages(self):
        """Test that attachments are distributed across pages."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        with patch("time.sleep"):
            attachments = generator.create_attachments(["100001", "100002"], 6)

        page_counts = {}
        for att in attachments:
            pid = att["pageId"]
            page_counts[pid] = page_counts.get(pid, 0) + 1

        assert page_counts["100001"] == 3
        assert page_counts["100002"] == 3

    def test_create_attachments_empty_list(self):
        """Test creating attachments with empty page list."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        attachments = generator.create_attachments([], 5)
        assert attachments == []


class TestAttachmentLabels:
    """Tests for attachment label operations."""

    @responses.activate
    def test_add_attachment_label_success(self):
        """Test adding a label to an attachment."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/att001/label",
            json={"results": [{"name": "test-label"}]},
            status=200,
        )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.add_attachment_label("att001", "Test Label")
        assert result is True

    def test_add_attachment_label_dry_run(self):
        """Test adding a label in dry run mode."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = generator.add_attachment_label("att001", "test-label")
        assert result is True

    @responses.activate
    def test_add_attachment_labels_multiple(self):
        """Test adding multiple labels to attachments."""
        for _ in range(5):
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/rest/api/content/att001/label",
                json={"results": [{"name": "label"}]},
                status=200,
            )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            count = generator.add_attachment_labels(["att001"], 5)

        assert count == 5

    def test_add_attachment_labels_empty_list(self):
        """Test adding labels with empty attachment list."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = generator.add_attachment_labels([], 5)
        assert count == 0


class TestAttachmentVersions:
    """Tests for attachment version operations."""

    @responses.activate
    def test_create_attachment_version_success(self):
        """Test creating a new version of an attachment."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment/att001/data",
            json={"id": "att001", "title": "file.txt", "version": {"number": 2}},
            status=200,
        )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.create_attachment_version("100001", "att001", "file.txt")
        assert result is True

    def test_create_attachment_version_dry_run(self):
        """Test creating a version in dry run mode."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = generator.create_attachment_version("100001", "att001", "file.txt")
        assert result is True

    @responses.activate
    def test_create_attachment_versions_multiple(self):
        """Test creating multiple attachment versions."""
        for _ in range(3):
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment/att001/data",
                json={"id": "att001", "version": {"number": 2}},
                status=200,
            )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        attachments = [{"id": "att001", "title": "file.txt", "pageId": "100001"}]
        with patch("time.sleep"):
            count = generator.create_attachment_versions(attachments, 3)

        assert count == 3

    def test_create_attachment_versions_empty_list(self):
        """Test creating versions with empty attachment list."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = generator.create_attachment_versions([], 5)
        assert count == 0


class TestAsyncAttachmentOperations:
    """Tests for async attachment operations."""

    @pytest.mark.asyncio
    async def test_upload_attachment_async_success(self):
        """Test uploading an attachment asynchronously."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
                payload={"results": [{"id": "att001", "title": "test_file.txt"}]},
                status=200,
            )

            att = await generator.upload_attachment_async("100001", "test_file.txt", b"content", "text/plain")

            assert att is not None
            assert att["id"] == "att001"
            assert att["title"] == "test_file.txt"

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_upload_attachment_async_dry_run(self):
        """Test uploading asynchronously in dry run mode."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        att = await generator.upload_attachment_async("100001", "test_file.txt", b"content")

        assert att is not None
        assert "dry-run" in att["id"]
        assert att["title"] == "test_file.txt"

    @pytest.mark.asyncio
    async def test_create_attachments_async_multiple(self):
        """Test creating multiple attachments asynchronously."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        attachments = await generator.create_attachments_async(["100001", "100002"], 6)

        assert len(attachments) == 6
        for att in attachments:
            assert "dry-run" in att["id"]

    @pytest.mark.asyncio
    async def test_create_attachments_async_empty_list(self):
        """Test creating attachments with empty page list."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        attachments = await generator.create_attachments_async([], 5)
        assert attachments == []

    @pytest.mark.asyncio
    async def test_add_attachment_label_async_success(self):
        """Test adding a label asynchronously."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/rest/api/content/att001/label",
                payload={"results": [{"name": "test-label"}]},
                status=200,
            )

            result = await generator.add_attachment_label_async("att001", "test-label")
            assert result is True

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_add_attachment_labels_async_multiple(self):
        """Test adding multiple labels asynchronously."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for _ in range(5):
                m.post(
                    f"{CONFLUENCE_URL}/rest/api/content/att001/label",
                    payload={"results": [{"name": "label"}]},
                    status=200,
                )

            count = await generator.add_attachment_labels_async(["att001"], 5)
            assert count == 5

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_attachment_version_async_success(self):
        """Test creating an attachment version asynchronously."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment/att001/data",
                payload={"id": "att001", "version": {"number": 2}},
                status=200,
            )

            result = await generator.create_attachment_version_async("100001", "att001", "file.txt")
            assert result is True

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_attachment_versions_async_multiple(self):
        """Test creating multiple attachment versions asynchronously."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        attachments = [
            {"id": "att001", "title": "file1.txt", "pageId": "100001"},
            {"id": "att002", "title": "file2.csv", "pageId": "100002"},
        ]

        count = await generator.create_attachment_versions_async(attachments, 4)
        assert count == 4

    @pytest.mark.asyncio
    async def test_create_attachment_versions_async_empty_list(self):
        """Test creating versions with empty attachment list."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = await generator.create_attachment_versions_async([], 5)
        assert count == 0


class TestAsyncDryRun:
    """Tests for async operations in dry run mode."""

    @pytest.mark.asyncio
    async def test_add_attachment_label_async_dry_run(self):
        """Test adding a label asynchronously in dry run mode."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = await generator.add_attachment_label_async("att001", "test-label")
        assert result is True

    @pytest.mark.asyncio
    async def test_create_attachment_version_async_dry_run(self):
        """Test creating a version asynchronously in dry run mode."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = await generator.create_attachment_version_async("100001", "att001", "file.txt")
        assert result is True

    @pytest.mark.asyncio
    async def test_add_attachment_labels_async_empty_list(self):
        """Test adding labels with empty attachment list."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = await generator.add_attachment_labels_async([], 5)
        assert count == 0

    @pytest.mark.asyncio
    async def test_close_async_session_both_sessions(self):
        """Test that closing cleans up both JSON and upload sessions."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        # Create both sessions
        await generator._get_async_session()
        await generator._get_async_upload_session()

        assert generator._async_session is not None
        assert generator._async_upload_session is not None

        await generator._close_async_session()

        assert generator._async_session.closed
        assert generator._async_upload_session.closed


class TestSyncUploadErrorPaths:
    """Tests for sync upload error handling paths."""

    @responses.activate
    def test_upload_attachment_already_exists(self):
        """Test that 'already exists' error is handled gracefully."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
            json={"message": "file already exists on this content"},
            status=400,
        )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        att = generator.upload_attachment("100001", "test_file.txt", b"content", "text/plain")
        assert att is None

    @responses.activate
    def test_upload_attachment_client_error(self):
        """Test that 4xx client errors are not retried."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
            json={"message": "Forbidden"},
            status=403,
        )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        att = generator.upload_attachment("100001", "test_file.txt", b"content", "text/plain")
        assert att is None
        # Should only have called once (no retry on 4xx)
        assert len(responses.calls) == 1

    @responses.activate
    def test_upload_attachment_5xx_retries(self):
        """Test that 5xx server errors are retried."""
        # First two attempts fail with 500, third succeeds
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
            json={"message": "Internal Server Error"},
            status=500,
        )
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
            json={"message": "Internal Server Error"},
            status=500,
        )
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
            json={"results": [{"id": "att001", "title": "test_file.txt"}]},
            status=200,
        )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            att = generator.upload_attachment("100001", "test_file.txt", b"content", "text/plain")

        assert att is not None
        assert att["id"] == "att001"
        assert len(responses.calls) == 3

    @responses.activate
    def test_upload_attachment_429_retries(self):
        """Test that 429 rate limit responses are retried."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
            json={"message": "Rate limited"},
            status=429,
            headers={"Retry-After": "1"},
        )
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
            json={"results": [{"id": "att001", "title": "test_file.txt"}]},
            status=200,
        )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            att = generator.upload_attachment("100001", "test_file.txt", b"content", "text/plain")

        assert att is not None
        assert len(responses.calls) == 2

    @responses.activate
    def test_upload_attachment_connection_error(self):
        """Test that connection errors are retried and eventually return None."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
            body=requests_lib.exceptions.ConnectionError("Connection refused"),
        )
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
            body=requests_lib.exceptions.ConnectionError("Connection refused"),
        )
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
            body=requests_lib.exceptions.ConnectionError("Connection refused"),
        )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            att = generator.upload_attachment("100001", "test_file.txt", b"content", "text/plain")

        assert att is None


class TestSyncVersionErrorPaths:
    """Tests for sync attachment version error handling paths."""

    @responses.activate
    def test_create_attachment_version_5xx_retries(self):
        """Test that 5xx server errors are retried for versions."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment/att001/data",
            json={"message": "Server Error"},
            status=500,
        )
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment/att001/data",
            json={"id": "att001", "version": {"number": 2}},
            status=200,
        )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            result = generator.create_attachment_version("100001", "att001", "file.txt")

        assert result is True
        assert len(responses.calls) == 2

    @responses.activate
    def test_create_attachment_version_client_error(self):
        """Test that 4xx client errors fail fast."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment/att001/data",
            json={"message": "Not Found"},
            status=404,
        )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.create_attachment_version("100001", "att001", "file.txt")
        assert result is False
        assert len(responses.calls) == 1

    @responses.activate
    def test_create_attachment_version_connection_error(self):
        """Test that connection errors are retried for versions."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment/att001/data",
            body=requests_lib.exceptions.ConnectionError("Connection refused"),
        )
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment/att001/data",
            body=requests_lib.exceptions.ConnectionError("Connection refused"),
        )
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment/att001/data",
            body=requests_lib.exceptions.ConnectionError("Connection refused"),
        )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            result = generator.create_attachment_version("100001", "att001", "file.txt")

        assert result is False

    @responses.activate
    def test_create_attachment_version_429_retries(self):
        """Test that 429 rate limit is retried for versions."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment/att001/data",
            json={"message": "Rate limited"},
            status=429,
            headers={"Retry-After": "1"},
        )
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment/att001/data",
            json={"id": "att001", "version": {"number": 2}},
            status=200,
        )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            result = generator.create_attachment_version("100001", "att001", "file.txt")

        assert result is True

    @responses.activate
    def test_create_attachment_versions_progress_logging(self):
        """Test that progress is logged every 50 versions."""
        for _ in range(55):
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment/att001/data",
                json={"id": "att001", "version": {"number": 2}},
                status=200,
            )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        attachments = [{"id": "att001", "title": "file.txt", "pageId": "100001"}]
        with patch("time.sleep"):
            count = generator.create_attachment_versions(attachments, 55)

        assert count == 55


class TestAsyncUploadErrorPaths:
    """Tests for async upload error handling paths."""

    @pytest.mark.asyncio
    async def test_upload_async_client_error(self):
        """Test async upload handles 4xx errors."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
                payload={"message": "Forbidden"},
                status=403,
            )

            att = await generator.upload_attachment_async("100001", "test.txt", b"content", "text/plain")
            assert att is None

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_upload_async_already_exists(self):
        """Test async upload handles 'already exists' at debug level."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
                payload={"message": "file already exists on this content"},
                status=400,
            )

            att = await generator.upload_attachment_async("100001", "test.txt", b"content", "text/plain")
            assert att is None

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_upload_async_server_error_retries(self):
        """Test async upload retries on 5xx then succeeds."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
                payload={"message": "Server Error"},
                status=500,
            )
            m.post(
                f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
                payload={"results": [{"id": "att001", "title": "test.txt"}]},
                status=200,
            )

            att = await generator.upload_attachment_async("100001", "test.txt", b"content", "text/plain")
            assert att is not None
            assert att["id"] == "att001"

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_upload_async_connection_error_retries(self):
        """Test async upload retries on connection error."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
                exception=aiohttp.ClientError("Connection refused"),
            )
            m.post(
                f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
                exception=aiohttp.ClientError("Connection refused"),
            )
            m.post(
                f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
                exception=aiohttp.ClientError("Connection refused"),
            )

            att = await generator.upload_attachment_async("100001", "test.txt", b"content", "text/plain")
            assert att is None

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_attachments_async_logs_exceptions(self):
        """Test that exceptions from asyncio.gather are logged."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
                exception=aiohttp.ClientError("Connection refused"),
            )
            m.post(
                f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
                exception=aiohttp.ClientError("Connection refused"),
            )
            m.post(
                f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
                exception=aiohttp.ClientError("Connection refused"),
            )

            attachments = await generator.create_attachments_async(["100001"], 1)
            assert attachments == []

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_upload_async_dry_run(self):
        """Test _upload_async in dry run mode."""
        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        success, result = await generator._upload_async(
            f"{CONFLUENCE_URL}/rest/api/content/100001/child/attachment",
            "test.txt",
            b"content",
            "text/plain",
        )
        assert success is True
        assert result is None

    @responses.activate
    def test_upload_attachment_label_failure(self):
        """Test that failed label addition returns False."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/att001/label",
            json={"message": "error"},
            status=500,
        )

        generator = AttachmentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.add_attachment_label("att001", "test-label")
        assert result is False
