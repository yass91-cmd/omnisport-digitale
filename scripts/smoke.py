"""Verify a running API and its public-file boundary using only the standard library."""

import argparse
import json
from urllib.error import HTTPError
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    for path, status in [("/health/live", "ok"), ("/health/ready", "ready")]:
        with urlopen(args.url + path, timeout=10) as response:
            assert json.load(response)["status"] == status
    with urlopen(args.url + "/api/v1/complexes", timeout=10) as response:
        data = json.load(response)
        assert data["total"] >= 2
        assert all(item["is_demo"] for item in data["items"])
    with urlopen(args.url + "/account.html", timeout=10) as response:
        assert response.status == 200
    with urlopen(args.url + "/api/v1/auth/session", timeout=10) as response:
        assert json.load(response) is None
        assert response.headers["Cache-Control"] == "no-store"
    try:
        urlopen(args.url + "/api/v1/auth/me", timeout=10)
    except HTTPError as error:
        assert error.code == 401
    else:
        raise AssertionError("Anonymous request unexpectedly accessed an account")
    for path in ["/media/README.md", "/README.md", "/OmniSport_Digitale.pdf", "/.env"]:
        try:
            urlopen(args.url + path, timeout=10)
        except HTTPError as error:
            assert error.code == 404
        else:
            raise AssertionError(f"Private path unexpectedly served: {path}")
    print("Smoke checks passed: health, catalogue, account access, and private-file isolation.")


if __name__ == "__main__":
    main()
