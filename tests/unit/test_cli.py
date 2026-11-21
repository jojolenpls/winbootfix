import pytest

from winbootfix import cli, exitcodes


def test_help_in_french_and_english(capsys):
    assert cli.main(["--lang", "fr", "--help"]) == exitcodes.OK
    out = capsys.readouterr().out
    assert "utilisation" in out and "réparer ce qui a été trouvé" in out and "Codes de sortie" in out
    assert cli.main(["--lang", "en", "--help"]) == exitcodes.OK
    assert "usage" in capsys.readouterr().out


def test_bad_usage(capsys):
    assert cli.main(["--lang", "en", "nonsense"]) == exitcodes.USAGE
    assert cli.main(["--lang", "en", "--apply", "--dry-run"]) == exitcodes.USAGE


def test_not_root(monkeypatch, tmp_path, capsys):
    from winbootfix.system import platform
    monkeypatch.setattr(platform, "is_root", lambda: False)
    assert cli.main(["--lang", "fr", "--log", str(tmp_path / "l.log")]) == exitcodes.NOT_ROOT
    cap = capsys.readouterr()
    assert "sudo winbootfix" in cap.out + cap.err


def test_exit_code_logic():
    from winbootfix.engine import Action, ActionResult, Finding, Plan, Severity
    plan = Plan(findings=[Finding("x", "m", Severity.ERROR, "k")])
    a = Action()
    assert cli.exit_code(plan, [], False) == exitcodes.ISSUES_FOUND
    assert cli.exit_code(Plan(), [], False) == exitcodes.OK
    assert cli.exit_code(plan, [ActionResult(a, "applied")], True) == exitcodes.REPAIRED
    assert cli.exit_code(plan, [ActionResult(a, "applied"), ActionResult(a, "failed")], True) == exitcodes.PARTIAL
    assert cli.exit_code(plan, [ActionResult(a, "cancelled")], True) == exitcodes.CANCELLED


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_version(capsys, lang):
    with pytest.raises(SystemExit):
        cli.build_parser(__import__("winbootfix.core.i18n", fromlist=["Translator"]).Translator(lang)).parse_args(["--version"])
    assert "winbootfix" in capsys.readouterr().out
