"""Сверки CI сами работают: расхождение THIRD_PARTY.md и pyproject ловится."""

from pathlib import Path

from check_third_party import check


def test_third_party_detects_missing(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi>=1"]\n', encoding="utf-8")
    table = "## Python-зависимости\n\n| Пакет | Версия | Лицензия |\n"
    (tmp_path / "THIRD_PARTY.md").write_text(table, encoding="utf-8")
    assert check(tmp_path) == ["нет в THIRD_PARTY.md: fastapi"]


def test_repo_third_party_ok() -> None:
    assert check(Path(__file__).resolve().parents[1]) == []
