"""
Checkpoint management for resumable data generation.

Provides checkpoint saving and loading for long-running data generation tasks,
allowing resumption after failures or interruptions.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class PhaseProgress:
    """Tracks progress for a single generation phase."""

    status: str = "pending"  # pending, in_progress, complete
    target_count: int = 0
    created_count: int = 0
    # For phases that create named items (spaces, etc.)
    created_items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PhaseProgress":
        return cls(**data)


@dataclass
class CheckpointData:
    """Complete checkpoint state for a generation run."""

    # Run identification
    run_id: str
    prefix: str
    size: str
    target_content_count: int

    # Timestamps
    started_at: str
    last_updated: str

    # Configuration
    confluence_url: str
    async_mode: bool
    concurrency: int
    content_only: bool = False

    # Phase progress
    phases: dict[str, PhaseProgress] = field(default_factory=dict)

    # Critical data needed for resume
    space_keys: list[str] = field(default_factory=list)
    space_ids: dict[str, str] = field(default_factory=dict)  # key -> id mapping
    page_ids: list[str] = field(default_factory=list)
    blogpost_ids: list[str] = field(default_factory=list)

    # For large content counts, track per-space to avoid huge lists
    pages_per_space: dict[str, int] = field(default_factory=dict)
    blogposts_per_space: dict[str, int] = field(default_factory=dict)

    # Attachment metadata for resume (each dict has: id, title, pageId)
    attachment_metadata: list[dict[str, str]] = field(default_factory=list)

    # Comment metadata for resume (each dict has: id, pageId)
    inline_comment_metadata: list[dict[str, str]] = field(default_factory=list)
    footer_comment_metadata: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "run_id": self.run_id,
            "prefix": self.prefix,
            "size": self.size,
            "target_content_count": self.target_content_count,
            "started_at": self.started_at,
            "last_updated": self.last_updated,
            "confluence_url": self.confluence_url,
            "async_mode": self.async_mode,
            "concurrency": self.concurrency,
            "content_only": self.content_only,
            "space_keys": self.space_keys,
            "space_ids": self.space_ids,
            "page_ids": self.page_ids,
            "blogpost_ids": self.blogpost_ids,
            "pages_per_space": self.pages_per_space,
            "blogposts_per_space": self.blogposts_per_space,
            "attachment_metadata": self.attachment_metadata,
            "inline_comment_metadata": self.inline_comment_metadata,
            "footer_comment_metadata": self.footer_comment_metadata,
            "phases": {k: v.to_dict() for k, v in self.phases.items()},
        }
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CheckpointData":
        # Work on a shallow copy to avoid mutating the caller's dictionary
        data = dict(data)
        phases = {k: PhaseProgress.from_dict(v) for k, v in data.pop("phases", {}).items()}
        return cls(phases=phases, **data)


class CheckpointManager:
    """Manages checkpoint file operations for resumable generation.

    Thread-Safety Note:
        This class is designed for single-threaded use by the main orchestrator.
        Checkpoint updates are serialized through the orchestrator even when using
        async concurrency for API calls. Do not call checkpoint methods from multiple
        concurrent tasks - the orchestrator should aggregate results and update the
        checkpoint from a single task.
    """

    # All phases in execution order
    PHASE_ORDER = [
        "spaces",
        "space_properties",
        "space_labels",
        "space_permissions",
        "space_look_and_feel",
        "templates",
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
        "folders",
        "folder_restrictions",
        "inline_comments",
        "inline_comment_versions",
        "footer_comments",
        "footer_comment_versions",
    ]

    # Content-only phases (subset used with --content-only flag)
    CONTENT_ONLY_PHASES = [
        "spaces",
        "pages",
        "blogposts",
    ]

    def __init__(self, prefix: str, checkpoint_dir: Path | None = None):
        """Initialize checkpoint manager.

        Args:
            prefix: The run prefix (used for checkpoint filename)
            checkpoint_dir: Directory to store checkpoints (default: current directory)
        """
        self.prefix = prefix
        self.checkpoint_dir = checkpoint_dir or Path.cwd()
        self.logger = logging.getLogger(__name__)
        self._checkpoint: CheckpointData | None = None
        self._checkpoint_path: Path | None = None

    def get_checkpoint_path(self, run_id: str | None = None) -> Path:
        """Get the checkpoint file path."""
        if run_id:
            return self.checkpoint_dir / f"confluence_checkpoint_{run_id}.json"
        return self.checkpoint_dir / f"confluence_checkpoint_{self.prefix}.json"

    def find_existing_checkpoint(self) -> Path | None:
        """Find an existing checkpoint file for this prefix."""
        # First check for prefix-only checkpoint (active/latest)
        prefix_checkpoint = self.get_checkpoint_path()
        if prefix_checkpoint.exists():
            return prefix_checkpoint

        # Look for any run-specific checkpoints
        pattern = f"confluence_checkpoint_{self.prefix}-*.json"
        checkpoints = sorted(self.checkpoint_dir.glob(pattern), reverse=True)
        if checkpoints:
            return checkpoints[0]

        return None

    def initialize(
        self,
        run_id: str,
        size: str,
        target_content_count: int,
        confluence_url: str,
        async_mode: bool,
        concurrency: int,
        counts: dict[str, int],
        content_only: bool = False,
    ) -> CheckpointData:
        """Initialize a new checkpoint for a fresh run.

        Args:
            run_id: Unique run identifier
            size: Size bucket (small, medium, large)
            target_content_count: Total content items to create
            confluence_url: Confluence instance URL
            async_mode: Whether async mode is enabled
            concurrency: Concurrency level
            counts: Calculated counts for each item type
            content_only: Whether content-only mode is enabled

        Returns:
            Initialized CheckpointData
        """
        now = datetime.now().isoformat()

        # Initialize all phases from counts
        phases = {}
        phase_mapping = {
            "spaces": "space",
            "space_properties": "space_property",
            "space_labels": "space_label",
            "space_permissions": "space_permission",
            "space_look_and_feel": "space_look_and_feel",
            "templates": "template",
            "pages": "page",
            "page_labels": "page_label",
            "page_properties": "page_property",
            "page_restrictions": "page_restriction_v2",
            "page_versions": "page_version",
            "blogposts": "blogpost",
            "blogpost_labels": "blogpost_label",
            "blogpost_properties": "blogpost_property",
            "blogpost_restrictions": "blogpost_restriction_v2",
            "blogpost_versions": "blogpost_version",
            "attachments": "attachment_v2",
            "attachment_labels": "attachment_label",
            "attachment_versions": "attachment_version",
            "folders": "folder",
            "folder_restrictions": "folder_restriction",
            "inline_comments": "inline_comment",
            "inline_comment_versions": "inline_comment_version",
            "footer_comments": "footer_comment",
            "footer_comment_versions": "footer_comment_version",
        }

        # Determine which phases to include
        active_phases = self.CONTENT_ONLY_PHASES if content_only else self.PHASE_ORDER

        for phase_name in self.PHASE_ORDER:
            count_key = phase_mapping.get(phase_name)
            if count_key and count_key in counts:
                target = counts[count_key] if phase_name in active_phases else 0
            else:
                target = 0

            phases[phase_name] = PhaseProgress(status="pending", target_count=target, created_count=0, created_items=[])

        self._checkpoint = CheckpointData(
            run_id=run_id,
            prefix=self.prefix,
            size=size,
            target_content_count=target_content_count,
            started_at=now,
            last_updated=now,
            confluence_url=confluence_url,
            async_mode=async_mode,
            concurrency=concurrency,
            content_only=content_only,
            phases=phases,
            space_keys=[],
            space_ids={},
            page_ids=[],
            blogpost_ids=[],
            pages_per_space={},
            blogposts_per_space={},
        )

        # Use prefix-only path for active checkpoint
        self._checkpoint_path = self.get_checkpoint_path()
        self.save()

        self.logger.info(f"Initialized checkpoint: {self._checkpoint_path}")
        return self._checkpoint

    def load(self, checkpoint_path: Path | None = None) -> CheckpointData | None:
        """Load checkpoint from file.

        Args:
            checkpoint_path: Path to checkpoint file (auto-detect if None)

        Returns:
            Loaded CheckpointData or None if not found
        """
        if checkpoint_path is None:
            checkpoint_path = self.find_existing_checkpoint()

        if checkpoint_path is None or not checkpoint_path.exists():
            self.logger.debug(f"No checkpoint found for prefix: {self.prefix}")
            return None

        try:
            with open(checkpoint_path) as f:
                data = json.load(f)

            self._checkpoint = CheckpointData.from_dict(data)
            self._checkpoint_path = checkpoint_path
            self.logger.info(f"Loaded checkpoint from: {checkpoint_path}")
            self.logger.info(f"  Run ID: {self._checkpoint.run_id}")
            self.logger.info(f"  Started: {self._checkpoint.started_at}")
            self.logger.info(f"  Last updated: {self._checkpoint.last_updated}")

            return self._checkpoint

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            self.logger.error(f"Failed to load checkpoint from {checkpoint_path}: {e}")
            return None

    def save(self) -> bool:
        """Save current checkpoint to file.

        Returns:
            True if successful, False otherwise
        """
        if self._checkpoint is None:
            self.logger.warning("No checkpoint data to save")
            return False

        if self._checkpoint_path is None:
            self._checkpoint_path = self.get_checkpoint_path()

        self._checkpoint.last_updated = datetime.now().isoformat()

        try:
            # Write to temp file first, then rename for atomicity
            temp_path = self._checkpoint_path.with_suffix(".tmp")
            with open(temp_path, "w") as f:
                json.dump(self._checkpoint.to_dict(), f, indent=2)

            temp_path.replace(self._checkpoint_path)
            return True

        except OSError as e:
            self.logger.error(f"Failed to save checkpoint: {e}")
            return False

    @property
    def checkpoint(self) -> CheckpointData | None:
        """Get current checkpoint data."""
        return self._checkpoint

    # ========== Phase Management ==========

    def start_phase(self, phase_name: str) -> None:
        """Mark a phase as in progress."""
        if self._checkpoint and phase_name in self._checkpoint.phases:
            self._checkpoint.phases[phase_name].status = "in_progress"
            self.save()

    def complete_phase(self, phase_name: str) -> None:
        """Mark a phase as complete."""
        if self._checkpoint and phase_name in self._checkpoint.phases:
            self._checkpoint.phases[phase_name].status = "complete"
            self.save()

    def is_phase_complete(self, phase_name: str) -> bool:
        """Check if a phase is complete."""
        if self._checkpoint and phase_name in self._checkpoint.phases:
            return self._checkpoint.phases[phase_name].status == "complete"
        return False

    def get_phase_progress(self, phase_name: str) -> PhaseProgress | None:
        """Get progress for a specific phase."""
        if self._checkpoint and phase_name in self._checkpoint.phases:
            return self._checkpoint.phases[phase_name]
        return None

    def get_remaining_count(self, phase_name: str) -> int:
        """Get remaining items to create for a phase."""
        progress = self.get_phase_progress(phase_name)
        if progress:
            return max(0, progress.target_count - progress.created_count)
        return 0

    # ========== Progress Updates ==========

    def update_phase_count(self, phase_name: str, created_count: int) -> None:
        """Update the created count for a phase.

        Args:
            phase_name: Phase to update
            created_count: Total items created so far (not increment)
        """
        if self._checkpoint and phase_name in self._checkpoint.phases:
            self._checkpoint.phases[phase_name].created_count = created_count
            self.save()

    def increment_phase_count(self, phase_name: str, increment: int = 1) -> None:
        """Increment the created count for a phase.

        Args:
            phase_name: Phase to update
            increment: Number of items to add to count
        """
        if self._checkpoint and phase_name in self._checkpoint.phases:
            self._checkpoint.phases[phase_name].created_count += increment
            # Save periodically (every 50 items) to avoid excessive I/O
            if self._checkpoint.phases[phase_name].created_count % 50 == 0:
                self.save()

    def add_phase_items(self, phase_name: str, items: list[str]) -> None:
        """Add created items to a phase (for items that need to be tracked).

        Args:
            phase_name: Phase to update
            items: List of item identifiers (keys, IDs, etc.)
        """
        if self._checkpoint and phase_name in self._checkpoint.phases:
            self._checkpoint.phases[phase_name].created_items.extend(items)
            self._checkpoint.phases[phase_name].created_count = len(self._checkpoint.phases[phase_name].created_items)
            self.save()

    # ========== Critical Data Updates ==========

    def set_spaces(self, spaces: list[dict[str, str]]) -> None:
        """Store created spaces.

        Args:
            spaces: List of space dicts with 'key' and 'id'
        """
        if self._checkpoint:
            self._checkpoint.space_keys = [s["key"] for s in spaces]
            self._checkpoint.space_ids = {s["key"]: s["id"] for s in spaces}
            self.save()

    def add_space(self, space_key: str, space_id: str) -> None:
        """Add a single space to checkpoint."""
        if self._checkpoint:
            if space_key not in self._checkpoint.space_keys:
                self._checkpoint.space_keys.append(space_key)
            self._checkpoint.space_ids[space_key] = space_id
            self.save()

    def add_page_ids(self, page_ids: list[str], space_key: str) -> None:
        """Add page IDs to checkpoint.

        Args:
            page_ids: List of page IDs created
            space_key: Space the pages belong to
        """
        if self._checkpoint:
            # For very large runs, we only track count per space
            if len(self._checkpoint.page_ids) < 100000:
                self._checkpoint.page_ids.extend(page_ids)

            # Always track per-space counts
            current = self._checkpoint.pages_per_space.get(space_key, 0)
            self._checkpoint.pages_per_space[space_key] = current + len(page_ids)

            # Update phase progress
            total_pages = sum(self._checkpoint.pages_per_space.values())
            self._checkpoint.phases["pages"].created_count = total_pages

            # Save periodically (every 500 pages) to balance safety vs performance
            if total_pages % 500 == 0:
                self.save()

    def add_blogpost_ids(self, blogpost_ids: list[str], space_key: str) -> None:
        """Add blogpost IDs to checkpoint.

        Args:
            blogpost_ids: List of blogpost IDs created
            space_key: Space the blogposts belong to
        """
        if self._checkpoint:
            # For very large runs, we only track count per space
            if len(self._checkpoint.blogpost_ids) < 100000:
                self._checkpoint.blogpost_ids.extend(blogpost_ids)

            # Always track per-space counts
            current = self._checkpoint.blogposts_per_space.get(space_key, 0)
            self._checkpoint.blogposts_per_space[space_key] = current + len(blogpost_ids)

            # Update phase progress
            total_blogposts = sum(self._checkpoint.blogposts_per_space.values())
            self._checkpoint.phases["blogposts"].created_count = total_blogposts

            # Save periodically (every 500 blogposts)
            if total_blogposts % 500 == 0:
                self.save()

    def get_total_pages_created(self) -> int:
        """Get total number of pages created across all spaces."""
        if self._checkpoint:
            return sum(self._checkpoint.pages_per_space.values())
        return 0

    def get_total_blogposts_created(self) -> int:
        """Get total number of blogposts created across all spaces."""
        if self._checkpoint:
            return sum(self._checkpoint.blogposts_per_space.values())
        return 0

    def add_attachment_metadata(self, attachments: list[dict[str, str]]) -> None:
        """Add attachment metadata to checkpoint for resume support.

        Args:
            attachments: List of attachment dicts with keys: id, title, pageId
        """
        if self._checkpoint:
            # Cap stored metadata at 100k to avoid huge checkpoint files
            if len(self._checkpoint.attachment_metadata) < 100000:
                remaining_capacity = 100000 - len(self._checkpoint.attachment_metadata)
                self._checkpoint.attachment_metadata.extend(attachments[:remaining_capacity])

            # Always update phase count
            total = len(self._checkpoint.attachment_metadata)
            self._checkpoint.phases["attachments"].created_count = total

            # Save periodically (every 500 attachments)
            if total % 500 == 0:
                self.save()

    def add_inline_comment_metadata(self, comments: list[dict[str, str]]) -> None:
        """Add inline comment metadata to checkpoint for resume support.

        Args:
            comments: List of comment dicts with keys: id, pageId
        """
        if self._checkpoint:
            if len(self._checkpoint.inline_comment_metadata) < 100000:
                remaining_capacity = 100000 - len(self._checkpoint.inline_comment_metadata)
                self._checkpoint.inline_comment_metadata.extend(comments[:remaining_capacity])

            total = len(self._checkpoint.inline_comment_metadata)
            self._checkpoint.phases["inline_comments"].created_count = total

            if total % 500 == 0:
                self.save()

    def add_footer_comment_metadata(self, comments: list[dict[str, str]]) -> None:
        """Add footer comment metadata to checkpoint for resume support.

        Args:
            comments: List of comment dicts with keys: id, pageId
        """
        if self._checkpoint:
            if len(self._checkpoint.footer_comment_metadata) < 100000:
                remaining_capacity = 100000 - len(self._checkpoint.footer_comment_metadata)
                self._checkpoint.footer_comment_metadata.extend(comments[:remaining_capacity])

            total = len(self._checkpoint.footer_comment_metadata)
            self._checkpoint.phases["footer_comments"].created_count = total

            if total % 500 == 0:
                self.save()

    def get_total_attachments_created(self) -> int:
        """Get total number of attachments tracked in checkpoint."""
        if self._checkpoint:
            return len(self._checkpoint.attachment_metadata)
        return 0

    # ========== Resume Helpers ==========

    def get_pages_needed_per_space(self, spaces: list[dict], total_pages: int) -> dict[str, int]:
        """Calculate how many pages still need to be created per space.

        Args:
            spaces: List of space dicts with 'key'
            total_pages: Total target page count

        Returns:
            Dict mapping space_key -> pages_to_create
        """
        if not spaces:
            return {}

        if not self._checkpoint:
            # No checkpoint - create all pages evenly distributed
            per_space = total_pages // len(spaces)
            remainder = total_pages % len(spaces)
            return {s["key"]: per_space + (1 if i < remainder else 0) for i, s in enumerate(spaces)}

        # Calculate remaining per space
        existing = self._checkpoint.pages_per_space
        per_space = total_pages // len(spaces)
        remainder = total_pages % len(spaces)

        result = {}
        for i, space in enumerate(spaces):
            key = space["key"]
            target = per_space + (1 if i < remainder else 0)
            created = existing.get(key, 0)
            result[key] = max(0, target - created)

        return result

    def get_blogposts_needed_per_space(self, spaces: list[dict], total_blogposts: int) -> dict[str, int]:
        """Calculate how many blogposts still need to be created per space.

        Args:
            spaces: List of space dicts with 'key'
            total_blogposts: Total target blogpost count

        Returns:
            Dict mapping space_key -> blogposts_to_create
        """
        if not spaces:
            return {}

        if not self._checkpoint:
            # No checkpoint - create all blogposts evenly distributed
            per_space = total_blogposts // len(spaces)
            remainder = total_blogposts % len(spaces)
            return {s["key"]: per_space + (1 if i < remainder else 0) for i, s in enumerate(spaces)}

        # Calculate remaining per space
        existing = self._checkpoint.blogposts_per_space
        per_space = total_blogposts // len(spaces)
        remainder = total_blogposts % len(spaces)

        result = {}
        for i, space in enumerate(spaces):
            key = space["key"]
            target = per_space + (1 if i < remainder else 0)
            created = existing.get(key, 0)
            result[key] = max(0, target - created)

        return result

    def get_resume_summary(self) -> str:
        """Get a human-readable summary of checkpoint state for resume."""
        if not self._checkpoint:
            return "No checkpoint loaded"

        lines = [
            f"Resuming run: {self._checkpoint.run_id}",
            f"Started: {self._checkpoint.started_at}",
            f"Last updated: {self._checkpoint.last_updated}",
            f"Content-only mode: {self._checkpoint.content_only}",
            "",
            "Phase Progress:",
        ]

        for phase_name in self.PHASE_ORDER:
            progress = self._checkpoint.phases.get(phase_name)
            if progress and progress.target_count > 0:
                status_icon = {"complete": "[OK]", "in_progress": "[>>]", "pending": "[  ]"}.get(
                    progress.status, "[??]"
                )

                lines.append(f"  {status_icon} {phase_name}: {progress.created_count}/{progress.target_count}")

        lines.append("")
        lines.append(f"Spaces: {len(self._checkpoint.space_keys)}")
        lines.append(f"Total pages: {self.get_total_pages_created()}")
        lines.append(f"Total blogposts: {self.get_total_blogposts_created()}")
        lines.append(f"Total attachments: {self.get_total_attachments_created()}")
        lines.append(f"Target content: {self._checkpoint.target_content_count}")

        return "\n".join(lines)

    def finalize(self) -> None:
        """Mark all phases as complete and rename checkpoint to include run_id."""
        if not self._checkpoint:
            return

        # Mark all phases complete
        for phase in self._checkpoint.phases.values():
            if phase.status != "complete" and phase.created_count >= phase.target_count:
                phase.status = "complete"

        self.save()

        # Rename to run_id-specific file for archival
        if self._checkpoint_path:
            final_path = self.get_checkpoint_path(self._checkpoint.run_id)
            if self._checkpoint_path != final_path:
                try:
                    # Use replace for atomic overwrite if final_path already exists
                    self._checkpoint_path.replace(final_path)
                    self.logger.info(f"Archived checkpoint to: {final_path}")
                except OSError as e:
                    self.logger.warning(f"Could not archive checkpoint: {e}")

    def delete(self) -> bool:
        """Delete the checkpoint file."""
        if self._checkpoint_path and self._checkpoint_path.exists():
            try:
                self._checkpoint_path.unlink()
                self.logger.info(f"Deleted checkpoint: {self._checkpoint_path}")
                return True
            except OSError as e:
                self.logger.error(f"Failed to delete checkpoint: {e}")
                return False
        return False
