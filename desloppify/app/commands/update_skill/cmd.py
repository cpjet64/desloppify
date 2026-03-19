"""update-skill command: install or update the desloppify skill document."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import ssl
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

from desloppify.app.skill_docs import (
    SKILL_BEGIN,
    SKILL_END,
    SKILL_TARGETS,
    SKILL_VERSION,
    SKILL_VERSION_RE,
    SkillInstall,
    SkillScope,
    find_installed_skills,
    get_default_scope,
    get_skill_target,
)
from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.discovery.paths import get_project_root
from desloppify.base.exception_sets import CommandError
from desloppify.base.output.terminal import colorize

_RAW_BASE = "https://raw.githubusercontent.com/cpjet64/desloppify/main/docs"
_CODEX_LOOP95_HOOK_SCRIPT = "desloppify_loop95_hook.py"
_CODEX_LOOP95_GROUP_MARKER = "desloppify-loop95"
_CODEX_LOOP95_PROMPT_STATUS = "desloppify-loop95 prompt gate"
_CODEX_LOOP95_STOP_STATUS = "desloppify-loop95 Ralph loop"


def _get_home_path() -> Path:
    """Return the current user's home directory."""
    return Path.home()


def _ssl_context() -> ssl.SSLContext:
    """Build SSL context, preferring certifi CA bundle for macOS compatibility."""
    try:
        import certifi  # noqa: F811
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _download(filename: str) -> str:
    """Download a file from the desloppify docs directory on GitHub."""
    url = f"{_RAW_BASE}/{filename}"
    try:
        ctx = _ssl_context()
        with urllib.request.urlopen(url, timeout=15, context=ctx) as resp:  # nosec B310
            return resp.read().decode("utf-8")
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            raise CommandError(
                f"SSL certificate verification failed downloading {filename}.\n"
                "On macOS with Homebrew Python, try: pip install certifi\n"
                "Or run: /Applications/Python\\ 3.*/Install\\ Certificates.command"
            ) from exc
        raise


def _build_section(skill_content: str, overlay_content: str | None) -> str:
    """Assemble the complete skill section from downloaded parts."""
    def _split_frontmatter(content: str | None) -> tuple[str | None, str]:
        if not content:
            return None, ""
        normalized = content.lstrip("\ufeff")
        lines = normalized.splitlines()
        if not lines:
            return None, normalized
        fm_start = None
        for index, line in enumerate(lines):
            if line.strip() == "---":
                fm_start = index
                break
        if fm_start is None:
            return None, normalized
        for index in range(fm_start + 1, len(lines)):
            if lines[index].strip() == "---":
                frontmatter = "\n".join(lines[fm_start : index + 1]).rstrip()
                body_lines = lines[:fm_start] + lines[index + 1 :]
                body = "\n".join(body_lines).lstrip("\n")
                return frontmatter, body
        return None, normalized

    skill_frontmatter, skill_body = _split_frontmatter(skill_content)
    overlay_frontmatter, overlay_body = _split_frontmatter(overlay_content)

    frontmatter = overlay_frontmatter or skill_frontmatter
    parts = [part.rstrip() for part in (skill_body, overlay_body) if part and part.strip()]
    body = "\n\n".join(parts)

    if frontmatter and body:
        return f"{frontmatter}\n\n{body}\n"
    if frontmatter:
        return f"{frontmatter}\n"
    return body + ("\n" if body else "")


def _optional_metadata_filename(*, overlay_name: str | None, dedicated: bool) -> str | None:
    """Return the optional metadata asset filename for a dedicated skill target."""
    if not dedicated or not overlay_name:
        return None
    return f"{overlay_name}.openai.yaml"


def _hook_script_filename(*, interface: str, overlay_name: str | None, dedicated: bool) -> str | None:
    """Return the optional hook script asset filename for a supported target."""
    if interface != "codex_loop95" or not dedicated or not overlay_name:
        return None
    return f"{overlay_name}.hook.py"


def _download_optional_asset(filename: str | None, download_fn) -> str | None:
    """Best-effort download for optional skill assets.

    Optional metadata should never block the main skill install. Missing files
    and transient fetch failures fall back to no metadata.
    """
    if not filename:
        return None
    try:
        return download_fn(filename)
    except (urllib.error.URLError, OSError, KeyError):
        return None


def _codex_config_root(
    *,
    scope: SkillScope,
    get_home_path_fn,
    get_project_root_fn,
) -> Path:
    """Return the active Codex config root for the requested install scope."""
    if scope == "user":
        return get_home_path_fn() / ".codex"
    return get_project_root_fn() / ".codex"


def _shell_join(parts: list[str]) -> str:
    """Return a shell-safe command string for the current platform."""
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return " ".join(shlex.quote(part) for part in parts)


def _codex_loop95_hook_command(script_path: Path) -> str:
    """Build the command string Codex should execute for the loop95 hook."""
    return _shell_join([sys.executable, str(script_path)])


def _codex_loop95_group(*, status_message: str, command: str) -> dict[str, object]:
    """Return one merge-stable Claude-style hook matcher group."""
    return {
        "matcher": _CODEX_LOOP95_GROUP_MARKER,
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": 30,
                "statusMessage": status_message,
            }
        ],
    }


def _is_codex_loop95_group(group: object) -> bool:
    """Return True when an existing hook matcher group belongs to loop95."""
    if not isinstance(group, dict):
        return False
    matcher = str(group.get("matcher", "")).strip().lower()
    if matcher == _CODEX_LOOP95_GROUP_MARKER:
        return True
    hooks = group.get("hooks")
    if not isinstance(hooks, list):
        return False
    for hook in hooks:
        if not isinstance(hook, dict):
            continue
        command = str(hook.get("command", "")).strip()
        if _CODEX_LOOP95_HOOK_SCRIPT in command:
            return True
    return False


def _merged_hook_groups(
    groups: object,
    *,
    command: str,
    status_message: str,
) -> list[dict[str, object]]:
    """Return a hooks.json event list with the loop95 group updated in place."""
    if groups is None:
        merged: list[dict[str, object]] = []
    elif isinstance(groups, list):
        merged = [
            group for group in groups
            if not _is_codex_loop95_group(group)
        ]
    else:
        raise CommandError("Existing Codex hooks.json is invalid: hook event entries must be arrays.")
    merged.append(_codex_loop95_group(status_message=status_message, command=command))
    return merged


def _merge_codex_hooks_json(existing_text: str | None, *, command: str) -> str:
    """Merge the loop95 hook handlers into an existing Claude-style hooks.json."""
    if existing_text and existing_text.strip():
        try:
            payload = json.loads(existing_text)
        except json.JSONDecodeError as exc:
            raise CommandError(
                f"Existing Codex hooks.json is invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}."
            ) from exc
        if not isinstance(payload, dict):
            raise CommandError("Existing Codex hooks.json must contain a JSON object at the top level.")
    else:
        payload = {}

    hooks = payload.get("hooks")
    if hooks is None:
        hooks = {}
        payload["hooks"] = hooks
    if not isinstance(hooks, dict):
        raise CommandError("Existing Codex hooks.json is invalid: top-level `hooks` must be an object.")

    hooks["UserPromptSubmit"] = _merged_hook_groups(
        hooks.get("UserPromptSubmit"),
        command=command,
        status_message=_CODEX_LOOP95_PROMPT_STATUS,
    )
    hooks["Stop"] = _merged_hook_groups(
        hooks.get("Stop"),
        command=command,
        status_message=_CODEX_LOOP95_STOP_STATUS,
    )
    return json.dumps(payload, indent=2) + "\n"


_FEATURES_SECTION_RE = re.compile(r"(?ms)^\[features\]\s*$.*?(?=^\[|\Z)")


def _ensure_codex_hooks_enabled(existing_text: str | None) -> str:
    """Return config.toml text with `[features].codex_hooks = true` enforced."""
    text = existing_text or ""
    if text.strip():
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise CommandError(f"Existing Codex config.toml is invalid TOML: {exc}.") from exc
    else:
        return "[features]\ncodex_hooks = true\n"

    section_match = _FEATURES_SECTION_RE.search(text)
    if section_match is None:
        updated = text.rstrip() + "\n\n[features]\ncodex_hooks = true\n"
    else:
        section = section_match.group(0)
        if re.search(r"(?m)^\s*codex_hooks\s*=", section):
            replacement = re.sub(
                r"(?m)^(\s*codex_hooks\s*=\s*).*$",
                r"\1true",
                section,
                count=1,
            )
        else:
            replacement = section.rstrip() + "\ncodex_hooks = true\n"
        updated = text[: section_match.start()] + replacement + text[section_match.end() :]

    try:
        tomllib.loads(updated)
    except tomllib.TOMLDecodeError as exc:
        raise CommandError(f"Generated Codex config.toml update is invalid TOML: {exc}.") from exc
    return updated


_FRONTMATTER_FIRST_INTERFACES = frozenset({"amp", "codex", "codex_loop95"})


def _ensure_frontmatter_first(content: str) -> str:
    """Move YAML frontmatter to the top if HTML comments precede it."""
    lines = content.split("\n")

    fm_start = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            fm_start = i
            break
    if fm_start is None or fm_start == 0:
        return content

    prefix_lines = lines[:fm_start]

    fm_end = None
    for i, line in enumerate(lines[fm_start + 1 :], fm_start + 1):
        if line.strip() == "---":
            fm_end = i
            break
    if fm_end is None:
        return content

    reordered = lines[fm_start : fm_end + 1] + prefix_lines + lines[fm_end + 1 :]
    return "\n".join(reordered)


def _replace_section(file_content: str, new_section: str) -> str:
    """Replace the desloppify section in a shared file, preserving surrounding content.

    Uses first ``<!-- desloppify-begin -->`` and last ``<!-- desloppify-end -->``
    so the overlay (which also has an end marker) is captured correctly.

    Raises ``CommandError`` if the file already contains desloppify content
    (detected by the version marker) but is missing the begin/end markers —
    this prevents silently appending duplicate content.
    """
    begin = file_content.find(SKILL_BEGIN)
    end = file_content.rfind(SKILL_END)
    if begin == -1 or end == -1:
        # Check if the file already has desloppify content without markers.
        if SKILL_VERSION_RE.search(file_content):
            raise CommandError(
                "This file already contains desloppify skill content but is "
                "missing <!-- desloppify-begin --> / <!-- desloppify-end --> "
                "markers. Please add these markers around the existing "
                "desloppify section, or remove the old content first."
            )
        # No section markers and no existing content — append (first install).
        return file_content.rstrip() + "\n\n" + new_section

    before = file_content[:begin]
    after = file_content[end + len(SKILL_END) :]
    before = before.rstrip() + "\n\n" if before.strip() else ""
    after = "\n" + after.lstrip("\n") if after.strip() else "\n"
    return before + new_section + after


def resolve_interface(
    explicit: str | None = None,
    install: SkillInstall | None = None,
    installs: list[SkillInstall] | None = None,
    active_interface: str | None = None,
) -> str | None:
    """Resolve which interface to update."""
    if explicit:
        return explicit.lower()

    if install is not None and install.overlay:
        return install.overlay.lower()
    if install is not None and install.interface:
        return install.interface.lower()
    if install is not None:
        return None

    detected = installs if installs is not None else find_installed_skills()
    if active_interface:
        active_name = active_interface.lower()
        if any(item.interface == active_name for item in detected):
            return active_name

    interfaces = sorted({item.interface for item in detected if item.interface})
    if len(interfaces) == 1:
        return interfaces[0]
    return None


def resolve_scope(interface: str, requested_scope: str | None = "auto") -> SkillScope:
    """Resolve the install scope for an interface."""
    scope_name = (requested_scope or "auto").lower()
    if scope_name == "auto":
        return get_default_scope(interface)
    if scope_name not in {"user", "project"}:
        raise ValueError(f"Unknown scope '{requested_scope}'.")
    return scope_name


def _print_detected_installs(installs: list[SkillInstall]) -> None:
    if not installs:
        return
    print("Detected installs:")
    for install in installs:
        interface = install.interface or "unknown"
        freshness = "stale" if install.stale else "current"
        print(
            f"  - {interface}: {install.rel_path} "
            f"[scope={install.scope}, source={install.source_kind}, {freshness}]"
        )


def _update_installed_skill_with_deps(
    interface: str,
    *,
    scope: SkillScope | str = "auto",
    download_fn,
    get_home_path_fn,
    get_project_root_fn,
    safe_write_text_fn,
    colorize_fn,
) -> bool:
    """Download and install the skill document for the given interface."""
    resolved_scope = resolve_scope(interface, scope)
    target = get_skill_target(interface, resolved_scope)
    target_path = target.absolute_path(
        project_root=get_project_root_fn(),
        home=get_home_path_fn(),
    )

    print(colorize_fn(f"Downloading skill document ({interface})...", "dim"))
    try:
        skill_content = download_fn("SKILL.md")
        overlay_content = download_fn(f"{target.overlay_name}.md") if target.overlay_name else None
    except (urllib.error.URLError, OSError) as exc:
        print(colorize_fn(f"Download failed: {exc}", "red"))
        return False

    if "desloppify-skill-version" not in skill_content:
        print(colorize_fn("Downloaded content doesn't look like a skill document.", "red"))
        return False

    metadata_content = _download_optional_asset(
        _optional_metadata_filename(
            overlay_name=target.overlay_name,
            dedicated=target.dedicated,
        ),
        download_fn,
    )
    hook_script_content = None
    if interface == "codex_loop95":
        hook_filename = _hook_script_filename(
            interface=interface,
            overlay_name=target.overlay_name,
            dedicated=target.dedicated,
        )
        try:
            hook_script_content = download_fn(hook_filename) if hook_filename else None
        except (urllib.error.URLError, OSError, KeyError) as exc:
            print(colorize_fn(f"Hook asset download failed: {exc}", "red"))
            return False

    new_section = _build_section(skill_content, overlay_content)
    if interface in _FRONTMATTER_FIRST_INTERFACES:
        new_section = _ensure_frontmatter_first(new_section)

    if target.dedicated:
        result = new_section
    elif target_path.is_file():
        existing = target_path.read_text(encoding="utf-8", errors="replace")
        result = _replace_section(existing, new_section)
    else:
        result = new_section

    hook_script_path: Path | None = None
    merged_hooks_json: str | None = None
    updated_codex_config: str | None = None
    codex_hooks_path: Path | None = None
    codex_config_path: Path | None = None
    if interface == "codex_loop95" and hook_script_content is not None:
        codex_root = _codex_config_root(
            scope=resolved_scope,
            get_home_path_fn=get_home_path_fn,
            get_project_root_fn=get_project_root_fn,
        )
        hook_script_path = codex_root / "hooks" / _CODEX_LOOP95_HOOK_SCRIPT
        codex_hooks_path = codex_root / "hooks.json"
        codex_config_path = codex_root / "config.toml"
        try:
            merged_hooks_json = _merge_codex_hooks_json(
                codex_hooks_path.read_text(encoding="utf-8", errors="replace")
                if codex_hooks_path.is_file()
                else None,
                command=_codex_loop95_hook_command(hook_script_path),
            )
            updated_codex_config = _ensure_codex_hooks_enabled(
                codex_config_path.read_text(encoding="utf-8", errors="replace")
                if codex_config_path.is_file()
                else None
            )
        except (CommandError, OSError) as exc:
            print(colorize_fn(str(exc), "red"))
            return False

    target_path.parent.mkdir(parents=True, exist_ok=True)
    safe_write_text_fn(target_path, result)
    if metadata_content is not None:
        metadata_path = target_path.parent / "agents" / "openai.yaml"
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        safe_write_text_fn(metadata_path, metadata_content.rstrip() + "\n")
    if hook_script_path is not None and hook_script_content is not None:
        hook_script_path.parent.mkdir(parents=True, exist_ok=True)
        safe_write_text_fn(hook_script_path, hook_script_content.rstrip() + "\n")
    if codex_hooks_path is not None and merged_hooks_json is not None:
        codex_hooks_path.parent.mkdir(parents=True, exist_ok=True)
        safe_write_text_fn(codex_hooks_path, merged_hooks_json)
    if codex_config_path is not None and updated_codex_config is not None:
        codex_config_path.parent.mkdir(parents=True, exist_ok=True)
        safe_write_text_fn(codex_config_path, updated_codex_config)

    version_match = SKILL_VERSION_RE.search(new_section)
    version = version_match.group(1) if version_match else "?"
    print(
        colorize_fn(
            f"Updated {target.rel_path} (v{version}, tool expects v{SKILL_VERSION})",
            "green",
        )
    )
    if interface == "codex_loop95" and codex_hooks_path is not None and codex_config_path is not None:
        print(colorize_fn(f"Updated {codex_hooks_path}", "green"))
        print(colorize_fn(f"Enabled Codex hooks in {codex_config_path}", "green"))
        print(colorize_fn("Restart Codex to reload the updated hook configuration.", "yellow"))
    if interface in {"codex", "codex_loop95", "claude"} and resolved_scope == "project":
        print(colorize_fn("Wrote the project-scoped compatibility install.", "yellow"))
    return True


def update_installed_skill(interface: str, scope: str | None = "auto") -> bool:
    """Download and install the skill document for the given interface."""
    return _update_installed_skill_with_deps(
        interface,
        scope=resolve_scope(interface, scope),
        download_fn=_download,
        get_home_path_fn=_get_home_path,
        get_project_root_fn=get_project_root,
        safe_write_text_fn=safe_write_text,
        colorize_fn=colorize,
    )


def _run_cmd_update_skill(
    args: argparse.Namespace,
    *,
    resolve_interface_fn,
    update_installed_skill_fn,
    colorize_fn,
    find_installed_skills_fn=None,
) -> None:
    """Run the update-skill command with injectable package seams."""
    if find_installed_skills_fn is None:
        find_installed_skills_fn = find_installed_skills
    explicit_interface = getattr(args, "interface", None)
    requested_scope = getattr(args, "scope", "auto")
    installs = find_installed_skills_fn()
    interface = resolve_interface_fn(explicit_interface, installs=installs)

    if explicit_interface and interface not in SKILL_TARGETS:
        names = ", ".join(sorted(SKILL_TARGETS))
        print(colorize_fn(f"Unknown interface '{interface}'.", "red"))
        print(f"Available: {names}")
        return

    if not explicit_interface:
        interfaces = sorted({install.interface for install in installs if install.interface})
        if len(interfaces) > 1 and interface is None:
            print(colorize_fn("Multiple installed skill documents were detected.", "yellow"))
            _print_detected_installs(installs)
            print()
            print("Run: desloppify update-skill <interface>")
            return
        if interface is None:
            print(colorize_fn("No installed skill document found.", "yellow"))
            print()
            names = ", ".join(sorted(SKILL_TARGETS))
            print(f"Install with: desloppify update-skill <{names}>")
            return

    update_installed_skill_fn(interface, requested_scope)


def cmd_update_skill(args: argparse.Namespace) -> None:
    """Install or update the desloppify skill document."""
    _run_cmd_update_skill(
        args,
        resolve_interface_fn=resolve_interface,
        update_installed_skill_fn=update_installed_skill,
        colorize_fn=colorize,
    )
