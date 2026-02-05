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

from generators.benchmark import BenchmarkTracker
from generators.checkpoint import CheckpointManager
from generators.spaces import SpaceGenerator


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
                        pass

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
        }

        # Initialize space generator
        self.space_gen = SpaceGenerator(prefix=self.prefix, **common_args)

        # Future generators will be added here as they're implemented:
        # self.page_gen = PageGenerator(prefix=self.prefix, **common_args)
        # self.blogpost_gen = BlogPostGenerator(prefix=self.prefix, **common_args)
        # self.attachment_gen = AttachmentGenerator(prefix=self.prefix, **common_args)
        # self.comment_gen = CommentGenerator(prefix=self.prefix, **common_args)
        # self.template_gen = TemplateGenerator(prefix=self.prefix, **common_args)

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
        self.logger.info("")
        self.logger.info("=" * 60)
        self.logger.info("GENERATION COMPLETE")
        self.logger.info("=" * 60)
        self.logger.info(self.benchmark.get_summary())
        self.logger.info("=" * 60)

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
        created = self.checkpoint.get_phase_count(phase)
        return max(0, total - created)

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

        # Phase 2: Create space-related items (labels, properties, permissions)
        if not self.content_only:
            self._create_space_items_sync(spaces, counts)

        # Phase 3: Create pages (NOT YET IMPLEMENTED)
        # pages = self._create_pages_sync(spaces, counts)

        # Phase 4: Create page-related items (NOT YET IMPLEMENTED)
        # self._create_page_items_sync(pages, counts)

        # Phase 5: Create blogposts (NOT YET IMPLEMENTED)
        # blogposts = self._create_blogposts_sync(spaces, counts)

        # Phase 6: Create blogpost-related items (NOT YET IMPLEMENTED)
        # self._create_blogpost_items_sync(blogposts, counts)

        # Phase 7: Create attachments (NOT YET IMPLEMENTED)
        # Phase 8: Create comments (NOT YET IMPLEMENTED)
        # Phase 9: Create templates (NOT YET IMPLEMENTED)

        self._log_footer()

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
                    result = self.space_gen.add_space_labels(space_key, labels_per_space)
                    created += result

                self.benchmark.end_phase("space_labels", created)
                self._complete_phase("space_labels")
                self.logger.info(f"Created {created} space labels")

        # Space properties
        if not self._is_phase_complete("space_properties"):
            num_props = counts.get("space_property_v2", 0)
            if num_props > 0:
                self._start_phase("space_properties")
                props_per_space = max(1, num_props // len(spaces))
                total_props = props_per_space * len(spaces)

                self.logger.info(f"\nCreating {total_props} space properties ({props_per_space} per space)...")
                self.benchmark.start_phase("space_properties", total_props)

                created = 0
                for space_key in space_keys:
                    result = self.space_gen.add_space_properties(space_key, props_per_space)
                    created += result

                self.benchmark.end_phase("space_properties", created)
                self._complete_phase("space_properties")
                self.logger.info(f"Created {created} space properties")

        # Space permissions - requires user account IDs
        # Skip for now as it requires user lookup
        # if not self._is_phase_complete("space_permissions"):
        #     ...

        # Space look and feel
        if not self._is_phase_complete("space_look_and_feel"):
            num_laf = counts.get("space_look_and_feel_setting", 0)
            if num_laf > 0:
                self._start_phase("space_look_and_feel")
                # Apply look and feel to spaces that need it
                spaces_to_update = min(num_laf, len(spaces))

                self.logger.info(f"\nUpdating look and feel for {spaces_to_update} spaces...")
                self.benchmark.start_phase("space_look_and_feel", spaces_to_update)

                created = 0
                for space in spaces[:spaces_to_update]:
                    homepage_config = {"welcomeMessage": f"Welcome to {space.get('name', space['key'])}"}
                    success = self.space_gen.set_space_look_and_feel(space["key"], homepage_config)
                    if success:
                        created += 1

                self.benchmark.end_phase("space_look_and_feel", created)
                self._complete_phase("space_look_and_feel")
                self.logger.info(f"Updated {created} space look and feel settings")

    # ========== Async Generation Methods ==========

    async def generate_async(self, content_count: int, counts: dict[str, int]):
        """Generate all test data asynchronously.

        Args:
            content_count: Target number of content items
            counts: Pre-calculated item counts by type
        """
        self._init_or_resume_checkpoint(content_count, counts, async_mode=True)
        self._log_header(counts)

        # Phase 1: Create spaces
        spaces = await self._create_spaces_async(counts)

        if not spaces:
            self.logger.error("No spaces created, cannot continue")
            return

        # Phase 2: Create space-related items (labels, properties, permissions)
        if not self.content_only:
            await self._create_space_items_async(spaces, counts)

        # Phase 3: Create pages (NOT YET IMPLEMENTED)
        # pages = await self._create_pages_async(spaces, counts)

        # Phase 4: Create page-related items (NOT YET IMPLEMENTED)
        # await self._create_page_items_async(pages, counts)

        # Phase 5: Create blogposts (NOT YET IMPLEMENTED)
        # blogposts = await self._create_blogposts_async(spaces, counts)

        # Phase 6: Create blogpost-related items (NOT YET IMPLEMENTED)
        # await self._create_blogpost_items_async(blogposts, counts)

        # Phase 7: Create attachments (NOT YET IMPLEMENTED)
        # Phase 8: Create comments (NOT YET IMPLEMENTED)
        # Phase 9: Create templates (NOT YET IMPLEMENTED)

        # Close async session
        await self.space_gen.close_async_session()

        self._log_footer()

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

                # Create tasks for parallel execution
                tasks = [self.space_gen.add_space_labels_async(key, labels_per_space) for key in space_keys]
                results = await asyncio.gather(*tasks, return_exceptions=True)

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

                # Create tasks for parallel execution
                tasks = [self.space_gen.add_space_properties_async(key, props_per_space) for key in space_keys]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                created = sum(r for r in results if isinstance(r, int))

                self.benchmark.end_phase("space_properties", created)
                self._complete_phase("space_properties")
                self.logger.info(f"Created {created} space properties")

        # Space look and feel - run in parallel across spaces
        if not self._is_phase_complete("space_look_and_feel"):
            num_laf = counts.get("space_look_and_feel_setting", 0)
            if num_laf > 0:
                self._start_phase("space_look_and_feel")
                spaces_to_update = min(num_laf, len(spaces))

                self.logger.info(f"\nUpdating look and feel for {spaces_to_update} spaces (async)...")
                self.benchmark.start_phase("space_look_and_feel", spaces_to_update)

                # Create tasks for parallel execution
                tasks = []
                for space in spaces[:spaces_to_update]:
                    homepage_config = {"welcomeMessage": f"Welcome to {space.get('name', space['key'])}"}
                    tasks.append(self.space_gen.set_space_look_and_feel_async(space["key"], homepage_config))

                results = await asyncio.gather(*tasks, return_exceptions=True)
                created = sum(1 for r in results if r is True)

                self.benchmark.end_phase("space_look_and_feel", created)
                self._complete_phase("space_look_and_feel")
                self.logger.info(f"Updated {created} space look and feel settings")


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
        "--token",
        help="Confluence API token (or set CONFLUENCE_API_TOKEN in .env file or env var)",
    )
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

    # Get API token
    api_token = args.token or os.environ.get("CONFLUENCE_API_TOKEN")
    if not api_token:
        print(
            "Error: Confluence API token required. "
            "Use --token, set CONFLUENCE_API_TOKEN in .env file, or set as environment variable",
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
