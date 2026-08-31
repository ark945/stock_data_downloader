"""Local sanity checks for GitHub Actions workflow configuration."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKFLOW_DIR = ROOT / ".github" / "workflows"


def workflow_text(name: str) -> str:
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def assert_script_exists(script_name: str) -> None:
    assert (ROOT / script_name).exists(), f"workflow references missing script: {script_name}"


def test_workflows_parse() -> None:
    for workflow_path in WORKFLOW_DIR.glob("*.yml"):
        text = workflow_path.read_text(encoding="utf-8")
        assert "name:" in text, f"workflow missing name: {workflow_path}"
        assert "jobs:" in text, f"workflow missing jobs: {workflow_path}"


def test_daily_workflow_uses_current_sharding() -> None:
    text = workflow_text("daily_stock_crawler.yml")
    assert "TPEX 8-Runner" in text
    assert "tpex-probe:" in text
    assert "tpex-canary:" in text
    assert "--limit-symbols 5" in text
    assert "needs.tpex-probe.result == 'success'" in text
    assert "needs.tpex-canary.result == 'success'" in text
    assert "requirements_tpex_cloud.txt" in text
    assert "shard: [1, 2, 3, 4, 5, 6, 7]" in text
    assert "max-parallel: 1" in text
    assert "name: tpex-shard-0" in text
    assert "--num-shards 8" in text
    assert "TPEX_CI_ABORT_AFTER_CONSECUTIVE_FAILURES" in text
    assert "--max-rounds 1" in text
    assert "TPEX 20-Runner" not in text
    assert "--num-shards 20" not in text


def test_action_smoke_test_scripts_exist() -> None:
    assert_script_exists("test_gdrive.py")
    assert_script_exists("test_notify.py")
    assert_script_exists("test_cloud_diagnostics.py")


def test_gdrive_workflow_has_required_secret_wiring() -> None:
    text = workflow_text("test_gdrive.yml")
    assert "GDRIVE_UPLOAD_URL" in text
    assert "GDRIVE_SERVICE_ACCOUNT_KEY" in text
    assert "GDRIVE_FOLDER_ID" in text
    assert "exit 1" in text


def test_notification_workflow_fails_when_script_missing() -> None:
    text = workflow_text("test_notification.yml")
    assert "test_notify.py" in text
    assert "exit 1" in text


def main() -> int:
    checks = [
        test_workflows_parse,
        test_daily_workflow_uses_current_sharding,
        test_action_smoke_test_scripts_exist,
        test_gdrive_workflow_has_required_secret_wiring,
        test_notification_workflow_fails_when_script_missing,
    ]
    for check in checks:
        check()
        print(f"[✓] {check.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())