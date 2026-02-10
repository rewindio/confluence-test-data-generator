# Confluence Test Data Generator - Design Document

## Overview

A CLI tool to generate synthetic Confluence Cloud data at scale (millions of content items) for testing backup systems, performance benchmarks, and load testing.

**Core Architecture:** Mirrors the proven Jira test data generator patterns:

- **Async-first Python** (3.12+) with `aiohttp` for concurrent API calls
- **Modular generators** - Base class handles rate limiting, auth, session management; specialized generators per domain
- **CSV-driven multipliers** - Content counts calculated from `item_type_multipliers.csv` based on `--count` and `--size`
- **Checkpoint/resume** - Atomic JSON checkpoints every 500 items; resume from exact point after failure

## Key Design Decisions

| Decision | Choice |
|----------|--------|
| Platform | Confluence Cloud only (REST API v2) |
| Base unit | `--count` = total content items (matches Confluence "Total content" in Mission Control) |
| Size buckets | small (<500K), medium (500K-2.5M), large (2.5M-10M) per Atlassian definitions |
| Item types | v2 only where both v1/v2 exist |
| Authentication | Email + API token from `.env` or environment variable (never CLI) |
| Default prefix | `TESTDATA` (applied via labels AND content properties) |
| Page hierarchy | Realistic distribution: 60% root, 30% level 1, 10% level 2+ |
| Space permissions | Formula-based: spaces × users × 14 |
| Synthetic users | Gmail "+" trick (e.g., `user+sandbox1@domain.com`) |
| Attachments | Small synthetic files (same pattern as Jira) |
| Rate limiting | Adaptive throttling with exponential backoff (same as Jira) |

## Project Structure

```
confluence-test-data-generator/
├── confluence_data_generator.py      # Main orchestrator & CLI entry point
├── confluence_user_generator.py      # Synthetic user creation (Gmail "+" trick)
├── generators/
│   ├── __init__.py
│   ├── base.py                       # Base API client: auth, rate limiting, sessions
│   ├── spaces.py                     # Spaces, labels, properties, permissions, look-and-feel
│   ├── pages.py                      # Pages, versions, labels, properties, restrictions
│   ├── blogposts.py                  # Blog posts, versions, labels, properties, restrictions
│   ├── attachments.py                # Attachments, versions, labels, folders
│   ├── comments.py                   # Inline comments, footer comments, versions
│   ├── templates.py                  # Space and global templates
│   ├── checkpoint.py                 # Resume/checkpoint management
│   └── benchmark.py                  # Performance tracking & reporting
├── item_type_multipliers.csv         # Multipliers by size bucket (already exists)
├── requirements.txt                  # aiohttp, python-dotenv, requests
├── .env.example                      # Template for credentials
├── logs/                             # Log files (auto-created)
│   └── confluence_{prefix}_{timestamp}.log
├── checkpoints/                      # Checkpoint files (auto-created)
│   └── confluence_checkpoint_{prefix}.json
└── tests/
    ├── __init__.py
    ├── test_generators.py
    └── test_checkpoint.py
```

## CLI Interface

```bash
python confluence_data_generator.py \
  --url https://mycompany.atlassian.net/wiki   # Required: Confluence Cloud URL
  --email user@company.com                      # Required: Atlassian account email
  --count 10000                                 # Required: target content count
  --size small                                  # Optional: small/medium/large (default: small)
  --prefix TESTDATA                             # Optional: label/property prefix (default: TESTDATA)
  --users 10                                    # Optional: number of synthetic users to create
  --concurrency 5                               # Optional: max concurrent requests (default: 5)
  --request-delay 0.05                          # Optional: base delay between requests
  --content-only                                # Optional: only create spaces, pages, blogposts
  --dry-run                                     # Optional: preview counts without API calls
  --resume                                      # Optional: resume from checkpoint
  --no-checkpoint                               # Optional: disable checkpointing
  --no-async                                    # Optional: sequential mode (for debugging)
  --verbose                                     # Optional: debug logging
```

**Token:** Loaded only from `.env` file (`CONFLUENCE_API_TOKEN`) or environment variable - never from CLI args.

**Priority:** CLI args > `.env` file > environment variables

## Content Types & Generation Order

Generation respects dependencies. All item types use v2 where both v1/v2 exist.

| Phase | Item Types | Dependencies | Skipped with `--content-only` |
|-------|-----------|--------------|-------------------------------|
| 1. Users | Synthetic users | None | No |
| 2. Spaces | `space_v2` | None | No |
| 3. Space config | `space_label_v2`, `space_property_v2`, `space_custom_look_and_feel`, `space_look_and_feel_setting`, `space_theme` | Spaces | Yes |
| 4. Space permissions | `space_permission_v2` (formula: spaces × users × 14) | Spaces, Users | Yes |
| 5. Folders | `folder`, `folder_restriction` | Spaces | Yes |
| 6. Pages | `page_v2` (with hierarchy) | Spaces | No |
| 7. Page metadata | `page_label_v2`, `page_property_v2`, `page_restriction_v2` | Pages | Yes |
| 8. Page versions | `page_version_v2` | Pages | Yes |
| 9. Blog posts | `blogpost_v2` | Spaces | No |
| 10. Blog post metadata | `blogpost_label_v2`, `blogpost_property_v2`, `blogpost_restriction_v2` | Blog posts | Yes |
| 11. Blog post versions | `blogpost_version_v2` | Blog posts | Yes |
| 12. Attachments | `attachment_v2`, `attachment_v2_content` | Pages, Blog posts | Yes |
| 13. Attachment metadata | `attachment_label_v2` | Attachments | Yes |
| 14. Attachment versions | `attachment_version_v2` | Attachments | Yes |
| 15. Comments | `inline_comment_v2`, `footer_comment_v2` | Pages, Blog posts | Yes |
| 16. Comment versions | `inline_comment_version_v2`, `footer_comment_version_v2` | Comments | Yes |
| 17. Templates | `template` | Spaces | Yes |

## Page Hierarchy Distribution

Realistic nesting to match typical wiki structures:

- **60% root pages** - Direct children of space
- **30% level 1** - Children of root pages
- **10% level 2+** - Deeper nesting

Implementation: As pages are created, randomly assign parents from already-created pages in the same space, weighted by this distribution.

## Rate Limiting & Concurrency

Same proven approach as Jira generator:

### RateLimitState (Shared Across Async Tasks)

```python
@dataclass
class RateLimitState:
    retry_after: Optional[float] = None
    consecutive_429s: int = 0
    current_delay: float = 1.0
    max_delay: float = 60.0
    _lock: asyncio.Lock  # Thread-safe updates
    _cooldown_until: float = 0.0  # Global cooldown timestamp
    adaptive_delay: float = 0.0  # Increases on 429s
    recent_429_count: int = 0
    recent_success_count: int = 0
```

### Strategy

1. **Respect `Retry-After` headers** - Use server-specified delay when provided
2. **Exponential backoff** - On 429 without header: 1s → 2s → 4s → ... → 60s cap
3. **Global cooldown** - All concurrent requests wait when rate limited
4. **Adaptive throttling** - On 429: +0.1s delay; on 10 successes: -0.01s delay
5. **Jitter** - ±20% randomization prevents thundering herd
6. **Semaphore concurrency** - Limit concurrent requests (default: 5)

### Connection Pooling

```python
# Async
connector = aiohttp.TCPConnector(
    limit=100,
    limit_per_host=50,
    ttl_dns_cache=300,
    enable_cleanup_closed=True
)
```

## Checkpointing & Resume

- Atomic JSON writes (write to `.tmp`, then rename)
- Save every 500 items per phase
- Track phase status: `pending` → `in_progress` → `complete`
- Store created item IDs for resume
- `--resume` flag continues from last checkpoint
- `--no-checkpoint` disables for small test runs

**Checkpoint file location:** `checkpoints/confluence_checkpoint_{prefix}.json`

## User Generation

`confluence_user_generator.py` creates synthetic users:

- Takes base email (e.g., `admin@yourcompany.com`)
- Generates `admin+sandbox1@yourcompany.com`, `admin+sandbox2@yourcompany.com`, etc.
- `--users N` flag controls count (default: 10)
- Users created in phase 1, before space permissions

## Content Tagging

All generated content is tagged for easy identification and cleanup:

- **Labels**: `TESTDATA` (or custom prefix) applied to spaces, pages, blogposts, attachments
- **Content properties**: `testdata.generator` property with metadata (run ID, timestamp, prefix)

This enables bulk queries and cleanup via Confluence search/API.

## Benchmark & Reporting

Same pattern as Jira:

- Track requests, rate limits, errors per phase
- ETA extrapolation based on current rate
- Summary report at completion
- `--verbose` for detailed logging

**Log file location:** `logs/confluence_{prefix}_{timestamp}.log`

## Text Generation Pool

For performance at scale (millions of items):

- Pre-generate 1000 text strings per size category (short/medium/long)
- O(1) lookup instead of generating each time
- ~38x faster text generation at scale

## Dependencies

```
aiohttp>=3.9.0
python-dotenv>=1.0.0
requests>=2.31.0
```

## Example Usage

### Full hierarchy (small instance)

```bash
python confluence_data_generator.py \
  --url https://mycompany.atlassian.net/wiki \
  --email admin@yourcompany.com \
  --count 10000 \
  --size small \
  --users 20
```

### Core content only (for scale testing)

```bash
python confluence_data_generator.py \
  --url https://mycompany.atlassian.net/wiki \
  --email admin@yourcompany.com \
  --count 1000000 \
  --size medium \
  --content-only \
  --concurrency 10
```

### Resume interrupted run

```bash
python confluence_data_generator.py \
  --url https://mycompany.atlassian.net/wiki \
  --email admin@yourcompany.com \
  --count 1000000 \
  --resume
```

### Dry run (preview counts)

```bash
python confluence_data_generator.py \
  --url https://mycompany.atlassian.net/wiki \
  --email admin@yourcompany.com \
  --count 100000 \
  --dry-run
```
