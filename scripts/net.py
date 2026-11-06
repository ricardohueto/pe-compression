"""
net.py - Polite HTTP downloads, shared by the scripts that use the network.

Every request waits REQUEST_DELAY_S seconds first and sends a descriptive
User-Agent, so we never overload the servers (Gutenberg mirror, Wikimedia).
"""
import sys
import time

import requests

import config

SESSION = requests.Session()
SESSION.headers["User-Agent"] = config.USER_AGENT

MAX_ATTEMPTS = 4      # tries per request before giving up
RETRY_WAIT_S = 30     # pause after a failed try


def polite_get(url, **kwargs):
    """GET with a pause before every request.

    Network errors and temporary server errors (HTTP 429 and 5xx) are retried,
    so that a temporary problem never causes a file to be excluded. If the
    problem persists the script stops instead of continuing with a wrong sample.
    Any other answer (200, 404, ...) is returned to the caller.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        time.sleep(config.REQUEST_DELAY_S if attempt == 1 else RETRY_WAIT_S)
        try:
            r = SESSION.get(url, timeout=120, **kwargs)
        except requests.RequestException as e:
            error = type(e).__name__
        else:
            if r.status_code != 429 and r.status_code < 500:
                return r
            error = f"HTTP {r.status_code}"
        print(f"  (try {attempt}/{MAX_ATTEMPTS} failed for {url}: {error})")
    sys.exit(f"Giving up on {url} ({error}). Check the connection and run the "
             "script again.")
