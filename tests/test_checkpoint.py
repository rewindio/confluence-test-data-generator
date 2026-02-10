"""
Unit tests for generators/checkpoint.py - CheckpointManager, CheckpointData, PhaseProgress.
"""

import json

from generators.checkpoint import CheckpointData, CheckpointManager, PhaseProgress


class TestPhaseProgress:
    """Tests for PhaseProgress dataclass."""

    def test_init_defaults(self):
        """Test PhaseProgress initializes with defaults."""
        progress = PhaseProgress()
        assert progress.status == "pending"
        assert progress.target_count == 0
        assert progress.created_count == 0
        assert progress.created_items == []

    def test_init_with_values(self):
        """Test PhaseProgress with explicit values."""
        progress = PhaseProgress(
            status="in_progress", target_count=100, created_count=50, created_items=["item1", "item2"]
        )
        assert progress.status == "in_progress"
        assert progress.target_count == 100
        assert progress.created_count == 50
        assert progress.created_items == ["item1", "item2"]

    def test_to_dict(self):
        """Test PhaseProgress serialization."""
        progress = PhaseProgress(status="complete", target_count=10, created_count=10)
        result = progress.to_dict()
        assert result["status"] == "complete"
        assert result["target_count"] == 10
        assert result["created_count"] == 10
        assert "created_items" in result

    def test_from_dict(self):
        """Test PhaseProgress deserialization."""
        data = {"status": "in_progress", "target_count": 50, "created_count": 25, "created_items": ["a", "b"]}
        progress = PhaseProgress.from_dict(data)
        assert progress.status == "in_progress"
        assert progress.target_count == 50
        assert progress.created_count == 25
        assert progress.created_items == ["a", "b"]


class TestCheckpointData:
    """Tests for CheckpointData dataclass."""

    def test_init_required_fields(self):
        """Test CheckpointData with required fields."""
        data = CheckpointData(
            run_id="TESTDATA-123",
            prefix="TESTDATA",
            size="small",
            target_content_count=1000,
            started_at="2024-01-01T00:00:00",
            last_updated="2024-01-01T00:00:00",
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
        )
        assert data.run_id == "TESTDATA-123"
        assert data.prefix == "TESTDATA"
        assert data.phases == {}
        assert data.space_keys == []
        assert data.page_ids == []
        assert data.blogpost_ids == []
        assert data.content_only is False

    def test_init_with_content_only(self):
        """Test CheckpointData with content_only flag."""
        data = CheckpointData(
            run_id="TESTDATA-123",
            prefix="TESTDATA",
            size="small",
            target_content_count=1000,
            started_at="2024-01-01T00:00:00",
            last_updated="2024-01-01T00:00:00",
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            content_only=True,
        )
        assert data.content_only is True

    def test_to_dict(self):
        """Test CheckpointData serialization."""
        data = CheckpointData(
            run_id="TESTDATA-123",
            prefix="TESTDATA",
            size="small",
            target_content_count=1000,
            started_at="2024-01-01T00:00:00",
            last_updated="2024-01-01T00:00:00",
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            phases={"pages": PhaseProgress(status="in_progress", target_count=152)},
        )
        result = data.to_dict()
        assert result["run_id"] == "TESTDATA-123"
        assert result["prefix"] == "TESTDATA"
        assert "phases" in result
        assert result["phases"]["pages"]["status"] == "in_progress"

    def test_from_dict(self, sample_checkpoint_data):
        """Test CheckpointData deserialization."""
        data = CheckpointData.from_dict(sample_checkpoint_data.copy())
        assert data.run_id == "TESTDATA-20241208-120000"
        assert data.prefix == "TESTDATA"
        assert "spaces" in data.phases
        assert data.phases["spaces"].status == "complete"


class TestCheckpointManager:
    """Tests for CheckpointManager class."""

    def test_init(self, temp_checkpoint_dir):
        """Test CheckpointManager initialization."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        assert manager.prefix == "TESTDATA"
        assert manager.checkpoint_dir == temp_checkpoint_dir
        assert manager._checkpoint is None

    def test_get_checkpoint_path_no_run_id(self, temp_checkpoint_dir):
        """Test get_checkpoint_path without run_id."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        path = manager.get_checkpoint_path()
        assert path == temp_checkpoint_dir / "confluence_checkpoint_TESTDATA.json"

    def test_get_checkpoint_path_with_run_id(self, temp_checkpoint_dir):
        """Test get_checkpoint_path with run_id."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        path = manager.get_checkpoint_path(run_id="TESTDATA-20241208-120000")
        assert path == temp_checkpoint_dir / "confluence_checkpoint_TESTDATA-20241208-120000.json"

    def test_find_existing_checkpoint_none(self, temp_checkpoint_dir):
        """Test find_existing_checkpoint when none exists."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        assert manager.find_existing_checkpoint() is None

    def test_find_existing_checkpoint_prefix(self, temp_checkpoint_dir):
        """Test find_existing_checkpoint finds prefix checkpoint."""
        checkpoint_path = temp_checkpoint_dir / "confluence_checkpoint_TESTDATA.json"
        checkpoint_path.write_text("{}")

        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        found = manager.find_existing_checkpoint()
        assert found == checkpoint_path

    def test_find_existing_checkpoint_run_specific(self, temp_checkpoint_dir):
        """Test find_existing_checkpoint finds run-specific checkpoint."""
        checkpoint_path = temp_checkpoint_dir / "confluence_checkpoint_TESTDATA-20241208-120000.json"
        checkpoint_path.write_text("{}")

        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        found = manager.find_existing_checkpoint()
        assert found == checkpoint_path

    def test_initialize(self, temp_checkpoint_dir):
        """Test initialize creates checkpoint."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        counts = {"page": 152, "blogpost": 3, "attachment_v2": 659}

        result = manager.initialize(
            run_id="TESTDATA-20241208-120000",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts=counts,
        )

        assert result is not None
        assert result.run_id == "TESTDATA-20241208-120000"
        assert "pages" in result.phases
        assert result.phases["pages"].target_count == 152
        assert result.phases["blogposts"].target_count == 3
        assert result.phases["attachments"].target_count == 659

        # Check file was created
        checkpoint_path = temp_checkpoint_dir / "confluence_checkpoint_TESTDATA.json"
        assert checkpoint_path.exists()

    def test_initialize_content_only(self, temp_checkpoint_dir):
        """Test initialize with content_only mode."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        counts = {"space": 5, "page": 152, "blogpost": 3, "attachment_v2": 659, "inline_comment": 83}

        result = manager.initialize(
            run_id="TESTDATA-20241208-120000",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts=counts,
            content_only=True,
        )

        assert result.content_only is True
        # Content-only phases should have targets
        assert result.phases["spaces"].target_count == 5
        assert result.phases["pages"].target_count == 152
        assert result.phases["blogposts"].target_count == 3
        # Non-content phases should have 0 targets
        assert result.phases["attachments"].target_count == 0
        assert result.phases["inline_comments"].target_count == 0

    def test_load_success(self, temp_checkpoint_dir, sample_checkpoint_data):
        """Test load reads checkpoint file."""
        checkpoint_path = temp_checkpoint_dir / "confluence_checkpoint_TESTDATA.json"
        checkpoint_path.write_text(json.dumps(sample_checkpoint_data))

        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        result = manager.load(checkpoint_path)

        assert result is not None
        assert result.run_id == "TESTDATA-20241208-120000"
        assert len(result.space_keys) == 2

    def test_load_auto_detect(self, temp_checkpoint_dir, sample_checkpoint_data):
        """Test load auto-detects checkpoint file."""
        checkpoint_path = temp_checkpoint_dir / "confluence_checkpoint_TESTDATA.json"
        checkpoint_path.write_text(json.dumps(sample_checkpoint_data))

        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        result = manager.load()

        assert result is not None
        assert result.run_id == "TESTDATA-20241208-120000"

    def test_load_not_found(self, temp_checkpoint_dir):
        """Test load returns None when file not found."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        result = manager.load()
        assert result is None

    def test_load_invalid_json(self, temp_checkpoint_dir):
        """Test load handles invalid JSON."""
        checkpoint_path = temp_checkpoint_dir / "confluence_checkpoint_TESTDATA.json"
        checkpoint_path.write_text("not valid json")

        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        result = manager.load(checkpoint_path)
        assert result is None

    def test_save_no_checkpoint(self, temp_checkpoint_dir):
        """Test save returns False with no checkpoint."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        assert manager.save() is False

    def test_save_success(self, temp_checkpoint_dir):
        """Test save writes checkpoint file."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        # Modify and save
        manager._checkpoint.space_keys = ["TEST1"]
        result = manager.save()
        assert result is True

        # Verify file contents
        checkpoint_path = temp_checkpoint_dir / "confluence_checkpoint_TESTDATA.json"
        data = json.loads(checkpoint_path.read_text())
        assert data["space_keys"] == ["TEST1"]

    def test_checkpoint_property(self, temp_checkpoint_dir):
        """Test checkpoint property returns checkpoint."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        assert manager.checkpoint is None

        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )
        assert manager.checkpoint is not None
        assert manager.checkpoint.run_id == "TESTDATA-123"

    # ========== Phase Management Tests ==========

    def test_start_phase(self, temp_checkpoint_dir):
        """Test start_phase marks phase as in_progress."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        manager.start_phase("pages")
        assert manager._checkpoint.phases["pages"].status == "in_progress"

    def test_complete_phase(self, temp_checkpoint_dir):
        """Test complete_phase marks phase as complete."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        manager.start_phase("pages")
        manager.complete_phase("pages")
        assert manager._checkpoint.phases["pages"].status == "complete"

    def test_is_phase_complete(self, temp_checkpoint_dir):
        """Test is_phase_complete returns correct status."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        assert not manager.is_phase_complete("pages")
        manager.complete_phase("pages")
        assert manager.is_phase_complete("pages")

    def test_is_phase_complete_no_checkpoint(self, temp_checkpoint_dir):
        """Test is_phase_complete returns False with no checkpoint."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        assert not manager.is_phase_complete("pages")

    def test_get_phase_progress(self, temp_checkpoint_dir):
        """Test get_phase_progress returns phase."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={"page": 152},
        )

        progress = manager.get_phase_progress("pages")
        assert progress is not None
        assert progress.target_count == 152

    def test_get_phase_progress_not_found(self, temp_checkpoint_dir):
        """Test get_phase_progress returns None for unknown phase."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )
        assert manager.get_phase_progress("unknown") is None

    def test_get_remaining_count(self, temp_checkpoint_dir):
        """Test get_remaining_count calculation."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={"page": 152},
        )

        # Initially all remaining
        assert manager.get_remaining_count("pages") == 152

        # After some created
        manager._checkpoint.phases["pages"].created_count = 50
        assert manager.get_remaining_count("pages") == 102

    # ========== Progress Updates Tests ==========

    def test_update_phase_count(self, temp_checkpoint_dir):
        """Test update_phase_count sets count."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={"page": 152},
        )

        manager.update_phase_count("pages", 100)
        assert manager._checkpoint.phases["pages"].created_count == 100

    def test_increment_phase_count(self, temp_checkpoint_dir):
        """Test increment_phase_count adds to count."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={"page": 152},
        )

        manager.increment_phase_count("pages", 10)
        assert manager._checkpoint.phases["pages"].created_count == 10
        manager.increment_phase_count("pages", 5)
        assert manager._checkpoint.phases["pages"].created_count == 15

    def test_add_phase_items(self, temp_checkpoint_dir):
        """Test add_phase_items adds items and updates count."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        manager.add_phase_items("spaces", ["TEST1", "TEST2"])
        assert manager._checkpoint.phases["spaces"].created_items == ["TEST1", "TEST2"]
        assert manager._checkpoint.phases["spaces"].created_count == 2

    # ========== Critical Data Updates Tests ==========

    def test_set_spaces(self, temp_checkpoint_dir):
        """Test set_spaces stores space data."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        spaces = [{"key": "TEST1", "id": "10001"}, {"key": "TEST2", "id": "10002"}]
        manager.set_spaces(spaces)

        assert manager._checkpoint.space_keys == ["TEST1", "TEST2"]
        assert manager._checkpoint.space_ids == {"TEST1": "10001", "TEST2": "10002"}

    def test_add_space(self, temp_checkpoint_dir):
        """Test add_space adds single space."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        manager.add_space("TEST1", "10001")
        assert "TEST1" in manager._checkpoint.space_keys
        assert manager._checkpoint.space_ids["TEST1"] == "10001"

        # Adding same space again shouldn't duplicate
        manager.add_space("TEST1", "10001")
        assert manager._checkpoint.space_keys.count("TEST1") == 1

    def test_add_page_ids(self, temp_checkpoint_dir):
        """Test add_page_ids stores page data."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        manager.add_page_ids(["100001", "100002"], "TEST1")

        assert "100001" in manager._checkpoint.page_ids
        assert manager._checkpoint.pages_per_space["TEST1"] == 2
        assert manager._checkpoint.phases["pages"].created_count == 2

    def test_add_page_ids_large_count(self, temp_checkpoint_dir):
        """Test add_page_ids stops storing IDs after 100k."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=200000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        # Add 100k IDs
        ids = [str(i) for i in range(1, 100001)]
        manager.add_page_ids(ids, "TEST1")
        assert len(manager._checkpoint.page_ids) == 100000

        # Try to add more - count should update but IDs list should not grow
        more_ids = [str(i) for i in range(100001, 100011)]
        manager.add_page_ids(more_ids, "TEST1")
        assert len(manager._checkpoint.page_ids) == 100000  # Still capped
        assert manager._checkpoint.pages_per_space["TEST1"] == 100010  # Count updated

    def test_add_blogpost_ids(self, temp_checkpoint_dir):
        """Test add_blogpost_ids stores blogpost data."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        manager.add_blogpost_ids(["200001", "200002"], "TEST1")

        assert "200001" in manager._checkpoint.blogpost_ids
        assert manager._checkpoint.blogposts_per_space["TEST1"] == 2
        assert manager._checkpoint.phases["blogposts"].created_count == 2

    def test_get_total_pages_created(self, temp_checkpoint_dir):
        """Test get_total_pages_created sums all spaces."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        manager.add_page_ids(["100001", "100002"], "TEST1")
        manager.add_page_ids(["100003", "100004", "100005"], "TEST2")

        assert manager.get_total_pages_created() == 5

    def test_get_total_pages_created_no_checkpoint(self, temp_checkpoint_dir):
        """Test get_total_pages_created returns 0 with no checkpoint."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        assert manager.get_total_pages_created() == 0

    def test_get_total_blogposts_created(self, temp_checkpoint_dir):
        """Test get_total_blogposts_created sums all spaces."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        manager.add_blogpost_ids(["200001", "200002"], "TEST1")
        manager.add_blogpost_ids(["200003"], "TEST2")

        assert manager.get_total_blogposts_created() == 3

    # ========== Resume Helpers Tests ==========

    def test_get_pages_needed_per_space_no_checkpoint(self, temp_checkpoint_dir):
        """Test get_pages_needed_per_space without checkpoint."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        spaces = [{"key": "TEST1"}, {"key": "TEST2"}]

        result = manager.get_pages_needed_per_space(spaces, 100)
        assert result["TEST1"] == 50
        assert result["TEST2"] == 50

    def test_get_pages_needed_per_space_with_checkpoint(self, temp_checkpoint_dir):
        """Test get_pages_needed_per_space with partial progress."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        # Add some existing pages
        manager.add_page_ids([str(i) for i in range(30)], "TEST1")

        spaces = [{"key": "TEST1"}, {"key": "TEST2"}]
        result = manager.get_pages_needed_per_space(spaces, 100)

        assert result["TEST1"] == 20  # 50 - 30 = 20
        assert result["TEST2"] == 50  # None created yet

    def test_get_pages_needed_per_space_uneven_distribution(self, temp_checkpoint_dir):
        """Test get_pages_needed_per_space with uneven count."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        spaces = [{"key": "TEST1"}, {"key": "TEST2"}, {"key": "TEST3"}]

        result = manager.get_pages_needed_per_space(spaces, 100)
        # 100 / 3 = 33 with 1 remainder
        total = sum(result.values())
        assert total == 100

    def test_get_pages_needed_per_space_empty_spaces(self, temp_checkpoint_dir):
        """Test get_pages_needed_per_space with empty spaces list."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        result = manager.get_pages_needed_per_space([], 100)
        assert result == {}

    def test_get_blogposts_needed_per_space(self, temp_checkpoint_dir):
        """Test get_blogposts_needed_per_space calculation."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        # Add some existing blogposts
        manager.add_blogpost_ids(["200001", "200002"], "TEST1")

        spaces = [{"key": "TEST1"}, {"key": "TEST2"}]
        result = manager.get_blogposts_needed_per_space(spaces, 10)

        assert result["TEST1"] == 3  # 5 - 2 = 3
        assert result["TEST2"] == 5  # None created yet

    def test_get_resume_summary_no_checkpoint(self, temp_checkpoint_dir):
        """Test get_resume_summary without checkpoint."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        assert "No checkpoint loaded" in manager.get_resume_summary()

    def test_get_resume_summary(self, temp_checkpoint_dir):
        """Test get_resume_summary with checkpoint."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={"page": 152},
        )

        manager._checkpoint.space_keys = ["TEST1", "TEST2"]

        # Set target and create count for spaces to show in summary
        manager._checkpoint.phases["spaces"].target_count = 2
        manager._checkpoint.phases["spaces"].created_count = 2
        manager.complete_phase("spaces")

        manager.start_phase("pages")
        manager._checkpoint.phases["pages"].target_count = 152
        manager._checkpoint.phases["pages"].created_count = 50

        summary = manager.get_resume_summary()
        assert "Resuming run" in summary
        assert "TESTDATA-123" in summary
        assert "[OK]" in summary  # spaces complete
        assert "[>>]" in summary  # pages in progress

    def test_finalize(self, temp_checkpoint_dir):
        """Test finalize completes phases and renames file."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-20241208-120000",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        # Set all counts to match targets
        manager._checkpoint.phases["pages"].created_count = 152
        manager._checkpoint.phases["pages"].target_count = 152

        manager.finalize()

        # Check file was renamed
        final_path = temp_checkpoint_dir / "confluence_checkpoint_TESTDATA-20241208-120000.json"
        assert final_path.exists()

        # Original path should not exist
        original_path = temp_checkpoint_dir / "confluence_checkpoint_TESTDATA.json"
        assert not original_path.exists()

    def test_delete(self, temp_checkpoint_dir):
        """Test delete removes checkpoint file."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        checkpoint_path = temp_checkpoint_dir / "confluence_checkpoint_TESTDATA.json"
        assert checkpoint_path.exists()

        result = manager.delete()
        assert result is True
        assert not checkpoint_path.exists()

    def test_delete_no_file(self, temp_checkpoint_dir):
        """Test delete returns False when no file."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        assert manager.delete() is False

    def test_phase_order(self):
        """Test PHASE_ORDER contains expected phases."""
        assert "spaces" in CheckpointManager.PHASE_ORDER
        assert "pages" in CheckpointManager.PHASE_ORDER
        assert "blogposts" in CheckpointManager.PHASE_ORDER
        assert "attachments" in CheckpointManager.PHASE_ORDER
        assert "inline_comments" in CheckpointManager.PHASE_ORDER
        assert "footer_comments" in CheckpointManager.PHASE_ORDER

    def test_content_only_phases(self):
        """Test CONTENT_ONLY_PHASES contains expected phases."""
        assert "spaces" in CheckpointManager.CONTENT_ONLY_PHASES
        assert "pages" in CheckpointManager.CONTENT_ONLY_PHASES
        assert "blogposts" in CheckpointManager.CONTENT_ONLY_PHASES
        assert len(CheckpointManager.CONTENT_ONLY_PHASES) == 3

    # ========== Attachment Metadata Tests ==========

    def test_to_dict_includes_attachment_metadata(self, temp_checkpoint_dir):
        """Test that to_dict includes attachment_metadata field."""
        data = CheckpointData(
            run_id="TESTDATA-123",
            prefix="TESTDATA",
            size="small",
            target_content_count=1000,
            started_at="2024-01-01T00:00:00",
            last_updated="2024-01-01T00:00:00",
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            attachment_metadata=[{"id": "att-1", "title": "f.txt", "pageId": "100"}],
        )
        result = data.to_dict()
        assert "attachment_metadata" in result
        assert len(result["attachment_metadata"]) == 1
        assert result["attachment_metadata"][0]["id"] == "att-1"

    def test_from_dict_with_attachment_metadata(self, sample_checkpoint_data):
        """Test from_dict deserializes attachment_metadata."""
        data = CheckpointData.from_dict(sample_checkpoint_data.copy())
        assert len(data.attachment_metadata) == 2
        assert data.attachment_metadata[0]["id"] == "att-1"
        assert data.attachment_metadata[1]["title"] == "file2.txt"

    def test_from_dict_without_attachment_metadata(self):
        """Test from_dict handles old checkpoints missing attachment_metadata."""
        old_data = {
            "run_id": "OLD-123",
            "prefix": "OLD",
            "size": "small",
            "target_content_count": 100,
            "started_at": "2024-01-01T00:00:00",
            "last_updated": "2024-01-01T00:00:00",
            "confluence_url": "https://test.atlassian.net/wiki",
            "async_mode": True,
            "concurrency": 5,
            "content_only": False,
            "space_keys": [],
            "space_ids": {},
            "page_ids": [],
            "blogpost_ids": [],
            "pages_per_space": {},
            "blogposts_per_space": {},
            "phases": {},
        }
        data = CheckpointData.from_dict(old_data.copy())
        assert data.attachment_metadata == []

    def test_add_attachment_metadata(self, temp_checkpoint_dir):
        """Test add_attachment_metadata stores metadata and updates phase count."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={"attachment_v2": 100},
        )

        attachments = [
            {"id": "att-1", "title": "file1.txt", "pageId": "100001"},
            {"id": "att-2", "title": "file2.txt", "pageId": "100002"},
        ]
        manager.add_attachment_metadata(attachments)

        assert len(manager._checkpoint.attachment_metadata) == 2
        assert manager._checkpoint.phases["attachments"].created_count == 2

    def test_add_attachment_metadata_caps_at_100k(self, temp_checkpoint_dir):
        """Test add_attachment_metadata caps stored metadata at 100k."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=200000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={"attachment_v2": 200000},
        )

        # Add 100k attachments
        batch = [{"id": f"att-{i}", "title": f"f{i}.txt", "pageId": "100"} for i in range(100000)]
        manager.add_attachment_metadata(batch)
        assert len(manager._checkpoint.attachment_metadata) == 100000

        # Try to add more - list should not grow
        more = [{"id": "att-extra", "title": "extra.txt", "pageId": "100"}]
        manager.add_attachment_metadata(more)
        assert len(manager._checkpoint.attachment_metadata) == 100000
        # Phase count reflects capped list size
        assert manager._checkpoint.phases["attachments"].created_count == 100000

    def test_get_total_attachments_created(self, temp_checkpoint_dir):
        """Test get_total_attachments_created returns correct count."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={"attachment_v2": 100},
        )

        attachments = [
            {"id": "att-1", "title": "f1.txt", "pageId": "100"},
            {"id": "att-2", "title": "f2.txt", "pageId": "200"},
            {"id": "att-3", "title": "f3.txt", "pageId": "300"},
        ]
        manager.add_attachment_metadata(attachments)
        assert manager.get_total_attachments_created() == 3

    def test_get_total_attachments_created_no_checkpoint(self, temp_checkpoint_dir):
        """Test get_total_attachments_created returns 0 with no checkpoint."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        assert manager.get_total_attachments_created() == 0

    def test_resume_summary_includes_attachments(self, temp_checkpoint_dir):
        """Test get_resume_summary includes attachment count."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={"attachment_v2": 100},
        )

        attachments = [{"id": "att-1", "title": "f1.txt", "pageId": "100"}]
        manager.add_attachment_metadata(attachments)

        summary = manager.get_resume_summary()
        assert "Total attachments: 1" in summary

    def test_atomic_save(self, temp_checkpoint_dir):
        """Test save uses atomic write (temp file + rename)."""
        manager = CheckpointManager("TESTDATA", checkpoint_dir=temp_checkpoint_dir)
        manager.initialize(
            run_id="TESTDATA-123",
            size="small",
            target_content_count=1000,
            confluence_url="https://test.atlassian.net/wiki",
            async_mode=True,
            concurrency=5,
            counts={},
        )

        # The temp file shouldn't exist after save completes
        temp_path = temp_checkpoint_dir / "confluence_checkpoint_TESTDATA.tmp"
        manager.save()
        assert not temp_path.exists()

        # But the actual checkpoint should exist
        checkpoint_path = temp_checkpoint_dir / "confluence_checkpoint_TESTDATA.json"
        assert checkpoint_path.exists()
