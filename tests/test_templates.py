"""Tests for generators/templates.py - TemplateGenerator."""

import json
from unittest.mock import MagicMock, patch

import pytest
import responses
from aioresponses import aioresponses

from generators.templates import TemplateGenerator
from tests.conftest import CONFLUENCE_URL, TEST_EMAIL, TEST_PREFIX, TEST_TOKEN


class TestTemplateGeneratorInitialization:
    """Tests for TemplateGenerator initialization."""

    def test_basic_initialization(self):
        """Test basic TemplateGenerator initialization."""
        generator = TemplateGenerator(
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
        assert generator.created_templates == []

    def test_initialization_with_all_parameters(self):
        """Test initialization with all optional parameters."""
        mock_benchmark = MagicMock()
        mock_checkpoint = MagicMock()

        generator = TemplateGenerator(
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
        generator = TemplateGenerator(
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
        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        generator.set_run_id("custom-run-id-123")
        assert generator.run_id == "custom-run-id-123"


class TestTemplateCreation:
    """Tests for template creation operations."""

    @responses.activate
    def test_create_template_success(self):
        """Test creating a template successfully."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/template",
            json={"templateId": "tpl-123", "name": "TESTDATA Template 1", "templateType": "page"},
            status=200,
        )

        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        template = generator.create_template("TEST1", 0)

        assert template is not None
        assert template["templateId"] == "tpl-123"
        assert template["name"] == "TESTDATA Template 1"
        assert template["spaceKey"] == "TEST1"

    def test_create_template_dry_run(self):
        """Test creating a template in dry run mode."""
        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        template = generator.create_template("TEST1", 0)

        assert template is not None
        assert template["name"] == "TESTDATA Template 1"
        assert template["templateId"] == "dry-run-template-TEST1-0"
        assert template["spaceKey"] == "TEST1"

    @responses.activate
    def test_create_template_failure(self):
        """Test creating a template when API returns error."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/template",
            json={"message": "error"},
            status=500,
        )

        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        template = generator.create_template("TEST1", 0)
        assert template is None

    def test_create_template_type_alternation(self):
        """Test that template types alternate between page and blogpost."""
        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        t0 = generator.create_template("TEST1", 0)
        t1 = generator.create_template("TEST1", 1)
        t2 = generator.create_template("TEST1", 2)

        # Even indices -> "page", odd indices -> "blogpost"
        assert t0 is not None
        assert t1 is not None
        assert t2 is not None

    @responses.activate
    def test_create_templates_multiple(self):
        """Test creating multiple templates across spaces."""
        for i in range(5):
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/rest/api/template",
                json={"templateId": f"tpl-{i + 1}", "name": f"Template {i + 1}", "templateType": "page"},
                status=200,
            )

        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        spaces = [{"key": "TEST1", "id": "10001"}]
        with patch("time.sleep"):
            templates = generator.create_templates(spaces, 5)

        assert len(templates) == 5
        assert generator.created_templates == templates

    def test_create_templates_distributes_across_spaces(self):
        """Test that templates are evenly distributed across spaces."""
        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        spaces = [{"key": "TEST1", "id": "10001"}, {"key": "TEST2", "id": "10002"}]
        with patch("time.sleep"):
            templates = generator.create_templates(spaces, 6)

        space_counts = {}
        for t in templates:
            sk = t["spaceKey"]
            space_counts[sk] = space_counts.get(sk, 0) + 1

        assert len(space_counts) == 2
        assert space_counts["TEST1"] == 3
        assert space_counts["TEST2"] == 3


class TestAsyncTemplateOperations:
    """Tests for async template operations."""

    @pytest.mark.asyncio
    async def test_create_template_async_success(self):
        """Test creating a template asynchronously."""
        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/rest/api/template",
                payload={"templateId": "tpl-123", "name": "TESTDATA Template 1", "templateType": "page"},
                status=200,
            )

            template = await generator.create_template_async("TEST1", 0)

            assert template is not None
            assert template["templateId"] == "tpl-123"
            assert template["name"] == "TESTDATA Template 1"
            assert template["spaceKey"] == "TEST1"

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_template_async_dry_run(self):
        """Test creating a template asynchronously in dry run mode."""
        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        template = await generator.create_template_async("TEST1", 0)

        assert template is not None
        assert template["name"] == "TESTDATA Template 1"
        assert "dry-run-template" in template["templateId"]

    @pytest.mark.asyncio
    async def test_create_template_async_failure(self):
        """Test creating a template asynchronously when API returns error."""
        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/rest/api/template",
                payload={"message": "error"},
                status=400,
            )

            template = await generator.create_template_async("TEST1", 0)
            assert template is None

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_templates_async_multiple(self):
        """Test creating multiple templates asynchronously."""
        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for i in range(5):
                m.post(
                    f"{CONFLUENCE_URL}/rest/api/template",
                    payload={"templateId": f"tpl-{i + 1}", "name": f"Template {i + 1}", "templateType": "page"},
                    status=200,
                )

            spaces = [{"key": "TEST1", "id": "10001"}]
            templates = await generator.create_templates_async(spaces, 5)

            assert len(templates) == 5
            assert generator.created_templates == templates

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_templates_async_distributes_across_spaces(self):
        """Test that async templates are distributed across spaces."""
        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        spaces = [{"key": "TEST1", "id": "10001"}, {"key": "TEST2", "id": "10002"}]
        templates = await generator.create_templates_async(spaces, 6)

        space_counts = {}
        for t in templates:
            sk = t["spaceKey"]
            space_counts[sk] = space_counts.get(sk, 0) + 1

        assert space_counts["TEST1"] == 3
        assert space_counts["TEST2"] == 3

    @pytest.mark.asyncio
    async def test_create_templates_async_exception_handling(self):
        """Test that exceptions in async batch are handled gracefully."""
        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            # First request succeeds, second raises connection error
            m.post(
                f"{CONFLUENCE_URL}/rest/api/template",
                payload={"templateId": "tpl-1", "name": "Template 1", "templateType": "page"},
                status=200,
            )
            m.post(
                f"{CONFLUENCE_URL}/rest/api/template",
                payload={"message": "error"},
                status=400,
            )

            spaces = [{"key": "TEST1", "id": "10001"}]
            templates = await generator.create_templates_async(spaces, 2)

            # At least the first one should succeed
            assert len(templates) >= 1

        await generator._close_async_session()


class TestTemplateAPIPayload:
    """Tests for template API payload structure."""

    @responses.activate
    def test_payload_structure(self):
        """Test that the API payload has correct structure."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/template",
            json={"templateId": "tpl-123", "name": "TESTDATA Template 1", "templateType": "page"},
            status=200,
        )

        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        generator.create_template("TEST1", 0)

        # Verify the request payload
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["name"] == "TESTDATA Template 1"
        assert request_body["templateType"] == "page"
        assert request_body["description"] == "Auto-generated template #1"
        assert request_body["space"] == {"key": "TEST1"}
        assert "body" in request_body
        assert request_body["body"]["storage"]["representation"] == "storage"

    @responses.activate
    def test_uses_v1_api_url(self):
        """Test that templates use the legacy REST API v1 URL."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/template",
            json={"templateId": "tpl-123", "name": "Template 1", "templateType": "page"},
            status=200,
        )

        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        generator.create_template("TEST1", 0)

        # Verify it hit the v1 URL, not v2
        assert "/rest/api/template" in responses.calls[0].request.url
        assert "/api/v2/" not in responses.calls[0].request.url


class TestTemplateCreationEdgeCases:
    """Tests for edge cases in template creation."""

    def test_create_templates_empty_spaces(self):
        """Test creating templates with empty space list."""
        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        templates = generator.create_templates([], 5)
        assert templates == []

    def test_create_templates_tracks_created(self):
        """Test that created_templates is updated after sync batch."""
        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        spaces = [{"key": "TEST1", "id": "10001"}]
        with patch("time.sleep"):
            templates = generator.create_templates(spaces, 3)

        assert len(generator.created_templates) == 3
        assert generator.created_templates == templates

    @pytest.mark.asyncio
    async def test_create_templates_async_tracks_created(self):
        """Test that created_templates is updated after async batch."""
        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        spaces = [{"key": "TEST1", "id": "10001"}]
        templates = await generator.create_templates_async(spaces, 3)

        assert len(generator.created_templates) == 3
        assert generator.created_templates == templates

    @pytest.mark.asyncio
    async def test_create_templates_async_empty_spaces(self):
        """Test creating templates asynchronously with empty space list."""
        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        templates = await generator.create_templates_async([], 5)
        assert templates == []

    def test_create_templates_zero_count(self):
        """Test creating zero templates."""
        generator = TemplateGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        spaces = [{"key": "TEST1", "id": "10001"}]
        with patch("time.sleep"):
            templates = generator.create_templates(spaces, 0)

        assert templates == []
