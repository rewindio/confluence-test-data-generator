# Confluence Test Data Generator - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a CLI tool to generate synthetic Confluence Cloud data at scale, mirroring the Jira test data generator architecture.

**Architecture:** Async-first Python with modular generators. Base class handles rate limiting, authentication, and session management. Specialized generators per domain (spaces, pages, comments, etc.). CSV-driven multipliers calculate item counts. Checkpoint system enables resume after failures.

**Tech Stack:** Python 3.12+, aiohttp, python-dotenv, requests

**Reference:** `https://github.com/rewindio/jira-test-data-generator` - follow patterns exactly

---

## Task 1: Project Setup

**Status: COMPLETED**

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `generators/__init__.py`

**Step 1: Create requirements.txt**

```
aiohttp>=3.9.0
python-dotenv>=1.0.0
requests>=2.31.0
```

**Step 2: Create .env.example**

```
CONFLUENCE_API_TOKEN=your_api_token_here
CONFLUENCE_URL=https://yourcompany.atlassian.net/wiki
CONFLUENCE_EMAIL=your.email@company.com
```

**Step 3: Create .gitignore**

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
.venv/
ENV/

# Environment
.env

# IDE
.idea/
.vscode/
*.swp
*.swo

# Project specific
logs/
checkpoints/
*.log

# Testing
.pytest_cache/
.coverage
htmlcov/
```

**Step 4: Create generators/__init__.py**

```python
"""Confluence data generators package."""

from .base import ConfluenceAPIClient, RateLimitState
from .benchmark import BenchmarkTracker
from .checkpoint import CheckpointManager

__all__ = [
    "ConfluenceAPIClient",
    "RateLimitState",
    "BenchmarkTracker",
    "CheckpointManager",
]
```

**Step 5: Create directories**

Run: `mkdir -p generators tests logs checkpoints`

**Step 6: Commit**

```bash
git add requirements.txt .env.example .gitignore generators/__init__.py
git commit -m "feat: initial project setup with dependencies and structure"
```

---

## Task 2: Base API Client (generators/base.py)

**Status: COMPLETED**

**Files:**
- Create: `generators/base.py`
- Reference: `https://github.com/rewindio/jira-test-data-generator/blob/main/generators/base.py`

**Step 1: Create base.py with RateLimitState and ConfluenceAPIClient**

Copy the structure from Jira's base.py, adapting for Confluence:
- Change class name to `ConfluenceAPIClient`
- Change `jira_url` to `confluence_url`
- Update default API base URL to Confluence Cloud API v2: `{confluence_url}/wiki/api/v2`
- Keep all rate limiting logic identical (RateLimitState, adaptive throttling, etc.)
- Keep text pool generation identical
- Keep connection pooling settings identical

Key differences from Jira:
- API base: `/wiki/api/v2` for most endpoints
- Some endpoints use `/wiki/rest/api` (legacy)

**Step 2: Verify imports work**

Run: `python -c "from generators.base import ConfluenceAPIClient, RateLimitState; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add generators/base.py
git commit -m "feat: add base API client with rate limiting"
```

---

## Task 3: Benchmark Tracker (generators/benchmark.py)

**Status: COMPLETED**

**Files:**
- Create: `generators/benchmark.py`
- Reference: `https://github.com/rewindio/jira-test-data-generator/blob/main/generators/benchmark.py`

**Step 1: Create benchmark.py**

Copy from Jira's benchmark.py with these changes:
- Update `phase_display_names` dict to Confluence phases:
  ```python
  self.phase_display_names = {
      "users": "Users",
      "spaces": "Spaces",
      "space_labels": "Space Labels",
      "space_properties": "Space Properties",
      "space_permissions": "Space Permissions",
      "folders": "Folders",
      "pages": "Pages",
      "page_labels": "Page Labels",
      "page_properties": "Page Properties",
      "page_restrictions": "Page Restrictions",
      "page_versions": "Page Versions",
      "blogposts": "Blog Posts",
      "blogpost_labels": "Blog Post Labels",
      "blogpost_properties": "Blog Post Properties",
      "blogpost_restrictions": "Blog Post Restrictions",
      "blogpost_versions": "Blog Post Versions",
      "attachments": "Attachments",
      "attachment_labels": "Attachment Labels",
      "attachment_versions": "Attachment Versions",
      "inline_comments": "Inline Comments",
      "inline_comment_versions": "Inline Comment Versions",
      "footer_comments": "Footer Comments",
      "footer_comment_versions": "Footer Comment Versions",
      "templates": "Templates",
  }
  ```
- Update extrapolation to use "content" instead of "issues"
- Added `CONFLUENCE_SIZE_TIERS` constant and `format_size_tier_extrapolations()` method
- Benchmark output now shows time estimates for all 4 Atlassian instance sizes (S/M/L/XL)

**Step 2: Verify imports work**

Run: `python -c "from generators.benchmark import BenchmarkTracker; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add generators/benchmark.py
git commit -m "feat: add benchmark tracker for performance metrics"
```

---

## Task 4: Checkpoint Manager (generators/checkpoint.py)

**Status: COMPLETED**

**Files:**
- Create: `generators/checkpoint.py`
- Reference: `https://github.com/rewindio/jira-test-data-generator/blob/main/generators/checkpoint.py`

**Step 1: Create checkpoint.py**

Copy from Jira's checkpoint.py with these changes:
- Update `PHASE_ORDER` list:
  ```python
  PHASE_ORDER = [
      "users",
      "spaces",
      "space_labels",
      "space_properties",
      "space_permissions",
      "folders",
      "pages",
      "page_labels",
      "page_properties",
      "page_restrictions",
      "page_versions",
      "blogposts",
      "blogpost_labels",
      "blogpost_properties",
      "blogpost_restrictions",
      "blogpost_versions",
      "attachments",
      "attachment_labels",
      "attachment_versions",
      "inline_comments",
      "inline_comment_versions",
      "footer_comments",
      "footer_comment_versions",
      "templates",
  ]
  ```
- Update `CheckpointData` fields:
  - `target_issue_count` → `target_content_count`
  - `jira_url` → `confluence_url`
  - `project_keys` → `space_keys`
  - `project_ids` → `space_ids`
  - `issue_keys` → `page_ids`
  - `issues_per_project` → `pages_per_space`
  - Add: `blogpost_ids: list[str]`
  - Add: `user_account_ids: list[str]`
- Update checkpoint filename: `confluence_checkpoint_{prefix}.json`
- Default checkpoint directory: `checkpoints/`

**Step 2: Verify imports work**

Run: `python -c "from generators.checkpoint import CheckpointManager; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add generators/checkpoint.py
git commit -m "feat: add checkpoint manager for resumable generation"
```

---

## Task 5: User Generator (confluence_user_generator.py)

**Status: COMPLETED**

**Files:**
- Create: `confluence_user_generator.py`
- Create: `tests/test_user_generator.py`
- Reference: `https://github.com/rewindio/jira-test-data-generator/blob/main/jira_user_generator.py`

**Implementation Notes:**

The user generator was built with these key features:

1. **Gmail "+" Alias**: Creates sandbox emails like `user+confluence1@gmail.com`
2. **Configurable Suffix**: `--suffix` option (default: "confluence") to avoid collisions with Jira sandbox users
3. **Site Name Auto-Detection**: Extracts site name from URL (e.g., `mycompany` from `mycompany.atlassian.net`)
4. **Confluence Access via Group**: Users are added to `confluence-users-{site-name}` group for Confluence access
5. **Group Override**: `--confluence-users-group` option to override auto-detected group name

**Key API Learnings:**
- The `/rest/api/3/user` endpoint only accepts Jira product names in the `products` field
- Confluence access must be granted via group membership (not products field)
- Atlassian Cloud default groups include site name: `confluence-users-{site-name}`
- Adding users to groups uses Admin API: `POST /rest/api/3/group/user` with `groupname` (lowercase) param

**API Endpoints Used:**
- Check user: `GET /rest/api/3/user/search?query={email}`
- Create/invite user: `POST /rest/api/3/user` with `products: []`
- Add to group: `POST /rest/api/3/group/user?groupname={name}`

**Tests:** 46 tests covering URL handling, email parsing, API calls, user/group creation, CLI

---

## Task 6: Space Generator (generators/spaces.py)

**Status: COMPLETED**

**Files:**
- Create: `generators/spaces.py`
- Create: `tests/test_spaces.py`

**Implementation Notes:**

The space generator was built with both sync and async methods for all operations:

1. **Space CRUD**: `create_space()`, `create_spaces()`, `get_space()`
2. **Space Labels**: `add_space_label()`, `add_space_labels()`
3. **Space Properties**: `set_space_property()`, `set_space_properties()`
4. **Space Permissions**: `add_space_permission()`, `add_space_permissions()`
5. **Space Look and Feel**: `set_space_look_and_feel()`, `set_space_look_and_feel_multiple()`

All methods have async counterparts with `_async` suffix using memory-efficient batching.

**API Endpoints Used:**
- `POST /api/v2/spaces` - Create space
- `GET /api/v2/spaces?keys={key}` - Get space by key (v2 uses query param, not path)
- `POST /rest/api/space/{key}/label` - Add label (legacy API, v2 doesn't support)
- `POST /api/v2/spaces/{id}/categories` - Add category
- `POST /api/v2/spaces/{id}/properties` - Set property
- `POST /api/v2/spaces/{id}/permissions` - Add permission
- `PUT /rest/api/settings/lookandfeel/custom?spaceKey={key}` - Set look and feel (legacy API)

**Design Decision: Labels vs Categories**

Space labels are deprecated in Confluence Cloud, replaced by categories. However, we create BOTH:
- **Labels**: For backup compatibility (existing backups contain labels that need to be restored)
- **Categories**: The current Confluence Cloud mechanism for organizing spaces

When the `--labels` count is specified, both labels AND categories are created in the same ratio.
This ensures test data covers both the legacy format (for backup/restore testing) and the current format.

**Tests:** 45 tests covering initialization, space operations, labels, categories, properties, permissions, look and feel, and all async variants

---

## Task 7: Page Generator (generators/pages.py)

**Status: COMPLETED**

**Files:**
- Create: `generators/pages.py`

**Step 1: Create pages.py**

Inherits from `ConfluenceAPIClient`. Methods needed:

```python
class PageGenerator(ConfluenceAPIClient):
    """Generates Confluence pages with realistic hierarchy."""

    # Hierarchy distribution
    HIERARCHY_DISTRIBUTION = {
        "root": 0.60,      # 60% at root level
        "level_1": 0.30,   # 30% one level deep
        "level_2_plus": 0.10  # 10% deeper
    }

    async def create_page_async(
        self,
        space_id: str,
        title: str,
        body: str,
        parent_id: Optional[str] = None
    ) -> Optional[dict]:
        """Create page via POST /wiki/api/v2/pages"""

    async def create_pages_async(
        self,
        space_id: str,
        count: int,
        prefix: str
    ) -> list[dict]:
        """Create pages with realistic hierarchy distribution"""

    async def add_page_label_async(self, page_id: str, label: str) -> bool:
        """Add label via POST /wiki/api/v2/pages/{id}/labels"""

    async def set_page_property_async(self, page_id: str, key: str, value: dict) -> bool:
        """Set property via POST /wiki/api/v2/pages/{id}/properties"""

    async def add_page_restriction_async(self, page_id: str, operation: str, restrictions: dict) -> bool:
        """Add restriction via PUT /wiki/api/v2/pages/{id}/restrictions"""

    async def create_page_version_async(self, page_id: str, new_body: str, message: str) -> bool:
        """Create new version by updating page via PUT /wiki/api/v2/pages/{id}"""

    def _select_parent_id(self, created_pages: list[dict]) -> Optional[str]:
        """Select parent based on hierarchy distribution"""
```

Page title format: `{PREFIX} Page {number}` (e.g., `TESTDATA Page 1`)

**Step 2: Verify imports work**

Run: `python -c "from generators.pages import PageGenerator; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add generators/pages.py
git commit -m "feat: add page generator with hierarchy support"
```

---

## Task 8: Blog Post Generator (generators/blogposts.py)

**Status: COMPLETED**

**Files:**
- Create: `generators/blogposts.py`

**Step 1: Create blogposts.py**

Similar structure to pages.py but simpler (no hierarchy):

```python
class BlogPostGenerator(ConfluenceAPIClient):
    """Generates Confluence blog posts."""

    async def create_blogpost_async(
        self,
        space_id: str,
        title: str,
        body: str
    ) -> Optional[dict]:
        """Create blog post via POST /wiki/api/v2/blogposts"""

    async def create_blogposts_async(
        self,
        space_id: str,
        count: int,
        prefix: str
    ) -> list[dict]:
        """Create multiple blog posts"""

    async def add_blogpost_label_async(self, blogpost_id: str, label: str) -> bool:
    async def set_blogpost_property_async(self, blogpost_id: str, key: str, value: dict) -> bool:
    async def add_blogpost_restriction_async(self, blogpost_id: str, operation: str, restrictions: dict) -> bool:
    async def create_blogpost_version_async(self, blogpost_id: str, new_body: str, message: str) -> bool:
```

**Step 2: Verify imports work**

Run: `python -c "from generators.blogposts import BlogPostGenerator; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add generators/blogposts.py
git commit -m "feat: add blog post generator"
```

---

## Task 9: Attachment Generator (generators/attachments.py)

**Status: COMPLETED**

**Files:**
- Created: `generators/attachments.py`
- Created: `tests/test_attachments.py` (36 tests)

**Implementation Notes:**

The attachment generator was built with both sync and async methods using the legacy REST API v1 for multipart file uploads (v2 doesn't support attachment uploads).

1. **Pre-generated file pool**: 20 files (1-5 KB each) in 4 types (txt, json, csv, log), reused with random filename suffixes for uniqueness
2. **Separate upload session**: Dedicated `_async_upload_session` with `X-Atlassian-Token: no-check` header (base session hardcodes JSON content type)
3. **Attachment versioning**: Re-upload to `content/{pageId}/child/attachment/{attId}/data` creates a new version
4. **Attachment labels**: Uses same legacy `content/{id}/label` endpoint as pages/blogposts

**API Endpoints Used:**
- `POST /rest/api/content/{id}/child/attachment` - Upload attachment (multipart)
- `POST /rest/api/content/{id}/child/attachment/{attId}/data` - Upload new version (multipart)
- `POST /rest/api/content/{id}/label` - Add label to attachment

**Error handling improvements (applied project-wide):**
- `suppress_errors` parameter on `_api_call_async()` — callers with their own retry logic (e.g., 409 conflicts) can suppress base-class ERROR logging
- `_truncate_error_response()` — detects HTML error pages (5xx) and truncates to a short summary instead of dumping full HTML
- Transient errors (5xx, connection) log at DEBUG during retries, only ERROR when all retries exhausted

**Tests:** 36 tests covering file pool init, file generation, upload (sync/async), labels, versions, dry run, session cleanup

---

## Task 9b: Attachment Checkpoint Resume Support

**Status: COMPLETED**

**Context:** During PR #14 code review, it was identified that the checkpoint system does not persist attachment metadata (attachment IDs, which pages they belong to). This means `--resume` cannot skip already-uploaded attachments or resume attachment label/version phases.

**Files:**
- Modify: `generators/checkpoint.py`
- Modify: `generators/attachments.py`
- Modify: `confluence_data_generator.py`
- Modify: `tests/test_attachments.py`
- Modify: `tests/test_checkpoint.py`

**What's needed:**

1. **Persist attachment metadata in checkpoint**: Store attachment IDs and their parent page/blogpost IDs so that on resume, the attachment phase can skip already-uploaded files and the label/version phases know which attachments exist.

2. **Resume-aware attachment creation**: `create_attachments_async()` should check the checkpoint for already-created attachments and skip them, similar to how pages and blogposts handle resume.

3. **Resume-aware label/version phases**: `add_attachment_labels_async()` and `create_attachment_versions_async()` should use checkpoint data to pick up where they left off.

**Design considerations:**
- Attachment counts can be large — checkpoint data structure should be space-efficient
- Follow the existing pattern used for pages (`pages_per_space`, `page_ids`) in `CheckpointData`
- Consider storing as `attachment_ids: list[str]` and `attachments_per_page: dict[str, int]`

**PR Review Reference:** Comments #9 and #10 on PR #14

---

## Task 10: Comment Generator (generators/comments.py)

**Status: COMPLETED**

**Files:**
- Created: `generators/comments.py`
- Created: `tests/test_comments.py` (53 tests)
- Modified: `generators/__init__.py` (added CommentGenerator export)
- Modified: `generators/checkpoint.py` (added comment metadata fields and methods)
- Modified: `confluence_data_generator.py` (wired up comment phases with checkpoint resume)
- Modified: `tests/test_checkpoint.py` (added comment metadata tests)

**Implementation Notes:**

The comment generator was built with both sync and async methods for inline comments, footer comments, and their versions. Comments are simpler than pages/blogposts — no labels, properties, or restrictions.

1. **Footer comments**: `POST /api/v2/footer-comments` with `pageId` and body
2. **Inline comments**: `POST /api/v2/inline-comments` with `pageId`, body, and `inlineCommentProperties`
3. **Inline comment text selection**: Fetches page body via `GET /api/v2/pages/{id}?body-format=storage`, extracts a 4+ char word for `textSelection` (Confluence requires it to match real page text)
4. **Async page text caching**: Per-page `asyncio.Lock` prevents duplicate fetches when multiple tasks request the same page concurrently
5. **Comment versions**: GET current version + PUT with incremented version number
6. **Version conflict handling**: Both sync and async single-comment methods use 409 retry with exponential backoff and version re-read. Uses `suppress_errors=(409,)` to avoid log spam.
7. **Unified version methods**: `create_comment_version()` / `create_comment_versions_async()` take a `comment_type` parameter ("footer" or "inline") to select the right endpoint
8. **Checkpoint resume**: `inline_comment_metadata` and `footer_comment_metadata` fields in `CheckpointData` enable resuming version phases after interruption
9. **Exception handling**: `create_comment_versions_async()` logs and records exceptions from `asyncio.gather` instead of silently ignoring them

**API Endpoints Used:**
- `POST /api/v2/footer-comments` — Create footer comment
- `POST /api/v2/inline-comments` — Create inline comment
- `GET /api/v2/pages/{id}?body-format=storage` — Get page body for inline comment text selection
- `GET /api/v2/footer-comments/{id}` — Get footer comment (for version reads)
- `PUT /api/v2/footer-comments/{id}` — Update footer comment (version increment)
- `GET /api/v2/inline-comments/{id}` — Get inline comment (for version reads)
- `PUT /api/v2/inline-comments/{id}` — Update inline comment (version increment)

**Orchestrator wiring:**
- 4 sync methods: `_create_inline_comments_sync`, `_create_inline_comment_versions_sync`, `_create_footer_comments_sync`, `_create_footer_comment_versions_sync`
- 4 async methods: mirrors of sync with `await`
- All 8 methods persist/restore comment metadata via checkpoint for resume support
- Phase 8 replaces "NOT YET IMPLEMENTED" stubs in both `generate_sync` and `generate_async`
- Async session cleanup added to `finally` block

**API Gotcha:** The `inlineCommentProperties.textSelection` field must match actual text in the page body. Hardcoding a generic string like `"text"` results in a 400 BAD_REQUEST. The fix is to fetch the page body and extract a real word.

**Tests:** 53 tests covering initialization, text extraction, footer creation, inline creation (including inlineCommentProperties verification), versions (both types with 409 retry), dry run, async operations, page text cache locking, exception handling, and edge cases

---

## Task 11: Template Generator (generators/templates.py)

**Status: COMPLETED**

**Files:**
- Created: `generators/templates.py` (~190 lines)
- Created: `tests/test_templates.py` (23 tests)
- Modified: `generators/__init__.py` (added TemplateGenerator export)
- Modified: `confluence_data_generator.py` (wired up template phase)

**Implementation Notes:**

The template generator was built with both sync and async methods, following the blogpost generator pattern but simplified to just creation (no versions, labels, properties, or restrictions).

1. **Legacy API**: Uses `POST /rest/api/template` (v1) since there is no v2 endpoint
2. **Template types**: Alternates between `"page"` and `"blogpost"` using `index % 2`
3. **Space key**: Template API requires `"space": {"key": ...}` (not space ID)
4. **Dry-run IDs**: Format `dry-run-template-{space_key}-{index}`
5. **Batch async**: Uses `asyncio.gather` with `return_exceptions=True` for error handling

**API Endpoint Used:**
- `POST /rest/api/template` — Create content template

**Orchestrator wiring:**
- `_create_templates_sync()` and `_create_templates_async()` methods added
- Phase 9 stubs replaced with actual template creation
- Guarded by `not self.content_only` (templates skipped in content-only mode)
- Async session cleanup added to `finally` block

**Tests:** 22 tests covering initialization, sync/async creation, dry run, failure, type alternation, space distribution, payload structure, v1 URL verification, edge cases

---

## Task 12: Update generators/__init__.py

**Status: COMPLETED** — All generators including TemplateGenerator now exported.

**Files:**
- Modify: `generators/__init__.py`

**Step 1: Update __init__.py to export all generators**

```python
"""Confluence data generators package."""

from .base import ConfluenceAPIClient, RateLimitState
from .benchmark import BenchmarkTracker
from .checkpoint import CheckpointManager
from .spaces import SpaceGenerator
from .pages import PageGenerator
from .blogposts import BlogPostGenerator
from .attachments import AttachmentGenerator
from .comments import CommentGenerator
from .templates import TemplateGenerator

__all__ = [
    "ConfluenceAPIClient",
    "RateLimitState",
    "BenchmarkTracker",
    "CheckpointManager",
    "SpaceGenerator",
    "PageGenerator",
    "BlogPostGenerator",
    "AttachmentGenerator",
    "CommentGenerator",
    "TemplateGenerator",
]
```

**Step 2: Verify all imports work**

Run: `python -c "from generators import *; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add generators/__init__.py
git commit -m "feat: export all generators from package"
```

---

## Task 13: Main Orchestrator - Part 1: CLI and Setup (confluence_data_generator.py)

**Status: COMPLETED**

**Files:**
- Create: `confluence_data_generator.py`
- Reference: `https://github.com/rewindio/jira-test-data-generator/blob/main/jira_data_generator.py`

**Step 1: Create CLI argument parsing and setup**

Include:
- Argument parsing (same structure as Jira, adapted for Confluence)
- Environment variable loading
- Logging setup (to `logs/` directory)
- Multiplier loading from CSV
- Count calculation function

```python
def parse_args():
    parser = argparse.ArgumentParser(...)
    parser.add_argument("--url", required=True, help="Confluence Cloud URL")
    parser.add_argument("--email", required=True, help="Atlassian account email")
    parser.add_argument("--count", type=int, required=True, help="Target content count")
    parser.add_argument("--size", choices=["small", "medium", "large"], default="small")
    parser.add_argument("--prefix", default="TESTDATA")
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--request-delay", type=float, default=0.0)
    parser.add_argument("--content-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-checkpoint", action="store_true")
    parser.add_argument("--no-async", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()

def load_multipliers(csv_path: str) -> dict:
    """Load multipliers from CSV file"""

def calculate_counts(content_count: int, size: str, multipliers: dict) -> dict:
    """Calculate item counts using multipliers"""
```

**Step 2: Verify script runs with --help**

Run: `python confluence_data_generator.py --help`
Expected: Help text displays

**Step 3: Commit**

```bash
git add confluence_data_generator.py
git commit -m "feat: add main orchestrator CLI and setup"
```

---

## Task 14: Main Orchestrator - Part 2: ConfluenceDataGenerator Class

**Status: COMPLETED**

**Files:**
- Modify: `confluence_data_generator.py`

**Step 1: Add ConfluenceDataGenerator class with initialization**

```python
class ConfluenceDataGenerator:
    """Main orchestrator for Confluence test data generation."""

    def __init__(
        self,
        confluence_url: str,
        email: str,
        api_token: str,
        prefix: str = "TESTDATA",
        dry_run: bool = False,
        concurrency: int = 5,
        request_delay: float = 0.0,
        content_only: bool = False,
        checkpoint_manager: Optional[CheckpointManager] = None,
    ):
        # Initialize all generators
        self.space_gen = SpaceGenerator(...)
        self.page_gen = PageGenerator(...)
        self.blogpost_gen = BlogPostGenerator(...)
        self.attachment_gen = AttachmentGenerator(...)
        self.comment_gen = CommentGenerator(...)
        self.template_gen = TemplateGenerator(...)

        # Shared state
        self.benchmark = BenchmarkTracker()
        self.checkpoint = checkpoint_manager

    def _log_header(self, counts: dict):
        """Log generation plan header"""

    def _log_footer(self):
        """Log summary footer"""
```

**Step 2: Verify class instantiation works**

Run: `python -c "from confluence_data_generator import ConfluenceDataGenerator; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add confluence_data_generator.py
git commit -m "feat: add ConfluenceDataGenerator class"
```

---

## Task 15: Main Orchestrator - Part 3: Sync Generation Methods

**Status: COMPLETED**

**Files:**
- Modify: `confluence_data_generator.py`

**Step 1: Add synchronous generation methods**

```python
def generate_all(self, content_count: int, counts: dict):
    """Main synchronous generation entry point"""
    self.benchmark.start_overall()
    self._log_header(counts)

    # Phase 1: Users (if needed for permissions)
    if not self.content_only:
        self._create_users_sync(counts)

    # Phase 2: Spaces
    spaces = self._create_spaces_sync(counts)

    # Phase 3-5: Space metadata (skip if content_only)
    if not self.content_only:
        self._create_space_metadata_sync(spaces, counts)

    # Phase 6: Pages
    pages = self._create_pages_sync(spaces, counts)

    # Phase 7-8: Page metadata (skip if content_only)
    if not self.content_only:
        self._create_page_metadata_sync(pages, counts)

    # Phase 9: Blog posts
    blogposts = self._create_blogposts_sync(spaces, counts)

    # ... remaining phases

    self.benchmark.end_overall()
    self._log_footer()
```

**Step 2: Verify generate_all exists**

Run: `python -c "from confluence_data_generator import ConfluenceDataGenerator; print(hasattr(ConfluenceDataGenerator, 'generate_all'))"`
Expected: `True`

**Step 3: Commit**

```bash
git add confluence_data_generator.py
git commit -m "feat: add synchronous generation methods"
```

---

## Task 16: Main Orchestrator - Part 4: Async Generation Methods

**Status: COMPLETED**

**Files:**
- Modify: `confluence_data_generator.py`

**Step 1: Add asynchronous generation methods**

```python
async def generate_all_async(self, content_count: int, counts: dict):
    """Main asynchronous generation entry point"""
    self.benchmark.start_overall()
    self._log_header(counts)

    try:
        # Phase 1: Users
        if not self.content_only:
            await self._create_users_async(counts)

        # Phase 2: Spaces (sequential - low volume)
        spaces = await self._create_spaces_async(counts)

        # Phase 3-5: Space metadata (parallel within each phase)
        if not self.content_only:
            await self._create_space_metadata_async(spaces, counts)

        # Phase 6: Pages (parallel across spaces)
        pages = await self._create_pages_async(spaces, counts)

        # ... remaining phases

    finally:
        # Clean up async sessions
        await self._close_all_sessions()

    self.benchmark.end_overall()
    self._log_footer()
```

**Step 2: Verify generate_all_async exists**

Run: `python -c "from confluence_data_generator import ConfluenceDataGenerator; print(hasattr(ConfluenceDataGenerator, 'generate_all_async'))"`
Expected: `True`

**Step 3: Commit**

```bash
git add confluence_data_generator.py
git commit -m "feat: add asynchronous generation methods"
```

---

## Task 17: Main Orchestrator - Part 5: Main Entry Point

**Status: COMPLETED**

**Files:**
- Modify: `confluence_data_generator.py`

**Step 1: Add main() function**

```python
def main():
    args = parse_args()

    # Setup logging
    setup_logging(args.prefix, args.verbose)

    # Load API token from environment
    load_dotenv()
    api_token = os.environ.get("CONFLUENCE_API_TOKEN")
    if not api_token:
        print("Error: CONFLUENCE_API_TOKEN not set in .env or environment", file=sys.stderr)
        sys.exit(1)

    # Load multipliers and calculate counts
    multipliers = load_multipliers("item_type_multipliers.csv")
    counts = calculate_counts(args.count, args.size, multipliers)

    # Initialize checkpoint manager
    checkpoint_manager = None
    if not args.no_checkpoint:
        checkpoint_dir = Path("checkpoints")
        checkpoint_dir.mkdir(exist_ok=True)
        checkpoint_manager = CheckpointManager(args.prefix, checkpoint_dir)

        if args.resume:
            checkpoint_manager.load()

    # Create generator
    generator = ConfluenceDataGenerator(
        confluence_url=args.url,
        email=args.email,
        api_token=api_token,
        prefix=args.prefix,
        dry_run=args.dry_run,
        concurrency=args.concurrency,
        request_delay=args.request_delay,
        content_only=args.content_only,
        checkpoint_manager=checkpoint_manager,
    )

    # Run generation
    try:
        if args.no_async:
            generator.generate_all(args.count, counts)
        else:
            asyncio.run(generator.generate_all_async(args.count, counts))
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Progress saved to checkpoint.")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

**Step 2: Verify full script runs with --dry-run**

Run: `python confluence_data_generator.py --url https://test.atlassian.net/wiki --email test@test.com --count 100 --dry-run`
Expected: Dry run output showing planned counts

**Step 3: Commit**

```bash
git add confluence_data_generator.py
git commit -m "feat: add main entry point and dry-run support"
```

---

## Task 18: Integration Testing - Dry Run

**Status: COMPLETED**

**Files:**
- All files

**Step 1: Run comprehensive dry-run test**

Run:
```bash
python confluence_data_generator.py \
  --url https://test.atlassian.net/wiki \
  --email test@test.com \
  --count 1000 \
  --size small \
  --dry-run \
  --verbose
```

Expected:
- Shows calculated counts for all item types
- Shows generation plan
- No API calls made
- Completes without errors

**Step 2: Test with --content-only flag**

Run:
```bash
python confluence_data_generator.py \
  --url https://test.atlassian.net/wiki \
  --email test@test.com \
  --count 1000 \
  --content-only \
  --dry-run
```

Expected:
- Shows only spaces, pages, blogposts counts
- Skips metadata phases

**Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: integration testing fixes"
```

---

## Task 19: Documentation - README.md

**Status: COMPLETED**

**Files:**
- Modify: `README.md`

**Step 1: Update README with comprehensive documentation**

Include:
- Project description
- Installation instructions
- Configuration (.env setup)
- Usage examples
- CLI reference
- Architecture overview
- Multiplier explanation
- Troubleshooting section

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add comprehensive README"
```

---

## Task 20: Final Testing and PR

**Status: COMPLETED**

**Files:**
- All files

**Step 1: Run linting (if ruff available)**

Run: `ruff check . --fix` (if ruff installed)

**Step 2: Test import chain**

Run:
```bash
python -c "
from confluence_data_generator import ConfluenceDataGenerator, main
from confluence_user_generator import ConfluenceUserGenerator
from generators import *
print('All imports successful')
"
```

**Step 3: Create final commit**

```bash
git add -A
git commit -m "chore: final cleanup and polish"
```

**Step 4: Summary**

At this point, the implementation is complete and ready for real-world testing against a Confluence Cloud instance.

---

## Execution Notes

**Key files to reference during implementation:**
- `https://github.com/rewindio/jira-test-data-generator/blob/main/generators/base.py` - Rate limiting patterns
- `https://github.com/rewindio/jira-test-data-generator/blob/main/generators/checkpoint.py` - Checkpoint structure
- `https://github.com/rewindio/jira-test-data-generator/blob/main/generators/benchmark.py` - Benchmark tracking
- `https://github.com/rewindio/jira-test-data-generator/blob/main/jira_data_generator.py` - Main orchestrator patterns

**Confluence Cloud API v2 Reference:**
- Spaces: `POST /wiki/api/v2/spaces`
- Pages: `POST /wiki/api/v2/pages`
- Blog posts: `POST /wiki/api/v2/blogposts`
- Comments: `POST /wiki/api/v2/pages/{id}/footer-comments`, `POST /wiki/api/v2/pages/{id}/inline-comments`
- Attachments: `POST /wiki/api/v2/pages/{id}/attachments`
- Labels: `POST /wiki/api/v2/{type}/{id}/labels`
- Properties: `POST /wiki/api/v2/{type}/{id}/properties`

**Testing strategy:**
- Use `--dry-run` for all development testing
- Test against real instance only when dry-run passes
- Start with small counts (10-100) before scaling up

---

## Phase 2: Gap Coverage & Performance

These tasks address gaps between the multiplier CSV and what the orchestrator actually creates, plus performance improvements.

---

## Task A: Wire User Discovery and Space Permissions into Orchestrator

**Status: COMPLETED** (PR #18)

Implemented user discovery via v1 CQL search and space permissions via RBAC role assignments. Users are auto-discovered from the instance, and permissions are created as role assignments (not direct permission grants). The count is computed dynamically as `num_spaces × num_users × num_roles` (not from the multiplier CSV).

---

## Task B: Wire Page Restrictions into Orchestrator

**Status: COMPLETED** (PR #19)

Wired existing page restriction generator code into both sync and async orchestrator paths. Fixed hard-coded `time.sleep(0.2)` to use `self.request_delay`, added exception logging to `asyncio.gather` results, and added current-user self-inclusion to prevent restriction lockout (Confluence returns 400 if the API caller is evicted from read access). Count comes from multiplier CSV key `page_restriction_v2`.

---

## Task C: Wire Blogpost Restrictions into Orchestrator

**Status: COMPLETED**

Wired existing blogpost restriction generator code into both sync and async orchestrator paths, mirroring the page restrictions implementation from Task B. Fixed hard-coded `time.sleep(0.2)` to use `self.request_delay`, added current-user self-inclusion to prevent restriction lockout, added exception logging to `asyncio.gather` results with `zip(results, batch)` pattern, and fixed checkpoint mapping from `blogpost_restriction` to `blogpost_restriction_v2`. Count comes from multiplier CSV key `blogpost_restriction_v2`.

---

## Task D: Wire Folders and Folder Restrictions into Orchestrator

**Status: COMPLETED**

Created `generators/folders.py` with `FolderGenerator` class (sync + async methods for folder creation and folder restrictions). Wired into orchestrator as Phase 7c (between attachment items and comments). Folder creation uses `POST /api/v2/folders` (v2 endpoint), folder restrictions use `PUT /rest/api/content/{id}/restriction` (same v1 endpoint as pages/blogposts). Added `folder_restrictions` display name to benchmark. Multiplier CSV keys: `folder`, `folder_restriction`.

---

## Task E: Performance Improvements

**Status: NOT STARTED**

Investigate and implement performance improvements to increase throughput for large-scale data generation.

**Scope (to be refined during planning):**
- Profile current bottlenecks (rate limiting vs. serial operations vs. connection overhead)
- Consider batch API endpoints where available
- Optimize async concurrency (connection pooling, batch sizes)
- Reduce unnecessary API calls (e.g., fetching page body for every inline comment)
- Consider parallel space processing for independent operations
- Benchmark before/after to quantify improvements

---

## Task F: Fix `@responses.activate` on Async Tests

**Status: COMPLETED**

Replaced `@responses.activate` decorator with `responses.RequestsMock()` context manager on all async test functions that used it. The decorator can deactivate the mock before the async coroutine finishes, causing flaky tests.

**Fixed files:**
- `tests/test_pages.py` — `test_add_page_restrictions_async_multiple`
- `tests/test_spaces.py` — `test_add_space_permissions_async_multiple`

Fix pattern was already applied in `test_blogposts.py` (PR #20) and `test_folders.py` (PR #21).
