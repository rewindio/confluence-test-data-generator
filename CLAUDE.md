# CLAUDE.md - Confluence Test Data Generator

## Project Overview

**Purpose**: Generate realistic test data for Confluence Cloud instances using production-based multipliers derived from analyzing thousands of real Confluence backups.

**Key Features**:
- Async concurrency for high-volume content creation
- Intelligent rate limit handling with exponential backoff and adaptive throttling
- Production-based multipliers loaded from CSV file
- Content-only mode (`--content-only`) for scale testing (spaces, pages, blogposts only)
- Checkpointing for resumable large-scale runs
- Benchmarking with time extrapolation for planning large runs
- Pre-generated random text pool for reduced CPU overhead at scale
- Optimized connection pooling for both sync and async HTTP sessions

**Target User**: Teams who need to test Confluence backup/restore scenarios with realistic data volumes.

**Related Project**: This mirrors the architecture of the [Jira Test Data Generator](https://github.com/rewindio/jira-test-data-generator).

---

## File Structure

```
.
├── .ai/                          # AI-driven development resources
│   ├── README.md                # Directory overview and active plans
│   ├── plans/                   # Implementation plans by initiative
│   │   └── confluence-test-data-generator/
│   │       ├── PLAN.md          # Implementation plan
│   │       └── DESIGN.md        # Design document
│   └── guides/
│       └── AI_IMPLEMENTATION_GUIDE.md
├── confluence_data_generator.py  # Main orchestrator (all generators wired up)
├── confluence_user_generator.py  # Standalone user/group generator (DONE)
├── generators/                   # Modular generators package
│   ├── __init__.py              # Package exports
│   ├── base.py                  # ConfluenceAPIClient, RateLimitState (~680 lines)
│   ├── benchmark.py             # BenchmarkTracker, PhaseMetrics (~400 lines)
│   ├── blogposts.py             # BlogPostGenerator (DONE)
│   ├── checkpoint.py            # CheckpointManager (~620 lines)
│   ├── spaces.py                # SpaceGenerator (DONE)
│   ├── pages.py                 # PageGenerator (DONE)
│   ├── attachments.py           # AttachmentGenerator (DONE)
│   ├── comments.py              # CommentGenerator (DONE)
│   └── templates.py             # TemplateGenerator (DONE)
├── tests/                        # Unit tests (90%+ coverage required)
│   ├── conftest.py              # Shared pytest fixtures
│   ├── test_base.py             # ConfluenceAPIClient tests
│   ├── test_benchmark.py        # BenchmarkTracker tests
│   ├── test_blogposts.py        # BlogPostGenerator tests (49 tests)
│   ├── test_checkpoint.py       # CheckpointManager tests
│   ├── test_comments.py         # CommentGenerator tests (44 tests)
│   ├── test_templates.py        # TemplateGenerator tests (23 tests)
│   ├── test_attachments.py      # AttachmentGenerator tests (36 tests)
│   ├── test_pages.py            # PageGenerator tests
│   ├── test_spaces.py           # SpaceGenerator tests (53 tests)
│   └── test_user_generator.py   # User generator tests (51 tests)
├── .github/workflows/
│   ├── test.yml                 # Tests with 90% coverage threshold
│   ├── lint.yml                 # Ruff linting
│   └── code-scanning.yml        # CodeQL security scanning
├── item_type_multipliers.csv    # Multiplier configuration
├── test_connectivity.py         # API connectivity test
├── requirements.txt             # Python dependencies
├── requirements-dev.txt         # Test dependencies
├── pytest.ini                   # Pytest configuration
├── ruff.toml                    # Ruff linter configuration
├── .env.example                 # API token template
├── README.md                    # User-facing documentation
└── CLAUDE.md                    # This file - for AI agents
```

---

## Development Guidelines

### Code Quality Requirements

1. **Test Coverage**: Minimum 90% coverage enforced by CI. Never lower this threshold.
2. **Linting**: All code must pass `ruff check .` and `ruff format --check .`
3. **Security**: CodeQL scanning enabled - all security alerts must be resolved

### Task Completion Checklist

Before marking any task complete, verify documentation is up to date:

**Internal Documentation** (in `.ai/plans/`):
- [ ] Implementation plan status updated (mark tasks as COMPLETED)
- [ ] Any API learnings or gotchas documented
- [ ] Architecture decisions captured

**External Documentation**:
- [ ] `README.md` - User-facing usage instructions and examples
- [ ] `CLAUDE.md` - Technical details, patterns, and AI agent guidance
- [ ] CLI help text in the code itself (`--help` output)

**When to Update**:
- New feature added → Update README usage section + CLAUDE.md file structure
- New CLI option → Update README CLI table + CLAUDE.md Command Line Options
- Bug fix with learnings → Add to CLAUDE.md Coding Patterns section
- API endpoint used → Verify CLAUDE.md API Endpoints section is current

### Coding Patterns (Lessons from PR Reviews)

#### Security: Never Log Secrets
```python
# BAD - CodeQL will flag this
print(f"Token: {'*' * 8}...{api_token[-4:]}")

# GOOD - No part of the secret revealed
print(f"Token: {'*' * 12} (configured)")
```

#### Don't Mutate Function Inputs
```python
# BAD - Mutates caller's dictionary
@classmethod
def from_dict(cls, data: dict) -> "MyClass":
    value = data.pop("key", default)  # Modifies input!
    return cls(value=value, **data)

# GOOD - Work on a copy
@classmethod
def from_dict(cls, data: dict) -> "MyClass":
    data = dict(data)  # Shallow copy
    value = data.pop("key", default)
    return cls(value=value, **data)
```

#### Use `replace()` for Atomic File Operations
```python
# BAD - rename() fails if target exists
source_path.rename(target_path)

# GOOD - replace() does atomic overwrite
source_path.replace(target_path)
```

#### Document Thread-Safety Assumptions
```python
class CheckpointManager:
    """Manages checkpoint file operations for resumable generation.

    Note: This class is designed for single-threaded use by the main
    orchestrator. Checkpoint updates are serialized through the orchestrator
    even when using async concurrency for API calls. Do not call checkpoint
    methods from multiple concurrent tasks.
    """
```

#### Serialize Versioning Per Resource + Retry on 409
Confluence uses Hibernate optimistic locking (`HIBERNATEVERSION` column). Three things cause 409 CONFLICT (`StaleStateException`):

1. **Concurrent writes**: Two requests read version N, both try to write N+1
2. **Eventual consistency**: Sequential GET after PUT returns a stale version
3. **Cross-operation conflicts**: Other writes (e.g. property updates) increment `HIBERNATEVERSION` even though the API version number doesn't change

The fix has three parts:
- (a) Group versions by resource, process each resource sequentially
- (b) Fetch version once, increment locally
- (c) On failure, wait briefly, re-read the version from the API, and retry

```python
# GOOD - sequential per resource, local tracking, retry with re-read on 409
async def _versions_for_page(page_id, n):
    data = await api_get(f"pages/{page_id}")
    current = data["version"]["number"]
    for _ in range(n):
        for retry in range(3):                         # Retry on conflict
            next_ver = current + 1
            success = await api_put(f"pages/{page_id}", version=next_ver)
            if success:
                current = next_ver
                break
            # Re-read version on failure (409 from cross-operation conflict)
            await asyncio.sleep(0.5 * (retry + 1))
            fresh = await api_get(f"pages/{page_id}")
            current = fresh["version"]["number"]

# Parallel across pages, sequential within each page
for batch in batched(page_ids, concurrency):
    tasks = [_versions_for_page(pid, versions_per_page[pid]) for pid in batch]
    await asyncio.gather(*tasks)
```
This applies to **any** operation that does read-modify-write on the same resource: page versions, blogpost versions, attachment versions, comment versions.

#### Suppress Error Logging for Caller-Handled Errors
When a caller has its own retry logic for specific HTTP errors (e.g., 409 conflicts), use `suppress_errors` to prevent the base class from logging ERROR on every attempt:
```python
# BAD - base class logs ERROR on every 409, even when caller retries successfully
success, _ = await self._api_call_async("PUT", f"pages/{page_id}", data=update_data)

# GOOD - 409s logged at DEBUG; caller's retry loop handles them
success, _ = await self._api_call_async(
    "PUT", f"pages/{page_id}", data=update_data, suppress_errors=(409,)
)
```

#### Only Log Errors on Final Retry Failure
For transient errors (5xx, connection errors), log at DEBUG during retries and only escalate to ERROR when all retries are exhausted. This keeps logs clean when retries succeed.

#### Truncate HTML Error Responses
Confluence returns full HTML pages for 5xx errors. Use `_truncate_error_response()` to avoid dumping thousands of lines of HTML into logs:
```python
# BAD - logs entire HTML page
self.logger.error(f"Response: {error_text}")

# GOOD - detects HTML and truncates
self.logger.error(f"Response: {self._truncate_error_response(error_text)}")
```

#### Attachment Uploads Require Separate Session
The base `_api_call_async()` hardcodes `Content-Type: application/json`. Attachment uploads need multipart form data, so `AttachmentGenerator` creates a dedicated `_async_upload_session` with `X-Atlassian-Token: no-check` header and no Content-Type (let aiohttp set it from FormData).

#### Always Handle Exceptions from `asyncio.gather`
When using `asyncio.gather(*tasks, return_exceptions=True)`, you **must** check results for `Exception` instances and log them. This has been flagged in PRs #10, #14, #16, and #17 — it's the most common review finding.
```python
# BAD - silently drops exceptions
results = await asyncio.gather(*tasks, return_exceptions=True)
for result in results:
    if isinstance(result, dict):
        created.append(result)

# GOOD - log exceptions and track errors
results = await asyncio.gather(*tasks, return_exceptions=True)
for result in results:
    if isinstance(result, dict):
        created.append(result)
    elif isinstance(result, Exception):
        self._record_error()
        self.logger.error(f"Task failed with exception: {result}")
```

#### Update Checkpoint Progress Before Completing a Phase
In the orchestrator, always call `checkpoint.update_phase_count()` after work completes but **before** `_complete_phase()`. If the process is interrupted between `_start_phase` and `_complete_phase`, the checkpoint's `created_count` will still be 0, causing a resume to re-create everything.
```python
# BAD - resume retries all items if interrupted before _complete_phase
templates = self.template_gen.create_templates(spaces, remaining)
self.benchmark.end_phase("templates", len(templates))
self._complete_phase("templates")

# GOOD - checkpoint knows how many were created even if interrupted
templates = self.template_gen.create_templates(spaces, remaining)
self.benchmark.end_phase("templates", len(templates))
if self.checkpoint:
    self.checkpoint.update_phase_count("templates", len(templates))
self._complete_phase("templates")
```

#### Keep Sync and Async Implementations in Parity
When a generator has both sync and async methods, every behavior must exist in both paths: retry logic, checkpoint updates, error handling, request delays. Review both paths together — a fix applied to only one path will be flagged.

#### Use `request_delay` Not Hard-Coded Sleeps
Sync loops between API calls must use `self.request_delay` (passed from CLI `--request-delay`), not hard-coded values like `time.sleep(0.1)`. Hard-coded sleeps ignore user configuration and behave differently from async paths.
```python
# BAD - ignores CLI configuration
time.sleep(0.1)

# GOOD - respects user-configured delay
if self.request_delay > 0:
    time.sleep(self.request_delay)
```

#### Tests Must Assert the Behavior They Claim to Test
Test names and docstrings must match what is actually asserted. A test called `test_type_alternation` that only asserts `is not None` doesn't test alternation. A test called `test_exception_handling` that mocks a 400 response doesn't exercise the exception branch.
```python
# BAD - claims to test alternation but doesn't verify it
def test_create_template_type_alternation(self):
    t0 = generator.create_template("TEST1", 0)
    assert t0 is not None  # Only checks existence

# GOOD - actually verifies the alternation behavior
def test_create_template_type_alternation(self):
    t0 = generator.create_template("TEST1", 0)
    t1 = generator.create_template("TEST1", 1)
    assert t0["templateType"] == "page"
    assert t1["templateType"] == "blogpost"
```

#### Keep Doc Counts Accurate
When CLAUDE.md or PLAN.md reference test counts (e.g., "23 tests"), verify the actual count matches. Run `grep -c "def test_" tests/test_file.py` before writing the number.

### API Integration Gotchas

**Verify endpoints exist before implementing.** Confluence v2/v3 APIs are incomplete—many operations documented for v1 don't exist in newer APIs. Before writing code for a new API call:
1. Check the [Confluence Cloud REST API docs](https://developer.atlassian.com/cloud/confluence/rest/v2/intro/)
2. Test the endpoint manually with `curl` or Postman
3. Be prepared to fall back to v1 (`/rest/api/`) if v2 (`/api/v2/`) doesn't support the operation

When fixing Atlassian/Confluence API issues, always verify **both** the endpoint AND the resource naming conventions. Atlassian Cloud uses site-specific naming that differs from documentation examples:

- **Group names**: Cloud uses `confluence-users-{site-name}` not just `confluence-users`
- **User IDs**: Account IDs are long alphanumeric strings, not usernames
- **Space keys**: Query params for lookup (`?keys=KEY`), not path segments (`/spaces/KEY`)
- **Labels vs Categories**: Both use the same legacy endpoint with different prefixes (`global` vs `team`)

Always test against a real instance after API fixes—mock tests don't catch naming convention issues.

---

## Architecture & Design Patterns

### Core Classes

#### `RateLimitState` (dataclass) - `generators/base.py`
- **Purpose**: Track rate limiting state across API calls (thread-safe for async)
- **Fields**:
  - `retry_after`: Seconds to wait (from Retry-After header)
  - `consecutive_429s`: Count of consecutive rate limit hits
  - `current_delay`: Current exponential backoff delay
  - `max_delay`: Maximum delay cap (60s)
  - `adaptive_delay`: Auto-adjusted delay based on recent 429 rate
  - `_lock`: asyncio.Lock for thread-safe updates in async context

#### `ConfluenceAPIClient` (base class) - `generators/base.py`
- **Purpose**: Base class for all generators with shared API functionality
- **Key Methods**:
  - `_api_call()`: Synchronous API call with rate limiting
  - `_api_call_async()`: Async API call with rate limiting (supports `suppress_errors` param)
  - `_truncate_error_response()`: Truncate HTML/long error responses for clean logging
  - `_create_session()`: Create requests session with connection pooling
  - `_get_async_session()`: Get/create aiohttp session with connection pooling
  - `generate_random_text()`: Get random text from pre-generated pool

#### `CheckpointManager` - `generators/checkpoint.py`
- **Purpose**: Track progress and enable resumable data generation
- **Design Note**: Single-threaded use only (see Thread-Safety above)
- **Key Features**:
  - JSON-based checkpoint file (`confluence_checkpoint_{PREFIX}.json`)
  - Phase-level progress tracking (pending/in_progress/complete)
  - Per-space tracking for pages and blogposts (scales to millions)
  - Atomic file writes (temp file + replace)
  - Content-only mode support

#### `BenchmarkTracker` - `generators/benchmark.py`
- **Purpose**: Track performance metrics and provide time extrapolations
- **Key Features**:
  - Per-phase timing with items/second rate calculation
  - Rate limit (429) and error tracking with percentages
  - Time extrapolation based on observed rates

### Confluence Content Types

Based on `item_type_multipliers.csv`, the tool creates:

| Category | Types |
|----------|-------|
| **Spaces** | space, space_property, space_label, space_permission, space_look_and_feel |
| **Pages** | page, page_label, page_property, page_restriction, page_version |
| **Blogposts** | blogpost, blogpost_label, blogpost_property, blogpost_restriction, blogpost_version |
| **Attachments** | attachment_v2, attachment_label, attachment_version, folder, folder_restriction |
| **Comments** | inline_comment, inline_comment_version, footer_comment, footer_comment_version |
| **Other** | template |

### Phase Order

Generation follows this order (defined in `CheckpointManager.PHASE_ORDER`):
1. spaces → space_properties → space_labels → space_permissions → space_look_and_feel
2. templates
3. pages → page_labels → page_properties → page_restrictions → page_versions
4. blogposts → blogpost_labels → blogpost_properties → blogpost_restrictions → blogpost_versions
5. attachments → attachment_labels → attachment_versions
6. folders → folder_restrictions
7. inline_comments → inline_comment_versions
8. footer_comments → footer_comment_versions

**Content-Only Mode** (`--content-only`): Only creates spaces, pages, and blogposts.

### Rate Limiting Strategy

**Priority Order**:
1. **Primary**: Use `Retry-After` header from Confluence response
2. **Fallback**: Exponential backoff starting at 1s, doubling on each 429
3. **Reset**: Return to 1s delay on successful request
4. **Max**: Cap at 60s delay
5. **Thread-safe**: Uses asyncio.Lock for shared state in async context

**Adaptive Throttling** (async only):
- On 429: Increase `adaptive_delay` by 100ms (caps at 1s)
- On success: Decrease `adaptive_delay` by 10ms every 10 successes
- Jitter: ±20% on rate limit backoff, ±10% on request delay

---

## API Endpoints

### Confluence Cloud REST API v2

**Base URL**: `{confluence_url}/api/v2/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `spaces` | POST | Create space |
| `spaces/{id}` | GET | Get space details |
| `pages` | POST | Create page |
| `pages/{id}` | GET/PUT | Get/update page |
| `blogposts` | POST | Create blogpost |
| `footer-comments` | POST | Create footer comment |
| `inline-comments` | POST | Create inline comment |

### Confluence Cloud REST API v1 (Legacy)

**Base URL**: `{confluence_url}/rest/api/`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `space` | GET | List spaces |
| `space/{key}/label` | POST | Add space label (prefix: `global`) or category (prefix: `team`) |
| `space/{key}/property` | POST | Add space property |
| `user/current` | GET | Get current user |
| `content/{id}/child/attachment` | POST | Upload attachment (multipart form data) |
| `content/{id}/child/attachment/{att_id}/data` | POST | Upload new attachment version (multipart form data) |
| `content/{id}/label` | POST | Add label to content (pages, blogposts, attachments) |
| `template` | POST | Create content template (page or blogpost type) |

**Note on Labels vs Categories**: Both use the same endpoint but with different prefixes in the request body:
- Labels: `[{"prefix": "global", "name": "label-name"}]`
- Categories: `[{"prefix": "team", "name": "category-name"}]`

---

## Testing

### Running Tests

```bash
# Install dependencies (use venv)
.venv/bin/pip install -r requirements-dev.txt

# Run all tests in parallel
.venv/bin/pytest -n auto

# Run with coverage report
.venv/bin/pytest -n auto --cov=generators --cov-report=term-missing

# Run specific test file
.venv/bin/pytest tests/test_checkpoint.py -v

# Run tests matching a pattern
.venv/bin/pytest -k "test_dry_run"
```

### Test Connectivity

Before running the full generator, verify API credentials:

```bash
.venv/bin/python test_connectivity.py
```

### Mocking Strategy

- Sync HTTP calls: `responses` library
- Async HTTP calls: `aioresponses` library
- File I/O: `tmp_path` pytest fixture

### End-to-End Verification

After implementing a fix, verify the complete data flow end-to-end before considering the task complete—especially for user/permission assignments. Mock tests validate API call structure but don't catch:

- Incorrect resource naming conventions (site-specific names)
- Missing or deprecated API endpoints
- Permission/access issues with created resources
- Data format differences between v1 and v2 APIs

When possible, run a quick manual test against a real Confluence instance after fixing API-related issues.

---

## Command Line Options (Planned)

| Option | Required | Description | Default |
|--------|----------|-------------|---------|
| `--url` | Yes | Confluence instance URL | - |
| `--email` | Yes | Atlassian account email | - |
| `--count` | Yes | Target content count | - |
| `--size` | No | Size bucket: small, medium, large | `small` |
| `--prefix` | No | Label/property prefix | `TESTDATA` |
| `--users` | No | Number of synthetic users | `10` |
| `--concurrency` | No | Max concurrent requests | `5` |
| `--request-delay` | No | Base delay between requests | `0.0` |
| `--content-only` | No | Only create spaces, pages, blogposts | `false` |
| `--dry-run` | No | Preview without API calls | `false` |
| `--resume` | No | Resume from checkpoint | `false` |
| `--no-checkpoint` | No | Disable checkpointing | `false` |
| `--no-async` | No | Use synchronous mode | `false` |
| `--verbose` | No | Enable debug logging | `false` |

**Note**: API token is read from `CONFLUENCE_API_TOKEN` environment variable or `.env` file. Never pass tokens via command line.

---

## Size Buckets

Based on [Atlassian's sizing guide](https://confluence.atlassian.com/enterprise/confluence-data-center-load-profiles-946603546.html):

| Bucket | Content (all versions) |
|--------|------------------------|
| S | Up to 500,000 |
| M | 500,000 - 2.5 million |
| L | 2.5 million - 10 million |
| XL | 10 million - 25 million |

---

## Dependencies

### Required
- `aiohttp>=3.9.0`: Async HTTP library
- `python-dotenv>=1.0.0`: Load environment variables
- `requests>=2.31.0`: Sync HTTP library

### Development
- `ruff>=0.4.0`: Linting and formatting
- `pytest>=8.0.0`: Test framework
- `pytest-cov>=4.1.0`: Coverage reporting
- `pytest-asyncio>=0.23.0`: Async test support
- `pytest-xdist>=3.5.0`: Parallel test execution

### Python Version
- **Minimum**: Python 3.12
- **Target**: `py312` (configured in ruff.toml)

### Running Python Tools (IMPORTANT)

This project uses a virtual environment. **Do NOT use system `python`, `pip`, or `ruff`** - they won't work due to Homebrew's PEP 668 restrictions.

**Option 1: Use venv binaries directly (preferred)**
```bash
.venv/bin/python script.py
.venv/bin/ruff check .
.venv/bin/ruff format .
.venv/bin/pytest
```

**Option 2: Use uvx for one-off tool runs**
```bash
uvx ruff check .
uvx ruff format .
uvx pytest
```

**Option 3: Activate the venv first**
```bash
source .venv/bin/activate
python script.py
ruff check .
pytest
```

**Quick reference:**
| Task | Command |
|------|---------|
| Run linter | `.venv/bin/ruff check .` |
| Fix lint issues | `.venv/bin/ruff check --fix .` |
| Check formatting | `.venv/bin/ruff format --check .` |
| Fix formatting | `.venv/bin/ruff format .` |
| Run tests | `.venv/bin/pytest -n auto` |
| Run single test | `.venv/bin/pytest tests/test_file.py -v` |
| Install deps | `.venv/bin/pip install -r requirements.txt` |

---

## Workflow

### After PR Merge

After the user confirms a PR is merged, always:
1. `git checkout main`
2. `git pull origin main`
3. Create a new feature branch for the next task

Never continue working on the old feature branch after its PR is merged.

### Integration Testing Before User Review

Before asking the user to test new functionality, run integration tests yourself using credentials from `.env`:

1. **Run the tool with minimal data** using a unique prefix:
   ```bash
   source .env
   TEST_PREFIX="AITEST$(date +%H%M%S)"
   .venv/bin/python confluence_data_generator.py \
       --url $CONFLUENCE_URL \
       --email $CONFLUENCE_EMAIL \
       --count 1 \
       --spaces 1 \
       --prefix $TEST_PREFIX
   ```

2. **Check output for errors** - any API failures, missing methods, wrong parameters

3. **If errors occur:**
   - Fix the code
   - Delete the test space via API (permanently deleted, not moved to trash)
   - Re-run with the same or new prefix

4. **Clean up after successful test:**
   ```bash
   source .env
   # Delete the space (permanent - does NOT go to trash when deleted via API)
   # Replace AITEST1234561 with actual space key from output
   curl -s -u "$CONFLUENCE_EMAIL:$CONFLUENCE_API_TOKEN" -X DELETE \
       "$CONFLUENCE_URL/rest/api/space/${TEST_PREFIX}1"
   ```

   **Note:** Deleting a space via the REST API permanently removes it — it does **not** go to the trash like UI deletion does. The API returns 202 (accepted) and the space is gone.

This catches issues like wrong method names, incorrect API parameters, and missing async methods before the user wastes time debugging.

### Validate Fixes Before Committing

For Python projects, prefer running quick validation tests or API calls after fixes rather than assuming the change works:

```bash
# Quick unit test validation
.venv/bin/pytest tests/test_specific.py -v -k "test_name"

# Quick syntax/import check
.venv/bin/python -c "from generators.spaces import SpaceGenerator; print('OK')"

# Quick API validation (if credentials available)
.venv/bin/python test_connectivity.py

# Quick lint check
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

This catches issues early—before they're committed and before CI runs.

---

## GitHub CLI (gh) Operations

### Replying to PR Review Comments

When replying to individual review comments (code comments, not general PR comments), use:

```bash
# Correct format - note the -X POST and leading /
gh api -X POST /repos/{owner}/{repo}/pulls/{pr_number}/comments/{comment_id}/replies \
    -f body="Your reply here"
```

**Common mistakes:**
- Missing `-X POST` (defaults to GET, returns 404)
- Missing leading `/` in the path
- Using `repos/` instead of `/repos/`

### Viewing PR Comments

```bash
# Get all review comments (code comments) with their IDs
gh api repos/{owner}/{repo}/pulls/{pr_number}/comments \
    --jq '.[] | "ID: \(.id) | Path: \(.path):\(.line) | Body: \(.body | split("\n")[0])"'

# Get general PR comments (not code comments)
gh pr view {pr_number} --comments
```

### Adding a General PR Comment

```bash
gh pr comment {pr_number} --body "Your comment here"
```

---

## Quick Reference for Common Tasks

### "Add support for [new content type]"

1. Check Confluence API v2 docs for endpoint
2. Decide which generator module (or create new one)
3. Inherit from `ConfluenceAPIClient`
4. Add phase to `CheckpointManager.PHASE_ORDER`
5. Add multiplier key mapping in `CheckpointManager.initialize()`
6. Add tests with mocked responses
7. Update `generators/__init__.py` exports

### "Fix rate limiting issue"

1. Check `ConfluenceAPIClient._handle_rate_limit_async()` for async
2. Check `ConfluenceAPIClient._handle_rate_limit()` for sync
3. Verify asyncio.Lock is used for shared state
4. Adjust `max_delay` or backoff multiplier in `RateLimitState`

### "Add new CLI option"

1. Add to argparse in main orchestrator
2. Pass through to relevant generators
3. Update README.md
4. Update this file's Command Line Options section

### "Complete a task"

Always check documentation before marking complete:

1. **Internal docs**: Update `.ai/plans/` implementation plan (mark status, add learnings)
2. **README.md**: Add/update usage examples, CLI options, feature descriptions
3. **CLAUDE.md**: Update file structure, add patterns/gotchas, update API endpoints
4. **Code docs**: Ensure CLI `--help` text is accurate and helpful

---

**Last Updated**: 2026-02-09
**AI Agent Note**: This file is specifically for you. The user-facing docs are in README.md.
