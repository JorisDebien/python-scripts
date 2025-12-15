"""Confluence freshness checker.

This module provides a small utility to scan Confluence pages via the
REST API and report how many pages are considered "stale" based on their
last-modified timestamp.

It is intentionally lightweight so functions can be imported and used in
larger automation workflows or invoked as a standalone script.
"""

import argparse
import datetime
import os
import sys
from typing import Generator, Dict, Any, Optional

import requests
import yaml


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from a YAML file.

    If ``path`` is not provided, the function looks for ``config.yml`` in
    the same directory as this module. The YAML is loaded with
    :func:`yaml.safe_load` and an empty dict is returned if the file
    does not exist or contains no data.

    Parameters
    ----------
    path:
        Optional filesystem path to the YAML config file.

    Returns
    -------
    dict
        Configuration mapping (may be empty).
    """
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "config.yml")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def make_session(config: Dict[str, Any]) -> requests.Session:
    """Create an authenticated :class:`requests.Session`.

    The function will use the ``username`` and ``api_token`` keys from the
    provided config mapping to set HTTP basic auth on the session. If those
    keys are missing the session will be returned without authentication.

    Parameters
    ----------
    config:
        Configuration mapping containing authentication values.

    Returns
    -------
    requests.Session
        Configured HTTP session object.
    """
    session = requests.Session()
    session.auth = (config.get("username"), config.get("api_token"))
    return session


def iterate_pages(
    session: requests.Session,
    base_url: str,
    space_key: Optional[str] = None,
    limit: int = 50,
) -> Generator[Dict[str, Any], None, None]:
    """Yield Confluence page content objects.

    Uses the Confluence REST API endpoint ``/rest/api/content`` and
    paginates through results. This generator yields raw page objects as
    returned by the API (dictionaries).

    Parameters
    ----------
    session:
        Authenticated :class:`requests.Session` used for HTTP requests.
    base_url:
        Base URL of the Confluence instance (e.g. ``https://confluence.example.com``).
    space_key:
        Optional Confluence space key to filter pages by.
    limit:
        Page size for each API request.

    Yields
    ------
    dict
        Individual page objects from the Confluence API.
    """
    api = base_url.rstrip("/") + "/rest/api/content"
    start = 0
    while True:
        params = {"type": "page", "limit": limit, "start": start, "expand": "version"}
        if space_key:
            params["spaceKey"] = space_key

        resp = session.get(api, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # Results are in 'results' for newer API, fallback to 'page' or 'values'
        results = data.get("results") or data.get("page") or data.get("values")
        if results is None:
            results = data.get("results", [])

        for item in results:
            yield item

        size = data.get("size")
        if size is None:
            if not results:
                break
            start += len(results)
        else:
            start += size

        links = data.get("_links", {})
        if not links.get("next") and (not results or len(results) < limit):
            break


def get_last_modified(item: Dict[str, Any]) -> Optional[datetime.datetime]:
    """Extract and parse the last-modified timestamp from a page object.

    The Confluence API stores version metadata under the ``version`` key;
    the timestamp is commonly available as an ISO 8601 string in the
    ``when`` field. This function returns a ``datetime`` object in UTC
    on success or ``None`` if no parseable timestamp is found.

    Parameters
    ----------
    item:
        Raw page object returned by Confluence API.

    Returns
    -------
    Optional[datetime.datetime]
        Parsed datetime in UTC or ``None`` when unavailable or unparsable.
    """
    version = item.get("version") or {}
    when = version.get("when")
    if when:
        try:
            return datetime.datetime.fromisoformat(when.replace("Z", "+00:00"))
        except Exception:
            pass
    return None


def analyze(
    session: requests.Session,
    base_url: str,
    space_key: Optional[str],
    threshold_days: int,
    limit: int = 50,
) -> Dict[str, Any]:
    """Scan pages and compute basic freshness metrics.

    The function iterates over pages returned by :func:`iterate_pages` and
    counts pages whose last-modified timestamp is older than the provided
    threshold (in days). Pages without a timestamp are considered stale.

    Parameters
    ----------
    session:
        Authenticated HTTP session.
    base_url:
        Confluence base URL.
    space_key:
        Optional space key to filter the scan.
    threshold_days:
        Number of days to treat a page as stale.
    limit:
        Page size for API requests.

    Returns
    -------
    dict
        Summary mapping containing ``total``, ``stale`` and ``percent_stale``.
    """
    total = 0
    stale = 0
    now = datetime.datetime.now(datetime.timezone.utc)
    threshold = datetime.timedelta(days=threshold_days)

    for item in iterate_pages(session, base_url, space_key=space_key, limit=limit):
        total += 1
        lm = get_last_modified(item)
        if lm is None:
            # If no timestamp, consider it stale
            stale += 1
            continue
        # ensure timezone-aware
        if lm.tzinfo is None:
            lm = lm.replace(tzinfo=datetime.timezone.utc)
        if now - lm > threshold:
            stale += 1

    percent_stale = (stale / total * 100.0) if total else 0.0
    return {"total": total, "stale": stale, "percent_stale": percent_stale}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Confluence freshness checker")
    parser.add_argument("--config", help="Path to YAML config file")
    parser.add_argument("--base-url", required=True, help="Confluence base URL")
    parser.add_argument("--space", help="Space key to limit the scan")
    parser.add_argument(
        "--threshold", type=int, default=90, help="Days threshold (default: 90)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Page size for API requests (default: 50)",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    session = make_session(cfg)

    try:
        result = analyze(session, args.base_url, args.space, args.threshold, limit=args.limit)
    except requests.HTTPError as exc:
        print("HTTP error:", exc)
        sys.exit(1)
    except requests.RequestException as exc:
        print("Network error:", exc)
        sys.exit(1)

    print(f"Total pages: {result['total']}")
    print(f"Stale pages (>{args.threshold} days): {result['stale']}")
    print(f"Percent stale: {result['percent_stale']:.1f}%")


if __name__ == "__main__":
    main()
