from pathlib import Path

from typer.testing import CliRunner

from backend.cli import app

runner = CliRunner()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "run" in result.output
    assert "serve" not in result.output
    assert "ping" not in result.output


def test_offline_cli_and_exclusive_options(tmp_path):
    example = Path(__file__).resolve().parents[1] / "data" / "raw" / "example"
    result = runner.invoke(
        app, ["run", "--from-snapshot", str(example), "--data-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert '"accepted": 4' in result.output
    result = runner.invoke(app, ["run", "--market", "chicago", "--all-markets"])
    assert result.exit_code == 1
    assert "exactly one" in result.output
