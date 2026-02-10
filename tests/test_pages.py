"""Tests for generators/pages.py - PageGenerator."""

from unittest.mock import MagicMock, patch

import pytest
import responses
from aioresponses import aioresponses

from generators.pages import PageGenerator
from tests.conftest import CONFLUENCE_URL, TEST_EMAIL, TEST_PREFIX, TEST_TOKEN


class TestPageGeneratorInitialization:
    """Tests for PageGenerator initialization."""

    def test_basic_initialization(self):
        """Test basic PageGenerator initialization."""
        generator = PageGenerator(
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
        assert generator.created_pages == []

    def test_initialization_with_all_parameters(self):
        """Test initialization with all optional parameters."""
        mock_benchmark = MagicMock()
        mock_checkpoint = MagicMock()

        generator = PageGenerator(
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
        generator = PageGenerator(
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
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        generator.set_run_id("custom-run-id-123")
        assert generator.run_id == "custom-run-id-123"


class TestPageCreation:
    """Tests for page creation operations."""

    @responses.activate
    def test_create_page_success(self):
        """Test creating a page successfully."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/pages",
            json={"id": "100001", "title": "Test Page 1", "spaceId": "10001"},
            status=200,
        )

        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        page = generator.create_page("10001", "Test Page 1")

        assert page is not None
        assert page["id"] == "100001"
        assert page["title"] == "Test Page 1"
        assert page["spaceId"] == "10001"

    @responses.activate
    def test_create_page_with_parent(self):
        """Test creating a page with a parent ID."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/pages",
            json={"id": "100002", "title": "Child Page", "spaceId": "10001", "parentId": "100001"},
            status=200,
        )

        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        page = generator.create_page("10001", "Child Page", parent_id="100001")

        assert page is not None
        assert page["id"] == "100002"

        # Verify the request body included parentId
        request_body = responses.calls[0].request.body
        assert b"parentId" in request_body

    def test_create_page_dry_run(self):
        """Test creating a page in dry run mode."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        page = generator.create_page("10001", "Test Page 1")

        assert page is not None
        assert page["title"] == "Test Page 1"
        assert "dry-run" in page["id"]
        assert page["spaceId"] == "10001"

    def test_create_page_dry_run_with_parent(self):
        """Test creating a page in dry run mode with parent."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        page = generator.create_page("10001", "Child Page", parent_id="100001")

        assert page is not None
        assert page["parentId"] == "100001"

    @responses.activate
    def test_create_pages_multiple(self):
        """Test creating multiple pages across spaces."""
        for i in range(5):
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/api/v2/pages",
                json={"id": f"10000{i + 1}", "title": f"Page {i + 1}", "spaceId": "10001"},
                status=200,
            )

        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        spaces = [{"key": "TEST1", "id": "10001"}]
        with patch("time.sleep"):
            pages = generator.create_pages(spaces, 5)

        assert len(pages) == 5
        assert generator.created_pages == pages

    def test_create_pages_dry_run(self):
        """Test creating multiple pages in dry run mode."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        spaces = [{"key": "TEST1", "id": "10001"}, {"key": "TEST2", "id": "10002"}]
        with patch("time.sleep"):
            pages = generator.create_pages(spaces, 6)

        assert len(pages) == 6
        for page in pages:
            assert "dry-run" in page["id"]

    def test_create_pages_distributes_across_spaces(self):
        """Test that pages are evenly distributed across spaces."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        spaces = [{"key": "TEST1", "id": "10001"}, {"key": "TEST2", "id": "10002"}]
        with patch("time.sleep"):
            pages = generator.create_pages(spaces, 6)

        space_counts = {}
        for page in pages:
            sid = page["spaceId"]
            space_counts[sid] = space_counts.get(sid, 0) + 1

        # Pages should be distributed across spaces
        assert len(space_counts) == 2
        assert space_counts["10001"] == 3
        assert space_counts["10002"] == 3

    def test_create_pages_hierarchy(self):
        """Test that pages are created with parent-child hierarchy."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        spaces = [{"key": "TEST1", "id": "10001"}]
        with patch("time.sleep"):
            pages = generator.create_pages(spaces, 20)

        # Some pages should have parentId (child pages)
        root_pages = [p for p in pages if p.get("parentId") is None]
        child_pages = [p for p in pages if p.get("parentId") is not None]

        # At least some should be root and some children
        assert len(root_pages) > 0
        assert len(child_pages) > 0

    def test_create_pages_empty_spaces(self):
        """Test creating pages with empty space list."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        pages = generator.create_pages([], 5)
        assert pages == []


class TestPageLabels:
    """Tests for page label operations."""

    @responses.activate
    def test_add_page_label_success(self):
        """Test adding a label to a page."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/label",
            json={"results": [{"name": "test-label"}]},
            status=200,
        )

        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.add_page_label("100001", "Test Label")
        assert result is True

    @responses.activate
    def test_add_page_label_normalizes(self):
        """Test that labels are normalized to lowercase with hyphens."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/100001/label",
            json={"results": [{"name": "my-test-label"}]},
            status=200,
        )

        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.add_page_label("100001", "My Test Label")
        assert result is True

    def test_add_page_label_dry_run(self):
        """Test adding a label in dry run mode."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = generator.add_page_label("100001", "test-label")
        assert result is True

    @responses.activate
    def test_add_page_labels_multiple(self):
        """Test adding multiple labels to pages."""
        for _ in range(5):
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/rest/api/content/100001/label",
                json={"results": [{"name": "label"}]},
                status=200,
            )

        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            count = generator.add_page_labels(["100001"], 5)

        assert count == 5

    def test_add_page_labels_empty_list(self):
        """Test adding labels with empty page list."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = generator.add_page_labels([], 5)
        assert count == 0


class TestPageProperties:
    """Tests for page property operations."""

    @responses.activate
    def test_set_page_property_success(self):
        """Test setting a page property."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/pages/100001/properties",
            json={"key": "test_prop", "value": {"test": "value"}},
            status=200,
        )

        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.set_page_property("100001", "test_prop", {"test": "value"})
        assert result is True

    def test_set_page_property_dry_run(self):
        """Test setting a property in dry run mode."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = generator.set_page_property("100001", "test_prop", {"test": "value"})
        assert result is True

    @responses.activate
    def test_set_page_properties_multiple(self):
        """Test setting multiple properties on pages."""
        for _ in range(5):
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/api/v2/pages/100001/properties",
                json={"key": "prop", "value": {}},
                status=200,
            )

        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            count = generator.set_page_properties(["100001"], 5)

        assert count == 5

    def test_set_page_properties_empty_list(self):
        """Test setting properties with empty page list."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = generator.set_page_properties([], 5)
        assert count == 0


class TestPageRestrictions:
    """Tests for page restriction operations."""

    @responses.activate
    def test_add_page_restriction_success(self):
        """Test adding a restriction to a page."""
        responses.add(
            responses.PUT,
            f"{CONFLUENCE_URL}/rest/api/content/100001/restriction",
            json={"results": []},
            status=200,
        )

        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.add_page_restriction("100001", "user-123", "read")
        assert result is True

    def test_add_page_restriction_dry_run(self):
        """Test adding a restriction in dry run mode."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = generator.add_page_restriction("100001", "user-123", "read")
        assert result is True

    @responses.activate
    def test_add_page_restrictions_multiple(self):
        """Test adding multiple restrictions to pages."""
        # Mock current user lookup (required to prevent self-lockout skip)
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/rest/api/user/current",
            json={"accountId": "current-user-id"},
            status=200,
        )

        for _ in range(4):
            responses.add(
                responses.PUT,
                f"{CONFLUENCE_URL}/rest/api/content/100001/restriction",
                json={"results": []},
                status=200,
            )
            responses.add(
                responses.PUT,
                f"{CONFLUENCE_URL}/rest/api/content/100002/restriction",
                json={"results": []},
                status=200,
            )

        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            count = generator.add_page_restrictions(
                page_ids=["100001", "100002"],
                user_account_ids=["user-1", "user-2"],
                count=4,
            )

        assert count == 4

    def test_add_page_restrictions_empty_lists(self):
        """Test adding restrictions with empty lists."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = generator.add_page_restrictions([], ["user-1"], 5)
        assert count == 0

        count = generator.add_page_restrictions(["100001"], [], 5)
        assert count == 0


class TestPageVersions:
    """Tests for page version operations."""

    @responses.activate
    def test_create_page_version_success(self):
        """Test creating a new version of a page."""
        # First GET the current page to get its version number
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/pages/100001",
            json={
                "id": "100001",
                "title": "Test Page",
                "version": {"number": 1},
                "body": {"storage": {"value": "<p>old content</p>"}},
            },
            status=200,
        )
        # Then PUT to update it
        responses.add(
            responses.PUT,
            f"{CONFLUENCE_URL}/api/v2/pages/100001",
            json={"id": "100001", "version": {"number": 2}},
            status=200,
        )

        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.create_page_version("100001", "Test Page")
        assert result is True

    def test_create_page_version_dry_run(self):
        """Test creating a version in dry run mode."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = generator.create_page_version("100001", "Test Page")
        assert result is True

    @responses.activate
    def test_create_page_versions_multiple(self):
        """Test creating multiple page versions."""
        for _ in range(3):
            responses.add(
                responses.GET,
                f"{CONFLUENCE_URL}/api/v2/pages/100001",
                json={
                    "id": "100001",
                    "title": "Test Page",
                    "version": {"number": 1},
                    "body": {"storage": {"value": "<p>content</p>"}},
                },
                status=200,
            )
            responses.add(
                responses.PUT,
                f"{CONFLUENCE_URL}/api/v2/pages/100001",
                json={"id": "100001", "version": {"number": 2}},
                status=200,
            )

        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            count = generator.create_page_versions([{"id": "100001", "title": "Test Page"}], 3)

        assert count == 3

    def test_create_page_versions_empty_list(self):
        """Test creating versions with empty page list."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = generator.create_page_versions([], 5)
        assert count == 0

    @responses.activate
    def test_create_page_version_retries_on_conflict(self):
        """Test that sync page versioning retries on 409 conflict."""
        # GET current version
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/pages/100001",
            json={"version": {"number": 1}},
        )
        # First PUT fails with 409
        responses.add(
            responses.PUT,
            f"{CONFLUENCE_URL}/api/v2/pages/100001",
            json={"message": "Version conflict"},
            status=409,
        )
        # Re-read version after conflict
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/pages/100001",
            json={"version": {"number": 2}},
        )
        # Second PUT succeeds
        responses.add(
            responses.PUT,
            f"{CONFLUENCE_URL}/api/v2/pages/100001",
            json={"id": "100001", "version": {"number": 3}},
        )

        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            result = generator.create_page_version("100001", "Test Page")

        assert result is True

    @responses.activate
    def test_create_page_version_exhausts_retries(self):
        """Test that sync page versioning fails after max retries."""
        # GET current version
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/pages/100001",
            json={"version": {"number": 1}},
        )
        # All PUTs fail with 409
        for _ in range(5):
            responses.add(
                responses.PUT,
                f"{CONFLUENCE_URL}/api/v2/pages/100001",
                json={"message": "Version conflict"},
                status=409,
            )
            responses.add(
                responses.GET,
                f"{CONFLUENCE_URL}/api/v2/pages/100001",
                json={"version": {"number": 1}},
            )

        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            result = generator.create_page_version("100001", "Test Page")

        assert result is False


class TestAsyncPageOperations:
    """Tests for async page operations."""

    @pytest.mark.asyncio
    async def test_create_page_async_success(self):
        """Test creating a page asynchronously."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/api/v2/pages",
                payload={"id": "100001", "title": "Test Page 1", "spaceId": "10001"},
                status=200,
            )

            page = await generator.create_page_async("10001", "Test Page 1")

            assert page is not None
            assert page["id"] == "100001"
            assert page["title"] == "Test Page 1"

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_page_async_with_parent(self):
        """Test creating a page asynchronously with parent."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/api/v2/pages",
                payload={"id": "100002", "title": "Child Page", "spaceId": "10001", "parentId": "100001"},
                status=200,
            )

            page = await generator.create_page_async("10001", "Child Page", parent_id="100001")

            assert page is not None
            assert page["id"] == "100002"

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_page_async_dry_run(self):
        """Test creating a page asynchronously in dry run mode."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        page = await generator.create_page_async("10001", "Test Page 1")

        assert page is not None
        assert page["title"] == "Test Page 1"
        assert "dry-run" in page["id"]

    @pytest.mark.asyncio
    async def test_create_pages_async_multiple(self):
        """Test creating multiple pages asynchronously."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for i in range(5):
                m.post(
                    f"{CONFLUENCE_URL}/api/v2/pages",
                    payload={"id": f"10000{i + 1}", "title": f"Page {i + 1}", "spaceId": "10001"},
                    status=200,
                )

            spaces = [{"key": "TEST1", "id": "10001"}]
            pages = await generator.create_pages_async(spaces, 5)

            assert len(pages) == 5
            assert generator.created_pages == pages

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_add_page_label_async_success(self):
        """Test adding a label asynchronously."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/rest/api/content/100001/label",
                payload={"results": [{"name": "test-label"}]},
                status=200,
            )

            result = await generator.add_page_label_async("100001", "test-label")
            assert result is True

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_add_page_labels_async_multiple(self):
        """Test adding multiple labels asynchronously."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for _ in range(5):
                m.post(
                    f"{CONFLUENCE_URL}/rest/api/content/100001/label",
                    payload={"results": [{"name": "label"}]},
                    status=200,
                )

            count = await generator.add_page_labels_async(["100001"], 5)
            assert count == 5

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_set_page_property_async_success(self):
        """Test setting a property asynchronously."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/api/v2/pages/100001/properties",
                payload={"key": "test_prop", "value": {}},
                status=200,
            )

            result = await generator.set_page_property_async("100001", "test_prop", {"test": "value"})
            assert result is True

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_set_page_properties_async_multiple(self):
        """Test setting multiple properties asynchronously."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for _ in range(5):
                m.post(
                    f"{CONFLUENCE_URL}/api/v2/pages/100001/properties",
                    payload={"key": "prop", "value": {}},
                    status=200,
                )

            count = await generator.set_page_properties_async(["100001"], 5)
            assert count == 5

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_add_page_restriction_async_success(self):
        """Test adding a restriction asynchronously."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.put(
                f"{CONFLUENCE_URL}/rest/api/content/100001/restriction",
                payload={"results": []},
                status=200,
            )

            result = await generator.add_page_restriction_async("100001", "user-123", "read")
            assert result is True

        await generator._close_async_session()

    @pytest.mark.asyncio
    @responses.activate
    async def test_add_page_restrictions_async_multiple(self):
        """Test adding multiple restrictions asynchronously."""
        # Mock current user lookup (sync call via asyncio.to_thread)
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/rest/api/user/current",
            json={"accountId": "current-user-id"},
            status=200,
        )

        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for _ in range(4):
                m.put(
                    f"{CONFLUENCE_URL}/rest/api/content/100001/restriction",
                    payload={"results": []},
                    status=200,
                )
                m.put(
                    f"{CONFLUENCE_URL}/rest/api/content/100002/restriction",
                    payload={"results": []},
                    status=200,
                )

            count = await generator.add_page_restrictions_async(
                page_ids=["100001", "100002"],
                user_account_ids=["user-1", "user-2"],
                count=4,
            )
            assert count == 4

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_page_version_async_success(self):
        """Test creating a page version asynchronously."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            # aioresponses needs the full URL including query params
            m.get(
                f"{CONFLUENCE_URL}/api/v2/pages/100001?body-format=storage",
                payload={
                    "id": "100001",
                    "title": "Test Page",
                    "version": {"number": 1},
                    "body": {"storage": {"value": "<p>content</p>"}},
                },
                status=200,
            )
            m.put(
                f"{CONFLUENCE_URL}/api/v2/pages/100001",
                payload={"id": "100001", "version": {"number": 2}},
                status=200,
            )

            result = await generator.create_page_version_async("100001", "Test Page")
            assert result is True

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_page_versions_async_multiple(self):
        """Test creating multiple page versions asynchronously."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for _ in range(3):
                m.get(
                    f"{CONFLUENCE_URL}/api/v2/pages/100001?body-format=storage",
                    payload={
                        "id": "100001",
                        "title": "Test Page",
                        "version": {"number": 1},
                        "body": {"storage": {"value": "<p>content</p>"}},
                    },
                    status=200,
                )
                m.put(
                    f"{CONFLUENCE_URL}/api/v2/pages/100001",
                    payload={"id": "100001", "version": {"number": 2}},
                    status=200,
                )

            pages = [{"id": "100001", "title": "Test Page"}]
            count = await generator.create_page_versions_async(pages, 3)
            assert count == 3

        await generator._close_async_session()


class TestAsyncDryRun:
    """Tests for async operations in dry run mode."""

    @pytest.mark.asyncio
    async def test_add_page_label_async_dry_run(self):
        """Test adding a label asynchronously in dry run mode."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = await generator.add_page_label_async("100001", "test-label")
        assert result is True

    @pytest.mark.asyncio
    async def test_set_page_property_async_dry_run(self):
        """Test setting a property asynchronously in dry run mode."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = await generator.set_page_property_async("100001", "test_prop", {"test": "value"})
        assert result is True

    @pytest.mark.asyncio
    async def test_add_page_restriction_async_dry_run(self):
        """Test adding a restriction asynchronously in dry run mode."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = await generator.add_page_restriction_async("100001", "user-123", "read")
        assert result is True

    @pytest.mark.asyncio
    async def test_create_page_version_async_dry_run(self):
        """Test creating a page version asynchronously in dry run mode."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = await generator.create_page_version_async("100001", "Test Page")
        assert result is True

    @pytest.mark.asyncio
    async def test_add_page_labels_async_empty_list(self):
        """Test adding labels with empty page list."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = await generator.add_page_labels_async([], 5)
        assert count == 0

    @pytest.mark.asyncio
    async def test_set_page_properties_async_empty_list(self):
        """Test setting properties with empty page list."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = await generator.set_page_properties_async([], 5)
        assert count == 0

    @pytest.mark.asyncio
    async def test_add_page_restrictions_async_empty_lists(self):
        """Test adding restrictions with empty lists."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = await generator.add_page_restrictions_async([], ["user-1"], 5)
        assert count == 0

        count = await generator.add_page_restrictions_async(["100001"], [], 5)
        assert count == 0

    @pytest.mark.asyncio
    async def test_create_page_versions_async_empty_list(self):
        """Test creating versions with empty page list."""
        generator = PageGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = await generator.create_page_versions_async([], 5)
        assert count == 0
