#!/usr/bin/env python3
"""
Confluence Test Data Generator

Generates realistic test data for Confluence Cloud instances based on multipliers
from production data. Handles rate limiting intelligently and uses async for
high-volume content creation.
"""

import argparse
import asyncio
import csv
import logging
import math
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from generators.attachments import AttachmentGenerator
from generators.benchmark import BenchmarkTracker
from generators.blogposts import BlogPostGenerator
from generators.checkpoint import CheckpointManager
from generators.comments import CommentGenerator
from generators.folders import FolderGenerator
from generators.pages import PageGenerator
from generators.spaces import SpaceGenerator
from generators.templates import TemplateGenerator


def load_multipliers_from_csv(csv_path: str | None = None) -> dict[str, dict[str, float]]:
    """Load multipliers from CSV file.

    Returns dict keyed by size bucket (small, medium, large),
    with each value being a dict of item_type -> multiplier.
    """
    if csv_path is None:
        csv_path = Path(__file__).parent / "item_type_multipliers.csv"

    multipliers = {"small": {}, "medium": {}, "large": {}}

    size_map = {"Small": "small", "Medium": "medium", "Large": "large"}

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            item_type = row["Item Type"]
            for csv_col, size_key in size_map.items():
                value = row.get(csv_col, "").strip()
                if value:
                    try:
                        multipliers[size_key][item_type] = float(value)
                    except ValueError:
                        logging.warning(
                            "Invalid multiplier '%s' for item type '%s' and size bucket '%s' in CSV '%s'; skipping value",
                            value,
                            item_type,
                            size_key,
                            csv_path,
                        )

    return multipliers


# Load multipliers from CSV file at module load
MULTIPLIERS = load_multipliers_from_csv()


def calculate_counts(content_count: int, size_bucket: str, content_only: bool = False) -> dict[str, int]:
    """Calculate item counts based on multipliers and target content count.

    Args:
        content_count: Target number of content items (pages + blogposts)
        size_bucket: Size bucket (small, medium, large)
        content_only: If True, only calculate spaces, pages, and blogposts

    Returns:
        Dict mapping item type to count
    """
    multipliers = MULTIPLIERS[size_bucket]
    counts = {}

    # Items to include when content_only is True
    content_only_items = {"space", "space_v2", "page", "page_v2", "blogpost", "blogpost_v2"}

    for item_type, multiplier in multipliers.items():
        if content_only and item_type not in content_only_items:
            counts[item_type] = 0
        else:
            raw_count = content_count * multiplier
            counts[item_type] = max(1, math.ceil(raw_count))

    return counts


class ConfluenceDataGenerator:
    """Main orchestrator for Confluence test data generation.

    Coordinates all generators and manages the generation workflow including
    checkpointing, benchmarking, and phase ordering.
    """

    def __init__(
        self,
        confluence_url: str,
        email: str,
        api_token: str,
        prefix: str = "TESTDATA",
        size_bucket: str = "small",
        dry_run: bool = False,
        concurrency: int = 5,
        request_delay: float = 0.0,
        settling_delay: float = 1.0,
        content_only: bool = False,
        checkpoint_manager: CheckpointManager | None = None,
    ):
        """Initialize the data generator.

        Args:
            confluence_url: Confluence Cloud URL
            email: Atlassian account email
            api_token: Confluence API token
            prefix: Prefix for labels and properties
            size_bucket: Size bucket (small, medium, large)
            dry_run: If True, don't make API calls
            concurrency: Number of concurrent requests
            request_delay: Delay between requests in seconds
            settling_delay: Delay before version creation in seconds
            content_only: If True, only create spaces, pages, blogposts
            checkpoint_manager: Optional checkpoint manager for resumable runs
        """
        self.confluence_url = confluence_url.rstrip("/")
        self.email = email
        self.api_token = api_token
        self.prefix = prefix
        self.size_bucket = size_bucket.lower()
        self.dry_run = dry_run
        self.concurrency = concurrency
        self.request_delay = request_delay
        self.settling_delay = settling_delay
        self.content_only = content_only
        self.checkpoint = checkpoint_manager

        self.logger = logging.getLogger(__name__)

        # Generate unique run ID (may be overridden by checkpoint)
        self.run_id = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        # Validate size bucket
        if self.size_bucket not in MULTIPLIERS:
            raise ValueError(f"Invalid size bucket. Must be one of: {', '.join(MULTIPLIERS.keys())}")

        # Initialize benchmark tracker
        self.benchmark = BenchmarkTracker()

        # Discovered user account IDs (populated during generation)
        self.user_account_ids: list[str] = []

        # Initialize generators
        self._init_generators()

    def _init_generators(self):
        """Initialize all generator modules."""
        common_args = {
            "confluence_url": self.confluence_url,
            "email": self.email,
            "api_token": self.api_token,
            "dry_run": self.dry_run,
            "concurrency": self.concurrency,
            "benchmark": self.benchmark,
            "request_delay": self.request_delay,
            "settling_delay": self.settling_delay,
        }

        # Initialize space generator
        self.space_gen = SpaceGenerator(prefix=self.prefix, **common_args)

        # Initialize page generator
        self.page_gen = PageGenerator(prefix=self.prefix, **common_args)

        # Initialize blogpost generator
        self.blogpost_gen = BlogPostGenerator(prefix=self.prefix, **common_args)

        # Initialize attachment generator
        self.attachment_gen = AttachmentGenerator(prefix=self.prefix, **common_args)

        # Initialize comment generator
        self.comment_gen = CommentGenerator(prefix=self.prefix, **common_args)

        # Initialize folder generator
        self.folder_gen = FolderGenerator(prefix=self.prefix, **common_args)

        # Initialize template generator
        self.template_gen = TemplateGenerator(prefix=self.prefix, **common_args)

    def _log_header(self, counts: dict[str, int]):
        """Log generation plan header."""
        self.logger.info("=" * 60)
        self.logger.info("GENERATION PLAN")
        self.logger.info("=" * 60)
        self.logger.info(f"Run ID: {self.run_id}")
        self.logger.info(f"Size bucket: {self.size_bucket}")
        self.logger.info(f"Content-only mode: {self.content_only}")
        self.logger.info("")
        self.logger.info("Planned counts:")
        for item_type, count in sorted(counts.items()):
            if count > 0:
                self.logger.info(f"  {item_type}: {count:,}")
        self.logger.info("=" * 60)

    def _log_footer(self):
        """Log summary footer with benchmark results."""
        # get_summary_report() includes its own header/dividers
        self.logger.info(self.benchmark.get_summary_report())
        # Show time estimates for Atlassian-defined instance sizes
        size_report = self.benchmark.format_size_tier_extrapolations()
        if size_report:
            self.logger.info(size_report)

    # ========== Checkpoint Helper Methods ==========

    def _is_phase_complete(self, phase: str) -> bool:
        """Check if a phase is complete in the checkpoint."""
        if not self.checkpoint or not self.checkpoint.checkpoint:
            return False
        return self.checkpoint.is_phase_complete(phase)

    def _start_phase(self, phase: str):
        """Mark a phase as started in the checkpoint."""
        if self.checkpoint:
            self.checkpoint.start_phase(phase)

    def _complete_phase(self, phase: str):
        """Mark a phase as complete in the checkpoint."""
        if self.checkpoint:
            self.checkpoint.complete_phase(phase)

    def _get_remaining_count(self, phase: str, total: int) -> int:
        """Get remaining items to create for a phase."""
        if not self.checkpoint or not self.checkpoint.checkpoint:
            return total
        progress = self.checkpoint.get_phase_progress(phase)
        if progress:
            return max(0, total - progress.created_count)
        return total

    def _init_or_resume_checkpoint(self, content_count: int, counts: dict[str, int], async_mode: bool) -> bool:
        """Initialize checkpoint for new run or prepare for resume.

        Returns True if resuming from existing checkpoint.
        """
        if not self.checkpoint:
            return False

        # Check if we're resuming (checkpoint was pre-loaded)
        if self.checkpoint.checkpoint is not None:
            # Use run_id from checkpoint
            self.run_id = self.checkpoint.checkpoint.run_id
            self.logger.info("\n" + "=" * 60)
            self.logger.info("RESUMING FROM CHECKPOINT")
            self.logger.info("=" * 60)
            self.logger.info(self.checkpoint.get_resume_summary())
            self.logger.info("=" * 60 + "\n")
            return True

        # Initialize new checkpoint
        self.checkpoint.initialize(
            run_id=self.run_id,
            size=self.size_bucket,
            target_content_count=content_count,
            confluence_url=self.confluence_url,
            async_mode=async_mode,
            concurrency=self.concurrency,
            counts=counts,
        )
        return False

    # ========== Sync Generation Methods ==========

    def generate_sync(self, content_count: int, counts: dict[str, int]):
        """Generate all test data synchronously.

        Args:
            content_count: Target number of content items
            counts: Pre-calculated item counts by type
        """
        self._init_or_resume_checkpoint(content_count, counts, async_mode=False)
        self._log_header(counts)

        # Phase 1: Create spaces
        spaces = self._create_spaces_sync(counts)

        if not spaces:
            self.logger.error("No spaces created, cannot continue")
            return

        # Discover users for permissions/restrictions
        if not self.content_only:
            self.user_account_ids = self.space_gen.get_all_users(max_users=100)
            if self.user_account_ids:
                self.logger.info(f"Discovered {len(self.user_account_ids)} users for permissions/restrictions")
            else:
                self.logger.warning("No users discovered - space permissions and restrictions will be skipped")

        # Phase 2: Create space-related items (labels, properties, permissions)
        if not self.content_only:
            self._create_space_items_sync(spaces, counts)

        # Phase 3: Create pages
        pages = self._create_pages_sync(spaces, counts)

        # Phase 4: Create page-related items
        if pages and not self.content_only:
            self._create_page_items_sync(pages, counts)

        # Phase 5: Create blogposts
        blogposts = self._create_blogposts_sync(spaces, counts)

        # Phase 6: Create blogpost-related items
        if blogposts and not self.content_only:
            self._create_blogpost_items_sync(blogposts, counts)

        # Phase 7: Create attachments
        all_content_ids = [p["id"] for p in pages] + [bp["id"] for bp in blogposts]
        if all_content_ids and not self.content_only:
            attachments = self._create_attachments_sync(all_content_ids, counts)

            # Phase 7b: Attachment-related items
            if attachments:
                self._create_attachment_items_sync(attachments, counts)

        # Phase 7c: Create folders
        if not self.content_only:
            folders = self._create_folders_sync(spaces, counts)
            if folders:
                self._create_folder_restrictions_sync(folders, counts)

        # Phase 8: Create comments
        page_id_list = [p["id"] for p in pages] if pages else []
        if page_id_list and not self.content_only:
            inline_comments = self._create_inline_comments_sync(page_id_list, counts)
            if inline_comments:
                self._create_inline_comment_versions_sync(inline_comments, counts)

            footer_comments = self._create_footer_comments_sync(page_id_list, counts)
            if footer_comments:
                self._create_footer_comment_versions_sync(footer_comments, counts)

        # Create templates
        if not self.content_only:
            self._create_templates_sync(spaces, counts)

        self._log_footer()

    def _create_folders_sync(self, spaces: list[dict], counts: dict[str, int]) -> list[dict]:
        """Create folders synchronously.

        Returns list of created folder dicts with keys: id, title, spaceId
        """
        if self._is_phase_complete("folders"):
            return []

        num_folders = counts.get("folder", 0)
        if num_folders <= 0:
            return []

        self._start_phase("folders")
        remaining = self._get_remaining_count("folders", num_folders)

        if remaining <= 0:
            self._complete_phase("folders")
            return []

        self.logger.info(f"\nCreating {remaining} folders...")
        self.benchmark.start_phase("folders", remaining)

        folders = self.folder_gen.create_folders(spaces, remaining)

        self.benchmark.end_phase("folders", len(folders))
        if self.checkpoint:
            self.checkpoint.update_phase_count("folders", len(folders))
        self._complete_phase("folders")

        self.logger.info(f"Created {len(folders)} folders")
        return folders

    def _create_folder_restrictions_sync(self, folders: list[dict], counts: dict[str, int]):
        """Create folder restrictions synchronously."""
        if self._is_phase_complete("folder_restrictions"):
            return

        num_restrictions = counts.get("folder_restriction", 0)
        if num_restrictions <= 0 or not self.user_account_ids:
            self._complete_phase("folder_restrictions")
            return

        folder_ids = [f["id"] for f in folders]

        self._start_phase("folder_restrictions")
        self.logger.info(f"\nCreating {num_restrictions} folder restrictions...")
        self.benchmark.start_phase("folder_restrictions", num_restrictions)

        created = self.folder_gen.add_folder_restrictions(folder_ids, self.user_account_ids, num_restrictions)

        self.benchmark.end_phase("folder_restrictions", created)
        if self.checkpoint:
            self.checkpoint.update_phase_count("folder_restrictions", created)
        self._complete_phase("folder_restrictions")
        self.logger.info(f"Created {created} folder restrictions")

    def _create_templates_sync(self, spaces: list[dict], counts: dict[str, int]) -> int:
        """Create templates synchronously.

        Returns number of templates created.
        """
        if self._is_phase_complete("templates"):
            return 0

        num = counts.get("template", 0)
        if num <= 0:
            return 0

        self._start_phase("templates")
        remaining = self._get_remaining_count("templates", num)

        if remaining <= 0:
            self._complete_phase("templates")
            return 0

        self.logger.info(f"\nCreating {remaining} templates...")
        self.benchmark.start_phase("templates", remaining)

        templates = self.template_gen.create_templates(spaces, remaining)

        self.benchmark.end_phase("templates", len(templates))
        if self.checkpoint:
            self.checkpoint.update_phase_count("templates", len(templates))
        self._complete_phase("templates")

        self.logger.info(f"Created {len(templates)} templates")
        return len(templates)

    def _create_spaces_sync(self, counts: dict[str, int]) -> list[dict]:
        """Create spaces synchronously.

        Returns list of created space dicts with keys: key, id, name
        """
        if self._is_phase_complete("spaces"):
            # Restore spaces from checkpoint
            if self.checkpoint and self.checkpoint.checkpoint:
                space_keys = self.checkpoint.checkpoint.space_keys
                space_ids = self.checkpoint.checkpoint.space_ids
                if space_keys and space_ids:
                    self.logger.info(f"Restored {len(space_keys)} spaces from checkpoint")
                    return [{"key": key, "id": space_id} for key, space_id in zip(space_keys, space_ids, strict=True)]
            return []

        self._start_phase("spaces")

        # Get space count - use space_v2 or space
        num_spaces = counts.get("space_v2", counts.get("space", 1))
        remaining = self._get_remaining_count("spaces", num_spaces)

        if remaining <= 0:
            self._complete_phase("spaces")
            return []

        self.logger.info(f"\nCreating {remaining} spaces...")
        self.benchmark.start_phase("spaces", remaining)

        spaces = self.space_gen.create_spaces(remaining)

        self.benchmark.end_phase("spaces", len(spaces))

        # Update checkpoint with created spaces
        if self.checkpoint and spaces:
            for space in spaces:
                self.checkpoint.add_space(space["key"], space["id"])

        self._complete_phase("spaces")

        self.logger.info(f"Created {len(spaces)} spaces")
        return spaces

    def _create_space_items_sync(self, spaces: list[dict], counts: dict[str, int]):
        """Create space-related items (labels, properties, permissions) synchronously."""
        space_keys = [s["key"] for s in spaces]

        # Space labels (and categories)
        if not self._is_phase_complete("space_labels"):
            num_labels = counts.get("space_label_v2", 0)
            if num_labels > 0:
                self._start_phase("space_labels")
                labels_per_space = max(1, num_labels // len(spaces))
                total_labels = labels_per_space * len(spaces)

                self.logger.info(f"\nCreating {total_labels} space labels ({labels_per_space} per space)...")
                self.benchmark.start_phase("space_labels", total_labels)

                created = 0
                for space_key in space_keys:
                    result = self.space_gen.add_space_labels([space_key], labels_per_space)
                    created += result

                self.benchmark.end_phase("space_labels", created)
                self._complete_phase("space_labels")
                self.logger.info(f"Created {created} space labels")

        # Space properties - uses space IDs not keys
        if not self._is_phase_complete("space_properties"):
            num_props = counts.get("space_property_v2", 0)
            if num_props > 0:
                self._start_phase("space_properties")
                props_per_space = max(1, num_props // len(spaces))
                total_props = props_per_space * len(spaces)

                self.logger.info(f"\nCreating {total_props} space properties ({props_per_space} per space)...")
                self.benchmark.start_phase("space_properties", total_props)

                created = 0
                space_ids = [s["id"] for s in spaces]
                for space_id in space_ids:
                    result = self.space_gen.set_space_properties([space_id], props_per_space)
                    created += result

                self.benchmark.end_phase("space_properties", created)
                self._complete_phase("space_properties")
                self.logger.info(f"Created {created} space properties")

        # Space permissions via role assignments (v2 RBAC API)
        if not self._is_phase_complete("space_permissions"):
            if self.user_account_ids:
                roles = self.space_gen.get_space_roles()
                num_roles = len(roles) if roles else 5
                num_perms = len(spaces) * len(self.user_account_ids) * num_roles
                self._start_phase("space_permissions")

                self.logger.info(
                    f"\nCreating {num_perms} space permissions "
                    f"({len(spaces)} spaces × {len(self.user_account_ids)} users × {num_roles} roles)..."
                )
                self.benchmark.start_phase("space_permissions", num_perms)

                space_ids = [s["id"] for s in spaces]
                created = self.space_gen.add_space_permissions(space_ids, self.user_account_ids, num_perms)

                self.benchmark.end_phase("space_permissions", created)
                if self.checkpoint:
                    self.checkpoint.update_phase_count("space_permissions", created)
                self._complete_phase("space_permissions")
                self.logger.info(f"Created {created} space permissions")

    def _create_pages_sync(self, spaces: list[dict], counts: dict[str, int]) -> list[dict]:
        """Create pages synchronously.

        Returns list of created page dicts with keys: id, title, spaceId
        """
        if self._is_phase_complete("pages"):
            # Restore pages from checkpoint
            if self.checkpoint and self.checkpoint.checkpoint:
                page_ids = self.checkpoint.checkpoint.page_ids
                if page_ids:
                    self.logger.info(f"Restored {len(page_ids)} pages from checkpoint")
                    return [{"id": pid, "title": f"Page {pid}"} for pid in page_ids]
            return []

        self._start_phase("pages")

        num_pages = counts.get("page_v2", counts.get("page", 0))
        remaining = self._get_remaining_count("pages", num_pages)

        if remaining <= 0:
            self._complete_phase("pages")
            return []

        self.logger.info(f"\nCreating {remaining} pages...")
        self.benchmark.start_phase("pages", remaining)

        pages = self.page_gen.create_pages(spaces, remaining)

        self.benchmark.end_phase("pages", len(pages))

        # Update checkpoint with created pages (grouped by space key, not space ID)
        if self.checkpoint and pages:
            space_id_to_key: dict[str, str] = {
                space["id"]: space["key"] for space in spaces if "id" in space and "key" in space
            }

            pages_by_space: dict[str, list[str]] = {}
            for page in pages:
                space_id = page.get("spaceId")
                space_key = space_id_to_key.get(space_id, "unknown")
                pages_by_space.setdefault(space_key, []).append(page["id"])
            for space_key, page_ids in pages_by_space.items():
                self.checkpoint.add_page_ids(page_ids, space_key)
            self.checkpoint.save()

        self._complete_phase("pages")

        self.logger.info(f"Created {len(pages)} pages")
        return pages

    def _create_page_items_sync(self, pages: list[dict], counts: dict[str, int]):
        """Create page-related items (labels, properties, restrictions, versions) synchronously."""
        page_ids = [p["id"] for p in pages]

        # Page labels
        if not self._is_phase_complete("page_labels"):
            num_labels = counts.get("page_label_v2", 0)
            if num_labels > 0:
                self._start_phase("page_labels")
                self.logger.info(f"\nCreating {num_labels} page labels...")
                self.benchmark.start_phase("page_labels", num_labels)

                created = self.page_gen.add_page_labels(page_ids, num_labels)

                self.benchmark.end_phase("page_labels", created)
                self._complete_phase("page_labels")
                self.logger.info(f"Created {created} page labels")

        # Page properties
        if not self._is_phase_complete("page_properties"):
            num_props = counts.get("page_property_v2", 0)
            if num_props > 0:
                self._start_phase("page_properties")
                self.logger.info(f"\nCreating {num_props} page properties...")
                self.benchmark.start_phase("page_properties", num_props)

                created = self.page_gen.set_page_properties(page_ids, num_props)

                self.benchmark.end_phase("page_properties", created)
                self._complete_phase("page_properties")
                self.logger.info(f"Created {created} page properties")

        # Page restrictions - uses v1 REST API with user account IDs
        if not self._is_phase_complete("page_restrictions"):
            num_restrictions = counts.get("page_restriction_v2", 0)
            if num_restrictions > 0 and self.user_account_ids and pages:
                self._start_phase("page_restrictions")
                self.logger.info(f"\nCreating {num_restrictions} page restrictions...")
                self.benchmark.start_phase("page_restrictions", num_restrictions)

                created = self.page_gen.add_page_restrictions(page_ids, self.user_account_ids, num_restrictions)

                self.benchmark.end_phase("page_restrictions", created)
                if self.checkpoint:
                    self.checkpoint.update_phase_count("page_restrictions", created)
                self._complete_phase("page_restrictions")
                self.logger.info(f"Created {created} page restrictions")
            else:
                self._complete_phase("page_restrictions")

        # Page versions
        if not self._is_phase_complete("page_versions"):
            num_versions = counts.get("page_version_v2", 0)
            if num_versions > 0:
                self._start_phase("page_versions")
                self.logger.info(f"\nCreating {num_versions} page versions...")
                self.benchmark.start_phase("page_versions", num_versions)

                created = self.page_gen.create_page_versions(pages, num_versions)

                self.benchmark.end_phase("page_versions", created)
                self._complete_phase("page_versions")
                self.logger.info(f"Created {created} page versions")

    def _create_blogposts_sync(self, spaces: list[dict], counts: dict[str, int]) -> list[dict]:
        """Create blogposts synchronously.

        Returns list of created blogpost dicts with keys: id, title, spaceId
        """
        if self._is_phase_complete("blogposts"):
            if self.checkpoint and self.checkpoint.checkpoint:
                blogpost_ids = self.checkpoint.checkpoint.blogpost_ids
                if blogpost_ids:
                    self.logger.info(f"Restored {len(blogpost_ids)} blogposts from checkpoint")
                    return [{"id": bid, "title": f"Blog Post {bid}"} for bid in blogpost_ids]
            return []

        self._start_phase("blogposts")

        num_blogposts = counts.get("blogpost_v2", counts.get("blogpost", 0))
        remaining = self._get_remaining_count("blogposts", num_blogposts)

        if remaining <= 0:
            self._complete_phase("blogposts")
            return []

        self.logger.info(f"\nCreating {remaining} blogposts...")
        self.benchmark.start_phase("blogposts", remaining)

        blogposts = self.blogpost_gen.create_blogposts(spaces, remaining)

        self.benchmark.end_phase("blogposts", len(blogposts))

        # Update checkpoint with created blogposts
        if self.checkpoint and blogposts:
            space_id_to_key: dict[str, str] = {
                space["id"]: space["key"] for space in spaces if "id" in space and "key" in space
            }

            blogposts_by_space: dict[str, list[str]] = {}
            for bp in blogposts:
                space_id = bp.get("spaceId")
                space_key = space_id_to_key.get(space_id, "unknown")
                blogposts_by_space.setdefault(space_key, []).append(bp["id"])
            for space_key, bp_ids in blogposts_by_space.items():
                self.checkpoint.add_blogpost_ids(bp_ids, space_key)
            self.checkpoint.save()

        self._complete_phase("blogposts")

        self.logger.info(f"Created {len(blogposts)} blogposts")
        return blogposts

    def _create_blogpost_items_sync(self, blogposts: list[dict], counts: dict[str, int]):
        """Create blogpost-related items (labels, properties, restrictions, versions) synchronously."""
        blogpost_ids = [bp["id"] for bp in blogposts]

        # Blogpost labels
        if not self._is_phase_complete("blogpost_labels"):
            num_labels = counts.get("blogpost_label_v2", counts.get("blogpost_label", 0))
            if num_labels > 0:
                self._start_phase("blogpost_labels")
                self.logger.info(f"\nCreating {num_labels} blogpost labels...")
                self.benchmark.start_phase("blogpost_labels", num_labels)

                created = self.blogpost_gen.add_blogpost_labels(blogpost_ids, num_labels)

                self.benchmark.end_phase("blogpost_labels", created)
                self._complete_phase("blogpost_labels")
                self.logger.info(f"Created {created} blogpost labels")

        # Blogpost properties
        if not self._is_phase_complete("blogpost_properties"):
            num_props = counts.get("blogpost_property_v2", counts.get("blogpost_property", 0))
            if num_props > 0:
                self._start_phase("blogpost_properties")
                self.logger.info(f"\nCreating {num_props} blogpost properties...")
                self.benchmark.start_phase("blogpost_properties", num_props)

                created = self.blogpost_gen.set_blogpost_properties(blogpost_ids, num_props)

                self.benchmark.end_phase("blogpost_properties", created)
                self._complete_phase("blogpost_properties")
                self.logger.info(f"Created {created} blogpost properties")

        # Blogpost restrictions - uses v1 REST API with user account IDs
        if not self._is_phase_complete("blogpost_restrictions"):
            num_restrictions = counts.get("blogpost_restriction_v2", 0)
            if num_restrictions > 0 and self.user_account_ids and blogposts:
                self._start_phase("blogpost_restrictions")
                self.logger.info(f"\nCreating {num_restrictions} blogpost restrictions...")
                self.benchmark.start_phase("blogpost_restrictions", num_restrictions)

                created = self.blogpost_gen.add_blogpost_restrictions(
                    blogpost_ids, self.user_account_ids, num_restrictions
                )

                self.benchmark.end_phase("blogpost_restrictions", created)
                if self.checkpoint:
                    self.checkpoint.update_phase_count("blogpost_restrictions", created)
                self._complete_phase("blogpost_restrictions")
                self.logger.info(f"Created {created} blogpost restrictions")
            else:
                self._complete_phase("blogpost_restrictions")

        # Blogpost versions
        if not self._is_phase_complete("blogpost_versions"):
            num_versions = counts.get("blogpost_version_v2", counts.get("blogpost_version", 0))
            if num_versions > 0:
                self._start_phase("blogpost_versions")
                self.logger.info(f"\nCreating {num_versions} blogpost versions...")
                self.benchmark.start_phase("blogpost_versions", num_versions)

                created = self.blogpost_gen.create_blogpost_versions(blogposts, num_versions)

                self.benchmark.end_phase("blogpost_versions", created)
                self._complete_phase("blogpost_versions")
                self.logger.info(f"Created {created} blogpost versions")

    def _create_attachments_sync(self, content_ids: list[str], counts: dict[str, int]) -> list[dict]:
        """Create attachments synchronously.

        Returns list of attachment dicts with keys: id, title, pageId
        """
        if self._is_phase_complete("attachments"):
            if self.checkpoint and self.checkpoint.checkpoint:
                metadata = self.checkpoint.checkpoint.attachment_metadata
                if metadata:
                    self.logger.info(f"Restored {len(metadata)} attachments from checkpoint")
                    return metadata
            return []

        num_attachments = counts.get("attachment_v2", counts.get("attachment", 0))
        if num_attachments <= 0:
            return []

        self._start_phase("attachments")
        remaining = self._get_remaining_count("attachments", num_attachments)

        if remaining <= 0:
            self._complete_phase("attachments")
            return []

        self.logger.info(f"\nCreating {remaining} attachments...")
        self.benchmark.start_phase("attachments", remaining)

        attachments = self.attachment_gen.create_attachments(content_ids, remaining)

        if self.checkpoint and attachments:
            self.checkpoint.add_attachment_metadata(attachments)
            self.checkpoint.save()

        self.benchmark.end_phase("attachments", len(attachments))
        self._complete_phase("attachments")

        self.logger.info(f"Created {len(attachments)} attachments")
        return attachments

    def _create_attachment_items_sync(self, attachments: list[dict], counts: dict[str, int]):
        """Create attachment-related items (labels, versions) synchronously."""
        attachment_ids = [a["id"] for a in attachments]

        # Attachment labels
        if not self._is_phase_complete("attachment_labels"):
            num_labels = counts.get("attachment_label_v2", counts.get("attachment_label", 0))
            if num_labels > 0:
                self._start_phase("attachment_labels")
                self.logger.info(f"\nCreating {num_labels} attachment labels...")
                self.benchmark.start_phase("attachment_labels", num_labels)

                created = self.attachment_gen.add_attachment_labels(attachment_ids, num_labels)

                self.benchmark.end_phase("attachment_labels", created)
                self._complete_phase("attachment_labels")
                self.logger.info(f"Created {created} attachment labels")

        # Attachment versions
        if not self._is_phase_complete("attachment_versions"):
            num_versions = counts.get("attachment_version_v2", counts.get("attachment_version", 0))
            if num_versions > 0:
                self._start_phase("attachment_versions")
                self.logger.info(f"\nCreating {num_versions} attachment versions...")
                self.benchmark.start_phase("attachment_versions", num_versions)

                created = self.attachment_gen.create_attachment_versions(attachments, num_versions)

                self.benchmark.end_phase("attachment_versions", created)
                self._complete_phase("attachment_versions")
                self.logger.info(f"Created {created} attachment versions")

    # ========== Comment Sync Methods ==========

    def _create_inline_comments_sync(self, page_ids: list[str], counts: dict[str, int]) -> list[dict]:
        """Create inline comments synchronously.

        Returns list of comment dicts with keys: id, pageId
        """
        if self._is_phase_complete("inline_comments"):
            if self.checkpoint and self.checkpoint.checkpoint:
                metadata = self.checkpoint.checkpoint.inline_comment_metadata
                if metadata:
                    self.logger.info(f"Restored {len(metadata)} inline comments from checkpoint")
                    return metadata
            return []

        num = counts.get("inline_comment_v2", counts.get("inline_comment", 0))
        if num <= 0:
            return []

        self._start_phase("inline_comments")
        remaining = self._get_remaining_count("inline_comments", num)

        if remaining <= 0:
            self._complete_phase("inline_comments")
            return []

        self.logger.info(f"\nCreating {remaining} inline comments...")
        self.benchmark.start_phase("inline_comments", remaining)

        comments = self.comment_gen.create_inline_comments(page_ids, remaining)

        if self.checkpoint and comments:
            self.checkpoint.add_inline_comment_metadata(comments)
            self.checkpoint.save()

        self.benchmark.end_phase("inline_comments", len(comments))
        self._complete_phase("inline_comments")

        self.logger.info(f"Created {len(comments)} inline comments")
        return comments

    def _create_inline_comment_versions_sync(self, comments: list[dict], counts: dict[str, int]):
        """Create inline comment versions synchronously."""
        if self._is_phase_complete("inline_comment_versions"):
            return

        num = counts.get("inline_comment_version_v2", counts.get("inline_comment_version", 0))
        if num <= 0:
            return

        self._start_phase("inline_comment_versions")
        self.logger.info(f"\nCreating {num} inline comment versions...")
        self.benchmark.start_phase("inline_comment_versions", num)

        created = self.comment_gen.create_comment_versions(comments, num, "inline")

        self.benchmark.end_phase("inline_comment_versions", created)
        self._complete_phase("inline_comment_versions")
        self.logger.info(f"Created {created} inline comment versions")

    def _create_footer_comments_sync(self, page_ids: list[str], counts: dict[str, int]) -> list[dict]:
        """Create footer comments synchronously.

        Returns list of comment dicts with keys: id, pageId
        """
        if self._is_phase_complete("footer_comments"):
            if self.checkpoint and self.checkpoint.checkpoint:
                metadata = self.checkpoint.checkpoint.footer_comment_metadata
                if metadata:
                    self.logger.info(f"Restored {len(metadata)} footer comments from checkpoint")
                    return metadata
            return []

        num = counts.get("footer_comment_v2", counts.get("footer_comment", 0))
        if num <= 0:
            return []

        self._start_phase("footer_comments")
        remaining = self._get_remaining_count("footer_comments", num)

        if remaining <= 0:
            self._complete_phase("footer_comments")
            return []

        self.logger.info(f"\nCreating {remaining} footer comments...")
        self.benchmark.start_phase("footer_comments", remaining)

        comments = self.comment_gen.create_footer_comments(page_ids, remaining)

        if self.checkpoint and comments:
            self.checkpoint.add_footer_comment_metadata(comments)
            self.checkpoint.save()

        self.benchmark.end_phase("footer_comments", len(comments))
        self._complete_phase("footer_comments")

        self.logger.info(f"Created {len(comments)} footer comments")
        return comments

    def _create_footer_comment_versions_sync(self, comments: list[dict], counts: dict[str, int]):
        """Create footer comment versions synchronously."""
        if self._is_phase_complete("footer_comment_versions"):
            return

        num = counts.get("footer_comment_version_v2", counts.get("footer_comment_version", 0))
        if num <= 0:
            return

        self._start_phase("footer_comment_versions")
        self.logger.info(f"\nCreating {num} footer comment versions...")
        self.benchmark.start_phase("footer_comment_versions", num)

        created = self.comment_gen.create_comment_versions(comments, num, "footer")

        self.benchmark.end_phase("footer_comment_versions", created)
        self._complete_phase("footer_comment_versions")
        self.logger.info(f"Created {created} footer comment versions")

    # ========== Async Generation Methods ==========

    async def generate_async(self, content_count: int, counts: dict[str, int]):
        """Generate all test data asynchronously.

        Args:
            content_count: Target number of content items
            counts: Pre-calculated item counts by type
        """
        self._init_or_resume_checkpoint(content_count, counts, async_mode=True)
        self._log_header(counts)

        try:
            # Phase 1: Create spaces
            spaces = await self._create_spaces_async(counts)

            if not spaces:
                self.logger.error("No spaces created, cannot continue")
                return

            # Discover users for permissions/restrictions
            if not self.content_only:
                self.user_account_ids = self.space_gen.get_all_users(max_users=100)
                if self.user_account_ids:
                    self.logger.info(f"Discovered {len(self.user_account_ids)} users for permissions/restrictions")
                else:
                    self.logger.warning("No users discovered - space permissions and restrictions will be skipped")

            # Phase 2: Create space-related items (labels, properties, permissions)
            if not self.content_only:
                await self._create_space_items_async(spaces, counts)

            # Phase 3: Create pages
            pages = await self._create_pages_async(spaces, counts)

            # Phase 4: Create page-related items
            if pages and not self.content_only:
                await self._create_page_items_async(pages, counts)

            # Phase 5: Create blogposts
            blogposts = await self._create_blogposts_async(spaces, counts)

            # Phase 6: Create blogpost-related items
            if blogposts and not self.content_only:
                await self._create_blogpost_items_async(blogposts, counts)

            # Phase 7: Create attachments
            all_content_ids = [p["id"] for p in pages] + [bp["id"] for bp in blogposts]
            if all_content_ids and not self.content_only:
                attachments = await self._create_attachments_async(all_content_ids, counts)

                # Phase 7b: Attachment-related items
                if attachments:
                    await self._create_attachment_items_async(attachments, counts)

            # Phase 7c: Create folders
            if not self.content_only:
                folders = await self._create_folders_async(spaces, counts)
                if folders:
                    await self._create_folder_restrictions_async(folders, counts)

            # Phase 8: Create comments
            page_id_list = [p["id"] for p in pages] if pages else []
            if page_id_list and not self.content_only:
                inline_comments = await self._create_inline_comments_async(page_id_list, counts)
                if inline_comments:
                    await self._create_inline_comment_versions_async(inline_comments, counts)

                footer_comments = await self._create_footer_comments_async(page_id_list, counts)
                if footer_comments:
                    await self._create_footer_comment_versions_async(footer_comments, counts)

            # Create templates
            if not self.content_only:
                await self._create_templates_async(spaces, counts)

            self._log_footer()
        finally:
            # Always close async sessions
            await self.space_gen._close_async_session()
            await self.page_gen._close_async_session()
            await self.blogpost_gen._close_async_session()
            await self.attachment_gen._close_async_session()
            await self.folder_gen._close_async_session()
            await self.comment_gen._close_async_session()
            await self.template_gen._close_async_session()

    async def _create_folders_async(self, spaces: list[dict], counts: dict[str, int]) -> list[dict]:
        """Create folders asynchronously.

        Returns list of created folder dicts with keys: id, title, spaceId
        """
        if self._is_phase_complete("folders"):
            return []

        num_folders = counts.get("folder", 0)
        if num_folders <= 0:
            return []

        self._start_phase("folders")
        remaining = self._get_remaining_count("folders", num_folders)

        if remaining <= 0:
            self._complete_phase("folders")
            return []

        self.logger.info(f"\nCreating {remaining} folders (async)...")
        self.benchmark.start_phase("folders", remaining)

        folders = await self.folder_gen.create_folders_async(spaces, remaining)

        self.benchmark.end_phase("folders", len(folders))
        if self.checkpoint:
            self.checkpoint.update_phase_count("folders", len(folders))
        self._complete_phase("folders")

        self.logger.info(f"Created {len(folders)} folders")
        return folders

    async def _create_folder_restrictions_async(self, folders: list[dict], counts: dict[str, int]):
        """Create folder restrictions asynchronously."""
        if self._is_phase_complete("folder_restrictions"):
            return

        num_restrictions = counts.get("folder_restriction", 0)
        if num_restrictions <= 0 or not self.user_account_ids:
            self._complete_phase("folder_restrictions")
            return

        folder_ids = [f["id"] for f in folders]

        self._start_phase("folder_restrictions")
        self.logger.info(f"\nCreating {num_restrictions} folder restrictions (async)...")
        self.benchmark.start_phase("folder_restrictions", num_restrictions)

        created = await self.folder_gen.add_folder_restrictions_async(
            folder_ids, self.user_account_ids, num_restrictions
        )

        self.benchmark.end_phase("folder_restrictions", created)
        if self.checkpoint:
            self.checkpoint.update_phase_count("folder_restrictions", created)
        self._complete_phase("folder_restrictions")
        self.logger.info(f"Created {created} folder restrictions")

    async def _create_templates_async(self, spaces: list[dict], counts: dict[str, int]) -> int:
        """Create templates asynchronously.

        Returns number of templates created.
        """
        if self._is_phase_complete("templates"):
            return 0

        num = counts.get("template", 0)
        if num <= 0:
            return 0

        self._start_phase("templates")
        remaining = self._get_remaining_count("templates", num)

        if remaining <= 0:
            self._complete_phase("templates")
            return 0

        self.logger.info(f"\nCreating {remaining} templates (async)...")
        self.benchmark.start_phase("templates", remaining)

        templates = await self.template_gen.create_templates_async(spaces, remaining)

        self.benchmark.end_phase("templates", len(templates))
        if self.checkpoint:
            self.checkpoint.update_phase_count("templates", len(templates))
        self._complete_phase("templates")

        self.logger.info(f"Created {len(templates)} templates")
        return len(templates)

    async def _create_spaces_async(self, counts: dict[str, int]) -> list[dict]:
        """Create spaces asynchronously.

        Returns list of created space dicts with keys: key, id, name
        """
        if self._is_phase_complete("spaces"):
            # Restore spaces from checkpoint
            if self.checkpoint and self.checkpoint.checkpoint:
                space_keys = self.checkpoint.checkpoint.space_keys
                space_ids = self.checkpoint.checkpoint.space_ids
                if space_keys and space_ids:
                    self.logger.info(f"Restored {len(space_keys)} spaces from checkpoint")
                    return [{"key": key, "id": space_id} for key, space_id in zip(space_keys, space_ids, strict=True)]
            return []

        self._start_phase("spaces")

        # Get space count - use space_v2 or space
        num_spaces = counts.get("space_v2", counts.get("space", 1))
        remaining = self._get_remaining_count("spaces", num_spaces)

        if remaining <= 0:
            self._complete_phase("spaces")
            return []

        self.logger.info(f"\nCreating {remaining} spaces (async)...")
        self.benchmark.start_phase("spaces", remaining)

        spaces = await self.space_gen.create_spaces_async(remaining)

        self.benchmark.end_phase("spaces", len(spaces))

        # Update checkpoint with created spaces
        if self.checkpoint and spaces:
            for space in spaces:
                self.checkpoint.add_space(space["key"], space["id"])

        self._complete_phase("spaces")

        self.logger.info(f"Created {len(spaces)} spaces")
        return spaces

    async def _create_space_items_async(self, spaces: list[dict], counts: dict[str, int]):
        """Create space-related items (labels, properties, permissions) asynchronously."""
        space_keys = [s["key"] for s in spaces]

        # Space labels (and categories) - run in parallel across spaces
        if not self._is_phase_complete("space_labels"):
            num_labels = counts.get("space_label_v2", 0)
            if num_labels > 0:
                self._start_phase("space_labels")
                labels_per_space = max(1, num_labels // len(spaces))
                total_labels = labels_per_space * len(spaces)

                self.logger.info(f"\nCreating {total_labels} space labels ({labels_per_space} per space, async)...")
                self.benchmark.start_phase("space_labels", total_labels)

                # Create tasks for parallel execution - wrap each key in a list
                tasks = [self.space_gen.add_space_labels_async([key], labels_per_space) for key in space_keys]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Log any exceptions from failed tasks
                for r in results:
                    if isinstance(r, Exception):
                        self.logger.warning(f"Space label task failed: {r}")

                created = sum(r for r in results if isinstance(r, int))

                self.benchmark.end_phase("space_labels", created)
                self._complete_phase("space_labels")
                self.logger.info(f"Created {created} space labels")

        # Space properties - run in parallel across spaces
        if not self._is_phase_complete("space_properties"):
            num_props = counts.get("space_property_v2", 0)
            if num_props > 0:
                self._start_phase("space_properties")
                props_per_space = max(1, num_props // len(spaces))
                total_props = props_per_space * len(spaces)

                self.logger.info(f"\nCreating {total_props} space properties ({props_per_space} per space, async)...")
                self.benchmark.start_phase("space_properties", total_props)

                # Create tasks for parallel execution - uses space IDs, wrap each in list
                space_ids = [s["id"] for s in spaces]
                tasks = [self.space_gen.set_space_properties_async([sid], props_per_space) for sid in space_ids]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Log any exceptions from failed tasks
                for r in results:
                    if isinstance(r, Exception):
                        self.logger.warning(f"Space property task failed: {r}")

                created = sum(r for r in results if isinstance(r, int))

                self.benchmark.end_phase("space_properties", created)
                self._complete_phase("space_properties")
                self.logger.info(f"Created {created} space properties")

        # Space permissions via role assignments (v2 RBAC API)
        if not self._is_phase_complete("space_permissions"):
            if self.user_account_ids:
                roles = self.space_gen.get_space_roles()
                num_roles = len(roles) if roles else 5
                num_perms = len(spaces) * len(self.user_account_ids) * num_roles
                self._start_phase("space_permissions")

                self.logger.info(
                    f"\nCreating {num_perms} space permissions "
                    f"({len(spaces)} spaces × {len(self.user_account_ids)} users × {num_roles} roles, async)..."
                )
                self.benchmark.start_phase("space_permissions", num_perms)

                space_ids = [s["id"] for s in spaces]
                created = await self.space_gen.add_space_permissions_async(space_ids, self.user_account_ids, num_perms)

                self.benchmark.end_phase("space_permissions", created)
                if self.checkpoint:
                    self.checkpoint.update_phase_count("space_permissions", created)
                self._complete_phase("space_permissions")
                self.logger.info(f"Created {created} space permissions")

    async def _create_pages_async(self, spaces: list[dict], counts: dict[str, int]) -> list[dict]:
        """Create pages asynchronously.

        Returns list of created page dicts with keys: id, title, spaceId
        """
        if self._is_phase_complete("pages"):
            if self.checkpoint and self.checkpoint.checkpoint:
                page_ids = self.checkpoint.checkpoint.page_ids
                if page_ids:
                    self.logger.info(f"Restored {len(page_ids)} pages from checkpoint")
                    return [{"id": pid, "title": f"Page {pid}"} for pid in page_ids]
            return []

        self._start_phase("pages")

        num_pages = counts.get("page_v2", counts.get("page", 0))
        remaining = self._get_remaining_count("pages", num_pages)

        if remaining <= 0:
            self._complete_phase("pages")
            return []

        self.logger.info(f"\nCreating {remaining} pages (async)...")
        self.benchmark.start_phase("pages", remaining)

        pages = await self.page_gen.create_pages_async(spaces, remaining)

        self.benchmark.end_phase("pages", len(pages))

        # Update checkpoint with created pages (grouped by space key, not space ID)
        if self.checkpoint and pages:
            space_id_to_key: dict[str, str] = {
                space["id"]: space["key"] for space in spaces if "id" in space and "key" in space
            }

            pages_by_space: dict[str, list[str]] = {}
            for page in pages:
                space_id = page.get("spaceId")
                space_key = space_id_to_key.get(space_id, "unknown")
                pages_by_space.setdefault(space_key, []).append(page["id"])
            for space_key, page_ids in pages_by_space.items():
                self.checkpoint.add_page_ids(page_ids, space_key)
            self.checkpoint.save()

        self._complete_phase("pages")

        self.logger.info(f"Created {len(pages)} pages")
        return pages

    async def _create_page_items_async(self, pages: list[dict], counts: dict[str, int]):
        """Create page-related items asynchronously."""
        page_ids = [p["id"] for p in pages]

        # Page labels
        if not self._is_phase_complete("page_labels"):
            num_labels = counts.get("page_label_v2", 0)
            if num_labels > 0:
                self._start_phase("page_labels")
                self.logger.info(f"\nCreating {num_labels} page labels (async)...")
                self.benchmark.start_phase("page_labels", num_labels)

                created = await self.page_gen.add_page_labels_async(page_ids, num_labels)

                self.benchmark.end_phase("page_labels", created)
                self._complete_phase("page_labels")
                self.logger.info(f"Created {created} page labels")

        # Page properties
        if not self._is_phase_complete("page_properties"):
            num_props = counts.get("page_property_v2", 0)
            if num_props > 0:
                self._start_phase("page_properties")
                self.logger.info(f"\nCreating {num_props} page properties (async)...")
                self.benchmark.start_phase("page_properties", num_props)

                created = await self.page_gen.set_page_properties_async(page_ids, num_props)

                self.benchmark.end_phase("page_properties", created)
                self._complete_phase("page_properties")
                self.logger.info(f"Created {created} page properties")

        # Page restrictions
        if not self._is_phase_complete("page_restrictions"):
            num_restrictions = counts.get("page_restriction_v2", 0)
            if num_restrictions > 0 and self.user_account_ids and pages:
                self._start_phase("page_restrictions")
                self.logger.info(f"\nCreating {num_restrictions} page restrictions (async)...")
                self.benchmark.start_phase("page_restrictions", num_restrictions)

                created = await self.page_gen.add_page_restrictions_async(
                    page_ids, self.user_account_ids, num_restrictions
                )

                self.benchmark.end_phase("page_restrictions", created)
                if self.checkpoint:
                    self.checkpoint.update_phase_count("page_restrictions", created)
                self._complete_phase("page_restrictions")
                self.logger.info(f"Created {created} page restrictions")
            else:
                self._complete_phase("page_restrictions")

        # Page versions
        if not self._is_phase_complete("page_versions"):
            num_versions = counts.get("page_version_v2", 0)
            if num_versions > 0:
                self._start_phase("page_versions")
                self.logger.info(f"\nCreating {num_versions} page versions (async)...")
                self.benchmark.start_phase("page_versions", num_versions)

                created = await self.page_gen.create_page_versions_async(pages, num_versions)

                self.benchmark.end_phase("page_versions", created)
                self._complete_phase("page_versions")
                self.logger.info(f"Created {created} page versions")

    async def _create_blogposts_async(self, spaces: list[dict], counts: dict[str, int]) -> list[dict]:
        """Create blogposts asynchronously.

        Returns list of created blogpost dicts with keys: id, title, spaceId
        """
        if self._is_phase_complete("blogposts"):
            if self.checkpoint and self.checkpoint.checkpoint:
                blogpost_ids = self.checkpoint.checkpoint.blogpost_ids
                if blogpost_ids:
                    self.logger.info(f"Restored {len(blogpost_ids)} blogposts from checkpoint")
                    return [{"id": bid, "title": f"Blog Post {bid}"} for bid in blogpost_ids]
            return []

        self._start_phase("blogposts")

        num_blogposts = counts.get("blogpost_v2", counts.get("blogpost", 0))
        remaining = self._get_remaining_count("blogposts", num_blogposts)

        if remaining <= 0:
            self._complete_phase("blogposts")
            return []

        self.logger.info(f"\nCreating {remaining} blogposts (async)...")
        self.benchmark.start_phase("blogposts", remaining)

        blogposts = await self.blogpost_gen.create_blogposts_async(spaces, remaining)

        self.benchmark.end_phase("blogposts", len(blogposts))

        # Update checkpoint with created blogposts
        if self.checkpoint and blogposts:
            space_id_to_key: dict[str, str] = {
                space["id"]: space["key"] for space in spaces if "id" in space and "key" in space
            }

            blogposts_by_space: dict[str, list[str]] = {}
            for bp in blogposts:
                space_id = bp.get("spaceId")
                space_key = space_id_to_key.get(space_id, "unknown")
                blogposts_by_space.setdefault(space_key, []).append(bp["id"])
            for space_key, bp_ids in blogposts_by_space.items():
                self.checkpoint.add_blogpost_ids(bp_ids, space_key)
            self.checkpoint.save()

        self._complete_phase("blogposts")

        self.logger.info(f"Created {len(blogposts)} blogposts")
        return blogposts

    async def _create_blogpost_items_async(self, blogposts: list[dict], counts: dict[str, int]):
        """Create blogpost-related items asynchronously."""
        blogpost_ids = [bp["id"] for bp in blogposts]

        # Blogpost labels
        if not self._is_phase_complete("blogpost_labels"):
            num_labels = counts.get("blogpost_label_v2", counts.get("blogpost_label", 0))
            if num_labels > 0:
                self._start_phase("blogpost_labels")
                self.logger.info(f"\nCreating {num_labels} blogpost labels (async)...")
                self.benchmark.start_phase("blogpost_labels", num_labels)

                created = await self.blogpost_gen.add_blogpost_labels_async(blogpost_ids, num_labels)

                self.benchmark.end_phase("blogpost_labels", created)
                self._complete_phase("blogpost_labels")
                self.logger.info(f"Created {created} blogpost labels")

        # Blogpost properties
        if not self._is_phase_complete("blogpost_properties"):
            num_props = counts.get("blogpost_property_v2", counts.get("blogpost_property", 0))
            if num_props > 0:
                self._start_phase("blogpost_properties")
                self.logger.info(f"\nCreating {num_props} blogpost properties (async)...")
                self.benchmark.start_phase("blogpost_properties", num_props)

                created = await self.blogpost_gen.set_blogpost_properties_async(blogpost_ids, num_props)

                self.benchmark.end_phase("blogpost_properties", created)
                self._complete_phase("blogpost_properties")
                self.logger.info(f"Created {created} blogpost properties")

        # Blogpost restrictions
        if not self._is_phase_complete("blogpost_restrictions"):
            num_restrictions = counts.get("blogpost_restriction_v2", 0)
            if num_restrictions > 0 and self.user_account_ids and blogposts:
                self._start_phase("blogpost_restrictions")
                self.logger.info(f"\nCreating {num_restrictions} blogpost restrictions (async)...")
                self.benchmark.start_phase("blogpost_restrictions", num_restrictions)

                created = await self.blogpost_gen.add_blogpost_restrictions_async(
                    blogpost_ids, self.user_account_ids, num_restrictions
                )

                self.benchmark.end_phase("blogpost_restrictions", created)
                if self.checkpoint:
                    self.checkpoint.update_phase_count("blogpost_restrictions", created)
                self._complete_phase("blogpost_restrictions")
                self.logger.info(f"Created {created} blogpost restrictions")
            else:
                self._complete_phase("blogpost_restrictions")

        # Blogpost versions
        if not self._is_phase_complete("blogpost_versions"):
            num_versions = counts.get("blogpost_version_v2", counts.get("blogpost_version", 0))
            if num_versions > 0:
                self._start_phase("blogpost_versions")
                self.logger.info(f"\nCreating {num_versions} blogpost versions (async)...")
                self.benchmark.start_phase("blogpost_versions", num_versions)

                created = await self.blogpost_gen.create_blogpost_versions_async(blogposts, num_versions)

                self.benchmark.end_phase("blogpost_versions", created)
                self._complete_phase("blogpost_versions")
                self.logger.info(f"Created {created} blogpost versions")

    async def _create_attachments_async(self, content_ids: list[str], counts: dict[str, int]) -> list[dict]:
        """Create attachments asynchronously.

        Returns list of attachment dicts with keys: id, title, pageId
        """
        if self._is_phase_complete("attachments"):
            if self.checkpoint and self.checkpoint.checkpoint:
                metadata = self.checkpoint.checkpoint.attachment_metadata
                if metadata:
                    self.logger.info(f"Restored {len(metadata)} attachments from checkpoint")
                    return metadata
            return []

        num_attachments = counts.get("attachment_v2", counts.get("attachment", 0))
        if num_attachments <= 0:
            return []

        self._start_phase("attachments")
        remaining = self._get_remaining_count("attachments", num_attachments)

        if remaining <= 0:
            self._complete_phase("attachments")
            return []

        self.logger.info(f"\nCreating {remaining} attachments (async)...")
        self.benchmark.start_phase("attachments", remaining)

        attachments = await self.attachment_gen.create_attachments_async(content_ids, remaining)

        if self.checkpoint and attachments:
            self.checkpoint.add_attachment_metadata(attachments)
            self.checkpoint.save()

        self.benchmark.end_phase("attachments", len(attachments))
        self._complete_phase("attachments")

        self.logger.info(f"Created {len(attachments)} attachments")
        return attachments

    async def _create_attachment_items_async(self, attachments: list[dict], counts: dict[str, int]):
        """Create attachment-related items (labels, versions) asynchronously."""
        attachment_ids = [a["id"] for a in attachments]

        # Attachment labels
        if not self._is_phase_complete("attachment_labels"):
            num_labels = counts.get("attachment_label_v2", counts.get("attachment_label", 0))
            if num_labels > 0:
                self._start_phase("attachment_labels")
                self.logger.info(f"\nCreating {num_labels} attachment labels (async)...")
                self.benchmark.start_phase("attachment_labels", num_labels)

                created = await self.attachment_gen.add_attachment_labels_async(attachment_ids, num_labels)

                self.benchmark.end_phase("attachment_labels", created)
                self._complete_phase("attachment_labels")
                self.logger.info(f"Created {created} attachment labels")

        # Attachment versions
        if not self._is_phase_complete("attachment_versions"):
            num_versions = counts.get("attachment_version_v2", counts.get("attachment_version", 0))
            if num_versions > 0:
                self._start_phase("attachment_versions")
                self.logger.info(f"\nCreating {num_versions} attachment versions (async)...")
                self.benchmark.start_phase("attachment_versions", num_versions)

                created = await self.attachment_gen.create_attachment_versions_async(attachments, num_versions)

                self.benchmark.end_phase("attachment_versions", created)
                self._complete_phase("attachment_versions")
                self.logger.info(f"Created {created} attachment versions")

    # ========== Comment Async Methods ==========

    async def _create_inline_comments_async(self, page_ids: list[str], counts: dict[str, int]) -> list[dict]:
        """Create inline comments asynchronously.

        Returns list of comment dicts with keys: id, pageId
        """
        if self._is_phase_complete("inline_comments"):
            if self.checkpoint and self.checkpoint.checkpoint:
                metadata = self.checkpoint.checkpoint.inline_comment_metadata
                if metadata:
                    self.logger.info(f"Restored {len(metadata)} inline comments from checkpoint")
                    return metadata
            return []

        num = counts.get("inline_comment_v2", counts.get("inline_comment", 0))
        if num <= 0:
            return []

        self._start_phase("inline_comments")
        remaining = self._get_remaining_count("inline_comments", num)

        if remaining <= 0:
            self._complete_phase("inline_comments")
            return []

        self.logger.info(f"\nCreating {remaining} inline comments (async)...")
        self.benchmark.start_phase("inline_comments", remaining)

        comments = await self.comment_gen.create_inline_comments_async(page_ids, remaining)

        if self.checkpoint and comments:
            self.checkpoint.add_inline_comment_metadata(comments)
            self.checkpoint.save()

        self.benchmark.end_phase("inline_comments", len(comments))
        self._complete_phase("inline_comments")

        self.logger.info(f"Created {len(comments)} inline comments")
        return comments

    async def _create_inline_comment_versions_async(self, comments: list[dict], counts: dict[str, int]):
        """Create inline comment versions asynchronously."""
        if self._is_phase_complete("inline_comment_versions"):
            return

        num = counts.get("inline_comment_version_v2", counts.get("inline_comment_version", 0))
        if num <= 0:
            return

        self._start_phase("inline_comment_versions")
        self.logger.info(f"\nCreating {num} inline comment versions (async)...")
        self.benchmark.start_phase("inline_comment_versions", num)

        created = await self.comment_gen.create_comment_versions_async(comments, num, "inline")

        self.benchmark.end_phase("inline_comment_versions", created)
        self._complete_phase("inline_comment_versions")
        self.logger.info(f"Created {created} inline comment versions")

    async def _create_footer_comments_async(self, page_ids: list[str], counts: dict[str, int]) -> list[dict]:
        """Create footer comments asynchronously.

        Returns list of comment dicts with keys: id, pageId
        """
        if self._is_phase_complete("footer_comments"):
            if self.checkpoint and self.checkpoint.checkpoint:
                metadata = self.checkpoint.checkpoint.footer_comment_metadata
                if metadata:
                    self.logger.info(f"Restored {len(metadata)} footer comments from checkpoint")
                    return metadata
            return []

        num = counts.get("footer_comment_v2", counts.get("footer_comment", 0))
        if num <= 0:
            return []

        self._start_phase("footer_comments")
        remaining = self._get_remaining_count("footer_comments", num)

        if remaining <= 0:
            self._complete_phase("footer_comments")
            return []

        self.logger.info(f"\nCreating {remaining} footer comments (async)...")
        self.benchmark.start_phase("footer_comments", remaining)

        comments = await self.comment_gen.create_footer_comments_async(page_ids, remaining)

        if self.checkpoint and comments:
            self.checkpoint.add_footer_comment_metadata(comments)
            self.checkpoint.save()

        self.benchmark.end_phase("footer_comments", len(comments))
        self._complete_phase("footer_comments")

        self.logger.info(f"Created {len(comments)} footer comments")
        return comments

    async def _create_footer_comment_versions_async(self, comments: list[dict], counts: dict[str, int]):
        """Create footer comment versions asynchronously."""
        if self._is_phase_complete("footer_comment_versions"):
            return

        num = counts.get("footer_comment_version_v2", counts.get("footer_comment_version", 0))
        if num <= 0:
            return

        self._start_phase("footer_comment_versions")
        self.logger.info(f"\nCreating {num} footer comment versions (async)...")
        self.benchmark.start_phase("footer_comment_versions", num)

        created = await self.comment_gen.create_comment_versions_async(comments, num, "footer")

        self.benchmark.end_phase("footer_comment_versions", created)
        self._complete_phase("footer_comment_versions")
        self.logger.info(f"Created {created} footer comment versions")


def setup_logging(prefix: str, verbose: bool = False) -> str:
    """Setup logging to console and file.

    Args:
        prefix: Prefix for log filename
        verbose: Enable debug logging

    Returns:
        Log filename path
    """
    # Ensure logs directory exists
    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Generate log filename based on prefix and timestamp
    log_filename = logs_dir / f"confluence_generator_{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    # Setup logging
    log_level = logging.DEBUG if verbose else logging.INFO
    log_format = "%(asctime)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Clear existing handlers
    logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    logger.addHandler(console_handler)

    # File handler
    file_handler = logging.FileHandler(log_filename)
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    logger.addHandler(file_handler)

    return str(log_filename)


def main():
    parser = argparse.ArgumentParser(
        description="Generate test data for Confluence Cloud based on production multipliers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate 100 content items for a small instance
  %(prog)s --url https://mycompany.atlassian.net/wiki \\
           --email user@example.com \\
           --count 100 \\
           --size small \\
           --prefix TESTDATA

  # Faster generation with higher concurrency
  %(prog)s --url https://mycompany.atlassian.net/wiki \\
           --email user@example.com \\
           --count 500 \\
           --size medium \\
           --concurrency 10 \\
           --prefix LOAD

  # Content-only mode (spaces, pages, blogposts only)
  %(prog)s --url https://mycompany.atlassian.net/wiki \\
           --email user@example.com \\
           --count 500 \\
           --content-only \\
           --prefix SCALE

  # Dry run to see what would be created
  %(prog)s --url https://mycompany.atlassian.net/wiki \\
           --email user@example.com \\
           --count 500 \\
           --dry-run \\
           --prefix TEST

  # Resume from checkpoint (after interruption)
  %(prog)s --url https://mycompany.atlassian.net/wiki \\
           --email user@example.com \\
           --count 500 \\
           --resume \\
           --prefix LOAD

Checkpointing:
  - Progress is automatically saved to confluence_checkpoint_{PREFIX}.json
  - Use --resume to continue from where you left off
  - Use --no-checkpoint to disable checkpointing entirely
        """,
    )

    # Required arguments
    parser.add_argument(
        "--url",
        required=True,
        help="Confluence Cloud URL (e.g., https://mycompany.atlassian.net/wiki)",
    )
    parser.add_argument("--email", required=True, help="Atlassian account email")
    parser.add_argument(
        "--count",
        type=int,
        required=True,
        help="Target number of content items (pages + blogposts)",
    )
    parser.add_argument(
        "--prefix",
        default="TESTDATA",
        help="Prefix for labels and properties (default: TESTDATA)",
    )

    # Optional arguments
    parser.add_argument(
        "--size",
        choices=["small", "medium", "large"],
        default="small",
        help="Instance size bucket - affects multipliers (default: small)",
    )
    parser.add_argument(
        "--spaces",
        type=int,
        default=None,
        help="Override number of spaces (default: calculated from multipliers)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Number of concurrent API requests (default: 5)",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.0,
        help="Delay between requests in seconds (default: 0)",
    )
    parser.add_argument(
        "--settling-delay",
        type=float,
        default=0.0,
        help="Delay before version creation to let Confluence settle (default: 0). Retry-on-409 logic handles eventual consistency automatically; increase if you see excessive 409 retries.",
    )
    parser.add_argument(
        "--content-only",
        action="store_true",
        help="Only create spaces, pages, and blogposts (skip labels, properties, etc.)",
    )
    parser.add_argument(
        "--no-async",
        action="store_true",
        help="Disable async mode (use sequential requests)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without making API calls",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose/debug logging",
    )

    # Checkpoint options
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing checkpoint file",
    )
    parser.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Disable checkpointing (not recommended for large runs)",
    )

    args = parser.parse_args()

    # Setup logging
    log_filename = setup_logging(args.prefix, args.verbose)
    logging.info(f"Logging to file: {log_filename}")

    # Load environment variables from .env file
    load_dotenv()

    # Get API token from environment variable or .env file
    api_token = os.environ.get("CONFLUENCE_API_TOKEN")
    if not api_token:
        print(
            "Error: Confluence API token required. Set CONFLUENCE_API_TOKEN in .env file or as environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Validate size bucket
    if args.size not in MULTIPLIERS:
        print(f"Error: Invalid size bucket. Must be one of: {', '.join(MULTIPLIERS.keys())}", file=sys.stderr)
        sys.exit(1)

    # Calculate counts
    counts = calculate_counts(args.count, args.size, args.content_only)

    # Apply space override if specified
    if args.spaces is not None:
        counts["space"] = max(1, args.spaces)
        counts["space_v2"] = max(1, args.spaces)

    # Setup checkpoint manager
    checkpoint_manager = None
    if not args.no_checkpoint:
        checkpoint_manager = CheckpointManager(args.prefix)

        if args.resume:
            # Try to load existing checkpoint
            checkpoint_path = checkpoint_manager.find_existing_checkpoint()
            if checkpoint_path:
                loaded = checkpoint_manager.load(checkpoint_path)
                if loaded:
                    logging.info(f"Found checkpoint: {checkpoint_path}")
                    # Validate checkpoint matches current parameters
                    if loaded.confluence_url != args.url:
                        logging.warning(f"Checkpoint URL ({loaded.confluence_url}) differs from current ({args.url})")
                else:
                    logging.warning("Failed to load checkpoint, starting fresh")
            else:
                logging.warning(f"No checkpoint found for prefix '{args.prefix}', starting fresh")

    # Log configuration
    logging.info("=" * 60)
    logging.info("Confluence Test Data Generator")
    logging.info("=" * 60)
    logging.info(f"URL: {args.url}")
    logging.info(f"Email: {args.email}")
    logging.info(f"Prefix: {args.prefix}")
    logging.info(f"Size bucket: {args.size}")
    logging.info(f"Target content count: {args.count}")
    logging.info(f"Concurrency: {args.concurrency}")
    logging.info(f"Async mode: {not args.no_async}")
    logging.info(f"Content-only: {args.content_only}")
    logging.info(f"Dry run: {args.dry_run}")
    logging.info(f"Checkpointing: {not args.no_checkpoint}")
    logging.info("=" * 60)

    # Log planned counts
    logging.info("\nPlanned item counts:")
    for item_type, count in sorted(counts.items()):
        if count > 0:
            logging.info(f"  {item_type}: {count}")

    if args.dry_run:
        logging.info("\n[DRY RUN] No API calls will be made")
        logging.info("Exiting after showing planned counts")
        return

    # Initialize the generator
    generator = ConfluenceDataGenerator(
        confluence_url=args.url,
        email=args.email,
        api_token=api_token,
        prefix=args.prefix,
        size_bucket=args.size,
        dry_run=args.dry_run,
        concurrency=args.concurrency,
        request_delay=args.request_delay,
        settling_delay=args.settling_delay,
        content_only=args.content_only,
        checkpoint_manager=checkpoint_manager,
    )

    # Run generation
    try:
        if args.no_async:
            logging.info("\nStarting synchronous generation...")
            generator.generate_sync(args.count, counts)
        else:
            logging.info("\nStarting asynchronous generation...")
            asyncio.run(generator.generate_async(args.count, counts))
        logging.info("\nGeneration complete!")
    except KeyboardInterrupt:
        logging.warning("\nGeneration interrupted by user")
        if checkpoint_manager:
            logging.info("Progress saved to checkpoint file")
        sys.exit(1)
    except Exception as e:
        logging.error(f"\nGeneration failed: {e}")
        if args.verbose:
            logging.exception("Full traceback:")
        sys.exit(1)


if __name__ == "__main__":
    main()
