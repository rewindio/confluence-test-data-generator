#!/usr/bin/env python3
"""
Confluence API Connectivity Test

Tests basic connectivity to Confluence Cloud API using credentials from .env file.
"""

import os
import sys

import requests
from dotenv import load_dotenv


def test_connectivity():
    """Test Confluence API connectivity."""
    # Load environment variables
    load_dotenv()

    confluence_url = os.environ.get("CONFLUENCE_URL")
    email = os.environ.get("CONFLUENCE_EMAIL")
    api_token = os.environ.get("CONFLUENCE_API_TOKEN")

    # Validate required variables
    missing = []
    if not confluence_url:
        missing.append("CONFLUENCE_URL")
    if not email:
        missing.append("CONFLUENCE_EMAIL")
    if not api_token:
        missing.append("CONFLUENCE_API_TOKEN")

    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        print("Please set these in your .env file")
        sys.exit(1)

    # Clean up URL - remove trailing slash and handle /wiki suffix
    confluence_url = confluence_url.rstrip("/")

    # Determine the base URL and wiki path
    # If URL already ends with /wiki, use it as-is for the base
    # Otherwise, we'll add /wiki when making requests
    if confluence_url.endswith("/wiki"):
        wiki_base = confluence_url
        confluence_url = confluence_url[:-5]  # Remove /wiki for display
    else:
        wiki_base = f"{confluence_url}/wiki"

    print("=" * 60)
    print("Confluence API Connectivity Test")
    print("=" * 60)
    print(f"URL: {confluence_url}")
    print(f"Email: {email}")
    print(f"Token: {'*' * 12} (configured)")
    print()

    # Create session
    session = requests.Session()
    session.auth = (email, api_token)
    session.headers.update(
        {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
    )

    # Test 1: Get current user (try v1 API first, then v2)
    print("Test 1: Get current user...")
    user = None

    # Try v1 API (more widely supported)
    try:
        response = session.get(f"{wiki_base}/rest/api/user/current")
        if response.status_code == 200:
            user = response.json()
            print(f"  ✓ Success (v1 API)! Logged in as: {user.get('displayName', 'Unknown')}")
            print(f"    Account ID: {user.get('accountId', 'Unknown')}")
            print(f"    Username: {user.get('username', user.get('publicName', 'N/A'))}")
        elif response.status_code == 404:
            print("  ? v1 API returned 404, trying v2...")
            # Try v2 API
            response = session.get(f"{wiki_base}/api/v2/users/current")
            if response.status_code == 200:
                user = response.json()
                print(f"  ✓ Success (v2 API)! Logged in as: {user.get('displayName', 'Unknown')}")
                print(f"    Account ID: {user.get('accountId', 'Unknown')}")
            else:
                print(f"  ✗ v2 API also failed with status {response.status_code}")
                print("    This may indicate Confluence is not enabled on this site.")
                print(f"    URL tested: {wiki_base}/")
                sys.exit(1)
        else:
            print(f"  ✗ Failed with status {response.status_code}")
            print(f"    Response: {response.text[:500]}")
            sys.exit(1)
    except requests.RequestException as e:
        print(f"  ✗ Request failed: {e}")
        sys.exit(1)

    print()

    # Test 2: List spaces (try v1 API first)
    print("Test 2: List spaces...")
    try:
        # Try v1 API
        response = session.get(f"{wiki_base}/rest/api/space", params={"limit": 5})
        if response.status_code == 200:
            data = response.json()
            spaces = data.get("results", [])
            print(f"  ✓ Success (v1 API)! Found {len(spaces)} spaces (showing up to 5)")
            for space in spaces[:5]:
                print(f"    - {space.get('key')}: {space.get('name')}")
            if not spaces:
                print("    (No spaces found - you may need to create one)")
        elif response.status_code == 404:
            # Try v2 API
            response = session.get(f"{wiki_base}/api/v2/spaces", params={"limit": 5})
            if response.status_code == 200:
                data = response.json()
                spaces = data.get("results", [])
                print(f"  ✓ Success (v2 API)! Found {len(spaces)} spaces (showing up to 5)")
                for space in spaces[:5]:
                    print(f"    - {space.get('key')}: {space.get('name')}")
            else:
                print(f"  ✗ Failed with status {response.status_code}")
                print(f"    Response: {response.text[:200]}")
        else:
            print(f"  ✗ Failed with status {response.status_code}")
            print(f"    Response: {response.text[:200]}")
            sys.exit(1)
    except requests.RequestException as e:
        print(f"  ✗ Request failed: {e}")
        sys.exit(1)

    print()

    # Test 3: Check API permissions...
    print("Test 3: Check API permissions...")
    try:
        # Try to access the content endpoint
        response = session.get(f"{wiki_base}/api/v2/pages", params={"limit": 1})
        if response.status_code == 200:
            print("  ✓ Can read pages")
        elif response.status_code == 403:
            print("  ⚠ Cannot read pages (permission denied)")
        else:
            print(f"  ? Unexpected status: {response.status_code}")
    except requests.RequestException as e:
        print(f"  ✗ Request failed: {e}")

    print()
    print("=" * 60)
    print("Connectivity test complete!")
    print("=" * 60)


if __name__ == "__main__":
    test_connectivity()
