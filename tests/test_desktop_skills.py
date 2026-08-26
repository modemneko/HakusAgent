from pathlib import Path

import pytest

from hakusai_server.skills import (
    SkillError,
    discover_skills,
    expand_skill_mentions,
    install_skill,
    remove_skill,
    set_enabled,
)


def write_skill(root: Path, name: str, description: str = "Test skill") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\nFollow this skill.\n",
        encoding="utf-8",
    )
    return skill_dir


@pytest.fixture
def skill_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HAKUS_HOME", str(home))
    return home, project


def test_discovery_toggle_and_prompt_expansion(skill_env: tuple[Path, Path]) -> None:
    home, project = skill_env
    write_skill(home / "skills", "review-code", "Review source changes")

    response = discover_skills(project)
    assert [skill["name"] for skill in response["skills"]] == ["review-code"]
    assert response["skills"][0]["enabled"] is True

    expanded = expand_skill_mentions("Please use @skill:review-code", project)
    assert '<skill name="review-code"' in expanded
    assert "Follow this skill." in expanded

    set_enabled("review-code", False, project)
    assert discover_skills(project)["skills"][0]["enabled"] is False
    with pytest.raises(SkillError, match="disabled or unavailable"):
        expand_skill_mentions("Please use @skill:review-code", project)


def test_install_local_project_skill_and_remove(skill_env: tuple[Path, Path], tmp_path: Path) -> None:
    _, project = skill_env
    source = write_skill(tmp_path / "source", "project-helper")

    receipt = install_skill(str(source), scope="project", project_dir=project)
    assert receipt["outcome"] == "installed"
    assert (project / ".hakus" / "skills" / "project-helper" / "SKILL.md").is_file()

    skills = discover_skills(project)["skills"]
    assert skills[0]["scope"] == "project"
    assert skills[0]["writable"] is True

    removed = remove_skill("project-helper", scope="project", project_dir=project)
    assert removed["outcome"] == "removed"
    assert not (project / ".hakus" / "skills" / "project-helper").exists()


def test_install_rejects_ambiguous_skill_bundle(skill_env: tuple[Path, Path], tmp_path: Path) -> None:
    home, project = skill_env
    bundle = tmp_path / "bundle"
    write_skill(bundle, "one")
    write_skill(bundle, "two")

    with pytest.raises(SkillError, match="multiple Skills"):
        install_skill(str(bundle), scope="global", project_dir=project)
    assert not (home / "skills" / "one").exists()


def test_skills_api_works_without_an_active_project(skill_env: tuple[Path, Path]) -> None:
    home, _ = skill_env
    write_skill(home / "skills", "global-helper")

    from fastapi.testclient import TestClient
    from hakusai_server.server import HakusAIServer

    client = TestClient(HakusAIServer().create_app())
    response = client.get("/api/skills")

    assert response.status_code == 200
    assert [skill["name"] for skill in response.json()["skills"]] == ["global-helper"]
