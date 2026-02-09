# Confluence Test Data Generator - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a CLI tool to generate synthetic Confluence Cloud data at scale, mirroring the Jira test data generator architecture.

**Architecture:** Async-first Python with modular generators. Base class handles rate limiting, authentication, and session management. Specialized generators per domain (spaces, pages, comments, etc.). CSV-driven multipliers calculate item counts. Checkpoint system enables resume after failures.

**Tech Stack:** Python 3.12+, aiohttp, python-dotenv, requests

**Reference:** `/Users/dnorth/src/tooling/jira-test-data-generator/` - follow patterns exactly

---

## Task 1: Project Setup

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

**Files:**
- Create: `generators/base.py`
- Reference: `/Users/dnorth/src/tooling/jira-test-data-generator/generators/base.py`

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

**Files:**
- Create: `generators/benchmark.py`
- Reference: `/Users/dnorth/src/tooling/jira-test-data-generator/generators/benchmark.py`

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

**Files:**
- Create: `generators/checkpoint.py`
- Reference: `/Users/dnorth/src/tooling/jira-test-data-generator/generators/checkpoint.py`

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
- Reference: `/Users/dnorth/src/tooling/jira-test-data-generator/jira_user_generator.py`

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

**Files:**
- Create: `generators/attachments.py`

**Step 1: Create attachments.py**

```python
class AttachmentGenerator(ConfluenceAPIClient):
    """Generates Confluence attachments with small synthetic files."""

    # Small file sizes to minimize upload time (same as Jira)
    FILE_SIZES = {
        "tiny": 100,      # 100 bytes
        "small": 1024,    # 1 KB
        "medium": 5120,   # 5 KB
    }

    def _generate_file_content(self, size: int = 1024) -> bytes:
        """Generate synthetic file content"""

    async def create_attachment_async(
        self,
        page_id: str,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream"
    ) -> Optional[dict]:
        """Create attachment via POST /wiki/api/v2/pages/{id}/attachments"""

    async def create_attachments_async(
        self,
        page_ids: list[str],
        count: int,
        prefix: str
    ) -> list[dict]:
        """Create attachments distributed across pages"""

    async def add_attachment_label_async(self, attachment_id: str, label: str) -> bool:
    async def create_attachment_version_async(self, attachment_id: str, new_content: bytes) -> bool:
```

**Step 2: Verify imports work**

Run: `python -c "from generators.attachments import AttachmentGenerator; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add generators/attachments.py
git commit -m "feat: add attachment generator"
```

---

## Task 10: Comment Generator (generators/comments.py)

**Files:**
- Create: `generators/comments.py`

**Step 1: Create comments.py**

```python
class CommentGenerator(ConfluenceAPIClient):
    """Generates Confluence inline and footer comments."""

    async def create_footer_comment_async(
        self,
        page_id: str,
        body: str
    ) -> Optional[dict]:
        """Create footer comment via POST /wiki/api/v2/pages/{id}/footer-comments"""

    async def create_inline_comment_async(
        self,
        page_id: str,
        body: str,
        inline_marker: dict  # text selection location
    ) -> Optional[dict]:
        """Create inline comment via POST /wiki/api/v2/pages/{id}/inline-comments"""

    async def create_footer_comments_async(
        self,
        page_ids: list[str],
        count: int
    ) -> list[dict]:
        """Create footer comments distributed across pages"""

    async def create_inline_comments_async(
        self,
        page_ids: list[str],
        count: int
    ) -> list[dict]:
        """Create inline comments distributed across pages"""

    async def create_comment_version_async(
        self,
        comment_id: str,
        comment_type: str,  # "footer" or "inline"
        new_body: str
    ) -> bool:
        """Update comment to create new version"""
```

**Step 2: Verify imports work**

Run: `python -c "from generators.comments import CommentGenerator; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add generators/comments.py
git commit -m "feat: add comment generator for inline and footer comments"
```

---

## Task 11: Template Generator (generators/templates.py)

**Files:**
- Create: `generators/templates.py`

**Step 1: Create templates.py**

```python
class TemplateGenerator(ConfluenceAPIClient):
    """Generates Confluence templates."""

    async def create_template_async(
        self,
        space_id: str,
        name: str,
        body: str,
        description: str = ""
    ) -> Optional[dict]:
        """Create template via POST /wiki/rest/api/template"""

    async def create_templates_async(
        self,
        space_ids: list[str],
        count: int,
        prefix: str
    ) -> list[dict]:
        """Create templates distributed across spaces"""
```

Note: Templates use the older REST API (`/wiki/rest/api/template`)

**Step 2: Verify imports work**

Run: `python -c "from generators.templates import TemplateGenerator; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add generators/templates.py
git commit -m "feat: add template generator"
```

---

## Task 12: Update generators/__init__.py

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

**Files:**
- Create: `confluence_data_generator.py`
- Reference: `/Users/dnorth/src/tooling/jira-test-data-generator/jira_data_generator.py`

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
- `/Users/dnorth/src/tooling/jira-test-data-generator/generators/base.py` - Rate limiting patterns
- `/Users/dnorth/src/tooling/jira-test-data-generator/generators/checkpoint.py` - Checkpoint structure
- `/Users/dnorth/src/tooling/jira-test-data-generator/generators/benchmark.py` - Benchmark tracking
- `/Users/dnorth/src/tooling/jira-test-data-generator/jira_data_generator.py` - Main orchestrator patterns

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
