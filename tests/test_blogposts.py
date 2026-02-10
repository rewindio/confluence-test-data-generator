"""Tests for generators/blogposts.py - BlogPostGenerator."""

from unittest.mock import MagicMock, patch

import pytest
import responses
from aioresponses import aioresponses

from generators.blogposts import BlogPostGenerator
from tests.conftest import CONFLUENCE_URL, TEST_EMAIL, TEST_PREFIX, TEST_TOKEN


class TestBlogPostGeneratorInitialization:
    """Tests for BlogPostGenerator initialization."""

    def test_basic_initialization(self):
        """Test basic BlogPostGenerator initialization."""
        generator = BlogPostGenerator(
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
        assert generator.created_blogposts == []

    def test_initialization_with_all_parameters(self):
        """Test initialization with all optional parameters."""
        mock_benchmark = MagicMock()
        mock_checkpoint = MagicMock()

        generator = BlogPostGenerator(
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
        generator = BlogPostGenerator(
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
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        generator.set_run_id("custom-run-id-123")
        assert generator.run_id == "custom-run-id-123"


class TestBlogPostCreation:
    """Tests for blog post creation operations."""

    @responses.activate
    def test_create_blogpost_success(self):
        """Test creating a blog post successfully."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/blogposts",
            json={"id": "200001", "title": "Test Blog Post 1", "spaceId": "10001"},
            status=200,
        )

        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        blogpost = generator.create_blogpost("10001", "Test Blog Post 1")

        assert blogpost is not None
        assert blogpost["id"] == "200001"
        assert blogpost["title"] == "Test Blog Post 1"
        assert blogpost["spaceId"] == "10001"

    def test_create_blogpost_dry_run(self):
        """Test creating a blog post in dry run mode."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        blogpost = generator.create_blogpost("10001", "Test Blog Post 1")

        assert blogpost is not None
        assert blogpost["title"] == "Test Blog Post 1"
        assert "dry-run" in blogpost["id"]
        assert blogpost["spaceId"] == "10001"

    @responses.activate
    def test_create_blogpost_failure(self):
        """Test creating a blog post when API returns error."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/blogposts",
            json={"message": "error"},
            status=500,
        )

        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        blogpost = generator.create_blogpost("10001", "Test Blog Post 1")
        assert blogpost is None

    @responses.activate
    def test_create_blogposts_multiple(self):
        """Test creating multiple blog posts across spaces."""
        for i in range(5):
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/api/v2/blogposts",
                json={"id": f"20000{i + 1}", "title": f"Blog Post {i + 1}", "spaceId": "10001"},
                status=200,
            )

        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        spaces = [{"key": "TEST1", "id": "10001"}]
        with patch("time.sleep"):
            blogposts = generator.create_blogposts(spaces, 5)

        assert len(blogposts) == 5
        assert generator.created_blogposts == blogposts

    def test_create_blogposts_dry_run(self):
        """Test creating multiple blog posts in dry run mode."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        spaces = [{"key": "TEST1", "id": "10001"}, {"key": "TEST2", "id": "10002"}]
        with patch("time.sleep"):
            blogposts = generator.create_blogposts(spaces, 6)

        assert len(blogposts) == 6
        for blogpost in blogposts:
            assert "dry-run" in blogpost["id"]

    def test_create_blogposts_distributes_across_spaces(self):
        """Test that blog posts are evenly distributed across spaces."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        spaces = [{"key": "TEST1", "id": "10001"}, {"key": "TEST2", "id": "10002"}]
        with patch("time.sleep"):
            blogposts = generator.create_blogposts(spaces, 6)

        space_counts = {}
        for blogpost in blogposts:
            sid = blogpost["spaceId"]
            space_counts[sid] = space_counts.get(sid, 0) + 1

        assert len(space_counts) == 2
        assert space_counts["10001"] == 3
        assert space_counts["10002"] == 3

    def test_create_blogposts_empty_spaces(self):
        """Test creating blog posts with empty space list."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        blogposts = generator.create_blogposts([], 5)
        assert blogposts == []


class TestBlogPostLabels:
    """Tests for blog post label operations."""

    @responses.activate
    def test_add_blogpost_label_success(self):
        """Test adding a label to a blog post."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/200001/label",
            json={"results": [{"name": "test-label"}]},
            status=200,
        )

        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.add_blogpost_label("200001", "Test Label")
        assert result is True

    @responses.activate
    def test_add_blogpost_label_normalizes(self):
        """Test that labels are normalized to lowercase with hyphens."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/content/200001/label",
            json={"results": [{"name": "my-test-label"}]},
            status=200,
        )

        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.add_blogpost_label("200001", "My Test Label")
        assert result is True

    def test_add_blogpost_label_dry_run(self):
        """Test adding a label in dry run mode."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = generator.add_blogpost_label("200001", "test-label")
        assert result is True

    @responses.activate
    def test_add_blogpost_labels_multiple(self):
        """Test adding multiple labels to blog posts."""
        for _ in range(5):
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/rest/api/content/200001/label",
                json={"results": [{"name": "label"}]},
                status=200,
            )

        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            count = generator.add_blogpost_labels(["200001"], 5)

        assert count == 5

    def test_add_blogpost_labels_empty_list(self):
        """Test adding labels with empty blog post list."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = generator.add_blogpost_labels([], 5)
        assert count == 0


class TestBlogPostProperties:
    """Tests for blog post property operations."""

    @responses.activate
    def test_set_blogpost_property_success(self):
        """Test setting a blog post property."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/blogposts/200001/properties",
            json={"key": "test_prop", "value": {"test": "value"}},
            status=200,
        )

        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.set_blogpost_property("200001", "test_prop", {"test": "value"})
        assert result is True

    def test_set_blogpost_property_dry_run(self):
        """Test setting a property in dry run mode."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = generator.set_blogpost_property("200001", "test_prop", {"test": "value"})
        assert result is True

    @responses.activate
    def test_set_blogpost_properties_multiple(self):
        """Test setting multiple properties on blog posts."""
        for _ in range(5):
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/api/v2/blogposts/200001/properties",
                json={"key": "prop", "value": {}},
                status=200,
            )

        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            count = generator.set_blogpost_properties(["200001"], 5)

        assert count == 5

    def test_set_blogpost_properties_empty_list(self):
        """Test setting properties with empty blog post list."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = generator.set_blogpost_properties([], 5)
        assert count == 0


class TestBlogPostRestrictions:
    """Tests for blog post restriction operations."""

    @responses.activate
    def test_add_blogpost_restriction_success(self):
        """Test adding a restriction to a blog post."""
        responses.add(
            responses.PUT,
            f"{CONFLUENCE_URL}/rest/api/content/200001/restriction",
            json={"results": []},
            status=200,
        )

        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.add_blogpost_restriction("200001", "user-123", "read")
        assert result is True

    def test_add_blogpost_restriction_dry_run(self):
        """Test adding a restriction in dry run mode."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = generator.add_blogpost_restriction("200001", "user-123", "read")
        assert result is True

    @responses.activate
    def test_add_blogpost_restrictions_multiple(self):
        """Test adding multiple restrictions to blog posts."""
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
                f"{CONFLUENCE_URL}/rest/api/content/200001/restriction",
                json={"results": []},
                status=200,
            )
            responses.add(
                responses.PUT,
                f"{CONFLUENCE_URL}/rest/api/content/200002/restriction",
                json={"results": []},
                status=200,
            )

        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            count = generator.add_blogpost_restrictions(
                blogpost_ids=["200001", "200002"],
                user_account_ids=["user-1", "user-2"],
                count=4,
            )

        assert count == 4

    def test_add_blogpost_restrictions_empty_lists(self):
        """Test adding restrictions with empty lists."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = generator.add_blogpost_restrictions([], ["user-1"], 5)
        assert count == 0

        count = generator.add_blogpost_restrictions(["200001"], [], 5)
        assert count == 0


class TestBlogPostVersions:
    """Tests for blog post version operations."""

    @responses.activate
    def test_create_blogpost_version_success(self):
        """Test creating a new version of a blog post."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/blogposts/200001",
            json={
                "id": "200001",
                "title": "Test Blog Post",
                "version": {"number": 1},
                "body": {"storage": {"value": "<p>old content</p>"}},
            },
            status=200,
        )
        responses.add(
            responses.PUT,
            f"{CONFLUENCE_URL}/api/v2/blogposts/200001",
            json={"id": "200001", "version": {"number": 2}},
            status=200,
        )

        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.create_blogpost_version("200001", "Test Blog Post")
        assert result is True

    def test_create_blogpost_version_dry_run(self):
        """Test creating a version in dry run mode."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = generator.create_blogpost_version("200001", "Test Blog Post")
        assert result is True

    @responses.activate
    def test_create_blogpost_version_get_fails(self):
        """Test creating a version when GET fails."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/blogposts/200001",
            json={"message": "Not found"},
            status=404,
        )

        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.create_blogpost_version("200001", "Test Blog Post")
        assert result is False

    @responses.activate
    def test_create_blogpost_versions_multiple(self):
        """Test creating multiple blog post versions."""
        for _ in range(3):
            responses.add(
                responses.GET,
                f"{CONFLUENCE_URL}/api/v2/blogposts/200001",
                json={
                    "id": "200001",
                    "title": "Test Blog Post",
                    "version": {"number": 1},
                    "body": {"storage": {"value": "<p>content</p>"}},
                },
                status=200,
            )
            responses.add(
                responses.PUT,
                f"{CONFLUENCE_URL}/api/v2/blogposts/200001",
                json={"id": "200001", "version": {"number": 2}},
                status=200,
            )

        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            count = generator.create_blogpost_versions([{"id": "200001", "title": "Test Blog Post"}], 3)

        assert count == 3

    def test_create_blogpost_versions_empty_list(self):
        """Test creating versions with empty blog post list."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = generator.create_blogpost_versions([], 5)
        assert count == 0


class TestAsyncBlogPostOperations:
    """Tests for async blog post operations."""

    @pytest.mark.asyncio
    async def test_create_blogpost_async_success(self):
        """Test creating a blog post asynchronously."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/api/v2/blogposts",
                payload={"id": "200001", "title": "Test Blog Post 1", "spaceId": "10001"},
                status=200,
            )

            blogpost = await generator.create_blogpost_async("10001", "Test Blog Post 1")

            assert blogpost is not None
            assert blogpost["id"] == "200001"
            assert blogpost["title"] == "Test Blog Post 1"

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_blogpost_async_dry_run(self):
        """Test creating a blog post asynchronously in dry run mode."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        blogpost = await generator.create_blogpost_async("10001", "Test Blog Post 1")

        assert blogpost is not None
        assert blogpost["title"] == "Test Blog Post 1"
        assert "dry-run" in blogpost["id"]

    @pytest.mark.asyncio
    async def test_create_blogposts_async_multiple(self):
        """Test creating multiple blog posts asynchronously."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for i in range(5):
                m.post(
                    f"{CONFLUENCE_URL}/api/v2/blogposts",
                    payload={"id": f"20000{i + 1}", "title": f"Blog Post {i + 1}", "spaceId": "10001"},
                    status=200,
                )

            spaces = [{"key": "TEST1", "id": "10001"}]
            blogposts = await generator.create_blogposts_async(spaces, 5)

            assert len(blogposts) == 5
            assert generator.created_blogposts == blogposts

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_blogposts_async_empty_spaces(self):
        """Test creating blog posts with empty space list."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        blogposts = await generator.create_blogposts_async([], 5)
        assert blogposts == []

    @pytest.mark.asyncio
    async def test_add_blogpost_label_async_success(self):
        """Test adding a label asynchronously."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/rest/api/content/200001/label",
                payload={"results": [{"name": "test-label"}]},
                status=200,
            )

            result = await generator.add_blogpost_label_async("200001", "test-label")
            assert result is True

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_add_blogpost_labels_async_multiple(self):
        """Test adding multiple labels asynchronously."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for _ in range(5):
                m.post(
                    f"{CONFLUENCE_URL}/rest/api/content/200001/label",
                    payload={"results": [{"name": "label"}]},
                    status=200,
                )

            count = await generator.add_blogpost_labels_async(["200001"], 5)
            assert count == 5

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_set_blogpost_property_async_success(self):
        """Test setting a property asynchronously."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/api/v2/blogposts/200001/properties",
                payload={"key": "test_prop", "value": {}},
                status=200,
            )

            result = await generator.set_blogpost_property_async("200001", "test_prop", {"test": "value"})
            assert result is True

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_set_blogpost_properties_async_multiple(self):
        """Test setting multiple properties asynchronously."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for _ in range(5):
                m.post(
                    f"{CONFLUENCE_URL}/api/v2/blogposts/200001/properties",
                    payload={"key": "prop", "value": {}},
                    status=200,
                )

            count = await generator.set_blogpost_properties_async(["200001"], 5)
            assert count == 5

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_add_blogpost_restriction_async_success(self):
        """Test adding a restriction asynchronously."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.put(
                f"{CONFLUENCE_URL}/rest/api/content/200001/restriction",
                payload={"results": []},
                status=200,
            )

            result = await generator.add_blogpost_restriction_async("200001", "user-123", "read")
            assert result is True

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_add_blogpost_restrictions_async_multiple(self):
        """Test adding multiple restrictions asynchronously."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        # Use RequestsMock as context manager so the sync mock stays active
        # through the entire coroutine (asyncio.to_thread calls requests).
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"{CONFLUENCE_URL}/rest/api/user/current",
                json={"accountId": "current-user-id"},
                status=200,
            )

            with aioresponses() as m:
                for _ in range(4):
                    m.put(
                        f"{CONFLUENCE_URL}/rest/api/content/200001/restriction",
                        payload={"results": []},
                        status=200,
                    )
                    m.put(
                        f"{CONFLUENCE_URL}/rest/api/content/200002/restriction",
                        payload={"results": []},
                        status=200,
                    )

                count = await generator.add_blogpost_restrictions_async(
                    blogpost_ids=["200001", "200002"],
                    user_account_ids=["user-1", "user-2"],
                    count=4,
                )
                assert count == 4

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_blogpost_version_async_success(self):
        """Test creating a blog post version asynchronously."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.get(
                f"{CONFLUENCE_URL}/api/v2/blogposts/200001?body-format=storage",
                payload={
                    "id": "200001",
                    "title": "Test Blog Post",
                    "version": {"number": 1},
                    "body": {"storage": {"value": "<p>content</p>"}},
                },
                status=200,
            )
            m.put(
                f"{CONFLUENCE_URL}/api/v2/blogposts/200001",
                payload={"id": "200001", "version": {"number": 2}},
                status=200,
            )

            result = await generator.create_blogpost_version_async("200001", "Test Blog Post")
            assert result is True

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_blogpost_versions_async_multiple(self):
        """Test creating multiple blog post versions asynchronously."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for _ in range(3):
                m.get(
                    f"{CONFLUENCE_URL}/api/v2/blogposts/200001?body-format=storage",
                    payload={
                        "id": "200001",
                        "title": "Test Blog Post",
                        "version": {"number": 1},
                        "body": {"storage": {"value": "<p>content</p>"}},
                    },
                    status=200,
                )
                m.put(
                    f"{CONFLUENCE_URL}/api/v2/blogposts/200001",
                    payload={"id": "200001", "version": {"number": 2}},
                    status=200,
                )

            blogposts = [{"id": "200001", "title": "Test Blog Post"}]
            count = await generator.create_blogpost_versions_async(blogposts, 3)
            assert count == 3

        await generator._close_async_session()


class TestAsyncDryRun:
    """Tests for async operations in dry run mode."""

    @pytest.mark.asyncio
    async def test_add_blogpost_label_async_dry_run(self):
        """Test adding a label asynchronously in dry run mode."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = await generator.add_blogpost_label_async("200001", "test-label")
        assert result is True

    @pytest.mark.asyncio
    async def test_set_blogpost_property_async_dry_run(self):
        """Test setting a property asynchronously in dry run mode."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = await generator.set_blogpost_property_async("200001", "test_prop", {"test": "value"})
        assert result is True

    @pytest.mark.asyncio
    async def test_add_blogpost_restriction_async_dry_run(self):
        """Test adding a restriction asynchronously in dry run mode."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = await generator.add_blogpost_restriction_async("200001", "user-123", "read")
        assert result is True

    @pytest.mark.asyncio
    async def test_create_blogpost_version_async_dry_run(self):
        """Test creating a blog post version asynchronously in dry run mode."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = await generator.create_blogpost_version_async("200001", "Test Blog Post")
        assert result is True

    @pytest.mark.asyncio
    async def test_add_blogpost_labels_async_empty_list(self):
        """Test adding labels with empty blog post list."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = await generator.add_blogpost_labels_async([], 5)
        assert count == 0

    @pytest.mark.asyncio
    async def test_set_blogpost_properties_async_empty_list(self):
        """Test setting properties with empty blog post list."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = await generator.set_blogpost_properties_async([], 5)
        assert count == 0

    @pytest.mark.asyncio
    async def test_add_blogpost_restrictions_async_empty_lists(self):
        """Test adding restrictions with empty lists."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = await generator.add_blogpost_restrictions_async([], ["user-1"], 5)
        assert count == 0

        count = await generator.add_blogpost_restrictions_async(["200001"], [], 5)
        assert count == 0

    @pytest.mark.asyncio
    async def test_create_blogpost_versions_async_empty_list(self):
        """Test creating versions with empty blog post list."""
        generator = BlogPostGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = await generator.create_blogpost_versions_async([], 5)
        assert count == 0
