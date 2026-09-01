"""
Google Drive smoke test for GitHub Actions.

The default mode verifies that required secrets are present and uploads a tiny
text file through the same gdrive_sync path used by the crawler. Use
``--offline`` for local CI-safe validation without secrets or network access.
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

from gdrive_sync import upload_file_to_gdrive


REQUIRED_FOLDER_ENV = "GDRIVE_FOLDER_ID"
AUTH_ENV_OPTIONS = ("GDRIVE_UPLOAD_URL", "GDRIVE_SERVICE_ACCOUNT_KEY")


def validate_env() -> list[str]:
    missing = []
    if not os.environ.get(REQUIRED_FOLDER_ENV, "").strip():
        missing.append(REQUIRED_FOLDER_ENV)
    if not any(os.environ.get(name, "").strip() for name in AUTH_ENV_OPTIONS):
        missing.append(" or ".join(AUTH_ENV_OPTIONS))
    return missing


def run_offline_check() -> bool:
    missing = validate_env()
    print("[*] Offline mode: verified test_gdrive.py imports and environment checks.")
    if missing:
        print(f"[*] Offline mode: missing secrets would be reported clearly: {', '.join(missing)}")
    return True


def run_upload_check() -> bool:
    missing = validate_env()
    if missing:
        print("[!] Missing required GitHub secrets for Google Drive smoke test:")
        for name in missing:
            print(f"    - {name}")
        return False

    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = Path(tmp_dir) / "github_actions_gdrive_smoke_test.txt"
        test_file.write_text("GitHub Actions Google Drive smoke test\n", encoding="utf-8")

        print(f"[*] Uploading smoke-test file: {test_file.name}")
        result = upload_file_to_gdrive(str(test_file), subfolder="Log")
        if not result or not result.get("file_id"):
            print("[!] Google Drive upload smoke test failed: no file_id returned.")
            return False

        print(f"[✓] Google Drive upload smoke test passed. File ID: {result.get('file_id')}")
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Google Drive upload settings.")
    parser.add_argument("--offline", action="store_true", help="Run without secrets or network access.")
    args = parser.parse_args()

    success = run_offline_check() if args.offline else run_upload_check()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())