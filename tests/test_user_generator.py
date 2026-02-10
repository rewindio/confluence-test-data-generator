"""
Tests for confluence_user_generator.py
"""

from unittest.mock import patch

import pytest
import responses

from confluence_user_generator import ConfluenceUserGenerator, main

# ========== Constants ==========

CONFLUENCE_URL = "https://test.atlassian.net"
TEST_EMAIL = "admin@example.com"
TEST_TOKEN = "test-api-token"
BASE_EMAIL = "user@example.com"


# ========== Fixtures ==========


@pytest.fixture
def generator():
    """Create a test generator instance."""
    return ConfluenceUserGenerator(
        confluence_url=CONFLUENCE_URL,
        email=TEST_EMAIL,
        api_token=TEST_TOKEN,
        dry_run=False,
    )


@pytest.fixture
def dry_run_generator():
    """Create a dry-run generator instance."""
    return ConfluenceUserGenerator(
        confluence_url=CONFLUENCE_URL,
        email=TEST_EMAIL,
        api_token=TEST_TOKEN,
        dry_run=True,
    )


# ========== URL Handling Tests ==========


class TestURLHandling:
    """Tests for URL normalization."""

    def test_strips_trailing_slash(self):
        """URL trailing slash is removed."""
        gen = ConfluenceUserGenerator(
            confluence_url="https://test.atlassian.net/",
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
        )
        assert gen.confluence_url == "https://test.atlassian.net"

    def test_removes_wiki_suffix(self):
        """URL /wiki suffix is removed."""
        gen = ConfluenceUserGenerator(
            confluence_url="https://test.atlassian.net/wiki",
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
        )
        assert gen.confluence_url == "https://test.atlassian.net"

    def test_removes_wiki_suffix_with_trailing_slash(self):
        """URL /wiki/ suffix is removed."""
        gen = ConfluenceUserGenerator(
            confluence_url="https://test.atlassian.net/wiki/",
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
        )
        assert gen.confluence_url == "https://test.atlassian.net"

    def test_extracts_site_name(self):
        """Site name is extracted from Atlassian Cloud URL."""
        gen = ConfluenceUserGenerator(
            confluence_url="https://mycompany.atlassian.net",
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
        )
        assert gen.site_name == "mycompany"

    def test_extracts_site_name_with_hyphens(self):
        """Site name with hyphens is extracted correctly."""
        gen = ConfluenceUserGenerator(
            confluence_url="https://my-test-instance.atlassian.net",
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
        )
        assert gen.site_name == "my-test-instance"

    def test_default_confluence_users_group(self):
        """Confluence users group is auto-detected from site name."""
        gen = ConfluenceUserGenerator(
            confluence_url="https://mycompany.atlassian.net",
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
        )
        assert gen.confluence_users_group == "confluence-users-mycompany"

    def test_custom_confluence_users_group(self):
        """Custom confluence users group can be specified."""
        gen = ConfluenceUserGenerator(
            confluence_url="https://mycompany.atlassian.net",
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            confluence_users_group="custom-group",
        )
        assert gen.confluence_users_group == "custom-group"


# ========== Email Parsing Tests ==========


class TestEmailParsing:
    """Tests for email parsing functionality."""

    def test_parse_simple_email(self, generator):
        """Simple email is parsed correctly."""
        prefix, domain = generator.parse_email("user@example.com")
        assert prefix == "user"
        assert domain == "example.com"

    def test_parse_email_with_plus(self, generator):
        """Email with + is parsed correctly."""
        prefix, domain = generator.parse_email("user+tag@example.com")
        assert prefix == "user"
        assert domain == "example.com"

    def test_parse_email_invalid(self, generator):
        """Invalid email raises ValueError."""
        with pytest.raises(ValueError, match="Invalid email format"):
            generator.parse_email("not-an-email")

    def test_parse_email_empty_local_part(self, generator):
        """Email with empty local part raises ValueError."""
        with pytest.raises(ValueError, match="Invalid email format"):
            generator.parse_email("@example.com")

    def test_parse_email_empty_domain(self, generator):
        """Email with empty domain raises ValueError."""
        with pytest.raises(ValueError, match="Invalid email format"):
            generator.parse_email("user@")

    def test_parse_email_whitespace_only(self, generator):
        """Email with whitespace-only parts raises ValueError."""
        with pytest.raises(ValueError, match="Invalid email format"):
            generator.parse_email("  @  ")

    def test_generate_sandbox_email(self, generator):
        """Sandbox email is generated correctly with default suffix."""
        email = generator.generate_sandbox_email("user@example.com", 1)
        assert email == "user+confluence1@example.com"

    def test_generate_sandbox_email_from_plus_email(self, generator):
        """Sandbox email from existing + email."""
        email = generator.generate_sandbox_email("user+existing@example.com", 5)
        assert email == "user+confluence5@example.com"

    def test_generate_sandbox_email_custom_suffix(self):
        """Sandbox email with custom suffix."""
        gen = ConfluenceUserGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
            email_suffix="custom",
        )
        email = gen.generate_sandbox_email("user@example.com", 3)
        assert email == "user+custom3@example.com"


# ========== Session Tests ==========


class TestSession:
    """Tests for session creation."""

    def test_session_created(self, generator):
        """Session is created with retry logic."""
        assert generator.session is not None
        # Check adapters are mounted
        assert "http://" in generator.session.adapters
        assert "https://" in generator.session.adapters


# ========== Dry Run Tests ==========


class TestDryRun:
    """Tests for dry-run mode."""

    def test_dry_run_create_user(self, dry_run_generator):
        """Dry run returns mock user without API call."""
        result = dry_run_generator.create_user("test@example.com", "Test User")
        assert result is not None
        assert result["email"] == "test@example.com"
        assert result["displayName"] == "Test User"
        assert len(dry_run_generator.created_users) == 1
        assert dry_run_generator.created_users[0]["status"] == "dry_run"

    def test_dry_run_check_user_exists(self, dry_run_generator):
        """Dry run check_user_exists returns None."""
        result = dry_run_generator.check_user_exists("test@example.com")
        assert result is None

    def test_dry_run_create_group(self, dry_run_generator):
        """Dry run returns mock group without API call."""
        result = dry_run_generator.create_group("Test Group")
        assert result is not None
        assert result["name"] == "Test Group"
        assert len(dry_run_generator.created_groups) == 1
        assert dry_run_generator.created_groups[0]["status"] == "dry_run"

    def test_dry_run_check_group_exists(self, dry_run_generator):
        """Dry run check_group_exists returns None."""
        result = dry_run_generator.check_group_exists("Test Group")
        assert result is None

    def test_dry_run_add_user_to_group(self, dry_run_generator):
        """Dry run add_user_to_group returns True."""
        result = dry_run_generator.add_user_to_group("account123", "Test Group")
        assert result is True


# ========== API Call Tests ==========


class TestAPICall:
    """Tests for API call functionality."""

    @responses.activate
    def test_api_call_success_v1(self, generator):
        """API call v1 succeeds."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/wiki/rest/api/test",
            json={"result": "success"},
            status=200,
        )
        response = generator._api_call("GET", "test", api_version="v1")
        assert response is not None
        assert response.json() == {"result": "success"}

    @responses.activate
    def test_api_call_success_v2(self, generator):
        """API call v2 succeeds."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/wiki/api/v2/test",
            json={"result": "success"},
            status=200,
        )
        response = generator._api_call("GET", "test", api_version="v2")
        assert response is not None
        assert response.json() == {"result": "success"}

    @responses.activate
    def test_api_call_rate_limited(self, generator):
        """API call handles 429 rate limit."""
        # First call: rate limited
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/wiki/rest/api/test",
            status=429,
            headers={"Retry-After": "0.1"},
        )
        # Second call: success
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/wiki/rest/api/test",
            json={"result": "success"},
            status=200,
        )
        response = generator._api_call("GET", "test")
        assert response is not None
        assert response.json() == {"result": "success"}

    def test_api_call_dry_run(self, dry_run_generator):
        """API call in dry run mode returns None."""
        result = dry_run_generator._api_call("GET", "test")
        assert result is None


# ========== Admin API Call Tests ==========


class TestAdminAPICall:
    """Tests for Admin API call functionality."""

    @responses.activate
    def test_admin_api_call_success(self, generator):
        """Admin API call succeeds."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/3/user",
            json={"accountId": "abc123"},
            status=200,
        )
        response = generator._admin_api_call("POST", "user", data={"email": "test@example.com"})
        assert response is not None
        assert response.json()["accountId"] == "abc123"

    @responses.activate
    def test_admin_api_call_rate_limited(self, generator):
        """Admin API call handles 429 rate limit."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/3/user",
            status=429,
            headers={"Retry-After": "0.1"},
        )
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/3/user",
            json={"accountId": "abc123"},
            status=200,
        )
        response = generator._admin_api_call("POST", "user", data={})
        assert response is not None

    def test_admin_api_call_dry_run(self, dry_run_generator):
        """Admin API call in dry run mode returns None."""
        result = dry_run_generator._admin_api_call("POST", "user", data={})
        assert result is None


# ========== User Creation Tests ==========


class TestUserCreation:
    """Tests for user creation functionality."""

    @responses.activate
    def test_check_user_exists_found(self, generator):
        """Check user exists returns user when found."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/rest/api/3/user/search",
            json=[{"emailAddress": "test@example.com", "accountId": "abc123"}],
            status=200,
        )
        result = generator.check_user_exists("test@example.com")
        assert result is not None
        assert result["emailAddress"] == "test@example.com"

    @responses.activate
    def test_check_user_exists_not_found(self, generator):
        """Check user exists returns None when not found."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/rest/api/3/user/search",
            json=[],
            status=200,
        )
        result = generator.check_user_exists("test@example.com")
        assert result is None

    @responses.activate
    def test_create_user_new(self, generator):
        """Create user invites new user and adds to confluence-users group."""
        # User doesn't exist
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/rest/api/3/user/search",
            json=[],
            status=200,
        )
        # Invite user
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/3/user",
            json={"accountId": "abc123", "displayName": "Test User"},
            status=200,
        )
        # Add user to confluence-users group for Confluence access (uses Admin API)
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/3/group/user",
            json={},
            status=200,
        )

        result = generator.create_user("test@example.com", "Test User")
        assert result is not None
        assert result["accountId"] == "abc123"
        assert len(generator.created_users) == 1
        assert generator.created_users[0]["status"] == "invited"

    @responses.activate
    def test_create_user_already_exists(self, generator):
        """Create user returns existing user."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/rest/api/3/user/search",
            json=[{"emailAddress": "test@example.com", "accountId": "abc123", "displayName": "Existing"}],
            status=200,
        )

        result = generator.create_user("test@example.com", "Test User")
        assert result is not None
        assert result["accountId"] == "abc123"
        assert len(generator.existing_users) == 1
        assert generator.existing_users[0]["status"] == "exists"


# ========== Group Creation Tests ==========


class TestGroupCreation:
    """Tests for group creation functionality."""

    @responses.activate
    def test_check_group_exists_found(self, generator):
        """Check group exists returns group when found."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/wiki/rest/api/group",
            json={"name": "Test Group", "id": "group123"},
            status=200,
        )
        result = generator.check_group_exists("Test Group")
        assert result is not None
        assert result["name"] == "Test Group"

    @responses.activate
    def test_check_group_exists_not_found(self, generator):
        """Check group exists returns None when not found."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/wiki/rest/api/group",
            status=404,
        )
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/wiki/rest/api/group",
            json={"results": []},
            status=200,
        )
        result = generator.check_group_exists("Nonexistent Group")
        assert result is None

    @responses.activate
    def test_create_group_new(self, generator):
        """Create group creates new group."""
        # Group doesn't exist
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/wiki/rest/api/group",
            status=404,
        )
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/wiki/rest/api/group",
            json={"results": []},
            status=200,
        )
        # Create group
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/wiki/rest/api/group",
            json={"name": "New Group", "id": "group456"},
            status=200,
        )

        result = generator.create_group("New Group")
        assert result is not None
        assert result["name"] == "New Group"
        assert len(generator.created_groups) == 1
        assert generator.created_groups[0]["status"] == "created"

    @responses.activate
    def test_create_group_already_exists(self, generator):
        """Create group returns existing group."""
        responses.add(
            responses.GET,
            f"{CONFLUENCE_URL}/wiki/rest/api/group",
            json={"name": "Existing Group", "id": "group789"},
            status=200,
        )

        result = generator.create_group("Existing Group")
        assert result is not None
        assert result["id"] == "group789"
        assert len(generator.existing_groups) == 1
        assert generator.existing_groups[0]["status"] == "exists"


# ========== Add User to Group Tests ==========


class TestAddUserToGroup:
    """Tests for adding users to groups."""

    @responses.activate
    def test_add_user_to_group_success(self, generator):
        """Add user to group succeeds (uses Admin API)."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/3/group/user",
            json={},
            status=200,
        )
        result = generator.add_user_to_group("account123", "Test Group")
        assert result is True

    @responses.activate
    def test_add_user_to_group_failure(self, generator):
        """Add user to group fails gracefully."""
        responses.add(
            responses.POST,
            f"{CONFLUENCE_URL}/rest/api/3/group/user",
            status=404,
        )
        result = generator.add_user_to_group("account123", "Nonexistent Group")
        assert result is False


# ========== Batch Generation Tests ==========


class TestBatchGeneration:
    """Tests for batch user/group generation."""

    def test_generate_users_dry_run(self, dry_run_generator):
        """Generate users in dry run mode."""
        users = dry_run_generator.generate_users(BASE_EMAIL, 3, prefix="Test")
        assert len(users) == 3
        assert len(dry_run_generator.created_users) == 3
        for i, user in enumerate(dry_run_generator.created_users, 1):
            assert user["email"] == f"user+confluence{i}@example.com"
            assert user["displayName"] == f"Test User {i}"
            assert user["status"] == "dry_run"

    def test_generate_groups_dry_run(self, dry_run_generator):
        """Generate groups in dry run mode."""
        group_names = ["Group A", "Group B"]
        groups = dry_run_generator.generate_groups(group_names)
        assert len(groups) == 2
        assert len(dry_run_generator.created_groups) == 2

    def test_generate_all_dry_run(self, dry_run_generator, caplog):
        """Generate all in dry run mode."""
        import logging

        caplog.set_level(logging.INFO)

        dry_run_generator.generate_all(
            base_email=BASE_EMAIL,
            user_count=2,
            group_names=["Test Group"],
            user_prefix="TestUser",
        )

        assert len(dry_run_generator.created_users) == 2
        assert len(dry_run_generator.created_groups) == 1
        assert "Generation complete!" in caplog.text


# ========== Default Values Tests ==========


class TestDefaults:
    """Tests for default values."""

    def test_default_dry_run(self):
        """Default dry_run is False."""
        gen = ConfluenceUserGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
        )
        assert gen.dry_run is False

    def test_default_email_suffix(self):
        """Default email_suffix is 'confluence'."""
        gen = ConfluenceUserGenerator(
            confluence_url=CONFLUENCE_URL,
            email=TEST_EMAIL,
            api_token=TEST_TOKEN,
        )
        assert gen.email_suffix == "confluence"

    def test_empty_tracking_lists(self, generator):
        """Tracking lists start empty."""
        assert generator.created_users == []
        assert generator.created_groups == []
        assert generator.existing_users == []
        assert generator.existing_groups == []


# ========== CLI Tests ==========


class TestCLI:
    """Tests for CLI functionality."""

    def test_main_missing_token(self, monkeypatch, capsys):
        """Main exits with error when token is missing."""
        monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)
        # Prevent load_dotenv from loading .env file
        monkeypatch.setattr("confluence_user_generator.load_dotenv", lambda: None)
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--url", CONFLUENCE_URL, "--email", TEST_EMAIL, "--base-email", BASE_EMAIL, "--users", "1"],
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "API token required" in captured.err

    def test_main_zero_users(self, monkeypatch, capsys):
        """Main exits with error when user count is zero."""
        monkeypatch.setenv("CONFLUENCE_API_TOKEN", TEST_TOKEN)
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--url", CONFLUENCE_URL, "--email", TEST_EMAIL, "--base-email", BASE_EMAIL, "--users", "0"],
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "must be a positive integer" in captured.err

    def test_main_negative_users(self, monkeypatch, capsys):
        """Main exits with error when user count is negative."""
        monkeypatch.setenv("CONFLUENCE_API_TOKEN", TEST_TOKEN)
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--url", CONFLUENCE_URL, "--email", TEST_EMAIL, "--base-email", BASE_EMAIL, "--users", "-5"],
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "must be a positive integer" in captured.err

    def test_main_dry_run(self, monkeypatch, capsys):
        """Main runs in dry-run mode."""
        monkeypatch.setenv("CONFLUENCE_API_TOKEN", TEST_TOKEN)
        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "--url",
                CONFLUENCE_URL,
                "--email",
                TEST_EMAIL,
                "--base-email",
                BASE_EMAIL,
                "--users",
                "2",
                "--dry-run",
            ],
        )

        # Should complete without error
        main()

    def test_main_with_groups(self, monkeypatch):
        """Main runs with groups specified."""
        monkeypatch.setenv("CONFLUENCE_API_TOKEN", TEST_TOKEN)
        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "--url",
                CONFLUENCE_URL,
                "--email",
                TEST_EMAIL,
                "--base-email",
                BASE_EMAIL,
                "--users",
                "1",
                "--groups",
                "Group1",
                "Group2",
                "--dry-run",
            ],
        )

        main()

    def test_main_keyboard_interrupt(self, monkeypatch, capsys):
        """Main handles keyboard interrupt gracefully."""
        monkeypatch.setenv("CONFLUENCE_API_TOKEN", TEST_TOKEN)
        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "--url",
                CONFLUENCE_URL,
                "--email",
                TEST_EMAIL,
                "--base-email",
                BASE_EMAIL,
                "--users",
                "1",
            ],
        )

        # Mock generate_all to raise KeyboardInterrupt
        with patch.object(ConfluenceUserGenerator, "generate_all", side_effect=KeyboardInterrupt):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "Interrupted" in captured.err
