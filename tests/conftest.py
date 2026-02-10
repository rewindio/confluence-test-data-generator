"""
Shared pytest fixtures for confluence-test-data-generator tests.
"""

import sys
from pathlib import Path

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# ========== Constants ==========

CONFLUENCE_URL = "https://test.atlassian.net/wiki"
TEST_EMAIL = "test@example.com"
TEST_TOKEN = "test-api-token"
TEST_PREFIX = "TESTDATA"


# ========== Fixture: Reset class-level state ==========


@pytest.fixture(autouse=True)
def reset_text_pool():
    """Reset the text pool before each test to ensure isolation."""
    from generators.base import ConfluenceAPIClient

    ConfluenceAPIClient._text_pool = None
    ConfluenceAPIClient._text_pool_lock = None
    yield


# ========== Fixture: Temporary directories ==========


@pytest.fixture
def temp_checkpoint_dir(tmp_path):
    """Provide a temporary directory for checkpoint files."""
    return tmp_path


# ========== Fixture: Sample data ==========


@pytest.fixture
def sample_space():
    """Sample space data."""
    return {"key": "TEST1", "id": "10001", "name": "Test Space 1"}


@pytest.fixture
def sample_spaces():
    """Sample list of spaces."""
    return [
        {"key": "TEST1", "id": "10001", "name": "Test Space 1"},
        {"key": "TEST2", "id": "10002", "name": "Test Space 2"},
    ]


@pytest.fixture
def sample_page_ids():
    """Sample list of page IDs."""
    return [str(i) for i in range(100001, 100011)]


@pytest.fixture
def sample_blogpost_ids():
    """Sample list of blogpost IDs."""
    return [str(i) for i in range(200001, 200011)]


@pytest.fixture
def sample_user_ids():
    """Sample list of user account IDs."""
    return [f"user-{i}" for i in range(1, 6)]


# ========== Fixture: Multipliers ==========


@pytest.fixture
def sample_multipliers():
    """Sample multipliers data (small bucket)."""
    return {
        "small": {
            "space": 0.00519,
            "page": 0.15197,
            "blogpost": 0.00284,
            "attachment_v2": 0.65907,
            "inline_comment": 0.08268,
            "footer_comment": 0.02612,
            "space_property": 0.00047,
            "space_label": 0.00224,
            "page_label": 0.03527,
            "page_property": 0.01377,
            "page_restriction": 0.01036,
            "page_version": 0.23089,
            "blogpost_label": 0.00106,
            "blogpost_property": 0.00026,
            "blogpost_restriction": 0.00075,
            "blogpost_version": 0.00424,
            "attachment_label": 0.00073,
            "attachment_version": 0.08682,
            "folder": 0.00127,
            "folder_restriction": 0.00009,
            "inline_comment_version": 0.01023,
            "footer_comment_version": 0.00341,
            "template": 0.00239,
            "space_permission": 0.07294,
            "space_look_and_feel": 0.00010,
        }
    }


# ========== Fixture: CSV content ==========


@pytest.fixture
def sample_csv_content():
    """Sample multipliers CSV content."""
    return """Item Type,Small,Medium,Large
space,0.00519,0.00134,0.00050
page,0.15197,0.16006,0.16837
blogpost,0.00284,0.00303,0.00261
attachment_v2,0.65907,0.62838,0.62096
inline_comment,0.08268,0.08839,0.09015
footer_comment,0.02612,0.02754,0.02655
space_property,0.00047,0.00039,0.00028
space_label,0.00224,0.00216,0.00178
page_label,0.03527,0.03609,0.03502
page_property,0.01377,0.01479,0.01478
page_restriction,0.01036,0.01111,0.01143
page_version,0.23089,0.25049,0.26682
blogpost_label,0.00106,0.00094,0.00095
blogpost_property,0.00026,0.00031,0.00030
blogpost_restriction,0.00075,0.00065,0.00053
blogpost_version,0.00424,0.00478,0.00427
attachment_label,0.00073,0.00080,0.00079
attachment_version,0.08682,0.08310,0.08267
folder,0.00127,0.00131,0.00115
folder_restriction,0.00009,0.00009,0.00007
inline_comment_version,0.01023,0.01167,0.01323
footer_comment_version,0.00341,0.00371,0.00381
template,0.00239,0.00179,0.00143
space_permission,0.07294,0.02451,0.01201
space_look_and_feel,0.00010,0.00006,0.00004
"""


# ========== Fixture: Checkpoint data ==========


@pytest.fixture
def sample_checkpoint_data():
    """Sample checkpoint data structure."""
    return {
        "run_id": "TESTDATA-20241208-120000",
        "prefix": "TESTDATA",
        "size": "small",
        "target_content_count": 1000,
        "started_at": "2024-12-08T12:00:00",
        "last_updated": "2024-12-08T12:30:00",
        "confluence_url": CONFLUENCE_URL,
        "async_mode": True,
        "concurrency": 5,
        "content_only": False,
        "space_keys": ["TEST1", "TEST2"],
        "space_ids": {"TEST1": "10001", "TEST2": "10002"},
        "page_ids": [str(i) for i in range(100001, 100051)],
        "blogpost_ids": [str(i) for i in range(200001, 200006)],
        "pages_per_space": {"TEST1": 50, "TEST2": 0},
        "blogposts_per_space": {"TEST1": 5, "TEST2": 0},
        "attachment_metadata": [
            {"id": "att-1", "title": "file1.txt", "pageId": "100001"},
            {"id": "att-2", "title": "file2.txt", "pageId": "100002"},
        ],
        "phases": {
            "spaces": {"status": "complete", "target_count": 2, "created_count": 2, "created_items": []},
            "pages": {"status": "in_progress", "target_count": 152, "created_count": 50, "created_items": []},
            "blogposts": {"status": "pending", "target_count": 3, "created_count": 0, "created_items": []},
        },
    }


# ========== Fixture: Base client setup ==========


@pytest.fixture
def base_client_kwargs():
    """Common kwargs for creating test clients."""
    return {
        "confluence_url": CONFLUENCE_URL,
        "email": TEST_EMAIL,
        "api_token": TEST_TOKEN,
        "dry_run": False,
        "concurrency": 5,
        "benchmark": None,
        "request_delay": 0.0,
    }


@pytest.fixture
def dry_run_client_kwargs(base_client_kwargs):
    """Kwargs for creating dry-run test clients."""
    return {**base_client_kwargs, "dry_run": True}
