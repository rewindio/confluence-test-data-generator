"""Tests for generators/benchmark.py - PhaseMetrics and BenchmarkTracker."""

import time

from generators.benchmark import CONFLUENCE_SIZE_TIERS, BenchmarkTracker, PhaseMetrics


class TestPhaseMetricsInitialization:
    """Tests for PhaseMetrics dataclass initialization."""

    def test_default_initialization(self):
        """Test PhaseMetrics initializes with correct defaults."""
        metrics = PhaseMetrics(name="test_phase")

        assert metrics.name == "test_phase"
        assert metrics.start_time is None
        assert metrics.end_time is None
        assert metrics.items_created == 0
        assert metrics.items_target == 0
        assert metrics.rate_limited == 0
        assert metrics.errors == 0

    def test_full_initialization(self):
        """Test PhaseMetrics with all values."""
        metrics = PhaseMetrics(
            name="pages",
            start_time=1000.0,
            end_time=1100.0,
            items_created=500,
            items_target=1000,
            rate_limited=5,
            errors=2,
        )

        assert metrics.name == "pages"
        assert metrics.start_time == 1000.0
        assert metrics.end_time == 1100.0
        assert metrics.items_created == 500
        assert metrics.items_target == 1000
        assert metrics.rate_limited == 5
        assert metrics.errors == 2


class TestPhaseMetricsDurationSeconds:
    """Tests for PhaseMetrics.duration_seconds property."""

    def test_duration_with_start_and_end(self):
        """Test duration calculation with both start and end times."""
        metrics = PhaseMetrics(name="test", start_time=1000.0, end_time=1100.0)

        assert metrics.duration_seconds == 100.0

    def test_duration_with_only_start_uses_current_time(self):
        """Test duration uses current time when end_time is None."""
        start = time.time()
        metrics = PhaseMetrics(name="test", start_time=start)

        # Duration should be approximately 0 since we just started
        assert metrics.duration_seconds >= 0
        assert metrics.duration_seconds < 1.0

    def test_duration_with_no_start_returns_zero(self):
        """Test duration returns 0 when start_time is None."""
        metrics = PhaseMetrics(name="test")

        assert metrics.duration_seconds == 0.0


class TestPhaseMetricsItemsPerSecond:
    """Tests for PhaseMetrics.items_per_second property."""

    def test_items_per_second_calculation(self):
        """Test items per second calculation."""
        metrics = PhaseMetrics(
            name="test",
            start_time=1000.0,
            end_time=1010.0,  # 10 seconds
            items_created=100,
        )

        assert metrics.items_per_second == 10.0

    def test_items_per_second_zero_duration(self):
        """Test items per second returns 0 for zero duration."""
        metrics = PhaseMetrics(
            name="test",
            start_time=1000.0,
            end_time=1000.0,  # 0 seconds
            items_created=100,
        )

        assert metrics.items_per_second == 0.0

    def test_items_per_second_zero_items(self):
        """Test items per second returns 0 for zero items."""
        metrics = PhaseMetrics(
            name="test",
            start_time=1000.0,
            end_time=1010.0,
            items_created=0,
        )

        assert metrics.items_per_second == 0.0

    def test_items_per_second_no_start(self):
        """Test items per second returns 0 when no start time."""
        metrics = PhaseMetrics(name="test", items_created=100)

        assert metrics.items_per_second == 0.0


class TestPhaseMetricsSecondsPerItem:
    """Tests for PhaseMetrics.seconds_per_item property."""

    def test_seconds_per_item_calculation(self):
        """Test seconds per item calculation."""
        metrics = PhaseMetrics(
            name="test",
            start_time=1000.0,
            end_time=1100.0,  # 100 seconds
            items_created=50,
        )

        assert metrics.seconds_per_item == 2.0

    def test_seconds_per_item_zero_items(self):
        """Test seconds per item returns 0 for zero items."""
        metrics = PhaseMetrics(
            name="test",
            start_time=1000.0,
            end_time=1100.0,
            items_created=0,
        )

        assert metrics.seconds_per_item == 0.0


class TestPhaseMetricsIsComplete:
    """Tests for PhaseMetrics.is_complete property."""

    def test_is_complete_true(self):
        """Test is_complete returns True when end_time is set."""
        metrics = PhaseMetrics(name="test", start_time=1000.0, end_time=1100.0)

        assert metrics.is_complete is True

    def test_is_complete_false(self):
        """Test is_complete returns False when end_time is None."""
        metrics = PhaseMetrics(name="test", start_time=1000.0)

        assert metrics.is_complete is False


class TestPhaseMetricsFormatDuration:
    """Tests for PhaseMetrics.format_duration method."""

    def test_format_duration_seconds(self):
        """Test duration formatting in seconds."""
        metrics = PhaseMetrics(name="test", start_time=1000.0, end_time=1030.0)

        assert metrics.format_duration() == "30.0s"

    def test_format_duration_minutes(self):
        """Test duration formatting in minutes."""
        metrics = PhaseMetrics(name="test", start_time=1000.0, end_time=1300.0)  # 5 minutes

        assert metrics.format_duration() == "5.0m"

    def test_format_duration_hours(self):
        """Test duration formatting in hours."""
        metrics = PhaseMetrics(name="test", start_time=1000.0, end_time=8200.0)  # 2 hours

        assert metrics.format_duration() == "2.00h"

    def test_format_duration_at_minute_boundary(self):
        """Test formatting exactly at 60 seconds."""
        metrics = PhaseMetrics(name="test", start_time=1000.0, end_time=1060.0)

        assert metrics.format_duration() == "1.0m"

    def test_format_duration_at_hour_boundary(self):
        """Test formatting exactly at 3600 seconds."""
        metrics = PhaseMetrics(name="test", start_time=1000.0, end_time=4600.0)

        assert metrics.format_duration() == "1.00h"


class TestPhaseMetricsFormatRate:
    """Tests for PhaseMetrics.format_rate method."""

    def test_format_rate_high(self):
        """Test rate formatting for rates >= 1/s."""
        metrics = PhaseMetrics(
            name="test",
            start_time=1000.0,
            end_time=1010.0,
            items_created=50,
        )

        assert metrics.format_rate() == "5.0/s"

    def test_format_rate_low(self):
        """Test rate formatting for rates < 1/s."""
        metrics = PhaseMetrics(
            name="test",
            start_time=1000.0,
            end_time=1100.0,  # 100 seconds
            items_created=10,  # 0.1/s = 10s/item
        )

        assert metrics.format_rate() == "10.0s/item"

    def test_format_rate_zero(self):
        """Test rate formatting for zero rate."""
        metrics = PhaseMetrics(
            name="test",
            start_time=1000.0,
            end_time=1100.0,
            items_created=0,
        )

        assert metrics.format_rate() == "N/A"


class TestBenchmarkTrackerInitialization:
    """Tests for BenchmarkTracker initialization."""

    def test_default_initialization(self):
        """Test BenchmarkTracker initializes with correct defaults."""
        tracker = BenchmarkTracker()

        assert tracker.phases == {}
        assert tracker.overall_start is None
        assert tracker.overall_end is None
        assert tracker.total_requests == 0
        assert tracker.rate_limited_requests == 0
        assert tracker.error_count == 0
        assert tracker._current_phase is None

    def test_phase_display_names_initialized(self):
        """Test phase display names are initialized."""
        tracker = BenchmarkTracker()

        assert "pages" in tracker.phase_display_names
        assert tracker.phase_display_names["pages"] == "Pages"
        assert "blogposts" in tracker.phase_display_names
        assert tracker.phase_display_names["blogposts"] == "Blog Posts"


class TestBenchmarkTrackerStartEndOverall:
    """Tests for start_overall and end_overall methods."""

    def test_start_overall(self):
        """Test start_overall sets overall_start."""
        tracker = BenchmarkTracker()

        before = time.time()
        tracker.start_overall()
        after = time.time()

        assert tracker.overall_start is not None
        assert before <= tracker.overall_start <= after

    def test_end_overall(self):
        """Test end_overall sets overall_end."""
        tracker = BenchmarkTracker()
        tracker.start_overall()

        before = time.time()
        tracker.end_overall()
        after = time.time()

        assert tracker.overall_end is not None
        assert before <= tracker.overall_end <= after


class TestBenchmarkTrackerRecordMethods:
    """Tests for record_request, record_rate_limit, record_error methods."""

    def test_record_request(self):
        """Test record_request increments counter."""
        tracker = BenchmarkTracker()

        tracker.record_request()
        tracker.record_request()
        tracker.record_request()

        assert tracker.total_requests == 3

    def test_record_rate_limit(self):
        """Test record_rate_limit increments counter."""
        tracker = BenchmarkTracker()

        tracker.record_rate_limit()
        tracker.record_rate_limit()

        assert tracker.rate_limited_requests == 2

    def test_record_rate_limit_tracks_per_phase(self):
        """Test record_rate_limit tracks per-phase stats."""
        tracker = BenchmarkTracker()
        tracker.start_phase("pages")

        tracker.record_rate_limit()
        tracker.record_rate_limit()

        assert tracker.phases["pages"].rate_limited == 2

    def test_record_error(self):
        """Test record_error increments counter."""
        tracker = BenchmarkTracker()

        tracker.record_error()

        assert tracker.error_count == 1

    def test_record_error_tracks_per_phase(self):
        """Test record_error tracks per-phase stats."""
        tracker = BenchmarkTracker()
        tracker.start_phase("pages")

        tracker.record_error()
        tracker.record_error()
        tracker.record_error()

        assert tracker.phases["pages"].errors == 3


class TestBenchmarkTrackerRateLimitPercentage:
    """Tests for rate_limit_percentage property."""

    def test_rate_limit_percentage(self):
        """Test rate_limit_percentage calculation."""
        tracker = BenchmarkTracker()
        tracker.total_requests = 100
        tracker.rate_limited_requests = 10

        assert tracker.rate_limit_percentage == 10.0

    def test_rate_limit_percentage_zero_requests(self):
        """Test rate_limit_percentage with zero requests."""
        tracker = BenchmarkTracker()

        assert tracker.rate_limit_percentage == 0.0


class TestBenchmarkTrackerErrorPercentage:
    """Tests for error_percentage property."""

    def test_error_percentage(self):
        """Test error_percentage calculation."""
        tracker = BenchmarkTracker()
        tracker.total_requests = 100
        tracker.error_count = 5

        assert tracker.error_percentage == 5.0

    def test_error_percentage_zero_requests(self):
        """Test error_percentage with zero requests."""
        tracker = BenchmarkTracker()

        assert tracker.error_percentage == 0.0


class TestBenchmarkTrackerPhases:
    """Tests for start_phase, end_phase, get_phase methods."""

    def test_start_phase(self):
        """Test start_phase creates phase metrics."""
        tracker = BenchmarkTracker()

        before = time.time()
        tracker.start_phase("pages", target_count=100)
        after = time.time()

        assert "pages" in tracker.phases
        assert tracker.phases["pages"].name == "pages"
        assert before <= tracker.phases["pages"].start_time <= after
        assert tracker.phases["pages"].items_target == 100
        assert tracker._current_phase == "pages"

    def test_end_phase(self):
        """Test end_phase updates phase metrics."""
        tracker = BenchmarkTracker()
        tracker.start_phase("pages", target_count=100)

        before = time.time()
        tracker.end_phase("pages", items_created=95)
        after = time.time()

        assert before <= tracker.phases["pages"].end_time <= after
        assert tracker.phases["pages"].items_created == 95
        assert tracker._current_phase is None

    def test_end_phase_unknown_phase(self):
        """Test end_phase handles unknown phase gracefully."""
        tracker = BenchmarkTracker()

        # Should not raise
        tracker.end_phase("unknown", items_created=50)

    def test_get_phase(self):
        """Test get_phase returns phase metrics."""
        tracker = BenchmarkTracker()
        tracker.start_phase("pages")

        phase = tracker.get_phase("pages")

        assert phase is not None
        assert phase.name == "pages"

    def test_get_phase_unknown(self):
        """Test get_phase returns None for unknown phase."""
        tracker = BenchmarkTracker()

        phase = tracker.get_phase("unknown")

        assert phase is None


class TestBenchmarkTrackerTotalDurationSeconds:
    """Tests for total_duration_seconds property."""

    def test_total_duration_with_start_and_end(self):
        """Test total duration with both start and end."""
        tracker = BenchmarkTracker()
        tracker.overall_start = 1000.0
        tracker.overall_end = 1100.0

        assert tracker.total_duration_seconds == 100.0

    def test_total_duration_with_only_start(self):
        """Test total duration uses current time when end is None."""
        tracker = BenchmarkTracker()
        tracker.overall_start = time.time()

        # Should be approximately 0
        assert tracker.total_duration_seconds >= 0
        assert tracker.total_duration_seconds < 1.0

    def test_total_duration_no_start(self):
        """Test total duration returns 0 when start is None."""
        tracker = BenchmarkTracker()

        assert tracker.total_duration_seconds == 0.0


class TestBenchmarkTrackerTotalItemsCreated:
    """Tests for total_items_created property."""

    def test_total_items_created(self):
        """Test total items created sums all phases."""
        tracker = BenchmarkTracker()
        tracker.start_phase("pages")
        tracker.end_phase("pages", items_created=100)
        tracker.start_phase("blogposts")
        tracker.end_phase("blogposts", items_created=50)
        tracker.start_phase("comments")
        tracker.end_phase("comments", items_created=200)

        assert tracker.total_items_created == 350

    def test_total_items_created_empty(self):
        """Test total items created is 0 when no phases."""
        tracker = BenchmarkTracker()

        assert tracker.total_items_created == 0


class TestBenchmarkTrackerExtrapolateTime:
    """Tests for extrapolate_time method."""

    def test_extrapolate_basic(self):
        """Test basic extrapolation calculation."""
        tracker = BenchmarkTracker()
        tracker.start_phase("pages")
        tracker.phases["pages"].start_time = 1000.0
        tracker.phases["pages"].end_time = 1100.0  # 100 seconds
        tracker.phases["pages"].items_created = 100

        result = tracker.extrapolate_time(target_content=1000, current_content=100)

        assert result["target_content"] == 1000
        assert result["current_content"] == 100
        assert result["scale_factor"] == 10.0
        assert "phase_estimates" in result
        assert "pages" in result["phase_estimates"]

    def test_extrapolate_with_zero_content(self):
        """Test extrapolation with zero current content."""
        tracker = BenchmarkTracker()

        result = tracker.extrapolate_time(target_content=1000, current_content=0)

        assert "error" in result

    def test_extrapolate_calculates_phase_estimates(self):
        """Test extrapolation calculates per-phase estimates."""
        tracker = BenchmarkTracker()

        # Pages: 100 items in 100 seconds = 1/s
        tracker.start_phase("pages")
        tracker.phases["pages"].start_time = 1000.0
        tracker.phases["pages"].end_time = 1100.0
        tracker.phases["pages"].items_created = 100

        result = tracker.extrapolate_time(target_content=1000, current_content=100)

        pages_estimate = result["phase_estimates"]["pages"]
        assert pages_estimate["estimated_items"] == 1000
        assert pages_estimate["rate_per_second"] == 1.0
        # 1000 items at 1 second/item = 1000 seconds
        assert pages_estimate["estimated_seconds"] == 1000.0

    def test_extrapolate_total_time_calculation(self):
        """Test extrapolation calculates total time."""
        tracker = BenchmarkTracker()

        # Pages: 100 items in 100 seconds
        tracker.start_phase("pages")
        tracker.phases["pages"].start_time = 1000.0
        tracker.phases["pages"].end_time = 1100.0
        tracker.phases["pages"].items_created = 100

        # Comments: 200 items in 50 seconds
        tracker.start_phase("footer_comments")
        tracker.phases["footer_comments"].start_time = 1100.0
        tracker.phases["footer_comments"].end_time = 1150.0
        tracker.phases["footer_comments"].items_created = 200

        result = tracker.extrapolate_time(target_content=1000, current_content=100)

        assert result["total_estimated_seconds"] > 0
        assert result["total_estimated_hours"] == result["total_estimated_seconds"] / 3600
        assert result["total_estimated_days"] == result["total_estimated_seconds"] / 86400


class TestBenchmarkTrackerFormatExtrapolation:
    """Tests for format_extrapolation method."""

    def test_format_extrapolation_basic(self):
        """Test format_extrapolation generates report."""
        tracker = BenchmarkTracker()

        tracker.start_phase("pages")
        tracker.phases["pages"].start_time = 1000.0
        tracker.phases["pages"].end_time = 1100.0
        tracker.phases["pages"].items_created = 100

        report = tracker.format_extrapolation(target_content=1000, current_content=100)

        assert "TIME EXTRAPOLATION" in report
        assert "1,000" in report
        assert "Scale factor" in report

    def test_format_extrapolation_with_error(self):
        """Test format_extrapolation handles error case."""
        tracker = BenchmarkTracker()

        report = tracker.format_extrapolation(target_content=1000, current_content=0)

        assert "Cannot extrapolate" in report

    def test_format_extrapolation_time_formats(self):
        """Test format_extrapolation uses appropriate time units."""
        tracker = BenchmarkTracker()

        # Create a phase that would extrapolate to hours
        tracker.start_phase("pages")
        tracker.phases["pages"].start_time = 1000.0
        tracker.phases["pages"].end_time = 1100.0  # 100 seconds for 10 items = 10s/item
        tracker.phases["pages"].items_created = 10

        # 10000 items at 10s/item = 100000 seconds = ~27 hours
        report = tracker.format_extrapolation(target_content=10000, current_content=10)

        # Should mention hours in the total
        assert "TOTAL ESTIMATED TIME" in report


class TestConfluenceSizeTiers:
    """Tests for CONFLUENCE_SIZE_TIERS constant."""

    def test_has_four_tiers(self):
        """Test all four Atlassian-defined tiers are present."""
        assert len(CONFLUENCE_SIZE_TIERS) == 4

    def test_tier_names(self):
        """Test tier names match Atlassian's labels."""
        names = [t[0] for t in CONFLUENCE_SIZE_TIERS]
        assert names == ["S", "M", "L", "XL"]

    def test_tier_values_ascending(self):
        """Test tier content counts are in ascending order."""
        values = [t[1] for t in CONFLUENCE_SIZE_TIERS]
        assert values == sorted(values)
        assert values == [500_000, 2_500_000, 10_000_000, 25_000_000]


class TestFormatSizeTierExtrapolations:
    """Tests for format_size_tier_extrapolations method."""

    def test_returns_empty_when_no_items(self):
        """Test returns empty string when no items created."""
        tracker = BenchmarkTracker()
        assert tracker.format_size_tier_extrapolations() == ""

    def test_includes_all_tiers(self):
        """Test report includes all four size tiers."""
        tracker = BenchmarkTracker()
        tracker.start_phase("pages")
        tracker.phases["pages"].start_time = 1000.0
        tracker.phases["pages"].end_time = 1100.0  # 100s for 100 items
        tracker.phases["pages"].items_created = 100

        report = tracker.format_size_tier_extrapolations()

        assert "S" in report
        assert "M" in report
        assert "L" in report
        assert "XL" in report

    def test_includes_header(self):
        """Test report includes header and source attribution."""
        tracker = BenchmarkTracker()
        tracker.start_phase("pages")
        tracker.phases["pages"].start_time = 1000.0
        tracker.phases["pages"].end_time = 1100.0
        tracker.phases["pages"].items_created = 100

        report = tracker.format_size_tier_extrapolations()

        assert "TIME ESTIMATES BY INSTANCE SIZE" in report
        assert "Atlassian" in report

    def test_shows_current_item_count(self):
        """Test report shows current run's item count."""
        tracker = BenchmarkTracker()
        tracker.start_phase("pages")
        tracker.phases["pages"].start_time = 1000.0
        tracker.phases["pages"].end_time = 1100.0
        tracker.phases["pages"].items_created = 100

        report = tracker.format_size_tier_extrapolations()

        assert "100" in report

    def test_estimates_scale_linearly(self):
        """Test that larger tiers produce larger time estimates."""
        tracker = BenchmarkTracker()
        tracker.start_phase("pages")
        tracker.phases["pages"].start_time = 1000.0
        tracker.phases["pages"].end_time = 1010.0  # 10s for 10 items = 1s/item
        tracker.phases["pages"].items_created = 10

        data_s = tracker.extrapolate_time(500_000, 10)
        data_xl = tracker.extrapolate_time(25_000_000, 10)

        assert data_xl["total_estimated_seconds"] > data_s["total_estimated_seconds"]

    def test_content_items_formatted(self):
        """Test tier content counts are comma-formatted."""
        tracker = BenchmarkTracker()
        tracker.start_phase("pages")
        tracker.phases["pages"].start_time = 1000.0
        tracker.phases["pages"].end_time = 1100.0
        tracker.phases["pages"].items_created = 100

        report = tracker.format_size_tier_extrapolations()

        assert "500,000" in report
        assert "2,500,000" in report
        assert "10,000,000" in report
        assert "25,000,000" in report


class TestFormatTimeEstimate:
    """Tests for _format_time_estimate static method."""

    def test_seconds(self):
        assert BenchmarkTracker._format_time_estimate(45) == "45s"

    def test_minutes(self):
        assert BenchmarkTracker._format_time_estimate(300) == "5.0m"

    def test_hours(self):
        assert BenchmarkTracker._format_time_estimate(7200) == "2.0h"

    def test_days(self):
        assert BenchmarkTracker._format_time_estimate(172800) == "2.0d"


class TestBenchmarkTrackerGetSummaryReport:
    """Tests for get_summary_report method."""

    def test_summary_report_basic(self):
        """Test get_summary_report generates report."""
        tracker = BenchmarkTracker()
        tracker.overall_start = 1000.0
        tracker.overall_end = 1100.0
        tracker.total_requests = 100
        tracker.rate_limited_requests = 5
        tracker.error_count = 2

        tracker.start_phase("pages")
        tracker.phases["pages"].start_time = 1000.0
        tracker.phases["pages"].end_time = 1050.0
        tracker.phases["pages"].items_created = 50
        tracker.phases["pages"].rate_limited = 3
        tracker.phases["pages"].errors = 1

        report = tracker.get_summary_report()

        assert "BENCHMARK SUMMARY" in report
        assert "Total duration" in report
        assert "Total items created" in report
        assert "Phase breakdown" in report
        assert "Pages" in report
        assert "Request statistics" in report

    def test_summary_report_duration_formatting(self):
        """Test summary report formats duration appropriately."""
        tracker = BenchmarkTracker()
        tracker.overall_start = 1000.0
        tracker.overall_end = 1030.0  # 30 seconds

        report = tracker.get_summary_report()

        assert "30.0 seconds" in report

    def test_summary_report_minutes_formatting(self):
        """Test summary report formats minutes appropriately."""
        tracker = BenchmarkTracker()
        tracker.overall_start = 1000.0
        tracker.overall_end = 1300.0  # 5 minutes

        report = tracker.get_summary_report()

        assert "5.0 minutes" in report

    def test_summary_report_hours_formatting(self):
        """Test summary report formats hours appropriately."""
        tracker = BenchmarkTracker()
        tracker.overall_start = 1000.0
        tracker.overall_end = 8200.0  # 2 hours

        report = tracker.get_summary_report()

        assert "2.00 hours" in report

    def test_summary_report_dry_run_mode(self):
        """Test summary report indicates dry-run when no requests."""
        tracker = BenchmarkTracker()
        tracker.overall_start = 1000.0
        tracker.overall_end = 1100.0

        report = tracker.get_summary_report()

        assert "dry-run mode" in report

    def test_summary_report_key_rates(self):
        """Test summary report includes key rates."""
        tracker = BenchmarkTracker()
        tracker.overall_start = 1000.0
        tracker.overall_end = 1100.0

        tracker.start_phase("pages")
        tracker.phases["pages"].start_time = 1000.0
        tracker.phases["pages"].end_time = 1050.0
        tracker.phases["pages"].items_created = 50

        tracker.start_phase("footer_comments")
        tracker.phases["footer_comments"].start_time = 1050.0
        tracker.phases["footer_comments"].end_time = 1100.0
        tracker.phases["footer_comments"].items_created = 100

        report = tracker.get_summary_report()

        assert "Key rates" in report


class TestBenchmarkTrackerToDict:
    """Tests for to_dict method."""

    def test_to_dict_basic(self):
        """Test to_dict returns correct structure."""
        tracker = BenchmarkTracker()
        tracker.overall_start = 1704067200.0  # 2024-01-01 00:00:00 UTC
        tracker.overall_end = 1704067300.0
        tracker.total_requests = 100
        tracker.rate_limited_requests = 5
        tracker.error_count = 2

        tracker.start_phase("pages")
        tracker.phases["pages"].start_time = 1704067200.0
        tracker.phases["pages"].end_time = 1704067250.0
        tracker.phases["pages"].items_created = 50
        tracker.phases["pages"].items_target = 100
        tracker.phases["pages"].rate_limited = 3
        tracker.phases["pages"].errors = 1

        result = tracker.to_dict()

        assert "overall_start" in result
        assert "overall_end" in result
        assert "total_duration_seconds" in result
        assert "total_items_created" in result
        assert "request_stats" in result
        assert "phases" in result

    def test_to_dict_request_stats(self):
        """Test to_dict includes request statistics."""
        tracker = BenchmarkTracker()
        tracker.total_requests = 100
        tracker.rate_limited_requests = 10
        tracker.error_count = 5

        result = tracker.to_dict()

        assert result["request_stats"]["total_requests"] == 100
        assert result["request_stats"]["rate_limited"] == 10
        assert result["request_stats"]["rate_limit_percentage"] == 10.0
        assert result["request_stats"]["errors"] == 5
        assert result["request_stats"]["error_percentage"] == 5.0

    def test_to_dict_phases(self):
        """Test to_dict includes phase data."""
        tracker = BenchmarkTracker()
        tracker.start_phase("pages")
        tracker.phases["pages"].start_time = 1000.0
        tracker.phases["pages"].end_time = 1100.0
        tracker.phases["pages"].items_created = 50
        tracker.phases["pages"].items_target = 100
        tracker.phases["pages"].rate_limited = 3
        tracker.phases["pages"].errors = 1

        result = tracker.to_dict()

        assert "pages" in result["phases"]
        pages = result["phases"]["pages"]
        assert pages["items_created"] == 50
        assert pages["items_target"] == 100
        assert pages["duration_seconds"] == 100.0
        assert pages["items_per_second"] == 0.5
        assert pages["rate_limited"] == 3
        assert pages["errors"] == 1

    def test_to_dict_none_timestamps(self):
        """Test to_dict handles None timestamps."""
        tracker = BenchmarkTracker()

        result = tracker.to_dict()

        assert result["overall_start"] is None
        assert result["overall_end"] is None

    def test_to_dict_timestamps_are_iso_format(self):
        """Test to_dict converts timestamps to ISO format."""
        tracker = BenchmarkTracker()
        tracker.overall_start = 1704067200.0  # 2024-01-01 00:00:00 UTC
        tracker.overall_end = 1704067300.0

        result = tracker.to_dict()

        # Should be ISO format strings
        assert isinstance(result["overall_start"], str)
        assert isinstance(result["overall_end"], str)
        assert "T" in result["overall_start"]  # ISO format has T separator
