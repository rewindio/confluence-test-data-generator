# Confluence Test Data Generator

[![Tests](https://github.com/rewindio/confluence-test-data-generator/actions/workflows/test.yml/badge.svg)](https://github.com/rewindio/confluence-test-data-generator/actions/workflows/test.yml)
[![Lint](https://github.com/rewindio/confluence-test-data-generator/actions/workflows/lint.yml/badge.svg)](https://github.com/rewindio/confluence-test-data-generator/actions/workflows/lint.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Coverage](https://img.shields.io/badge/coverage-96%25-brightgreen.svg)](https://github.com/rewindio/confluence-test-data-generator)

A Python tool to generate realistic test data for Confluence Cloud instances based on production data multipliers. Intelligently handles rate limiting and uses async concurrency for optimal performance.

## Features

- **Async Concurrency** - Concurrent API requests for faster generation
- **Intelligent Rate Limiting** - Adaptive throttling with exponential backoff
- **Production-Based Multipliers** - Creates realistic data distributions from CSV config derived from thousands of real Confluence backups
- **Easy Cleanup** - All items tagged with labels and properties for easy querying
- **Size-Based Generation** - Supports Small/Medium/Large instance profiles
- **Dry Run Mode** - Preview what will be created without making changes
- **Checkpointing** - Resume interrupted runs for large-scale data generation
- **Benchmarking** - Track timing per phase with time estimates for S/M/L/XL instance sizes
- **Content-Only Mode** - Generate just spaces, pages, and blogposts for scale testing
- **Performance Optimized** - Connection pooling, text pooling, memory-efficient batching

## What Gets Created

Based on the size bucket you choose, the tool creates:

**Spaces:**
- Spaces (with labels, properties, permissions)
- Space look and feel settings
- Templates

**Pages:**
- Pages (with realistic parent-child hierarchy: 60% root, 30% level 1, 10% deeper)
- Page labels, properties, restrictions
- Page versions

**Blog Posts:**
- Blog posts (with labels, properties, restrictions)
- Blog post versions

**Attachments:**
- Attachments (small synthetic files for fast uploads)
- Attachment labels and versions
- Folders and folder restrictions

**Comments:**
- Inline comments (with versions)
- Footer comments (with versions)

**Users & Permissions:**
- Synthetic users (using Gmail "+" trick for verification emails)
- Space permissions via RBAC role assignments (formula: spaces × users × roles)

Most item counts are derived from multipliers in `item_type_multipliers.csv`. **Space permissions are the exception** — they are not in the CSV. Instead, the count is computed dynamically as `num_spaces × num_discovered_users × num_available_roles`. Users are auto-discovered from the Confluence instance, and roles are fetched from the v2 Space Roles API.

## Prerequisites

- Python 3.12 or higher
- An Atlassian Cloud account with admin access
- An Atlassian API token

## Installation

```bash
# Clone the repository
git clone https://github.com/rewindio/confluence-test-data-generator.git
cd confluence-test-data-generator

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt
```

## Setup

### 1. Generate an Atlassian API Token

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token"
3. Give it a name (e.g., "Data Generator")
4. Copy the token (you won't see it again!)

### 2. Configure Your API Token

```bash
# Copy the example file
cp .env.example .env

# Edit .env and add your token
# CONFLUENCE_API_TOKEN=your_actual_token_here
# CONFLUENCE_URL=https://yourcompany.atlassian.net/wiki
# CONFLUENCE_EMAIL=your.email@company.com
```

**Important:** Never pass the token via command line - it should only be in `.env` or environment variables.

## Standalone User Generator

For creating test users separately (before running the main data generator), use the standalone user generator:

```bash
# Generate 5 test users
python confluence_user_generator.py \
  --url https://yourcompany.atlassian.net \
  --email admin@yourcompany.com \
  --base-email youremail@gmail.com \
  --users 5

# Generate users with custom suffix (to avoid collision with Jira sandbox users)
python confluence_user_generator.py \
  --url https://yourcompany.atlassian.net \
  --email admin@yourcompany.com \
  --base-email youremail@gmail.com \
  --users 10 \
  --suffix conftest

# Dry run to preview
python confluence_user_generator.py \
  --url https://yourcompany.atlassian.net \
  --email admin@yourcompany.com \
  --base-email youremail@gmail.com \
  --users 5 \
  --dry-run
```

### User Generator Features

- **Gmail "+" Alias**: Creates emails like `user+confluence1@gmail.com`, `user+confluence2@gmail.com`
- **Auto-Detection**: Automatically detects site name and adds users to correct `confluence-users-{site}` group
- **Confluence Access**: Users automatically get Confluence access via group membership
- **Configurable Suffix**: Use `--suffix` to avoid email collisions (default: "confluence")
- **Group Creation**: Optionally create custom groups with `--groups "Group 1" "Group 2"`

### User Generator CLI Options

| Option | Description | Default |
|--------|-------------|---------|
| `--url` | Confluence/Atlassian URL (required) | - |
| `--email` | Admin email (required) | - |
| `--token` | API token (or use env var) | - |
| `--base-email` | Base email for sandbox users (required) | - |
| `--users` | Number of users to create (required) | - |
| `--suffix` | Email suffix for sandbox users | confluence |
| `--confluence-users-group` | Override auto-detected group | auto |
| `--groups` | Additional groups to create | - |
| `--user-prefix` | Display name prefix | Sandbox |
| `--dry-run` | Preview without creating | false |
| `--verbose` | Enable debug logging | false |

## Usage

### Basic Usage

```bash
# Generate 1000 content items (small instance profile)
python confluence_data_generator.py \
  --url https://yourcompany.atlassian.net/wiki \
  --email your.email@company.com \
  --count 1000
```

### Dry Run (Preview)

```bash
# See what would be created without making any API calls
python confluence_data_generator.py \
  --url https://yourcompany.atlassian.net/wiki \
  --email your.email@company.com \
  --count 10000 \
  --dry-run
```

### Content-Only Mode (For Scale Testing)

```bash
# Only create spaces, pages, and blogposts (skip metadata, comments, attachments)
python confluence_data_generator.py \
  --url https://yourcompany.atlassian.net/wiki \
  --email your.email@company.com \
  --count 1000000 \
  --content-only
```

### Resume Interrupted Run

```bash
# Resume from last checkpoint
python confluence_data_generator.py \
  --url https://yourcompany.atlassian.net/wiki \
  --email your.email@company.com \
  --count 1000000 \
  --resume
```

## CLI Options

| Option | Description | Default |
|--------|-------------|---------|
| `--url` | Confluence Cloud URL (required) | - |
| `--email` | Atlassian account email (required) | - |
| `--count` | Target number of content items — pages + blogposts (required). Other item types (spaces, attachments, comments, etc.) are derived from multipliers in the CSV. | - |
| `--prefix` | Label/property prefix for tagging | TESTDATA |
| `--size` | Size bucket: small, medium, large | small |
| `--spaces` | Override number of spaces (otherwise calculated from multipliers) | auto |
| `--concurrency` | Max concurrent requests | 5 |
| `--request-delay` | Delay between API calls in sync loops (seconds). Useful for throttling on rate-limited instances. | 0.0 |
| `--settling-delay` | Delay before version creation to let Confluence's eventual consistency settle (seconds). Defaults to 0 since retry-on-409 logic handles this automatically; increase if you see excessive 409 retries. | 0.0 |
| `--content-only` | Only create spaces, pages, blogposts | false |
| `--dry-run` | Preview without making API calls | false |
| `--resume` | Resume from checkpoint | false |
| `--no-checkpoint` | Disable checkpointing | false |
| `--no-async` | Use synchronous mode | false |
| `--cleanup` | Delete all test spaces matching the prefix instead of generating data | false |
| `--yes` | Skip confirmation prompt during cleanup | false |
| `--verbose` | Enable debug logging | false |

## Size Buckets

Based on [Atlassian's sizing guide](https://confluence.atlassian.com/enterprise/confluence-data-center-load-profiles-946603546.html):

| Bucket | Content (all versions) |
|--------|------------------------|
| S | Up to 500,000 |
| M | 500,000 - 2.5 million |
| L | 2.5 million - 10 million |
| XL | 10 million - 25 million |

## Item Type Multipliers

The `item_type_multipliers.csv` file contains multipliers derived from analyzing thousands of real Confluence backups. These determine how many of each item type are created relative to the total content count.

For example, with `--count 1000 --size small`:
- ~5 spaces
- ~152 pages
- ~3 blogposts
- ~659 attachments
- ~83 inline comments
- etc.

## Cleanup

Use `--cleanup` to find and delete all test spaces matching your prefix:

```bash
# Show what would be deleted (dry run)
python confluence_data_generator.py \
  --url https://yourcompany.atlassian.net/wiki \
  --email your.email@company.com \
  --cleanup --dry-run \
  --prefix TESTDATA

# Delete with confirmation prompt
python confluence_data_generator.py \
  --url https://yourcompany.atlassian.net/wiki \
  --email your.email@company.com \
  --cleanup \
  --prefix TESTDATA

# Delete without confirmation (useful for CI/scripts)
python confluence_data_generator.py \
  --url https://yourcompany.atlassian.net/wiki \
  --email your.email@company.com \
  --cleanup --yes \
  --prefix TESTDATA
```

Cleanup discovers spaces whose key starts with the first 6 characters of your prefix (e.g., `TESTDA1`, `TESTDA2` for prefix `TESTDATA`), then deletes each via the REST API. Deletion is permanent — spaces do not go to the trash when deleted via API.

## Development

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests
pytest

# Run tests with coverage
pytest --cov=generators --cov-report=term-missing

# Run linting
ruff check .
ruff format .
```

## License

MIT
