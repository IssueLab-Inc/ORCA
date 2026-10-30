"""The architecture map (docs/architecture/) names every part of the application, so it can't silently fall behind.

Each test reads the code, lists what the map must mention, and says which doc to add a line to. Fix a failure by
adding the doc line (docs/architecture/README.md, "Keeping these docs current"), never by loosening the test.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "server" / "sightline"
DOCS = ROOT / "docs" / "architecture"
HTTP = {"get", "post", "put", "delete", "patch"}
ENV = re.compile(r"""["'](SIGHTLINE_[A-Z0-9_]+|META_[A-Z0-9_]+|TRIAGE_[A-Z0-9_]+|BASETEN_API_KEY|MODAL_TASK_ID)["']""")
FENCE = re.compile(r"^```.*?^```", re.S | re.M)
LINK = re.compile(r"\]\(([^)\s]+)\)")


def doc(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def topic_docs() -> list[Path]:
    return sorted(p for p in DOCS.glob("[0-9][0-9]-*.md"))


def missing(text: str, names: list[str], pattern) -> list[str]:
    return [n for n in names if not re.search(pattern(n), text)]


def test_the_index_lists_every_doc_and_every_listed_doc_exists():
    index = doc("README.md")
    unlisted = [p.name for p in topic_docs() if f"({p.name})" not in index]
    assert not unlisted, f"docs/architecture/README.md does not link {unlisted}: add them to the index"
    listed = set(re.findall(r"\((\d\d-[\w-]+\.md)\)", index))
    gone = sorted(n for n in listed if not (DOCS / n).exists())
    assert not gone, f"docs/architecture/README.md links {gone}, which do not exist"


def test_every_topic_doc_says_what_it_covers_and_when_to_update_it():
    for p in topic_docs():
        if p.name.startswith("22-"):
            continue  # the build log is history, not a map of the code
        text = p.read_text(encoding="utf-8")
        assert "**Checked against code:**" in text, f"{p.name} has no 'Checked against code' line in its header"
        assert "## When to update this doc" in text, f"{p.name} has no 'When to update this doc' section"


def test_relative_links_resolve():
    broken = []
    for p in [DOCS / "README.md", *topic_docs()]:
        for target in LINK.findall(FENCE.sub("", p.read_text(encoding="utf-8"))):
            if re.match(r"[a-z]+:", target) or target.startswith("#"):
                continue
            path = target.split("#", 1)[0]
            if path and not (p.parent / path).resolve().exists():
                broken.append(f"{p.name} → {target}")
    assert not broken, f"broken links in docs/architecture: {broken}"


def test_the_server_code_map_names_every_module():
    names = sorted(p.name for p in PKG.glob("*.py") if p.name != "__init__.py")
    gone = missing(doc("04-server-code-map.md"), names, lambda n: rf"`(?:[\w./]*/)?{re.escape(n)}`")
    assert not gone, f"04-server-code-map.md does not name {gone}: add each module to the map"


def test_every_prompt_is_in_the_prompt_inventory():
    names = sorted(f"domain_packs/{p.name}" for p in (PKG / "domain_packs").glob("*.md"))
    gone = missing(doc("08-ai-models-prompts-and-spend.md"), names, lambda n: rf"`(?:[\w./]*/)?{re.escape(n)}`")
    assert not gone, f"08-ai-models-prompts-and-spend.md does not list {gone} in its prompt inventory"


def test_every_web_source_file_is_mapped():
    src = ROOT / "web" / "src"
    names = sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file())
    text = doc("12-web-app.md") + doc("13-3d-viewer.md")
    gone = missing(text, names, lambda n: rf"`(?:(?:web/)?src/)?{re.escape(n)}`")
    assert not gone, f"12-web-app.md / 13-3d-viewer.md do not name {gone}: add each file to the map"


def routes() -> list[tuple[str, str]]:
    out = []
    for node in ast.walk(ast.parse((PKG / "app.py").read_text(encoding="utf-8"))):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in node.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and isinstance(d.func.value, ast.Name)
                    and d.func.value.id == "app" and d.func.attr in HTTP | {"websocket"}
                    and d.args and isinstance(d.args[0], ast.Constant)):
                out.append((d.func.attr, d.args[0].value))
    return out


def test_the_api_doc_lists_every_route():
    found = routes()
    assert len(found) > 50, "the route scan found too few routes; has app.py changed shape?"
    lines = doc("10-http-api-and-streams.md").splitlines()
    gone = []
    for method, path in found:
        verb = r"\b(?:WS|WEBSOCKET|WebSocket)\b" if method == "websocket" else rf"\b{method.upper()}\b"
        if not any(f"`{path}`" in line and re.search(verb, line) for line in lines):
            gone.append(f"{method.upper()} {path}")
    assert not gone, f"10-http-api-and-streams.md has no row naming method and path for {gone}"


def test_the_mcp_doc_lists_every_tool():
    tools = []
    for node in ast.walk(ast.parse((PKG / "mcp_server.py").read_text(encoding="utf-8"))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "tool"
                for d in node.decorator_list):
            tools.append(node.name)
    assert len(tools) > 20, "the MCP tool scan found too few tools; has mcp_server.py changed shape?"
    gone = missing(doc("11-mcp-and-agent-links.md"), sorted(tools), lambda n: rf"`{re.escape(n)}`")
    assert not gone, f"11-mcp-and-agent-links.md does not list the MCP tools {gone}"


def test_the_config_doc_names_every_env_var():
    names = set()
    for p in [*PKG.rglob("*.py"), *(ROOT / "deploy").glob("*.py")]:
        names.update(ENV.findall(p.read_text(encoding="utf-8")))
    gone = missing(doc("15-requirements-settings-and-config.md"), sorted(names), lambda n: rf"`{re.escape(n)}`")
    assert not gone, f"15-requirements-settings-and-config.md has no entry for the env vars {gone}"
