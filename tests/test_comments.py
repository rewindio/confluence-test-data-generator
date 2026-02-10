"""Tests for generators/comments.py - CommentGenerator."""

from unittest.mock import MagicMock, patch

import pytest
import responses
from aioresponses import aioresponses

from generators.comments import CommentGenerator
from tests.conftest import CONFLUENCE_URL, TEST_EMAIL, TEST_PREFIX, TEST_TOKEN


class TestCommentGeneratorInitialization:
    """Tests for CommentGenerator initialization."""

    def test_basic_initialization(self):
        """Test basic CommentGenerator initialization."""
        generator = CommentGenerator(
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
        assert generator.created_footer_comments == []
        assert generator.created_inline_comments == []

    def test_initialization_with_all_parameters(self):
        """Test initialization with all optional parameters."""
        mock_benchmark = MagicMock()
        mock_checkpoint = MagicMock()

        generator = CommentGenerator(
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
        generator = CommentGenerator(
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
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        generator.set_run_id("custom-run-id-123")
        assert generator.run_id == "custom-run-id-123"

    def test_extract_text_selection_from_html(self):
        """Test extracting a word from page body HTML."""
        result = CommentGenerator._extract_text_selection("<p>Hello world testing</p>")
        assert result == "Hello"

    def test_extract_text_selection_skips_short_words(self):
        """Test that short words (< 4 chars) are skipped."""
        result = CommentGenerator._extract_text_selection("<p>a to be or not long enough</p>")
        assert result == "long"

    def test_extract_text_selection_empty_body(self):
        """Test extracting from empty body returns None."""
        result = CommentGenerator._extract_text_selection("")
        assert result is None

    def test_extract_text_selection_no_suitable_words(self):
        """Test extracting from body with only short words returns None."""
        result = CommentGenerator._extract_text_selection("<p>a to be or</p>")
        assert result is None


class TestFooterCommentCreation:
    """Tests for footer comment creation operations."""

    @responses.activate
    def test_create_footer_comment_success(self):
        """Test creating a footer comment successfully."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/footer-comments",
            json={"id": "300001", "version": {"number": 1}},
            status=200,
        )

        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        comment = generator.create_footer_comment("100001", 1)

        assert comment is not None
        assert comment["id"] == "300001"
        assert comment["pageId"] == "100001"

    def test_create_footer_comment_dry_run(self):
        """Test creating a footer comment in dry run mode."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        comment = generator.create_footer_comment("100001", 1)

        assert comment is not None
        assert "dry-run-footer" in comment["id"]
        assert comment["pageId"] == "100001"

    @responses.activate
    def test_create_footer_comment_failure(self):
        """Test creating a footer comment when API returns error."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/footer-comments",
            json={"message": "error"},
            status=500,
        )

        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        comment = generator.create_footer_comment("100001", 1)
        assert comment is None

    @responses.activate
    def test_create_footer_comments_multiple(self):
        """Test creating multiple footer comments across pages."""
        for _ in range(5):
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/api/v2/footer-comments",
                json={"id": "300001", "version": {"number": 1}},
                status=200,
            )

        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            comments = generator.create_footer_comments(["100001", "100002"], 5)

        assert len(comments) == 5
        assert generator.created_footer_comments == comments

    def test_create_footer_comments_distributes_across_pages(self):
        """Test that footer comments are distributed round-robin across pages."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        with patch("time.sleep"):
            comments = generator.create_footer_comments(["100001", "100002"], 6)

        page_counts = {}
        for comment in comments:
            pid = comment["pageId"]
            page_counts[pid] = page_counts.get(pid, 0) + 1

        assert page_counts["100001"] == 3
        assert page_counts["100002"] == 3

    def test_create_footer_comments_empty_pages(self):
        """Test creating footer comments with empty page list."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        comments = generator.create_footer_comments([], 5)
        assert comments == []


PAGE_BODY_RESPONSE = {
    "id": "100001",
    "title": "Test Page",
    "version": {"number": 1},
    "body": {"storage": {"value": "<p>Lorem ipsum dolor sit amet consectetur</p>"}},
}


class TestInlineCommentCreation:
    """Tests for inline comment creation operations."""

    @responses.activate
    def test_create_inline_comment_success(self):
        """Test creating an inline comment successfully."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/pages/100001",
            json=PAGE_BODY_RESPONSE,
            status=200,
        )
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/inline-comments",
            json={"id": "400001", "version": {"number": 1}},
            status=200,
        )

        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        comment = generator.create_inline_comment("100001", 1)

        assert comment is not None
        assert comment["id"] == "400001"
        assert comment["pageId"] == "100001"

    @responses.activate
    def test_create_inline_comment_includes_inline_properties(self):
        """Test that inline comment creation includes inlineCommentProperties with real text."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/pages/100001",
            json=PAGE_BODY_RESPONSE,
            status=200,
        )
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/inline-comments",
            json={"id": "400001", "version": {"number": 1}},
            status=200,
        )

        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        generator.create_inline_comment("100001", 1)

        # Verify the request body includes inlineCommentProperties
        import json

        # The POST is the second call (after the GET for page body)
        body = json.loads(responses.calls[1].request.body)
        assert "inlineCommentProperties" in body
        # textSelection should be a real word from the page body, not "text"
        assert body["inlineCommentProperties"]["textSelection"] == "Lorem"
        assert body["inlineCommentProperties"]["textSelectionMatchCount"] == 1
        assert body["inlineCommentProperties"]["textSelectionMatchIndex"] == 0

    def test_create_inline_comment_dry_run(self):
        """Test creating an inline comment in dry run mode."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        comment = generator.create_inline_comment("100001", 1)

        assert comment is not None
        assert "dry-run-inline" in comment["id"]
        assert comment["pageId"] == "100001"

    @responses.activate
    def test_create_inline_comment_failure(self):
        """Test creating an inline comment when POST returns error."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/pages/100001",
            json=PAGE_BODY_RESPONSE,
            status=200,
        )
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/inline-comments",
            json={"message": "error"},
            status=500,
        )

        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        comment = generator.create_inline_comment("100001", 1)
        assert comment is None

    @responses.activate
    def test_create_inline_comment_page_fetch_fails(self):
        """Test creating an inline comment when page body fetch fails."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/pages/100001",
            json={"message": "Not found"},
            status=404,
        )

        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        comment = generator.create_inline_comment("100001", 1)
        assert comment is None

    @responses.activate
    def test_create_inline_comments_multiple(self):
        """Test creating multiple inline comments across pages."""
        # Page GET responses (cached per page, so 2 GETs for 2 pages)
        for pid in ["100001", "100002"]:
            responses.add(
                responses.GET,
                f"{CONFLUENCE_URL}/api/v2/pages/{pid}",
                json={**PAGE_BODY_RESPONSE, "id": pid},
                status=200,
            )
        for _ in range(5):
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/api/v2/inline-comments",
                json={"id": "400001", "version": {"number": 1}},
                status=200,
            )

        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            comments = generator.create_inline_comments(["100001", "100002"], 5)

        assert len(comments) == 5
        assert generator.created_inline_comments == comments

    def test_create_inline_comments_empty_pages(self):
        """Test creating inline comments with empty page list."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        comments = generator.create_inline_comments([], 5)
        assert comments == []


class TestCommentVersionsSync:
    """Tests for synchronous comment version operations."""

    @responses.activate
    def test_create_comment_version_footer_success(self):
        """Test creating a new version of a footer comment."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/footer-comments/300001",
            json={
                "id": "300001",
                "version": {"number": 1},
                "body": {"storage": {"value": "<p>old content</p>"}},
            },
            status=200,
        )
        responses.add(
            responses.PUT,
            f"{CONFLUENCE_URL}/api/v2/footer-comments/300001",
            json={"id": "300001", "version": {"number": 2}},
            status=200,
        )

        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.create_comment_version("300001", "footer")
        assert result is True

    @responses.activate
    def test_create_comment_version_inline_success(self):
        """Test creating a new version of an inline comment."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/inline-comments/400001",
            json={
                "id": "400001",
                "version": {"number": 1},
                "body": {"storage": {"value": "<p>old content</p>"}},
            },
            status=200,
        )
        responses.add(
            responses.PUT,
            f"{CONFLUENCE_URL}/api/v2/inline-comments/400001",
            json={"id": "400001", "version": {"number": 2}},
            status=200,
        )

        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.create_comment_version("400001", "inline")
        assert result is True

    def test_create_comment_version_dry_run(self):
        """Test creating a version in dry run mode."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = generator.create_comment_version("300001", "footer")
        assert result is True

    @responses.activate
    def test_create_comment_version_get_fails(self):
        """Test creating a version when GET fails."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/footer-comments/300001",
            json={"message": "Not found"},
            status=404,
        )

        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.create_comment_version("300001", "footer")
        assert result is False

    @responses.activate
    def test_create_comment_versions_multiple(self):
        """Test creating multiple comment versions."""
        for _ in range(3):
            responses.add(
                responses.GET,
                f"{CONFLUENCE_URL}/api/v2/footer-comments/300001",
                json={
                    "id": "300001",
                    "version": {"number": 1},
                    "body": {"storage": {"value": "<p>content</p>"}},
                },
                status=200,
            )
            responses.add(
                responses.PUT,
                f"{CONFLUENCE_URL}/api/v2/footer-comments/300001",
                json={"id": "300001", "version": {"number": 2}},
                status=200,
            )

        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            count = generator.create_comment_versions([{"id": "300001", "pageId": "100001"}], 3, "footer")

        assert count == 3

    def test_create_comment_versions_empty_list(self):
        """Test creating versions with empty comment list."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = generator.create_comment_versions([], 5, "footer")
        assert count == 0


class TestSyncDryRun:
    """Tests for sync dry run mode across all operations."""

    def test_create_footer_comments_dry_run(self):
        """Test creating multiple footer comments in dry run mode."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        with patch("time.sleep"):
            comments = generator.create_footer_comments(["100001", "100002"], 4)

        assert len(comments) == 4
        for comment in comments:
            assert "dry-run-footer" in comment["id"]

    def test_create_inline_comments_dry_run(self):
        """Test creating multiple inline comments in dry run mode."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        with patch("time.sleep"):
            comments = generator.create_inline_comments(["100001", "100002"], 4)

        assert len(comments) == 4
        for comment in comments:
            assert "dry-run-inline" in comment["id"]

    def test_create_comment_versions_dry_run(self):
        """Test creating comment versions in dry run mode."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        with patch("time.sleep"):
            count = generator.create_comment_versions([{"id": "300001", "pageId": "100001"}], 3, "footer")

        assert count == 3


class TestAsyncFooterCommentCreation:
    """Tests for async footer comment operations."""

    @pytest.mark.asyncio
    async def test_create_footer_comment_async_success(self):
        """Test creating a footer comment asynchronously."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/api/v2/footer-comments",
                payload={"id": "300001", "version": {"number": 1}},
                status=200,
            )

            comment = await generator.create_footer_comment_async("100001", 1)

            assert comment is not None
            assert comment["id"] == "300001"
            assert comment["pageId"] == "100001"

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_footer_comment_async_dry_run(self):
        """Test creating a footer comment asynchronously in dry run mode."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        comment = await generator.create_footer_comment_async("100001", 1)

        assert comment is not None
        assert "dry-run-footer" in comment["id"]
        assert comment["pageId"] == "100001"

    @pytest.mark.asyncio
    async def test_create_footer_comment_async_failure(self):
        """Test creating a footer comment asynchronously when API returns error."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/api/v2/footer-comments",
                payload={"message": "error"},
                status=500,
            )

            comment = await generator.create_footer_comment_async("100001", 1)
            assert comment is None

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_footer_comments_async_multiple(self):
        """Test creating multiple footer comments asynchronously."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for _ in range(5):
                m.post(
                    f"{CONFLUENCE_URL}/api/v2/footer-comments",
                    payload={"id": "300001", "version": {"number": 1}},
                    status=200,
                )

            comments = await generator.create_footer_comments_async(["100001", "100002"], 5)

            assert len(comments) == 5
            assert generator.created_footer_comments == comments

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_footer_comments_async_empty_pages(self):
        """Test creating footer comments with empty page list."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        comments = await generator.create_footer_comments_async([], 5)
        assert comments == []


class TestAsyncInlineCommentCreation:
    """Tests for async inline comment operations."""

    @pytest.mark.asyncio
    async def test_create_inline_comment_async_success(self):
        """Test creating an inline comment asynchronously."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.get(
                f"{CONFLUENCE_URL}/api/v2/pages/100001?body-format=storage",
                payload=PAGE_BODY_RESPONSE,
                status=200,
            )
            m.post(
                f"{CONFLUENCE_URL}/api/v2/inline-comments",
                payload={"id": "400001", "version": {"number": 1}},
                status=200,
            )

            comment = await generator.create_inline_comment_async("100001", 1)

            assert comment is not None
            assert comment["id"] == "400001"
            assert comment["pageId"] == "100001"

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_inline_comment_async_dry_run(self):
        """Test creating an inline comment asynchronously in dry run mode."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        comment = await generator.create_inline_comment_async("100001", 1)

        assert comment is not None
        assert "dry-run-inline" in comment["id"]
        assert comment["pageId"] == "100001"

    @pytest.mark.asyncio
    async def test_create_inline_comment_async_failure(self):
        """Test creating an inline comment asynchronously when POST returns error."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.get(
                f"{CONFLUENCE_URL}/api/v2/pages/100001?body-format=storage",
                payload=PAGE_BODY_RESPONSE,
                status=200,
            )
            m.post(
                f"{CONFLUENCE_URL}/api/v2/inline-comments",
                payload={"message": "error"},
                status=500,
            )

            comment = await generator.create_inline_comment_async("100001", 1)
            assert comment is None

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_inline_comment_async_page_fetch_fails(self):
        """Test creating an inline comment when page body fetch fails."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.get(
                f"{CONFLUENCE_URL}/api/v2/pages/100001?body-format=storage",
                payload={"message": "Not found"},
                status=404,
            )

            comment = await generator.create_inline_comment_async("100001", 1)
            assert comment is None

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_inline_comments_async_multiple(self):
        """Test creating multiple inline comments asynchronously."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            # Page GETs (one per unique page, cached after first)
            for pid in ["100001", "100002"]:
                m.get(
                    f"{CONFLUENCE_URL}/api/v2/pages/{pid}?body-format=storage",
                    payload={**PAGE_BODY_RESPONSE, "id": pid},
                    status=200,
                )
            for _ in range(5):
                m.post(
                    f"{CONFLUENCE_URL}/api/v2/inline-comments",
                    payload={"id": "400001", "version": {"number": 1}},
                    status=200,
                )

            comments = await generator.create_inline_comments_async(["100001", "100002"], 5)

            assert len(comments) == 5
            assert generator.created_inline_comments == comments

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_inline_comments_async_empty_pages(self):
        """Test creating inline comments with empty page list."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        comments = await generator.create_inline_comments_async([], 5)
        assert comments == []


class TestAsyncCommentVersions:
    """Tests for async comment version operations."""

    @pytest.mark.asyncio
    async def test_create_comment_version_async_success(self):
        """Test creating a comment version asynchronously."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.get(
                f"{CONFLUENCE_URL}/api/v2/footer-comments/300001?body-format=storage",
                payload={
                    "id": "300001",
                    "version": {"number": 1},
                    "body": {"storage": {"value": "<p>content</p>"}},
                },
                status=200,
            )
            m.put(
                f"{CONFLUENCE_URL}/api/v2/footer-comments/300001",
                payload={"id": "300001", "version": {"number": 2}},
                status=200,
            )

            result = await generator.create_comment_version_async("300001", "footer")
            assert result is True

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_comment_version_async_dry_run(self):
        """Test creating a comment version asynchronously in dry run mode."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = await generator.create_comment_version_async("300001", "footer")
        assert result is True

    @pytest.mark.asyncio
    async def test_create_comment_version_async_get_fails(self):
        """Test creating a comment version when GET fails."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.get(
                f"{CONFLUENCE_URL}/api/v2/footer-comments/300001?body-format=storage",
                payload={"message": "Not found"},
                status=404,
            )

            result = await generator.create_comment_version_async("300001", "footer")
            assert result is False

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_comment_versions_async_multiple(self):
        """Test creating multiple comment versions asynchronously."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for _ in range(3):
                m.get(
                    f"{CONFLUENCE_URL}/api/v2/footer-comments/300001?body-format=storage",
                    payload={
                        "id": "300001",
                        "version": {"number": 1},
                        "body": {"storage": {"value": "<p>content</p>"}},
                    },
                    status=200,
                )
                m.put(
                    f"{CONFLUENCE_URL}/api/v2/footer-comments/300001",
                    payload={"id": "300001", "version": {"number": 2}},
                    status=200,
                )

            comments = [{"id": "300001", "pageId": "100001"}]
            count = await generator.create_comment_versions_async(comments, 3, "footer")
            assert count == 3

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_comment_versions_async_empty_list(self):
        """Test creating versions with empty comment list."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = await generator.create_comment_versions_async([], 5, "footer")
        assert count == 0

    @pytest.mark.asyncio
    async def test_create_comment_versions_async_inline(self):
        """Test creating inline comment versions asynchronously."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.get(
                f"{CONFLUENCE_URL}/api/v2/inline-comments/400001?body-format=storage",
                payload={
                    "id": "400001",
                    "version": {"number": 1},
                    "body": {"storage": {"value": "<p>content</p>"}},
                },
                status=200,
            )
            m.put(
                f"{CONFLUENCE_URL}/api/v2/inline-comments/400001",
                payload={"id": "400001", "version": {"number": 2}},
                status=200,
            )

            comments = [{"id": "400001", "pageId": "100001"}]
            count = await generator.create_comment_versions_async(comments, 1, "inline")
            assert count == 1

        await generator._close_async_session()


class TestAsyncDryRun:
    """Tests for async operations in dry run mode."""

    @pytest.mark.asyncio
    async def test_create_footer_comments_async_dry_run(self):
        """Test creating multiple footer comments in dry run mode."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        comments = await generator.create_footer_comments_async(["100001", "100002"], 4)
        assert len(comments) == 4
        for comment in comments:
            assert "dry-run-footer" in comment["id"]

    @pytest.mark.asyncio
    async def test_create_inline_comments_async_dry_run(self):
        """Test creating multiple inline comments in dry run mode."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        comments = await generator.create_inline_comments_async(["100001", "100002"], 4)
        assert len(comments) == 4
        for comment in comments:
            assert "dry-run-inline" in comment["id"]

    @pytest.mark.asyncio
    async def test_create_comment_versions_async_dry_run(self):
        """Test creating comment versions asynchronously in dry run mode."""
        generator = CommentGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        comments = [{"id": "300001", "pageId": "100001"}]
        count = await generator.create_comment_versions_async(comments, 3, "footer")
        assert count == 3
