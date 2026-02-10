"""Tests for generators/folders.py - FolderGenerator."""

import json
from unittest.mock import MagicMock

import aiohttp
import pytest
import responses
from aioresponses import aioresponses

from generators.folders import FolderGenerator
from tests.conftest import CONFLUENCE_URL, TEST_EMAIL, TEST_PREFIX, TEST_TOKEN


class TestFolderGeneratorInitialization:
    """Tests for FolderGenerator initialization."""

    def test_basic_initialization(self):
        """Test basic FolderGenerator initialization."""
        generator = FolderGenerator(
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
        assert generator.created_folders == []

    def test_initialization_with_all_parameters(self):
        """Test initialization with all optional parameters."""
        mock_benchmark = MagicMock()
        mock_checkpoint = MagicMock()

        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
            concurrency=10,
            benchmark=mock_benchmark,
            request_delay=0.5,
            checkpoint=mock_checkpoint,
        )

        assert generator.dry_run is True
        assert generator.concurrency == 10
        assert generator.benchmark == mock_benchmark
        assert generator.request_delay == 0.5
        assert generator.checkpoint == mock_checkpoint

    def test_run_id_format(self):
        """Test that run_id is generated in correct format."""
        generator = FolderGenerator(
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
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        generator.set_run_id("custom-run-id-123")
        assert generator.run_id == "custom-run-id-123"


class TestFolderCreation:
    """Tests for folder creation operations."""

    @responses.activate
    def test_create_folder_success(self):
        """Test creating a folder successfully."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/folders",
            json={"id": "folder-123", "title": "TESTDATA Folder 1", "spaceId": "10001"},
            status=200,
        )

        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        folder = generator.create_folder("10001", "TESTDATA Folder 1")

        assert folder is not None
        assert folder["id"] == "folder-123"
        assert folder["title"] == "TESTDATA Folder 1"
        assert folder["spaceId"] == "10001"

    def test_create_folder_dry_run(self):
        """Test creating a folder in dry run mode."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        folder = generator.create_folder("10001", "TESTDATA Folder 1")

        assert folder is not None
        assert folder["title"] == "TESTDATA Folder 1"
        assert folder["spaceId"] == "10001"
        assert "dry-run-folder" in folder["id"]

    @responses.activate
    def test_create_folder_failure(self):
        """Test creating a folder when API returns error."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/folders",
            json={"message": "error"},
            status=500,
        )

        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        folder = generator.create_folder("10001", "TESTDATA Folder 1")
        assert folder is None

    @responses.activate
    def test_create_folder_payload_structure(self):
        """Test that the API payload has correct structure."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/folders",
            json={"id": "folder-123", "title": "TESTDATA Folder 1", "spaceId": "10001"},
            status=200,
        )

        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        generator.create_folder("10001", "TESTDATA Folder 1")

        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["spaceId"] == "10001"
        assert request_body["title"] == "TESTDATA Folder 1"

    @responses.activate
    def test_create_folder_uses_v2_api(self):
        """Test that folders use the v2 API URL."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/folders",
            json={"id": "folder-123", "title": "Folder 1", "spaceId": "10001"},
            status=200,
        )

        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        generator.create_folder("10001", "Folder 1")

        assert "/api/v2/folders" in responses.calls[0].request.url

    @responses.activate
    def test_create_folders_multiple(self):
        """Test creating multiple folders across spaces."""
        for i in range(5):
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/api/v2/folders",
                json={"id": f"folder-{i + 1}", "title": f"Folder {i + 1}", "spaceId": "10001"},
                status=200,
            )

        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        spaces = [{"key": "TEST1", "id": "10001"}]
        folders = generator.create_folders(spaces, 5)

        assert len(folders) == 5
        assert generator.created_folders == folders

    def test_create_folders_distributes_across_spaces(self):
        """Test that folders are evenly distributed across spaces."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        spaces = [{"key": "TEST1", "id": "10001"}, {"key": "TEST2", "id": "10002"}]
        folders = generator.create_folders(spaces, 6)

        space_counts = {}
        for f in folders:
            sid = f["spaceId"]
            space_counts[sid] = space_counts.get(sid, 0) + 1

        assert len(space_counts) == 2
        assert space_counts["10001"] == 3
        assert space_counts["10002"] == 3

    def test_create_folders_empty_spaces(self):
        """Test creating folders with empty space list."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        folders = generator.create_folders([], 5)
        assert folders == []

    def test_create_folders_zero_count(self):
        """Test creating zero folders."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        spaces = [{"key": "TEST1", "id": "10001"}]
        folders = generator.create_folders(spaces, 0)
        assert folders == []

    def test_create_folders_tracks_created(self):
        """Test that created_folders is updated after sync batch."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        spaces = [{"key": "TEST1", "id": "10001"}]
        folders = generator.create_folders(spaces, 3)

        assert len(generator.created_folders) == 3
        assert generator.created_folders == folders


class TestFolderRestrictions:
    """Tests for folder restriction operations."""

    @responses.activate
    def test_add_folder_restriction_success(self):
        """Test adding a folder restriction successfully."""
        responses.add(
            responses.PUT,
            f"{CONFLUENCE_URL}/rest/api/content/folder-123/restriction",
            json={},
            status=200,
        )

        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.add_folder_restriction("folder-123", "user-1", "read", "current-user")
        assert result is True

    @responses.activate
    def test_add_folder_restriction_includes_current_user(self):
        """Test that current user is included in restriction user list."""
        responses.add(
            responses.PUT,
            f"{CONFLUENCE_URL}/rest/api/content/folder-123/restriction",
            json={},
            status=200,
        )

        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        generator.add_folder_restriction("folder-123", "user-1", "read", "current-user")

        request_body = json.loads(responses.calls[0].request.body)
        users = request_body[0]["restrictions"]["user"]
        account_ids = [u["accountId"] for u in users]
        assert "user-1" in account_ids
        assert "current-user" in account_ids

    @responses.activate
    def test_add_folder_restriction_same_user_no_duplicate(self):
        """Test that current user is not duplicated when same as target user."""
        responses.add(
            responses.PUT,
            f"{CONFLUENCE_URL}/rest/api/content/folder-123/restriction",
            json={},
            status=200,
        )

        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        generator.add_folder_restriction("folder-123", "user-1", "read", "user-1")

        request_body = json.loads(responses.calls[0].request.body)
        users = request_body[0]["restrictions"]["user"]
        assert len(users) == 1
        assert users[0]["accountId"] == "user-1"

    def test_add_folder_restriction_dry_run(self):
        """Test adding a folder restriction in dry run mode."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = generator.add_folder_restriction("folder-123", "user-1", "read")
        assert result is True

    @responses.activate
    def test_add_folder_restriction_failure(self):
        """Test adding a folder restriction when API returns error."""
        responses.add(
            responses.PUT,
            f"{CONFLUENCE_URL}/rest/api/content/folder-123/restriction",
            json={"message": "error"},
            status=400,
        )

        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.add_folder_restriction("folder-123", "user-1", "read")
        assert result is False

    @responses.activate
    def test_add_folder_restriction_uses_v1_api(self):
        """Test that folder restrictions use the v1 REST API."""
        responses.add(
            responses.PUT,
            f"{CONFLUENCE_URL}/rest/api/content/folder-123/restriction",
            json={},
            status=200,
        )

        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        generator.add_folder_restriction("folder-123", "user-1", "read")

        assert "/rest/api/content/folder-123/restriction" in responses.calls[0].request.url

    @responses.activate
    def test_add_folder_restrictions_bulk(self):
        """Test adding multiple folder restrictions."""
        # Mock current user endpoint
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/rest/api/user/current",
            json={"accountId": "current-user-id"},
            status=200,
        )

        # Mock restriction endpoint (enough for the count)
        for _ in range(4):
            responses.add(
                responses.PUT,
                f"{CONFLUENCE_URL}/rest/api/content/folder-1/restriction",
                json={},
                status=200,
            )

        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        created = generator.add_folder_restrictions(["folder-1"], ["user-1", "user-2"], 4)
        assert created == 4

    @responses.activate
    def test_add_folder_restrictions_no_current_user(self):
        """Test that restrictions are skipped when current user cannot be determined."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/rest/api/user/current",
            json={"message": "error"},
            status=401,
        )

        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        created = generator.add_folder_restrictions(["folder-1"], ["user-1"], 2)
        assert created == 0

    def test_add_folder_restrictions_empty_folders(self):
        """Test adding restrictions with empty folder list."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        created = generator.add_folder_restrictions([], ["user-1"], 2)
        assert created == 0

    def test_add_folder_restrictions_empty_users(self):
        """Test adding restrictions with empty user list."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        created = generator.add_folder_restrictions(["folder-1"], [], 2)
        assert created == 0


class TestAsyncFolderOperations:
    """Tests for async folder operations."""

    @pytest.mark.asyncio
    async def test_create_folder_async_success(self):
        """Test creating a folder asynchronously."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/api/v2/folders",
                payload={"id": "folder-123", "title": "TESTDATA Folder 1", "spaceId": "10001"},
                status=200,
            )

            folder = await generator.create_folder_async("10001", "TESTDATA Folder 1")

            assert folder is not None
            assert folder["id"] == "folder-123"
            assert folder["title"] == "TESTDATA Folder 1"
            assert folder["spaceId"] == "10001"

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_folder_async_dry_run(self):
        """Test creating a folder asynchronously in dry run mode."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        folder = await generator.create_folder_async("10001", "TESTDATA Folder 1")

        assert folder is not None
        assert folder["title"] == "TESTDATA Folder 1"
        assert "dry-run-folder" in folder["id"]

    @pytest.mark.asyncio
    async def test_create_folder_async_failure(self):
        """Test creating a folder asynchronously when API returns error."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/api/v2/folders",
                payload={"message": "error"},
                status=400,
            )

            folder = await generator.create_folder_async("10001", "TESTDATA Folder 1")
            assert folder is None

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_folders_async_multiple(self):
        """Test creating multiple folders asynchronously."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for i in range(5):
                m.post(
                    f"{CONFLUENCE_URL}/api/v2/folders",
                    payload={"id": f"folder-{i + 1}", "title": f"Folder {i + 1}", "spaceId": "10001"},
                    status=200,
                )

            spaces = [{"key": "TEST1", "id": "10001"}]
            folders = await generator.create_folders_async(spaces, 5)

            assert len(folders) == 5
            assert generator.created_folders == folders

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_folders_async_distributes_across_spaces(self):
        """Test that async folders are distributed across spaces."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        spaces = [{"key": "TEST1", "id": "10001"}, {"key": "TEST2", "id": "10002"}]
        folders = await generator.create_folders_async(spaces, 6)

        space_counts = {}
        for f in folders:
            sid = f["spaceId"]
            space_counts[sid] = space_counts.get(sid, 0) + 1

        assert space_counts["10001"] == 3
        assert space_counts["10002"] == 3

    @pytest.mark.asyncio
    async def test_create_folders_async_exception_handling(self):
        """Test that exceptions in async batch are handled gracefully."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            # First request succeeds, second raises connection error
            m.post(
                f"{CONFLUENCE_URL}/api/v2/folders",
                payload={"id": "folder-1", "title": "Folder 1", "spaceId": "10001"},
                status=200,
            )
            m.post(
                f"{CONFLUENCE_URL}/api/v2/folders",
                exception=aiohttp.ClientError("Connection refused"),
            )

            spaces = [{"key": "TEST1", "id": "10001"}]
            folders = await generator.create_folders_async(spaces, 2)

            # At least the first one should succeed
            assert len(folders) >= 1

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_folders_async_empty_spaces(self):
        """Test creating folders asynchronously with empty space list."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        folders = await generator.create_folders_async([], 5)
        assert folders == []

    @pytest.mark.asyncio
    async def test_create_folders_async_tracks_created(self):
        """Test that created_folders is updated after async batch."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        spaces = [{"key": "TEST1", "id": "10001"}]
        folders = await generator.create_folders_async(spaces, 3)

        assert len(generator.created_folders) == 3
        assert generator.created_folders == folders

    @pytest.mark.asyncio
    async def test_add_folder_restriction_async_success(self):
        """Test adding a folder restriction asynchronously."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.put(
                f"{CONFLUENCE_URL}/rest/api/content/folder-123/restriction",
                payload={},
                status=200,
            )

            result = await generator.add_folder_restriction_async("folder-123", "user-1", "read", "current-user")
            assert result is True

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_add_folder_restriction_async_dry_run(self):
        """Test adding a folder restriction asynchronously in dry run mode."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = await generator.add_folder_restriction_async("folder-123", "user-1", "read")
        assert result is True

    @pytest.mark.asyncio
    async def test_add_folder_restrictions_async_bulk(self):
        """Test adding multiple folder restrictions asynchronously."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            # Mock restriction endpoints
            for _ in range(4):
                m.put(
                    f"{CONFLUENCE_URL}/rest/api/content/folder-1/restriction",
                    payload={},
                    status=200,
                )

            # Mock current user via sync call (runs in thread via asyncio.to_thread)
            with responses.RequestsMock() as rsps:
                rsps.add(
                    responses.GET,
                    f"{CONFLUENCE_URL}/rest/api/user/current",
                    json={"accountId": "current-user-id"},
                    status=200,
                )

                created = await generator.add_folder_restrictions_async(["folder-1"], ["user-1", "user-2"], 4)
                assert created == 4

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_add_folder_restrictions_async_no_current_user(self):
        """Test that async restrictions are skipped when current user cannot be determined."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        # Mock current user failure via sync call (runs in thread via asyncio.to_thread)
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"{CONFLUENCE_URL}/rest/api/user/current",
                json={"message": "error"},
                status=401,
            )

            created = await generator.add_folder_restrictions_async(["folder-1"], ["user-1"], 2)
            assert created == 0

    @pytest.mark.asyncio
    async def test_add_folder_restrictions_async_empty_folders(self):
        """Test adding async restrictions with empty folder list."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        created = await generator.add_folder_restrictions_async([], ["user-1"], 2)
        assert created == 0

    @pytest.mark.asyncio
    async def test_add_folder_restrictions_async_empty_users(self):
        """Test adding async restrictions with empty user list."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        created = await generator.add_folder_restrictions_async(["folder-1"], [], 2)
        assert created == 0

    @pytest.mark.asyncio
    async def test_add_folder_restrictions_async_exception_handling(self):
        """Test that exceptions in async restriction batch are logged."""
        generator = FolderGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            # First succeeds, second raises exception
            m.put(
                f"{CONFLUENCE_URL}/rest/api/content/folder-1/restriction",
                payload={},
                status=200,
            )
            m.put(
                f"{CONFLUENCE_URL}/rest/api/content/folder-1/restriction",
                exception=aiohttp.ClientError("Connection refused"),
            )

            with responses.RequestsMock() as rsps:
                rsps.add(
                    responses.GET,
                    f"{CONFLUENCE_URL}/rest/api/user/current",
                    json={"accountId": "current-user-id"},
                    status=200,
                )

                created = await generator.add_folder_restrictions_async(["folder-1"], ["user-1"], 2)
                # At least one should succeed
                assert created >= 1

        await generator._close_async_session()
