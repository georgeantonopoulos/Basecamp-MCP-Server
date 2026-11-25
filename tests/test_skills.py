"""Bundled workflow skills: valid folders, served over the MCP skills extension."""

import asyncio
import hashlib
import re
import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport
from fastmcp.skills.client import SkillsClientExtension

import basecamp_fastmcp
import basecamp_retrieval_mcp

SKILLS_DIR = basecamp_fastmcp.SKILLS_DIR
SKILL_FOLDERS = sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))
# Fields of Basecamp responses that skills tell the model to use.
RESPONSE_FIELDS = {"app_url"}
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RETRIEVAL_TOOLS = {
    "list_basecamp_categories",
    "discover_basecamp_tools",
    "call_basecamp_read_tool",
    "call_basecamp_write_tool",
}


def _frontmatter(text):
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, "SKILL.md must start with YAML frontmatter"
    return dict(line.split(": ", 1) for line in match.group(1).splitlines() if ": " in line)


def _skill_uris(skills):
    return sorted(str(skill.uri) for skill in skills)


def test_skills_folder_ships_some_skills():
    assert SKILL_FOLDERS, f"no skills in {SKILLS_DIR}"


@pytest.mark.parametrize("folder", SKILL_FOLDERS, ids=lambda p: p.name)
def test_every_skill_folder_is_valid(folder):
    skill_md = folder / "SKILL.md"
    assert skill_md.is_file()
    meta = _frontmatter(skill_md.read_text())
    assert meta.get("name") == folder.name, "frontmatter name must equal the folder name"
    assert NAME.match(folder.name)
    assert 20 <= len(meta.get("description", "")) <= 1024
    # Claude Code's limits: 100 KB per text file, 400 KB per skill.
    sizes = [f.stat().st_size for f in folder.rglob("*") if f.is_file()]
    assert max(sizes) <= 100_000 and sum(sizes) <= 400_000


@pytest.mark.parametrize("folder", SKILL_FOLDERS, ids=lambda p: p.name)
def test_skills_only_name_operations_that_exist(folder):
    """A renamed or removed tool must not leave a skill pointing at nothing."""
    tools = basecamp_fastmcp.registered_tools()
    arguments = {arg for tool in tools.values() for arg in tool.parameters.get("properties", {})}
    known = set(tools) | RETRIEVAL_TOOLS | arguments | RESPONSE_FIELDS
    skill_names = {p.name for p in SKILL_FOLDERS}
    text = (folder / "SKILL.md").read_text()
    named = set(re.findall(r"`([a-z]+_[a-z_]+)`", text))
    categories = set(basecamp_retrieval_mcp.CATEGORY_BY_NAME)
    unknown = sorted(named - known - categories - skill_names)
    assert not unknown, f"{folder.name} names operations that are not registered: {unknown}"


@pytest.mark.parametrize(
    "server",
    [basecamp_retrieval_mcp.retrieval_mcp, basecamp_fastmcp.mcp],
    ids=["retrieval", "full"],
)
def test_servers_list_and_serve_every_skill(server):
    async def exercise():
        async with Client(server, extensions=[SkillsClientExtension()]) as client:
            listed = await client.list_skills()
            read = {str(s.uri): await client.read_skill(str(s.uri)) for s in listed}
            tools = await client.list_tools()
            return listed, read, tools

    listed, read, tools = asyncio.run(exercise())
    assert _skill_uris(listed) == [f"skill://{p.name}/SKILL.md" for p in SKILL_FOLDERS]
    for skill in listed:
        name = str(skill.uri).split("/")[2]
        body = (SKILLS_DIR / name / "SKILL.md").read_bytes()
        (entry,) = skill.resources
        assert entry.digest == "sha256:" + hashlib.sha256(body).hexdigest()
        assert entry.size == len(body)
        assert read[str(skill.uri)] is not None
    # Skills add no tools: the retrieval server still advertises only its four.
    if server is basecamp_retrieval_mcp.retrieval_mcp:
        assert {t.name for t in tools} == RETRIEVAL_TOOLS


def test_stdio_server_negotiates_skills_protocol():
    """The real entry point speaks the protocol revision Claude Code needs for skills."""
    project_root = Path(__file__).resolve().parents[1]

    async def exercise():
        transport = PythonStdioTransport(
            script_path=str(project_root / "basecamp_retrieval_mcp.py"),
            python_cmd=sys.executable,
            cwd=str(project_root),
        )
        async with Client(transport, extensions=[SkillsClientExtension()], timeout=30) as client:
            return client.protocol_version, _skill_uris(await client.list_skills())

    version, uris = asyncio.run(exercise())
    assert version == "2026-07-28"
    assert uris == [f"skill://{p.name}/SKILL.md" for p in SKILL_FOLDERS]
