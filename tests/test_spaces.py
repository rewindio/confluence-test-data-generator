"""Tests for generators/spaces.py - SpaceGenerator."""

from unittest.mock import MagicMock, patch

import pytest
import responses
from aioresponses import aioresponses

from generators.spaces import SpaceGenerator

# Import test constants from conftest
from tests.conftest import CONFLUENCE_URL, TEST_EMAIL, TEST_PREFIX, TEST_TOKEN


class TestSpaceGeneratorInitialization:
    """Tests for SpaceGenerator initialization."""

    def test_basic_initialization(self):
        """Test basic SpaceGenerator initialization."""
        generator = SpaceGenerator(
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
        assert generator.created_spaces == []

    def test_initialization_with_all_parameters(self):
        """Test initialization with all optional parameters."""
        mock_benchmark = MagicMock()
        mock_checkpoint = MagicMock()

        generator = SpaceGenerator(
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
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        assert generator.run_id.startswith(TEST_PREFIX)
        # Should be like TESTDATA-20241208-120000
        parts = generator.run_id.split("-")
        assert len(parts) == 3

    def test_set_run_id(self):
        """Test setting custom run ID."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        generator.set_run_id("custom-run-id-123")
        assert generator.run_id == "custom-run-id-123"


class TestSpaceOperations:
    """Tests for space creation operations."""

    @responses.activate
    def test_get_space_success(self):
        """Test getting a space successfully."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/spaces",
            json={"results": [{"key": "TEST1", "id": "10001", "name": "Test Space 1"}]},
            status=200,
        )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        space = generator.get_space("TEST1")

        assert space is not None
        assert space["key"] == "TEST1"
        assert space["id"] == "10001"
        assert space["name"] == "Test Space 1"

    @responses.activate
    def test_get_space_not_found(self):
        """Test getting a space that doesn't exist."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/spaces",
            json={"results": []},
            status=200,
        )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        space = generator.get_space("NOTFOUND")
        assert space is None

    def test_get_space_dry_run(self):
        """Test getting a space in dry run mode."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        space = generator.get_space("TEST1")

        assert space is not None
        assert space["key"] == "TEST1"
        assert "dry-run" in space["id"]

    @responses.activate
    def test_create_space_success(self):
        """Test creating a space successfully."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/spaces",
            json={"key": "TEST1", "id": "10001", "name": "Test Space 1"},
            status=200,
        )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        space = generator.create_space("TEST1", "Test Space 1", "A test space")

        assert space is not None
        assert space["key"] == "TEST1"
        assert space["id"] == "10001"

    @responses.activate
    def test_create_space_already_exists(self):
        """Test creating a space that already exists."""
        # First call fails (space exists)
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/spaces",
            json={"message": "Space already exists"},
            status=409,
        )
        # Get space call succeeds (uses query param now)
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/spaces",
            json={"results": [{"key": "TEST1", "id": "10001", "name": "Existing Space"}]},
            status=200,
        )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        space = generator.create_space("TEST1", "Test Space 1")

        assert space is not None
        assert space["key"] == "TEST1"
        assert space["id"] == "10001"

    def test_create_space_dry_run(self):
        """Test creating a space in dry run mode."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        space = generator.create_space("TEST1", "Test Space 1", "A test space")

        assert space is not None
        assert space["key"] == "TEST1"
        assert "dry-run" in space["id"]
        assert space["name"] == "Test Space 1"

    @responses.activate
    def test_create_spaces_multiple(self):
        """Test creating multiple spaces."""
        for i in range(3):
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/api/v2/spaces",
                json={"key": f"TESTDA{i + 1}", "id": f"1000{i + 1}", "name": f"Test Space {i + 1}"},
                status=200,
            )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            spaces = generator.create_spaces(3)

        assert len(spaces) == 3
        assert generator.created_spaces == spaces
        assert spaces[0]["key"] == "TESTDA1"
        assert spaces[1]["key"] == "TESTDA2"
        assert spaces[2]["key"] == "TESTDA3"

    def test_create_spaces_dry_run(self):
        """Test creating multiple spaces in dry run mode."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        with patch("time.sleep"):
            spaces = generator.create_spaces(3)

        assert len(spaces) == 3
        for space in spaces:
            assert "dry-run" in space["id"]


class TestSpaceLabels:
    """Tests for space label operations."""

    @responses.activate
    def test_add_space_label_success(self):
        """Test adding a label to a space."""
        # Uses legacy API: POST /rest/api/space/{key}/label
        responses.add(
            responses.POST,
            "https://test.atlassian.net/wiki/rest/api/space/TEST1/label",
            json=[{"name": "test-label", "prefix": "global"}],
            status=200,
        )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.add_space_label("TEST1", "Test Label")
        assert result is True

    @responses.activate
    def test_add_space_label_normalizes_label(self):
        """Test that labels are normalized to lowercase with hyphens."""
        responses.add(
            responses.POST,
            "https://test.atlassian.net/wiki/rest/api/space/TEST1/label",
            json=[{"name": "my-test-label", "prefix": "global"}],
            status=200,
        )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.add_space_label("TEST1", "My Test Label")
        assert result is True

    def test_add_space_label_dry_run(self):
        """Test adding a label in dry run mode."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = generator.add_space_label("TEST1", "test-label")
        assert result is True

    @responses.activate
    def test_add_space_labels_multiple(self):
        """Test adding multiple labels to spaces."""
        for i in range(5):
            responses.add(
                responses.POST,
                "https://test.atlassian.net/wiki/rest/api/space/TEST1/label",
                json=[{"name": f"label-{i}", "prefix": "global"}],
                status=200,
            )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            count = generator.add_space_labels(["TEST1"], 5)

        assert count == 5

    def test_add_space_labels_empty_list(self):
        """Test adding labels with empty space list."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = generator.add_space_labels([], 5)
        assert count == 0


class TestSpaceCategories:
    """Tests for space category operations.

    Note: Categories are implemented as team-prefixed labels via legacy API.
    We create both regular labels and categories for backup compatibility.
    """

    @responses.activate
    def test_add_space_category_success(self):
        """Test adding a category to a space."""
        # Categories use legacy API with "team" prefix
        responses.add(
            responses.POST,
            "https://test.atlassian.net/wiki/rest/api/space/TEST1/label",
            json=[{"name": "test-category", "prefix": "team"}],
            status=200,
        )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.add_space_category("TEST1", "Test Category")
        assert result is True

    def test_add_space_category_dry_run(self):
        """Test adding a category in dry run mode."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = generator.add_space_category("TEST1", "Test Category")
        assert result is True

    @responses.activate
    def test_add_space_categories_multiple(self):
        """Test adding multiple categories to spaces."""
        for _ in range(5):
            responses.add(
                responses.POST,
                "https://test.atlassian.net/wiki/rest/api/space/TEST1/label",
                json=[{"name": "category", "prefix": "team"}],
                status=200,
            )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            count = generator.add_space_categories(["TEST1"], 5)

        assert count == 5

    def test_add_space_categories_empty_list(self):
        """Test adding categories with empty space list."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = generator.add_space_categories([], 5)
        assert count == 0


class TestSpaceProperties:
    """Tests for space property operations."""

    @responses.activate
    def test_set_space_property_success(self):
        """Test setting a space property."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/spaces/10001/properties",
            json={"key": "test_prop", "value": {"test": "value"}},
            status=200,
        )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.set_space_property("10001", "test_prop", {"test": "value"})
        assert result is True

    def test_set_space_property_dry_run(self):
        """Test setting a property in dry run mode."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = generator.set_space_property("10001", "test_prop", {"test": "value"})
        assert result is True

    @responses.activate
    def test_set_space_properties_multiple(self):
        """Test setting multiple properties on spaces."""
        for i in range(5):
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/api/v2/spaces/10001/properties",
                json={"key": f"prop_{i}", "value": {}},
                status=200,
            )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            count = generator.set_space_properties(["10001"], 5)

        assert count == 5

    def test_set_space_properties_empty_list(self):
        """Test setting properties with empty space list."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = generator.set_space_properties([], 5)
        assert count == 0


class TestSpacePermissions:
    """Tests for space permission operations.

    Uses v2 role-assignment API: POST /api/v2/spaces/{id}/role-assignments
    """

    @responses.activate
    def test_get_space_roles(self):
        """Test fetching available space roles."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/space-roles",
            json={
                "results": [
                    {"id": "role-1", "name": "Collaborator"},
                    {"id": "role-2", "name": "Viewer"},
                ]
            },
            status=200,
        )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        roles = generator.get_space_roles()
        assert len(roles) == 2
        assert roles[0]["name"] == "Collaborator"

    def test_get_space_roles_dry_run(self):
        """Test fetching roles in dry run mode returns defaults."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        roles = generator.get_space_roles()
        assert len(roles) == 5
        assert roles[0]["name"] == "Collaborator"

    @responses.activate
    def test_add_space_role_assignment_success(self):
        """Test assigning a role to a user in a space."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/api/v2/spaces/10001/role-assignments",
            json={
                "results": [
                    {
                        "roleId": "role-1",
                        "principal": {"principalType": "USER", "principalId": "user-123"},
                    }
                ]
            },
            status=200,
        )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.add_space_role_assignment("10001", "role-1", "user-123")
        assert result is True

    def test_add_space_role_assignment_dry_run(self):
        """Test role assignment in dry run mode."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = generator.add_space_role_assignment("10001", "role-1", "user-123")
        assert result is True

    @responses.activate
    def test_add_space_permissions_multiple(self):
        """Test adding multiple role assignments across spaces and users."""
        # Mock get_space_roles
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/space-roles",
            json={
                "results": [
                    {"id": "role-1", "name": "Collaborator"},
                    {"id": "role-2", "name": "Viewer"},
                ]
            },
            status=200,
        )
        # Mock role assignment calls for 2 spaces
        for _ in range(10):
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/api/v2/spaces/10001/role-assignments",
                json={"results": [{"roleId": "role-1"}]},
                status=200,
            )
            responses.add(
                responses.POST,
                f"{CONFLUENCE_URL}/api/v2/spaces/10002/role-assignments",
                json={"results": [{"roleId": "role-1"}]},
                status=200,
            )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            count = generator.add_space_permissions(
                space_ids=["10001", "10002"],
                user_account_ids=["user-1", "user-2"],
                count=6,
            )

        assert count == 6

    def test_add_space_permissions_empty_lists(self):
        """Test adding permissions with empty lists."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = generator.add_space_permissions([], ["user-1"], 5)
        assert count == 0

        count = generator.add_space_permissions(["10001"], [], 5)
        assert count == 0


class TestSpaceLookAndFeel:
    """Tests for space look and feel operations."""

    @responses.activate
    def test_set_space_look_and_feel_success(self):
        """Test setting space look and feel."""
        responses.add(
            responses.PUT,
            f"{CONFLUENCE_URL}/rest/api/settings/lookandfeel/custom",
            json={"spaceKey": "TEST1"},
            status=200,
        )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        result = generator.set_space_look_and_feel("TEST1")
        assert result is True

    def test_set_space_look_and_feel_dry_run(self):
        """Test setting look and feel in dry run mode."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = generator.set_space_look_and_feel("TEST1")
        assert result is True

    @responses.activate
    def test_set_space_look_and_feel_custom_settings(self):
        """Test setting custom look and feel settings."""
        responses.add(
            responses.PUT,
            f"{CONFLUENCE_URL}/rest/api/settings/lookandfeel/custom",
            json={"spaceKey": "TEST1"},
            status=200,
        )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        custom_settings = {
            "spaceKey": "TEST1",
            "headings": {"color": "#FF0000"},
        }

        result = generator.set_space_look_and_feel("TEST1", custom_settings)
        assert result is True

    @responses.activate
    def test_set_space_look_and_feel_multiple(self):
        """Test setting look and feel for multiple spaces."""
        for _ in range(3):
            responses.add(
                responses.PUT,
                f"{CONFLUENCE_URL}/rest/api/settings/lookandfeel/custom",
                json={},
                status=200,
            )

        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with patch("time.sleep"):
            count = generator.set_space_look_and_feel_multiple(
                space_keys=["TEST1", "TEST2", "TEST3"],
                count=3,
            )

        assert count == 3

    def test_set_space_look_and_feel_empty_list(self):
        """Test setting look and feel with empty space list."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = generator.set_space_look_and_feel_multiple([], 5)
        assert count == 0


class TestAsyncSpaceOperations:
    """Tests for async space operations."""

    @pytest.mark.asyncio
    async def test_create_space_async_success(self):
        """Test creating a space asynchronously."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/api/v2/spaces",
                payload={"key": "TEST1", "id": "10001", "name": "Test Space 1"},
                status=200,
            )

            space = await generator.create_space_async("TEST1", "Test Space 1")

            assert space is not None
            assert space["key"] == "TEST1"
            assert space["id"] == "10001"

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_create_space_async_dry_run(self):
        """Test creating a space asynchronously in dry run mode."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        space = await generator.create_space_async("TEST1", "Test Space 1")

        assert space is not None
        assert space["key"] == "TEST1"
        assert "dry-run" in space["id"]

    @pytest.mark.asyncio
    async def test_create_spaces_async_multiple(self):
        """Test creating multiple spaces asynchronously."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for i in range(3):
                m.post(
                    f"{CONFLUENCE_URL}/api/v2/spaces",
                    payload={"key": f"TESTDA{i + 1}", "id": f"1000{i + 1}", "name": f"Test Space {i + 1}"},
                    status=200,
                )

            spaces = await generator.create_spaces_async(3)

            assert len(spaces) == 3
            assert generator.created_spaces == spaces

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_add_space_label_async_success(self):
        """Test adding a label asynchronously."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            # Uses legacy API
            m.post(
                "https://test.atlassian.net/wiki/rest/api/space/TEST1/label",
                payload=[{"name": "test-label", "prefix": "global"}],
                status=200,
            )

            result = await generator.add_space_label_async("TEST1", "test-label")
            assert result is True

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_add_space_labels_async_multiple(self):
        """Test adding multiple labels asynchronously."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for _ in range(5):
                # Uses legacy API
                m.post(
                    "https://test.atlassian.net/wiki/rest/api/space/TEST1/label",
                    payload=[{"name": "label", "prefix": "global"}],
                    status=200,
                )

            count = await generator.add_space_labels_async(["TEST1"], 5)
            assert count == 5

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_set_space_property_async_success(self):
        """Test setting a property asynchronously."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/api/v2/spaces/10001/properties",
                payload={"key": "test_prop", "value": {}},
                status=200,
            )

            result = await generator.set_space_property_async("10001", "test_prop", {"test": "value"})
            assert result is True

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_set_space_properties_async_multiple(self):
        """Test setting multiple properties asynchronously."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for _ in range(5):
                m.post(
                    f"{CONFLUENCE_URL}/api/v2/spaces/10001/properties",
                    payload={"key": "prop", "value": {}},
                    status=200,
                )

            count = await generator.set_space_properties_async(["10001"], 5)
            assert count == 5

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_add_space_role_assignment_async_success(self):
        """Test assigning a role to a user in a space asynchronously."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            m.post(
                f"{CONFLUENCE_URL}/api/v2/spaces/10001/role-assignments",
                payload={"results": [{"roleId": "role-1"}]},
                status=200,
            )

            result = await generator.add_space_role_assignment_async("10001", "role-1", "user-123")
            assert result is True

        await generator._close_async_session()

    @responses.activate
    @pytest.mark.asyncio
    async def test_add_space_permissions_async_multiple(self):
        """Test adding multiple role assignments asynchronously."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        # Mock get_space_roles (sync call within async method)
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/api/v2/space-roles",
            json={
                "results": [
                    {"id": "role-1", "name": "Collaborator"},
                    {"id": "role-2", "name": "Viewer"},
                ]
            },
            status=200,
        )

        with aioresponses() as m:
            for _ in range(10):
                m.post(
                    f"{CONFLUENCE_URL}/api/v2/spaces/10001/role-assignments",
                    payload={"results": [{"roleId": "role-1"}]},
                    status=200,
                )
                m.post(
                    f"{CONFLUENCE_URL}/api/v2/spaces/10002/role-assignments",
                    payload={"results": [{"roleId": "role-1"}]},
                    status=200,
                )

            count = await generator.add_space_permissions_async(
                space_ids=["10001", "10002"],
                user_account_ids=["user-1", "user-2"],
                count=6,
            )
            assert count == 6

        await generator._close_async_session()


class TestAsyncSpaceCategories:
    """Tests for async space category operations."""

    @pytest.mark.asyncio
    async def test_add_space_category_async_success(self):
        """Test adding a category asynchronously."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            # Categories use legacy API with team prefix
            m.post(
                "https://test.atlassian.net/wiki/rest/api/space/TEST1/label",
                payload=[{"name": "test-category", "prefix": "team"}],
                status=200,
            )

            result = await generator.add_space_category_async("TEST1", "Test Category")
            assert result is True

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_add_space_categories_async_multiple(self):
        """Test adding multiple categories asynchronously."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        with aioresponses() as m:
            for _ in range(5):
                m.post(
                    "https://test.atlassian.net/wiki/rest/api/space/TEST1/label",
                    payload=[{"name": "category", "prefix": "team"}],
                    status=200,
                )

            count = await generator.add_space_categories_async(["TEST1"], 5)
            assert count == 5

        await generator._close_async_session()

    @pytest.mark.asyncio
    async def test_add_space_category_async_dry_run(self):
        """Test adding a category asynchronously in dry run mode."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = await generator.add_space_category_async("TEST1", "Test Category")
        assert result is True

    @pytest.mark.asyncio
    async def test_add_space_categories_async_empty_list(self):
        """Test adding categories with empty space list."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = await generator.add_space_categories_async([], 5)
        assert count == 0


class TestAsyncDryRun:
    """Tests for async operations in dry run mode."""

    @pytest.mark.asyncio
    async def test_add_space_label_async_dry_run(self):
        """Test adding a label asynchronously in dry run mode."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = await generator.add_space_label_async("TEST1", "test-label")
        assert result is True

    @pytest.mark.asyncio
    async def test_set_space_property_async_dry_run(self):
        """Test setting a property asynchronously in dry run mode."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = await generator.set_space_property_async("10001", "test_prop", {"test": "value"})
        assert result is True

    @pytest.mark.asyncio
    async def test_add_space_role_assignment_async_dry_run(self):
        """Test role assignment asynchronously in dry run mode."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
            dry_run=True,
        )

        result = await generator.add_space_role_assignment_async("10001", "role-1", "user-123")
        assert result is True

    @pytest.mark.asyncio
    async def test_add_space_labels_async_empty_list(self):
        """Test adding labels with empty space list."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = await generator.add_space_labels_async([], 5)
        assert count == 0

    @pytest.mark.asyncio
    async def test_set_space_properties_async_empty_list(self):
        """Test setting properties with empty space list."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = await generator.set_space_properties_async([], 5)
        assert count == 0

    @pytest.mark.asyncio
    async def test_add_space_permissions_async_empty_lists(self):
        """Test adding permissions with empty lists."""
        generator = SpaceGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            prefix=TEST_PREFIX,
        )

        count = await generator.add_space_permissions_async([], ["user-1"], 5)
        assert count == 0

        count = await generator.add_space_permissions_async(["10001"], [], 5)
        assert count == 0
