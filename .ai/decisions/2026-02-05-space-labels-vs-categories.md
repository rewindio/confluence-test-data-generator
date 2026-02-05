# Decision: Create Both Space Labels and Categories

**Date:** 2026-02-05
**Status:** Accepted
**Context:** Space Generator implementation

## Background

During real-world testing of the Space Generator against Confluence Cloud, we discovered that:

1. **Space labels are deprecated** in Confluence Cloud, replaced by categories
2. The v2 API endpoint `POST /api/v2/spaces/{id}/labels` returns "Method Not Allowed"
3. Labels must be created via the legacy REST API: `POST /rest/api/space/{key}/label`
4. Categories use the v2 API: `POST /api/v2/spaces/{id}/categories`

## Decision

We will create **BOTH** labels and categories when generating test data:

- **Labels**: Created via legacy API for backup compatibility
- **Categories**: Created via v2 API as the current mechanism

When the `--labels` count is specified, both labels AND categories are created in the same ratio (1:1).

## Rationale

1. **Backup Compatibility**: Existing Confluence backups contain space labels. To properly test backup/restore functionality, we need test data that includes labels.

2. **Current Functionality**: New Confluence Cloud instances use categories. Test data should also include categories to test current functionality.

3. **Complete Coverage**: By creating both, we ensure test data covers:
   - Legacy backup formats (labels)
   - Current Confluence Cloud features (categories)
   - Migration scenarios (instances with both)

## Consequences

- Test data generation takes slightly longer (two API calls per "label" count)
- Test data more accurately reflects real-world Confluence instances
- Backup/restore testing covers both legacy and current data formats

## API Endpoints

| Feature | API | Endpoint | Label Prefix |
|---------|-----|----------|--------------|
| Labels (deprecated) | Legacy REST | `POST /rest/api/space/{key}/label` | `global` |
| Categories (current) | Legacy REST | `POST /rest/api/space/{key}/label` | `team` |

**Note:** Categories in Confluence Cloud are implemented as labels with a `team` prefix.
The v2 API does not have a dedicated categories endpoint. Both labels and categories
use the same legacy endpoint but with different prefixes:
- Labels: `[{"prefix": "global", "name": "label-name"}]`
- Categories: `[{"prefix": "team", "name": "category-name"}]`

## Implementation

See `generators/spaces.py`:
- `add_space_label()` / `add_space_label_async()` - Legacy API
- `add_space_category()` / `add_space_category_async()` - v2 API
- `add_space_labels()` / `add_space_labels_async()` - Batch labels
- `add_space_categories()` / `add_space_categories_async()` - Batch categories

The test CLI (`test_space_generator.py`) automatically creates both when `--labels` is specified.
