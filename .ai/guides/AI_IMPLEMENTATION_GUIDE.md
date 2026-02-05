# AI Implementation Guide

Best practices for planning and executing AI-assisted implementations.

## Overview

AI assistants like Claude Code and GitHub Copilot can significantly accelerate development when given proper context and structure. This guide outlines how to effectively plan, execute, and document AI-driven implementations.

## When to Use AI-Driven Implementation

AI assistance is most effective for:

- **New generator modules** - Creating new content type generators following established patterns
- **Repetitive refactoring** - Consistent patterns across many files
- **Test generation** - Unit tests following existing patterns
- **API integration** - Implementing Confluence REST API calls with proper error handling
- **Documentation generation** - API docs, migration guides, README files

## Planning Phase

### 1. Create an Implementation Plan

Before starting, create a detailed plan in `.ai/plans/<initiative-name>/PLAN.md`:

```markdown
# Implementation Plan: <Initiative Name>

## Overview
Brief description of what we're building and why.

## Resources
- Links to API docs, specs, related projects

## Implementation Phases
Break work into logical phases:
- Phase 1: Foundation (setup, configuration)
- Phase 2: Core implementation
- Phase 3: Integration/testing
- Phase 4: Documentation and cleanup

## Success Criteria
How we'll know it's done correctly.
```

### 2. Gather Resources

Before implementation, collect:
- API documentation and endpoint details
- Existing code patterns to follow (e.g., `generators/spaces.py`, `generators/pages.py`)
- Test patterns from existing test files

### 3. Define Scope Boundaries

Clearly define:
- What's in scope for each phase
- Dependencies between phases
- What constitutes "done" for each phase

## Execution Phase

### Test-Driven Development

All implementation follows TDD:
1. Write failing test first
2. Verify the test fails for the right reason
3. Write minimal code to pass
4. Refactor while keeping tests green

### Integration Testing

Before marking any task complete:
1. Run the tool against the real Confluence instance with minimal data
2. Verify API calls succeed (not just unit tests)
3. Clean up test data after verification

### Code Review

- Create PRs with clear descriptions
- Address all review feedback
- Run full test suite before merging

## Documentation

Keep these files updated as work progresses:
- `CLAUDE.md` - Technical patterns, API gotchas, file structure
- `README.md` - User-facing documentation
- `.ai/plans/` - Implementation plan status

## Patterns for This Project

### Adding a New Generator

1. Check Confluence API docs for the endpoint
2. Create `generators/<type>.py` inheriting from `ConfluenceAPIClient`
3. Create `tests/test_<type>.py` with comprehensive tests
4. Wire into `confluence_data_generator.py` orchestrator
5. Add phase to `CheckpointManager.PHASE_ORDER`
6. Update `generators/__init__.py` exports
7. Run integration test against real Confluence instance

### Common API Gotchas

- v2 API is incomplete - many operations require legacy v1 API fallback
- Labels use legacy API: `POST /rest/api/content/{id}/label`
- Concurrent updates to same resource cause 409 conflicts (expected)
- Always test endpoints manually before implementing
