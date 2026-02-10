"""Tests for the cleanup_spaces() function."""

from unittest.mock import patch

import responses

from confluence_data_generator import cleanup_spaces
from tests.conftest import CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN

V2_SPACES_URL = f"{CONFLUENCE_URL}/api/v2/spaces"


def _make_spaces_response(spaces, next_cursor=None):
    """Build a v2 spaces API response."""
    result = {"results": spaces, "_links": {}}
    if next_cursor:
        result["_links"]["next"] = f"/api/v2/spaces?limit=250&cursor={next_cursor}"
    return result


def _make_space(key, name, space_id):
    return {"key": key, "name": name, "id": space_id}


# ========== Discovery Tests ==========


class TestCleanupDiscovery:
    @responses.activate
    def test_discovers_matching_spaces(self):
        """Finds spaces whose key starts with the prefix's first 6 chars."""
        spaces = [
            _make_space("TESTDA1", "Test Space 1", "10001"),
            _make_space("TESTDA2", "Test Space 2", "10002"),
        ]
        responses.get(V2_SPACES_URL, json=_make_spaces_response(spaces))

        # Add delete stubs so cleanup can proceed
        responses.delete(f"{CONFLUENCE_URL}/rest/api/space/TESTDA1", status=202)
        responses.delete(f"{CONFLUENCE_URL}/rest/api/space/TESTDA2", status=202)

        deleted = cleanup_spaces(CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN, "TESTDATA", skip_confirm=True)
        assert deleted == 2

    @responses.activate
    def test_ignores_non_matching_spaces(self):
        """Spaces that don't match the prefix are not deleted."""
        spaces = [
            _make_space("TESTDA1", "Test Space 1", "10001"),
            _make_space("OTHER1", "Other Space", "20001"),
        ]
        responses.get(V2_SPACES_URL, json=_make_spaces_response(spaces))
        responses.delete(f"{CONFLUENCE_URL}/rest/api/space/TESTDA1", status=202)

        deleted = cleanup_spaces(CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN, "TESTDATA", skip_confirm=True)
        assert deleted == 1

    @responses.activate
    def test_no_matching_spaces(self):
        """Gracefully returns 0 when no spaces match."""
        spaces = [_make_space("OTHER1", "Other Space", "20001")]
        responses.get(V2_SPACES_URL, json=_make_spaces_response(spaces))

        deleted = cleanup_spaces(CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN, "TESTDATA", skip_confirm=True)
        assert deleted == 0

    @responses.activate
    def test_empty_instance(self):
        """Handles empty instance with no spaces."""
        responses.get(V2_SPACES_URL, json=_make_spaces_response([]))

        deleted = cleanup_spaces(CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN, "TESTDATA", skip_confirm=True)
        assert deleted == 0

    @responses.activate
    def test_pagination(self):
        """Follows pagination to find all matching spaces."""
        page1_spaces = [_make_space("TESTDA1", "Test Space 1", "10001")]
        page2_spaces = [_make_space("TESTDA2", "Test Space 2", "10002")]

        responses.get(V2_SPACES_URL, json=_make_spaces_response(page1_spaces, next_cursor="abc123"))
        responses.get(V2_SPACES_URL, json=_make_spaces_response(page2_spaces))

        responses.delete(f"{CONFLUENCE_URL}/rest/api/space/TESTDA1", status=202)
        responses.delete(f"{CONFLUENCE_URL}/rest/api/space/TESTDA2", status=202)

        deleted = cleanup_spaces(CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN, "TESTDATA", skip_confirm=True)
        assert deleted == 2

    @responses.activate
    def test_api_error_on_list(self):
        """Returns 0 when space listing fails."""
        responses.get(V2_SPACES_URL, status=500, body="Internal Server Error")

        deleted = cleanup_spaces(CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN, "TESTDATA", skip_confirm=True)
        assert deleted == 0

    @responses.activate
    def test_prefix_truncated_to_six_chars(self):
        """Long prefixes are truncated to 6 chars for key matching."""
        spaces = [_make_space("MYLONG1", "Space 1", "10001")]
        responses.get(V2_SPACES_URL, json=_make_spaces_response(spaces))
        responses.delete(f"{CONFLUENCE_URL}/rest/api/space/MYLONG1", status=202)

        deleted = cleanup_spaces(CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN, "MYLONGPREFIX", skip_confirm=True)
        assert deleted == 1

    @responses.activate
    def test_short_prefix(self):
        """Short prefixes (< 6 chars) work without error."""
        spaces = [_make_space("ABC1", "Space 1", "10001")]
        responses.get(V2_SPACES_URL, json=_make_spaces_response(spaces))
        responses.delete(f"{CONFLUENCE_URL}/rest/api/space/ABC1", status=202)

        deleted = cleanup_spaces(CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN, "ABC", skip_confirm=True)
        assert deleted == 1


# ========== Deletion Tests ==========


class TestCleanupDeletion:
    @responses.activate
    def test_delete_returns_202(self):
        """Successful deletion returns 202 and is counted."""
        spaces = [_make_space("TESTDA1", "Test Space 1", "10001")]
        responses.get(V2_SPACES_URL, json=_make_spaces_response(spaces))
        responses.delete(f"{CONFLUENCE_URL}/rest/api/space/TESTDA1", status=202)

        deleted = cleanup_spaces(CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN, "TESTDATA", skip_confirm=True)
        assert deleted == 1

    @responses.activate
    def test_delete_failure_is_counted(self):
        """Failed deletion is not counted but doesn't stop processing."""
        spaces = [
            _make_space("TESTDA1", "Test Space 1", "10001"),
            _make_space("TESTDA2", "Test Space 2", "10002"),
        ]
        responses.get(V2_SPACES_URL, json=_make_spaces_response(spaces))
        responses.delete(f"{CONFLUENCE_URL}/rest/api/space/TESTDA1", status=403, body="Forbidden")
        responses.delete(f"{CONFLUENCE_URL}/rest/api/space/TESTDA2", status=202)

        deleted = cleanup_spaces(CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN, "TESTDATA", skip_confirm=True)
        assert deleted == 1


# ========== Dry Run Tests ==========


class TestCleanupDryRun:
    @responses.activate
    def test_dry_run_does_not_delete(self):
        """Dry run shows spaces but does not delete them."""
        spaces = [_make_space("TESTDA1", "Test Space 1", "10001")]
        responses.get(V2_SPACES_URL, json=_make_spaces_response(spaces))
        # No delete mock — if cleanup tries to delete, responses will raise

        deleted = cleanup_spaces(CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN, "TESTDATA", dry_run=True)
        assert deleted == 0

    @responses.activate
    def test_dry_run_with_no_matching_spaces(self):
        """Dry run with no matching spaces returns 0."""
        responses.get(V2_SPACES_URL, json=_make_spaces_response([]))

        deleted = cleanup_spaces(CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN, "TESTDATA", dry_run=True)
        assert deleted == 0


# ========== Confirmation Tests ==========


class TestCleanupConfirmation:
    @responses.activate
    def test_yes_flag_skips_prompt(self):
        """--yes skips the confirmation prompt."""
        spaces = [_make_space("TESTDA1", "Test Space 1", "10001")]
        responses.get(V2_SPACES_URL, json=_make_spaces_response(spaces))
        responses.delete(f"{CONFLUENCE_URL}/rest/api/space/TESTDA1", status=202)

        with patch("builtins.input") as mock_input:
            deleted = cleanup_spaces(CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN, "TESTDATA", skip_confirm=True)
            mock_input.assert_not_called()
        assert deleted == 1

    @responses.activate
    def test_confirmation_accepted(self):
        """User typing 'y' proceeds with deletion."""
        spaces = [_make_space("TESTDA1", "Test Space 1", "10001")]
        responses.get(V2_SPACES_URL, json=_make_spaces_response(spaces))
        responses.delete(f"{CONFLUENCE_URL}/rest/api/space/TESTDA1", status=202)

        with patch("builtins.input", return_value="y"):
            deleted = cleanup_spaces(CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN, "TESTDATA", skip_confirm=False)
        assert deleted == 1

    @responses.activate
    def test_confirmation_declined(self):
        """User typing 'n' cancels deletion."""
        spaces = [_make_space("TESTDA1", "Test Space 1", "10001")]
        responses.get(V2_SPACES_URL, json=_make_spaces_response(spaces))
        # No delete mock — shouldn't be called

        with patch("builtins.input", return_value="n"):
            deleted = cleanup_spaces(CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN, "TESTDATA", skip_confirm=False)
        assert deleted == 0

    @responses.activate
    def test_confirmation_empty_input_cancels(self):
        """Empty input (just pressing Enter) cancels deletion."""
        spaces = [_make_space("TESTDA1", "Test Space 1", "10001")]
        responses.get(V2_SPACES_URL, json=_make_spaces_response(spaces))

        with patch("builtins.input", return_value=""):
            deleted = cleanup_spaces(CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN, "TESTDATA", skip_confirm=False)
        assert deleted == 0

    @responses.activate
    def test_confirmation_eof_cancels(self):
        """EOFError (piped input) cancels deletion."""
        spaces = [_make_space("TESTDA1", "Test Space 1", "10001")]
        responses.get(V2_SPACES_URL, json=_make_spaces_response(spaces))

        with patch("builtins.input", side_effect=EOFError):
            deleted = cleanup_spaces(CONFLUENCE_URL, TEST_EMAIL, TEST_TOKEN, "TESTDATA", skip_confirm=False)
        assert deleted == 0
