"""Direct coverage tests for the update-skill command module."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import desloppify.app.commands.update_skill.cmd as update_skill_cmd_mod


def _install(
    rel_path: str,
    *,
    interface: str | None,
    overlay: str | None,
    scope: str = "project",
    source_kind: str = "legacy_project",
    canonical: bool = False,
    version: int = 5,
    stale: bool = False,
) -> update_skill_cmd_mod.SkillInstall:
    return update_skill_cmd_mod.SkillInstall(
        rel_path=rel_path,
        absolute_path=Path("C:/fake") / rel_path.replace("~/", ""),
        interface=interface,
        scope=scope,
        source_kind=source_kind,
        canonical=canonical,
        version=version,
        overlay=overlay,
        stale=stale,
    )


def test_update_skill_helper_functions_cover_frontmatter_resolution_and_replace() -> None:
    assert update_skill_cmd_mod._RAW_BASE == "https://raw.githubusercontent.com/cpjet64/desloppify/main/docs"

    content = (
        "<!-- desloppify-begin -->\n"
        "<!-- version -->\n"
        "---\n"
        "name: skill\n"
        "---\n"
        "body\n"
    )
    reordered = update_skill_cmd_mod._ensure_frontmatter_first(content)
    assert reordered.startswith("---\nname: skill\n---\n")
    assert "<!-- desloppify-begin -->" in reordered

    section = update_skill_cmd_mod._build_section("skill body\n", "overlay body\n")
    assert section == "skill body\n\noverlay body\n"

    skill_with_frontmatter = "---\nname: desloppify\n---\n<!-- body -->\n"
    overlay_with_frontmatter = (
        "---\nname: desloppify-loop95\n---\n"
        "## Codex Loop95 Overlay\n"
    )
    overridden = update_skill_cmd_mod._build_section(
        skill_with_frontmatter,
        overlay_with_frontmatter,
    )
    assert overridden.startswith("---\nname: desloppify-loop95\n---\n")
    assert "<!-- body -->" in overridden
    assert "## Codex Loop95 Overlay" in overridden
    assert "name: desloppify\n" not in overridden

    replaced = update_skill_cmd_mod._replace_section(
        f"prefix\n\n{update_skill_cmd_mod.SKILL_BEGIN}\nold\n{update_skill_cmd_mod.SKILL_END}\n",
        "new section\n",
    )
    assert "prefix" in replaced
    assert "new section" in replaced
    assert "old" not in replaced

    assert (
        update_skill_cmd_mod._optional_metadata_filename(
            overlay_name="CODEX_LOOP95",
            dedicated=True,
        )
        == "CODEX_LOOP95.openai.yaml"
    )
    assert (
        update_skill_cmd_mod._optional_metadata_filename(
            overlay_name="CODEX",
            dedicated=False,
        )
        is None
    )
    assert (
        update_skill_cmd_mod._hook_script_filename(
            interface="codex_loop95",
            overlay_name="CODEX_LOOP95",
            dedicated=True,
        )
        == "CODEX_LOOP95.hook.py"
    )
    assert (
        update_skill_cmd_mod._hook_script_filename(
            interface="codex",
            overlay_name="CODEX",
            dedicated=True,
        )
        is None
    )

    merged_hooks = update_skill_cmd_mod._merge_codex_hooks_json(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "keep-me",
                            "hooks": [{"type": "command", "command": "python3 keep.py"}],
                        }
                    ]
                }
            }
        ),
        command="python3 /tmp/desloppify_loop95_hook.py",
    )
    hooks_payload = json.loads(merged_hooks)
    assert hooks_payload["hooks"]["Stop"][0]["matcher"] == "keep-me"
    assert any(
        group.get("matcher") == "desloppify-loop95"
        for group in hooks_payload["hooks"]["Stop"]
    )
    assert hooks_payload["hooks"]["UserPromptSubmit"][0]["matcher"] == "desloppify-loop95"

    config_text = update_skill_cmd_mod._ensure_codex_hooks_enabled(
        "model = \"gpt-5.4\"\n\n[features]\ncodex_hooks = false\n"
    )
    assert "[features]" in config_text
    assert "codex_hooks = true" in config_text
    assert (
        update_skill_cmd_mod._shell_join(["python3", "/tmp/with space/hook.py"])
        == "python3 '/tmp/with space/hook.py'"
    )


def test_resolve_interface_prefers_explicit_then_install_metadata(monkeypatch) -> None:
    assert update_skill_cmd_mod.resolve_interface("CoDeX") == "codex"

    install = _install(
        ".claude/skills/desloppify/SKILL.md",
        interface="claude",
        overlay="windsurf",
    )
    assert update_skill_cmd_mod.resolve_interface(None, install=install) == "windsurf"

    inferred = _install(
        ".cursor/rules/desloppify.md",
        interface="cursor",
        overlay=None,
    )
    monkeypatch.setattr(update_skill_cmd_mod, "find_installed_skills", lambda: [inferred])
    assert update_skill_cmd_mod.resolve_interface() == "cursor"

    loop95 = _install(
        "~/.codex/skills/desloppify-loop95/SKILL.md",
        interface="codex_loop95",
        overlay="codex_loop95",
        scope="user",
        source_kind="canonical_user",
        canonical=True,
    )
    assert update_skill_cmd_mod.resolve_interface(None, install=loop95) == "codex_loop95"


def test_update_installed_skill_handles_download_and_shared_file_write(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    skill_content = (
        "<!-- desloppify-begin -->\n"
        f"<!-- desloppify-skill-version: {update_skill_cmd_mod.SKILL_VERSION} -->\n"
        "---\n"
        "name: desloppify\n"
        "---\n"
        "body\n"
        "<!-- desloppify-end -->\n"
    )
    overlay_content = "overlay text\n"
    writes: list[tuple[Path, str]] = []
    target = tmp_path / ".codex" / "skills" / "desloppify" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("prefix only", encoding="utf-8")

    def _download(filename: str) -> str:
        if filename == "SKILL.md":
            return skill_content
        if filename == "CODEX.md":
            return overlay_content
        raise KeyError(filename)

    monkeypatch.setattr(update_skill_cmd_mod, "_download", _download)
    monkeypatch.setattr(update_skill_cmd_mod, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(update_skill_cmd_mod, "_get_home_path", lambda: tmp_path)
    monkeypatch.setattr(
        update_skill_cmd_mod,
        "safe_write_text",
        lambda path, text: writes.append((path, text)) or path.write_text(text, encoding="utf-8"),
    )
    monkeypatch.setattr(update_skill_cmd_mod, "colorize", lambda text, _style: text)

    assert update_skill_cmd_mod.update_installed_skill("codex") is True
    assert writes and writes[-1][0] == target
    written = target.read_text(encoding="utf-8")
    assert written.startswith("---\nname: desloppify\n---\n")
    assert "overlay text" in written
    assert not (target.parent / "agents" / "openai.yaml").exists()
    out = capsys.readouterr().out
    assert "Updated .codex/skills/desloppify/SKILL.md" in out
    assert (
        f"(v{update_skill_cmd_mod.SKILL_VERSION}, tool expects v{update_skill_cmd_mod.SKILL_VERSION})"
        in out
    )


def test_update_installed_skill_supports_codex_loop95_target(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    skill_content = (
        "<!-- desloppify-begin -->\n"
        f"<!-- desloppify-skill-version: {update_skill_cmd_mod.SKILL_VERSION} -->\n"
        "---\n"
        "name: desloppify\n"
        "---\n"
        "body\n"
        "<!-- desloppify-end -->\n"
    )
    overlay_content = (
        "---\n"
        "name: desloppify-loop95\n"
        "description: >\n"
        "  Loop until strict score is at least 95.\n"
        "---\n"
        "loop95 overlay\n"
    )
    metadata_content = (
        "interface:\n"
        '  display_name: "Desloppify Loop95"\n'
        '  short_description: "Raise strict score to 95 with a persistent fix loop."\n'
        '  default_prompt: "Use $desloppify-loop95 to inspect the current repo state, run `desloppify scan --path .`, check `desloppify status`, review this scan cycle if needed, and keep working `desloppify next`. When the execution queue empties, run `desloppify plan queue` and follow its exact promotion guidance until strict >= 95.0."\n'
        "policy:\n"
        "  allow_implicit_invocation: false\n"
    )
    hook_content = "print('{}')\n"
    target = tmp_path / ".codex" / "skills" / "desloppify-loop95" / "SKILL.md"
    metadata_path = target.parent / "agents" / "openai.yaml"
    hook_path = tmp_path / ".codex" / "hooks" / "desloppify_loop95_hook.py"
    hooks_json_path = tmp_path / ".codex" / "hooks.json"
    config_path = tmp_path / ".codex" / "config.toml"

    def _download(filename: str) -> str:
        if filename == "SKILL.md":
            return skill_content
        if filename == "CODEX_LOOP95.md":
            return overlay_content
        if filename == "CODEX_LOOP95.openai.yaml":
            return metadata_content
        if filename == "CODEX_LOOP95.hook.py":
            return hook_content
        raise KeyError(filename)

    monkeypatch.setattr(update_skill_cmd_mod, "_download", _download)
    monkeypatch.setattr(update_skill_cmd_mod, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(update_skill_cmd_mod, "_get_home_path", lambda: tmp_path)
    monkeypatch.setattr(
        update_skill_cmd_mod,
        "safe_write_text",
        lambda path, text: path.write_text(text, encoding="utf-8"),
    )
    monkeypatch.setattr(update_skill_cmd_mod, "colorize", lambda text, _style: text)

    assert update_skill_cmd_mod.update_installed_skill("codex_loop95") is True
    written = target.read_text(encoding="utf-8")
    assert written.startswith("---\nname: desloppify-loop95\n")
    assert "loop95 overlay" in written
    assert "name: desloppify\n" not in written
    metadata = metadata_path.read_text(encoding="utf-8")
    assert 'display_name: "Desloppify Loop95"' in metadata
    assert "$desloppify-loop95" in metadata
    assert "allow_implicit_invocation: false" in metadata
    assert hook_path.read_text(encoding="utf-8") == hook_content
    hooks_payload = json.loads(hooks_json_path.read_text(encoding="utf-8"))
    assert any(
        group.get("matcher") == "desloppify-loop95"
        for group in hooks_payload["hooks"]["Stop"]
    )
    assert any(
        group.get("matcher") == "desloppify-loop95"
        for group in hooks_payload["hooks"]["UserPromptSubmit"]
    )
    config_text = config_path.read_text(encoding="utf-8")
    assert "[features]" in config_text
    assert "codex_hooks = true" in config_text
    out = capsys.readouterr().out
    assert "Updated .codex/skills/desloppify-loop95/SKILL.md" in out
    assert "Updated" in out and "hooks.json" in out
    assert "Enabled Codex hooks" in out


def test_update_installed_skill_supports_project_scoped_codex_loop95_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    skill_content = (
        "<!-- desloppify-begin -->\n"
        f"<!-- desloppify-skill-version: {update_skill_cmd_mod.SKILL_VERSION} -->\n"
        "body\n"
        "<!-- desloppify-end -->\n"
    )
    overlay_content = "loop95 overlay\n"
    metadata_content = (
        "interface:\n"
        '  display_name: "Desloppify Loop95"\n'
        '  short_description: "Raise strict score to 95 with a persistent fix loop."\n'
        '  default_prompt: "Use $desloppify-loop95 to inspect the current repo state, run `desloppify plan queue` when execution empties, and keep looping until strict >= 95.0."\n'
        "policy:\n"
        "  allow_implicit_invocation: false\n"
    )
    hook_content = "print('{}')\n"

    def _download(filename: str) -> str:
        if filename == "SKILL.md":
            return skill_content
        if filename == "CODEX_LOOP95.md":
            return overlay_content
        if filename == "CODEX_LOOP95.openai.yaml":
            return metadata_content
        if filename == "CODEX_LOOP95.hook.py":
            return hook_content
        raise KeyError(filename)

    monkeypatch.setattr(update_skill_cmd_mod, "_download", _download)
    monkeypatch.setattr(update_skill_cmd_mod, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(update_skill_cmd_mod, "_get_home_path", lambda: tmp_path)
    monkeypatch.setattr(
        update_skill_cmd_mod,
        "safe_write_text",
        lambda path, text: path.write_text(text, encoding="utf-8"),
    )
    monkeypatch.setattr(update_skill_cmd_mod, "colorize", lambda text, _style: text)

    assert update_skill_cmd_mod.update_installed_skill("codex_loop95", scope="project") is True
    assert (
        tmp_path
        / ".agents"
        / "skills"
        / "desloppify-loop95"
        / "agents"
        / "openai.yaml"
    ).is_file()
    assert (tmp_path / ".codex" / "hooks" / "desloppify_loop95_hook.py").is_file()
    assert (tmp_path / ".codex" / "hooks.json").is_file()
    assert (tmp_path / ".codex" / "config.toml").is_file()


def test_cmd_update_skill_handles_missing_and_ambiguous_installs(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        update_skill_cmd_mod,
        "find_installed_skills",
        lambda: [],
    )
    monkeypatch.setattr(
        update_skill_cmd_mod,
        "resolve_interface",
        lambda _explicit=None, installs=None: None,
    )
    monkeypatch.setattr(update_skill_cmd_mod, "colorize", lambda text, _style: text)
    update_skill_cmd_mod.cmd_update_skill(argparse.Namespace(interface=None, scope="auto"))
    out = capsys.readouterr().out
    assert "No installed skill document found." in out

    monkeypatch.setattr(
        update_skill_cmd_mod,
        "find_installed_skills",
        lambda: [
            _install("~/.codex/skills/desloppify/SKILL.md", interface="codex", overlay="codex", scope="user", source_kind="canonical_user", canonical=True),
            _install("~/.claude/skills/desloppify/SKILL.md", interface="claude", overlay="claude", scope="user", source_kind="canonical_user", canonical=True),
        ],
    )
    monkeypatch.setattr(
        update_skill_cmd_mod,
        "resolve_interface",
        lambda _explicit=None, installs=None: None,
    )
    update_skill_cmd_mod.cmd_update_skill(argparse.Namespace(interface=None, scope="auto"))
    out = capsys.readouterr().out
    assert "Multiple installed skill documents were detected." in out

    monkeypatch.setattr(
        update_skill_cmd_mod,
        "find_installed_skills",
        lambda: [
            _install("~/.codex/skills/desloppify/SKILL.md", interface="codex", overlay="codex", scope="user", source_kind="canonical_user", canonical=True),
            _install("~/.codex/skills/desloppify-loop95/SKILL.md", interface="codex_loop95", overlay="codex_loop95", scope="user", source_kind="canonical_user", canonical=True),
        ],
    )
    monkeypatch.setattr(
        update_skill_cmd_mod,
        "resolve_interface",
        lambda _explicit=None, installs=None: None,
    )
    update_skill_cmd_mod.cmd_update_skill(argparse.Namespace(interface=None, scope="auto"))
    out = capsys.readouterr().out
    assert "Multiple installed skill documents were detected." in out


def test_cmd_update_skill_handles_unknown_interface(monkeypatch, capsys) -> None:
    monkeypatch.setattr(update_skill_cmd_mod, "find_installed_skills", lambda: [])
    monkeypatch.setattr(update_skill_cmd_mod, "colorize", lambda text, _style: text)
    update_skill_cmd_mod.cmd_update_skill(argparse.Namespace(interface="unknown_thing", scope="auto"))
    out = capsys.readouterr().out
    assert "Unknown interface 'unknown_thing'." in out
    assert "codex_loop95" in out
