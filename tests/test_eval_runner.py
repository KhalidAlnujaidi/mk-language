"""The §8.3 regression runner: run the golden eval set, get a structured verdict."""

from evals.runner import run_eval_set


def test_run_eval_set_counts_pass_and_fail(tmp_path):
    (tmp_path / "test_sample.py").write_text(
        "def test_ok():\n    assert True\n\ndef test_bad():\n    assert False\n"
    )
    report = run_eval_set(str(tmp_path))
    assert report.passed == 1
    assert report.failed == 1
    assert report.total == 2
    assert report.ok is False


def test_run_eval_set_all_green_is_ok(tmp_path):
    (tmp_path / "test_green.py").write_text("def test_ok():\n    assert True\n")
    report = run_eval_set(str(tmp_path))
    assert report.ok is True
    assert report.failed == 0
    assert report.total == 1
