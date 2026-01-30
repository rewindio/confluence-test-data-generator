"""Tests for generators/base.py - ConfluenceAPIClient and RateLimitState."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
import requests

from generators.base import ConfluenceAPIClient, RateLimitState


class TestRateLimitState:
    """Tests for RateLimitState dataclass."""

    def test_default_initialization(self):
        """Test RateLimitState initializes with correct defaults."""
        state = RateLimitState()

        assert state.retry_after is None
        assert state.consecutive_429s == 0
        assert state.current_delay == 1.0
        assert state.max_delay == 60.0
        assert state._cooldown_until == 0.0
        assert state.adaptive_delay == 0.0
        assert state.recent_429_count == 0
        assert state.recent_success_count == 0

    def test_custom_initialization(self):
        """Test RateLimitState with custom values."""
        state = RateLimitState(
            retry_after=30.0,
            consecutive_429s=3,
            current_delay=8.0,
            max_delay=120.0,
            adaptive_delay=0.5,
        )

        assert state.retry_after == 30.0
        assert state.consecutive_429s == 3
        assert state.current_delay == 8.0
        assert state.max_delay == 120.0
        assert state.adaptive_delay == 0.5

    def test_lock_is_asyncio_lock(self):
        """Test that _lock is an asyncio.Lock instance."""
        state = RateLimitState()
        assert isinstance(state._lock, asyncio.Lock)


class TestConfluenceAPIClientInitialization:
    """Tests for ConfluenceAPIClient initialization."""

    def test_basic_initialization(self):
        """Test basic client initialization."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        assert client.confluence_url == "https://test.atlassian.net/wiki"
        assert client.email == "test@example.com"
        assert client.api_token == "test-token"
        assert client.dry_run is False
        assert client.concurrency == 5
        assert client.benchmark is None
        assert client.request_delay == 0.0

    def test_initialization_strips_trailing_slash(self):
        """Test that trailing slash is stripped from URL."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki/",
            email="test@example.com",
            api_token="test-token",
        )

        assert client.confluence_url == "https://test.atlassian.net/wiki"

    def test_initialization_with_all_parameters(self):
        """Test initialization with all optional parameters."""
        mock_benchmark = MagicMock()
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
            dry_run=True,
            concurrency=10,
            benchmark=mock_benchmark,
            request_delay=0.5,
        )

        assert client.dry_run is True
        assert client.concurrency == 10
        assert client.benchmark == mock_benchmark
        assert client.request_delay == 0.5

    def test_rate_limit_state_initialized(self):
        """Test that rate_limit state is initialized."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        assert isinstance(client.rate_limit, RateLimitState)

    def test_session_created(self):
        """Test that HTTP session is created."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        assert isinstance(client.session, requests.Session)


class TestCreateSession:
    """Tests for _create_session method."""

    def test_session_has_retry_strategy(self):
        """Test that session is configured with retry strategy."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        # Verify adapter is mounted for both http and https
        assert "https://" in client.session.adapters
        assert "http://" in client.session.adapters

    def test_retry_excludes_429(self):
        """Test that retry strategy excludes 429 status code."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        # Get the adapter and check its retry configuration
        adapter = client.session.get_adapter("https://test.atlassian.net")
        # 429 should NOT be in the status_forcelist
        assert 429 not in adapter.max_retries.status_forcelist
        # 5xx errors should be in the list
        assert 500 in adapter.max_retries.status_forcelist
        assert 502 in adapter.max_retries.status_forcelist
        assert 503 in adapter.max_retries.status_forcelist
        assert 504 in adapter.max_retries.status_forcelist


class TestHandleRateLimit:
    """Tests for _handle_rate_limit method."""

    def test_429_with_retry_after_header(self):
        """Test handling 429 with Retry-After header."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "30"}

        with patch("time.sleep") as mock_sleep:
            client._handle_rate_limit(mock_response)

        assert client.rate_limit.retry_after == 30.0
        assert client.rate_limit.consecutive_429s == 1
        mock_sleep.assert_called_once_with(30.0)

    def test_429_without_retry_after_uses_exponential_backoff(self):
        """Test handling 429 without Retry-After uses exponential backoff."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )
        client.rate_limit.current_delay = 4.0  # Set current delay

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}

        with patch("time.sleep") as mock_sleep:
            client._handle_rate_limit(mock_response)

        # Should double the current delay
        assert client.rate_limit.current_delay == 8.0
        assert client.rate_limit.retry_after == 8.0
        mock_sleep.assert_called_once_with(8.0)

    def test_429_exponential_backoff_respects_max_delay(self):
        """Test exponential backoff doesn't exceed max_delay."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )
        client.rate_limit.current_delay = 50.0
        client.rate_limit.max_delay = 60.0

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}

        with patch("time.sleep") as mock_sleep:
            client._handle_rate_limit(mock_response)

        # Should cap at max_delay
        assert client.rate_limit.current_delay == 60.0
        mock_sleep.assert_called_once_with(60.0)

    def test_429_with_invalid_retry_after_defaults_to_60(self):
        """Test invalid Retry-After header defaults to 60 seconds."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "invalid-date-string"}

        with patch("time.sleep") as mock_sleep:
            client._handle_rate_limit(mock_response)

        assert client.rate_limit.retry_after == 60
        mock_sleep.assert_called_once_with(60)

    def test_success_resets_backoff(self):
        """Test successful response resets backoff state."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )
        client.rate_limit.consecutive_429s = 5
        client.rate_limit.current_delay = 32.0

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("time.sleep") as mock_sleep:
            client._handle_rate_limit(mock_response)

        assert client.rate_limit.consecutive_429s == 0
        assert client.rate_limit.current_delay == 1.0
        mock_sleep.assert_not_called()

    def test_429_increments_consecutive_count(self):
        """Test 429 increments consecutive count."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )
        client.rate_limit.consecutive_429s = 2

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "5"}

        with patch("time.sleep"):
            client._handle_rate_limit(mock_response)

        assert client.rate_limit.consecutive_429s == 3

    def test_429_records_rate_limit_in_benchmark(self):
        """Test 429 records rate limit in benchmark."""
        mock_benchmark = MagicMock()
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
            benchmark=mock_benchmark,
        )

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "5"}

        with patch("time.sleep"):
            client._handle_rate_limit(mock_response)

        mock_benchmark.record_rate_limit.assert_called_once()


class TestApiCall:
    """Tests for _api_call method."""

    def test_success_path(self):
        """Test successful API call."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "123"}

        with patch.object(client.session, "request", return_value=mock_response):
            response = client._api_call("GET", "pages/123")

        assert response == mock_response

    def test_dry_run_returns_none(self):
        """Test dry run mode returns None without making request."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
            dry_run=True,
        )

        with patch.object(client.session, "request") as mock_request:
            response = client._api_call("GET", "pages/123")

        assert response is None
        mock_request.assert_not_called()

    def test_rate_limiting_triggers_retry(self):
        """Test 429 response triggers retry."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_429_response = MagicMock()
        mock_429_response.status_code = 429
        mock_429_response.headers = {"Retry-After": "1"}

        mock_success_response = MagicMock()
        mock_success_response.status_code = 200

        with patch.object(
            client.session,
            "request",
            side_effect=[mock_429_response, mock_success_response],
        ):
            with patch("time.sleep"):
                response = client._api_call("GET", "pages/123")

        assert response == mock_success_response

    def test_client_error_does_not_retry(self):
        """Test 4xx errors (except 429) don't retry."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not found"

        error = requests.exceptions.HTTPError(response=mock_response)
        mock_response.raise_for_status.side_effect = error

        with patch.object(client.session, "request", return_value=mock_response):
            response = client._api_call("GET", "pages/123")

        assert response is None

    def test_server_error_triggers_retry_with_backoff(self):
        """Test 5xx errors trigger retry with exponential backoff."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_500_response = MagicMock()
        mock_500_response.status_code = 500
        mock_500_response.text = "Server error"

        error = requests.exceptions.HTTPError(response=mock_500_response)
        mock_500_response.raise_for_status.side_effect = error

        mock_success_response = MagicMock()
        mock_success_response.status_code = 200

        with patch.object(
            client.session,
            "request",
            side_effect=[mock_500_response, mock_success_response],
        ):
            with patch("time.sleep") as mock_sleep:
                response = client._api_call("GET", "pages/123", max_retries=2)

        assert response == mock_success_response
        mock_sleep.assert_called_once_with(1)  # 2^0 = 1

    def test_already_exists_error_is_handled_gracefully(self):
        """Test 'already exists' error is logged at debug level."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_response = MagicMock()
        mock_response.status_code = 409
        mock_response.text = "Space already exists"

        error = requests.exceptions.HTTPError(response=mock_response)
        mock_response.raise_for_status.side_effect = error

        with patch.object(client.session, "request", return_value=mock_response):
            response = client._api_call("POST", "spaces")

        assert response is None

    def test_custom_base_url(self):
        """Test API call with custom base URL."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(client.session, "request", return_value=mock_response) as mock_request:
            client._api_call("GET", "endpoint", base_url="https://custom.api.com/v1")

        call_args = mock_request.call_args
        assert call_args[1]["url"] == "https://custom.api.com/v1/endpoint"

    def test_max_retries_exhausted_returns_none(self):
        """Test exhausting max retries returns None."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server error"

        error = requests.exceptions.HTTPError(response=mock_response)
        mock_response.raise_for_status.side_effect = error

        with patch.object(client.session, "request", return_value=mock_response):
            with patch("time.sleep"):
                response = client._api_call("GET", "pages/123", max_retries=3)

        assert response is None

    def test_records_request_in_benchmark(self):
        """Test that requests are recorded in benchmark."""
        mock_benchmark = MagicMock()
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
            benchmark=mock_benchmark,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(client.session, "request", return_value=mock_response):
            client._api_call("GET", "pages/123")

        mock_benchmark.record_request.assert_called_once()

    def test_records_error_in_benchmark(self):
        """Test that errors are recorded in benchmark."""
        mock_benchmark = MagicMock()
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
            benchmark=mock_benchmark,
        )

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"

        error = requests.exceptions.HTTPError(response=mock_response)
        mock_response.raise_for_status.side_effect = error

        with patch.object(client.session, "request", return_value=mock_response):
            client._api_call("GET", "pages/123")

        mock_benchmark.record_error.assert_called()


class TestHandleRateLimitAsync:
    """Tests for _handle_rate_limit_async method."""

    @pytest.mark.asyncio
    async def test_429_increases_adaptive_delay(self):
        """Test 429 response increases adaptive delay."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        delay = await client._handle_rate_limit_async(429, {"Retry-After": "5"})

        assert client.rate_limit.adaptive_delay > 0
        assert client.rate_limit.consecutive_429s == 1
        assert delay > 0  # Should return delay with jitter

    @pytest.mark.asyncio
    async def test_429_without_retry_after_uses_exponential_backoff(self):
        """Test 429 without Retry-After header uses exponential backoff."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )
        client.rate_limit.current_delay = 4.0

        await client._handle_rate_limit_async(429, {})

        assert client.rate_limit.current_delay == 8.0  # Doubled

    @pytest.mark.asyncio
    async def test_429_sets_cooldown_until(self):
        """Test 429 sets global cooldown."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        before = time.time()
        await client._handle_rate_limit_async(429, {"Retry-After": "10"})

        # Cooldown should be set to approximately now + 10 seconds (with jitter)
        assert client.rate_limit._cooldown_until > before

    @pytest.mark.asyncio
    async def test_success_resets_state(self):
        """Test success response resets rate limit state."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )
        client.rate_limit.consecutive_429s = 5
        client.rate_limit.current_delay = 16.0

        delay = await client._handle_rate_limit_async(200, {})

        assert delay == 0
        assert client.rate_limit.consecutive_429s == 0
        assert client.rate_limit.current_delay == 1.0

    @pytest.mark.asyncio
    async def test_success_gradually_reduces_adaptive_delay(self):
        """Test repeated successes gradually reduce adaptive delay."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )
        client.rate_limit.adaptive_delay = 0.5
        client.rate_limit.recent_success_count = 9  # One more will trigger reduction

        await client._handle_rate_limit_async(200, {})

        # After 10 successes, adaptive delay should be reduced
        assert client.rate_limit.adaptive_delay == 0.49  # 0.5 - 0.01
        assert client.rate_limit.recent_success_count == 0

    @pytest.mark.asyncio
    async def test_adaptive_delay_caps_at_1_second(self):
        """Test adaptive delay doesn't exceed 1 second."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )
        client.rate_limit.adaptive_delay = 0.95

        # Multiple 429s
        for _ in range(20):
            await client._handle_rate_limit_async(429, {"Retry-After": "1"})

        assert client.rate_limit.adaptive_delay <= 1.0

    @pytest.mark.asyncio
    async def test_429_records_in_benchmark(self):
        """Test 429 records rate limit in benchmark."""
        mock_benchmark = MagicMock()
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
            benchmark=mock_benchmark,
        )

        await client._handle_rate_limit_async(429, {"Retry-After": "5"})

        mock_benchmark.record_rate_limit.assert_called_once()


class TestWaitForCooldown:
    """Tests for _wait_for_cooldown method."""

    @pytest.mark.asyncio
    async def test_waits_when_in_cooldown(self):
        """Test that wait_for_cooldown waits during cooldown period."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )
        # Set cooldown to 0.1 seconds from now
        client.rate_limit._cooldown_until = time.time() + 0.1

        start = time.time()
        await client._wait_for_cooldown()
        elapsed = time.time() - start

        assert elapsed >= 0.09  # Should have waited

    @pytest.mark.asyncio
    async def test_no_wait_when_no_cooldown(self):
        """Test that no wait occurs when not in cooldown."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )
        client.rate_limit._cooldown_until = time.time() - 1  # Past

        start = time.time()
        await client._wait_for_cooldown()
        elapsed = time.time() - start

        assert elapsed < 0.05  # Should not have waited significantly


class TestApplyRequestDelay:
    """Tests for _apply_request_delay method."""

    @pytest.mark.asyncio
    async def test_applies_base_delay(self):
        """Test that base request delay is applied."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
            request_delay=0.1,
        )

        start = time.time()
        await client._apply_request_delay()
        elapsed = time.time() - start

        # Should have waited approximately 0.1 seconds (with jitter of +/-10%)
        assert elapsed >= 0.08
        assert elapsed <= 0.15

    @pytest.mark.asyncio
    async def test_applies_combined_delay(self):
        """Test that base + adaptive delay is applied."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
            request_delay=0.05,
        )
        client.rate_limit.adaptive_delay = 0.05  # Total: 0.1

        start = time.time()
        await client._apply_request_delay()
        elapsed = time.time() - start

        assert elapsed >= 0.08
        assert elapsed <= 0.15

    @pytest.mark.asyncio
    async def test_no_delay_when_zero(self):
        """Test no delay when request_delay is 0."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
            request_delay=0.0,
        )

        start = time.time()
        await client._apply_request_delay()
        elapsed = time.time() - start

        assert elapsed < 0.05


class TestApiCallAsync:
    """Tests for _api_call_async method."""

    @pytest.mark.asyncio
    async def test_success_path(self):
        """Test successful async API call."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {}
        mock_response.json = AsyncMock(return_value={"id": "123"})

        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

        with patch.object(client, "_get_async_session", return_value=mock_session):
            with patch.object(client, "_wait_for_cooldown", new_callable=AsyncMock):
                with patch.object(client, "_apply_request_delay", new_callable=AsyncMock):
                    # Set up semaphore
                    client._semaphore = asyncio.Semaphore(5)
                    success, result = await client._api_call_async("GET", "pages/123")

        assert success is True
        assert result == {"id": "123"}

    @pytest.mark.asyncio
    async def test_dry_run_returns_success_without_request(self):
        """Test dry run mode returns success without making request."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
            dry_run=True,
        )

        success, result = await client._api_call_async("GET", "pages/123")

        assert success is True
        assert result is None

    @pytest.mark.asyncio
    async def test_204_no_content_response(self):
        """Test 204 No Content response is handled."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_response = AsyncMock()
        mock_response.status = 204
        mock_response.headers = {}

        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

        with patch.object(client, "_get_async_session", return_value=mock_session):
            with patch.object(client, "_wait_for_cooldown", new_callable=AsyncMock):
                with patch.object(client, "_apply_request_delay", new_callable=AsyncMock):
                    client._semaphore = asyncio.Semaphore(5)
                    success, result = await client._api_call_async("DELETE", "pages/123")

        assert success is True
        assert result is None

    @pytest.mark.asyncio
    async def test_rate_limit_triggers_retry(self):
        """Test 429 response triggers retry."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_429_response = AsyncMock()
        mock_429_response.status = 429
        mock_429_response.headers = {"Retry-After": "0.1"}

        mock_success_response = AsyncMock()
        mock_success_response.status = 200
        mock_success_response.headers = {}
        mock_success_response.json = AsyncMock(return_value={"id": "123"})

        call_count = 0

        async def mock_aenter(self):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_429_response
            return mock_success_response

        mock_context = AsyncMock()
        mock_context.__aenter__ = mock_aenter

        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=mock_context)

        with patch.object(client, "_get_async_session", return_value=mock_session):
            with patch.object(client, "_wait_for_cooldown", new_callable=AsyncMock):
                with patch.object(client, "_apply_request_delay", new_callable=AsyncMock):
                    with patch("asyncio.sleep", new_callable=AsyncMock):
                        client._semaphore = asyncio.Semaphore(5)
                        success, result = await client._api_call_async("GET", "pages/123")

        assert success is True
        assert result == {"id": "123"}

    @pytest.mark.asyncio
    async def test_client_error_does_not_retry(self):
        """Test 4xx errors (except 429) don't retry."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.headers = {}
        mock_response.text = AsyncMock(return_value="Not found")

        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

        with patch.object(client, "_get_async_session", return_value=mock_session):
            with patch.object(client, "_wait_for_cooldown", new_callable=AsyncMock):
                with patch.object(client, "_apply_request_delay", new_callable=AsyncMock):
                    client._semaphore = asyncio.Semaphore(5)
                    success, result = await client._api_call_async("GET", "pages/123")

        assert success is False
        assert result is None

    @pytest.mark.asyncio
    async def test_client_error_exception_handling(self):
        """Test aiohttp.ClientError is handled."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_context = AsyncMock()
        mock_context.__aenter__.side_effect = aiohttp.ClientError("Connection failed")

        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=mock_context)

        with patch.object(client, "_get_async_session", return_value=mock_session):
            with patch.object(client, "_wait_for_cooldown", new_callable=AsyncMock):
                with patch.object(client, "_apply_request_delay", new_callable=AsyncMock):
                    with patch("asyncio.sleep", new_callable=AsyncMock):
                        client._semaphore = asyncio.Semaphore(5)
                        success, result = await client._api_call_async("GET", "pages/123", max_retries=2)

        assert success is False
        assert result is None


class TestGetAsyncSession:
    """Tests for _get_async_session method."""

    @pytest.mark.asyncio
    async def test_creates_session_with_proper_settings(self):
        """Test async session is created with proper configuration."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
            concurrency=10,
        )

        # Mock aiohttp components
        with patch("aiohttp.BasicAuth") as mock_auth:
            with patch("aiohttp.ClientTimeout") as mock_timeout:
                with patch("aiohttp.TCPConnector") as mock_connector:
                    with patch("aiohttp.ClientSession") as mock_session_class:
                        mock_session_class.return_value.closed = False
                        await client._get_async_session()

                        mock_auth.assert_called_once_with("test@example.com", "test-token")
                        mock_timeout.assert_called_once_with(total=30)
                        mock_connector.assert_called_once_with(
                            limit=100,
                            limit_per_host=50,
                            ttl_dns_cache=300,
                            enable_cleanup_closed=True,
                        )

        # Semaphore should be created with concurrency value
        assert client._semaphore is not None

    @pytest.mark.asyncio
    async def test_reuses_existing_session(self):
        """Test existing session is reused."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_session = MagicMock()
        mock_session.closed = False
        client._async_session = mock_session
        client._semaphore = asyncio.Semaphore(5)

        session = await client._get_async_session()

        assert session == mock_session


class TestCloseAsyncSession:
    """Tests for _close_async_session method."""

    @pytest.mark.asyncio
    async def test_closes_session(self):
        """Test async session is closed."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_session = AsyncMock()
        mock_session.closed = False
        client._async_session = mock_session

        await client._close_async_session()

        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_already_closed_session(self):
        """Test already closed session is handled gracefully."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_session = AsyncMock()
        mock_session.closed = True
        client._async_session = mock_session

        # Should not raise
        await client._close_async_session()
        mock_session.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_no_session(self):
        """Test no session is handled gracefully."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )
        client._async_session = None

        # Should not raise
        await client._close_async_session()


class TestGenerateRandomText:
    """Tests for generate_random_text method."""

    def test_returns_text_from_pool(self):
        """Test that text is returned from pool."""
        # Ensure pool is initialized
        ConfluenceAPIClient._init_text_pool()

        text = ConfluenceAPIClient.generate_random_text()

        assert isinstance(text, str)
        assert len(text) > 0

    def test_short_text_uses_short_pool(self):
        """Test short text range uses short pool."""
        ConfluenceAPIClient._init_text_pool()

        text = ConfluenceAPIClient.generate_random_text(min_words=3, max_words=5)

        assert isinstance(text, str)
        assert len(text) > 0

    def test_medium_text_uses_medium_pool(self):
        """Test medium text range uses medium pool."""
        ConfluenceAPIClient._init_text_pool()

        text = ConfluenceAPIClient.generate_random_text(min_words=8, max_words=12)

        assert isinstance(text, str)
        assert len(text) > 0

    def test_long_text_uses_long_pool(self):
        """Test long text range uses long pool."""
        ConfluenceAPIClient._init_text_pool()

        text = ConfluenceAPIClient.generate_random_text(min_words=15, max_words=25)

        assert isinstance(text, str)
        assert len(text) > 0


class TestInitTextPool:
    """Tests for _init_text_pool method."""

    def test_creates_text_pools(self):
        """Test that text pools are created."""
        # Reset pool for testing
        ConfluenceAPIClient._text_pool = None
        ConfluenceAPIClient._text_pool_lock = None

        ConfluenceAPIClient._init_text_pool()

        assert ConfluenceAPIClient._text_pool is not None
        assert "short" in ConfluenceAPIClient._text_pool
        assert "medium" in ConfluenceAPIClient._text_pool
        assert "long" in ConfluenceAPIClient._text_pool
        assert len(ConfluenceAPIClient._text_pool["short"]) == ConfluenceAPIClient._TEXT_POOL_SIZE

    def test_idempotent(self):
        """Test calling _init_text_pool multiple times is safe."""
        ConfluenceAPIClient._init_text_pool()
        first_pool = ConfluenceAPIClient._text_pool

        ConfluenceAPIClient._init_text_pool()
        second_pool = ConfluenceAPIClient._text_pool

        # Should be the same object
        assert first_pool is second_pool


class TestGetCurrentUserAccountId:
    """Tests for get_current_user_account_id method."""

    def test_returns_account_id_on_success(self):
        """Test returns account ID on successful response."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"accountId": "abc123"}

        with patch.object(client, "_api_call", return_value=mock_response):
            account_id = client.get_current_user_account_id()

        assert account_id == "abc123"

    def test_returns_dry_run_id_in_dry_run_mode(self):
        """Test returns dry-run ID in dry run mode."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
            dry_run=True,
        )

        account_id = client.get_current_user_account_id()

        assert account_id == "dry-run-account-id"

    def test_returns_none_on_failure(self):
        """Test returns None when API call fails."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        with patch.object(client, "_api_call", return_value=None):
            account_id = client.get_current_user_account_id()

        assert account_id is None


class TestGetAllUsers:
    """Tests for get_all_users method."""

    def test_returns_users_on_success(self):
        """Test returns list of account IDs on success."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"accountId": "user1", "accountType": "atlassian"},
                {"accountId": "user2", "accountType": "atlassian"},
                {"accountId": "app-user", "accountType": "app"},  # Should be filtered
            ],
            "_links": {},
        }

        with patch.object(client, "_api_call", return_value=mock_response):
            users = client.get_all_users()

        assert len(users) == 2
        assert "user1" in users
        assert "user2" in users
        assert "app-user" not in users

    def test_returns_dry_run_users_in_dry_run_mode(self):
        """Test returns dry-run users in dry run mode."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
            dry_run=True,
        )

        users = client.get_all_users()

        assert len(users) == 5
        assert all(u.startswith("dry-run-user-") for u in users)

    def test_handles_pagination(self):
        """Test handles paginated results."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        page1_response = MagicMock()
        page1_response.json.return_value = {
            "results": [{"accountId": "user1", "accountType": "atlassian"}],
            "_links": {"next": "/api/v2/users?cursor=abc123"},
        }

        page2_response = MagicMock()
        page2_response.json.return_value = {
            "results": [{"accountId": "user2", "accountType": "atlassian"}],
            "_links": {},
        }

        with patch.object(
            client,
            "_api_call",
            side_effect=[page1_response, page2_response],
        ):
            users = client.get_all_users()

        assert len(users) == 2
        assert "user1" in users
        assert "user2" in users

    def test_respects_max_users(self):
        """Test respects max_users parameter."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [{"accountId": f"user{i}", "accountType": "atlassian"} for i in range(10)],
            "_links": {},
        }

        with patch.object(client, "_api_call", return_value=mock_response):
            users = client.get_all_users(max_users=3)

        assert len(users) == 3

    def test_returns_empty_list_on_failure(self):
        """Test returns empty list when API call fails."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        with patch.object(client, "_api_call", return_value=None):
            users = client.get_all_users()

        assert users == []

    def test_handles_empty_results(self):
        """Test handles empty results gracefully."""
        client = ConfluenceAPIClient(
            confluence_url="https://test.atlassian.net/wiki",
            email="test@example.com",
            api_token="test-token",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"results": [], "_links": {}}

        with patch.object(client, "_api_call", return_value=mock_response):
            users = client.get_all_users()

        assert users == []
