"""Declared delivery identity and actual HTML/QGIS credit values.

No network is used: links must be structurally valid and match the manifest;
remote endpoint availability and natural-language translation are not certified.
"""
from __future__ import annotations

from decimal import Decimal
import re
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

from . import AssertionResult, failed, load_project_yaml, passed, project_root, warning, not_testable
from .. import credits
from ..delivery import targets
from ..project import get_in, project_path


def declaration_valid(workspace: Path, project_dir: str = ".") -> AssertionResult:
    project = load_project_yaml(workspace, project_dir)
    if project is None:
        return failed("project.yaml missing", code="manifest_missing")
    if not isinstance(project.get("project"), dict):
        return failed("project metadata must be an object", code="credits_declaration_invalid")
    if not credits.declared(project):
        return warning("legacy v1 project has neither author nor generated_with; add both before new delivery",
                       code="credits_legacy_missing")
    errors = credits.declaration_errors(project)
    if errors:
        return failed("; ".join(errors), code="credits_declaration_invalid")
    try:
        credits.credit_payload(project)
    except (ValueError, TypeError, AttributeError) as exc:
        return failed(str(exc), code="credits_declaration_invalid")
    return passed("delivery author and toolkit metadata are complete")


def _surfaces(root: Path, project: dict) -> dict[str, str]:
    selected = targets(project)
    if selected:
        surfaces = {project["outputs"][target["output"]]["path"]: target["kind"] for target in selected}
        for view in project.get("views") or []:
            if isinstance(view, dict):
                surfaces[project["outputs"][view["output"]]["path"]] = "dashboard"
        return surfaces
    surfaces = {}
    for output in (project.get("outputs") or {}).values():
        path = output.get("path", "") if isinstance(output, dict) else ""
        suffix = Path(path).suffix.lower()
        if suffix in {".html", ".qgz", ".qgs"}:
            surfaces[path] = "qgis" if suffix != ".html" else "dashboard"
    if get_in(project, "presentation", "dashboard") is not None:
        surfaces.setdefault("dashboard.html", "dashboard")
    if (root / "project.qgz").is_file():
        surfaces.setdefault("project.qgz", "qgis")
    return surfaces


class _HTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.nodes = []
        self.text_parts = []

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "text": "", "own_text": "", "parents": list(self.stack)}
        self.nodes.append(node)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if any(node["tag"] in {"script", "style", "template"} for node in self.stack):
            return
        for node in self.stack:
            node["text"] += data
        if self.stack:
            self.stack[-1]["own_text"] += data
            self.text_parts.append((self.stack[-1], data))


class _AmbiguousStyle(Exception):
    """Inline CSS outside the deliberately small static visibility contract."""


def _inline_hidden(style: str) -> bool:
    """Recognize simple declarations only; leave CSS interpretation to Chromium."""
    if not style:
        return False
    if re.search(r"[\"'()/{}\\]|--", style):
        raise _AmbiguousStyle("comments, strings, functions or custom properties")
    seen, hidden = set(), False
    for declaration in style.split(";"):
        if not declaration.strip():
            continue
        match = re.fullmatch(r"\s*([a-zA-Z][\w-]*)\s*:\s*([^:;!]+?)(?:\s*!\s*important)?\s*", declaration, re.I)
        if not match:
            raise _AmbiguousStyle("not a simple declaration list")
        name, value = match[1].lower(), match[2].strip().lower()
        if name in seen:
            raise _AmbiguousStyle("repeated declaration: " + name)
        seen.add(name)
        if name == "opacity":
            if not re.fullmatch(r"[+-]?(?:\d*\.\d+|\d+)", value) or Decimal(value) < 0:
                raise _AmbiguousStyle("opacity requires a simple nonnegative number")
            hidden |= Decimal(value) == 0
        elif name in {"display", "visibility"}:
            allowed = ({"none", "block", "inline", "inline-block", "flex", "grid", "contents"}
                       if name == "display" else {"visible", "hidden", "collapse"})
            if value not in allowed:
                raise _AmbiguousStyle("unsupported " + name + " value")
            hidden |= value in {"none", "hidden", "collapse"}
    return hidden


def _reachable_panel(node: dict, nodes: list[dict], visiting: tuple[int, ...]) -> bool:
    """A hidden panel needs an unambiguous, visible and enabled tab control.

    Static associations do not prove that its handler works; browser QA does.
    Cycles and a control inside its own hidden panel cannot establish access.
    """
    attrs = node["attrs"]
    panel_id = attrs.get("id")
    if not panel_id or sum(n["attrs"].get("id") == panel_id for n in nodes) != 1:
        return False
    labels = attrs.get("aria-labelledby", "").split()
    for tab in nodes:
        values = tab["attrs"]
        tab_id = values.get("id")
        if (values.get("role") != "tab" or not tab_id or tab_id not in labels
                or panel_id not in values.get("aria-controls", "").split()
                or sum(n["attrs"].get("id") == tab_id for n in nodes) != 1
                or any(parent is node for parent in tab["parents"])
                or (tab["tag"] == "input" and values.get("type", "").lower() == "hidden")
                or "disabled" in values or values.get("aria-disabled") == "true"
                or any("disabled" in parent["attrs"] and parent["tag"] == "fieldset"
                       or parent["attrs"].get("aria-disabled") == "true" for parent in tab["parents"])
                or values.get("aria-selected", "false") != "false"):
            continue
        label_ids = values.get("aria-labelledby", "").split()
        descendants = [n for n in nodes if n is tab or any(parent is tab for parent in n["parents"])]
        # Implicit names use rendered content, not text/alt hidden inside the
        # control. Explicit aria-labelledby references may name hidden nodes.
        visible_content = [n for n in descendants if not _hidden(n, nodes, visiting)]
        named = (any(n["own_text"].strip() or (n is not tab and n["attrs"].get("alt", "").strip()) for n in visible_content)
                 or values.get("aria-label", "").strip()
                 or any(n["attrs"].get("id") in label_ids and n["text"].strip() for n in nodes)
                 )
        if not named:
            continue
        if not _hidden(tab, nodes, visiting):
            return True
    return False


def _hidden(node: dict, nodes: list[dict], visiting: tuple[int, ...] = ()) -> bool:
    if id(node) in visiting:
        return True
    visiting = (*visiting, id(node))
    for ancestor in [node, *node["parents"]]:
        attrs = ancestor["attrs"]
        if ancestor["tag"] in {"script", "style", "template", "noscript"}:
            return True
        if "inert" in attrs:
            return True
        inline_hidden = _inline_hidden(attrs.get("style") or "")
        if "hidden" in attrs or attrs.get("aria-hidden") == "true" or inline_hidden:
            if attrs.get("role") != "tabpanel" or not _reachable_panel(ancestor, nodes, visiting):
                return True
    return False


def _visible_text(node: dict, parser: _HTML) -> str:
    # Preserve document order, including text on both sides of nested markup.
    return "".join(text for owner, text in parser.text_parts
                   if (owner is node or any(parent is node for parent in owner["parents"]))
                   and not _hidden(owner, parser.nodes))


def _html_errors(path: Path, expected: dict) -> list[str]:
    parser = _HTML()
    parser.feed(path.read_text(encoding="utf-8"))
    blocks = [node for node in parser.nodes if "data-openmapstack-credits" in node["attrs"]]
    if len(blocks) != 1:
        return ["view must expose exactly one non-hidden credits block"]
    block = blocks[0]
    # Even empty descendants can affect layout; unsupported styles never earn
    # a static visibility pass merely because they contain no text.
    for node in parser.nodes:
        if node is block or any(parent is block for parent in node["parents"]):
            _inline_hidden(node["attrs"].get("style") or "")
    if _hidden(block, parser.nodes):
        return ["view must expose exactly one non-hidden credits block"]
    errors = []
    def field(role):
        values = [node for node in parser.nodes if node["attrs"].get("data-oms-credit") == role and any(parent is block for parent in node["parents"])]
        return values[0] if len(values) == 1 and not _hidden(values[0], parser.nodes) else None

    author, toolkit = expected["author"], expected["generated_with"]
    block_text = _visible_text(block, parser)
    normalize = lambda text: " ".join(text.split())
    for role, href, labels in [
        ("toolkit", toolkit["url"], [toolkit["tool"], toolkit["tool"] + " toolkit"]),
        ("author", "mailto:" + quote(author["email"], safe="@+.-_"),
         [author["name"], f"{author['name']} ({author['email']})"]),
    ]:
        node = field(role)
        if node is None or node["tag"] != "a" or node["attrs"].get("href") != href or normalize(_visible_text(node, parser)) not in [normalize(label) for label in labels]:
            errors.append(f"{role} credit or link differs from the manifest")
    if author["email"] not in block_text:
        errors.append("author email missing from visible credits")
    if author.get("url"):
        node = field("author-url")
        if node is None or node["tag"] != "a" or node["attrs"].get("href") != author["url"] or not _visible_text(node, parser).strip():
            errors.append("author website credit/link differs from the manifest")
    node = field("analysis")
    try:
        if node is None or node["tag"] != "time" or credits.instant(node["attrs"].get("datetime")) != credits.instant(expected["analysis_at"]) or credits.instant(_visible_text(node, parser).strip()) != credits.instant(expected["analysis_at"]):
            raise ValueError("stale timestamp")
    except (TypeError, ValueError):
        errors.append("visible analysis timestamp/offset differs from the canonical completion time")
    clock_source = node["attrs"].get("data-oms-clock-source") if node else None
    expected_source = "project.updated_at" if expected["fallback"] else "runs.latest.completed_at"
    # Old helper output had only an English fallback label. New renderers bind
    # the source independently so labels, including that explanation, translate.
    if (clock_source != expected_source if clock_source is not None else
            ("no canonical run yet" in block_text) != expected["fallback"]):
        errors.append("pre-run timestamp fallback label differs")
    return errors


def _qgis_errors(path: Path, expected: dict) -> list[str]:
    if path.suffix.lower() == ".qgz":
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.endswith(".qgs")]
            if len(names) != 1:
                return ["QGZ must contain exactly one QGS member"]
            root = ET.fromstring(archive.read(names[0]))
    else:
        root = ET.fromstring(path.read_bytes())
    nodes = root.findall("projectMetadata")
    if len(nodes) != 1:
        return ["QGIS must expose one desktop-visible metadata block"]
    node = nodes[0]
    # Three leading logical credit lines, followed by unrestricted provenance.
    # Labels translate; the identity, ISO instant and field-name source do not.
    header = node.findtext("abstract", "").splitlines()[:3]
    author, toolkit = expected["author"], expected["generated_with"]
    errors = []
    if not header or toolkit["tool"] not in header[0]:
        errors.append("QGIS toolkit identity missing from the credit header")
    author_value = f"{author['name']} ({author['email']})"
    if author_value != node.findtext("author", ""):
        errors.append("QGIS author differs from the manifest")
    # The translated label is free; the entire author value must match in both
    # the abstract header and native field. Provenance elsewhere cannot supply it.
    if len(header) < 3 or not re.fullmatch(r"(?:[^\n]+?:\s*)?" + re.escape(author_value) + r"\.?", header[2].strip()):
        errors.append("QGIS credit header author differs from the manifest")
    times = re.findall(r"(?<![\w])\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})(?![\w:+-])", header[1] if len(header) > 1 else "")
    try:
        if len(times) != 1 or credits.instant(times[0]) != credits.instant(expected["analysis_at"]):
            raise ValueError("stale timestamp")
    except ValueError:
        errors.append("QGIS analysis timestamp/offset differs from the canonical completion time")
    header_text = "\n".join(header)
    sources = re.findall(r"\[clock:([^\]]*)\]", header_text)
    expected_source = "project.updated_at" if expected["fallback"] else "runs.latest.completed_at"
    if (sources != [expected_source] if "[clock:" in header_text else
            ("no canonical run yet" in header_text) != expected["fallback"]):
        errors.append("QGIS pre-run timestamp fallback label differs")
    urls = [link.get("url") for link in node.findall("links/link")]
    for url in [toolkit["url"], "mailto:" + quote(author["email"], safe="@+.-_"), *([author["url"]] if author.get("url") else [])]:
        if url not in urls:
            errors.append(f"QGIS credit link missing: {url}")
    return errors


def rendered_matches(workspace: Path, project_dir: str = ".") -> AssertionResult:
    """Check selected views, or known legacy view paths; never fetch remote links."""
    declaration = declaration_valid(workspace, project_dir)
    if declaration.status != "passed":
        return declaration
    root = project_root(workspace, project_dir)
    project = load_project_yaml(workspace, project_dir)
    try:
        expected = credits.credit_payload(project)
        surfaces = _surfaces(root, project)
    except (ValueError, TypeError, KeyError) as exc:
        return failed(str(exc), code="credits_declaration_invalid")
    errors, uncertain = [], []
    for relative, kind in surfaces.items():
        path = project_path(root, relative)
        if path is None or not path.is_file():
            errors.append(f"{relative}: delivery view is missing or unsafe")
            continue
        try:
            problems = _qgis_errors(path, expected) if kind == "qgis" else _html_errors(path, expected)
        except _AmbiguousStyle as exc:
            uncertain.append(f"{relative}: {exc}")
            continue
        except (OSError, UnicodeError, ValueError, ET.ParseError, zipfile.BadZipFile) as exc:
            problems = [f"cannot inspect credits: {exc}"]
        errors.extend(f"{relative}: {problem}" for problem in problems)
    if errors:
        return failed("; ".join(errors), code="credits_rendered_mismatch", errors=errors)
    if uncertain:
        return not_testable("ambiguous inline credits visibility; run visual.credits_visible_in_browser: "
                            + "; ".join(uncertain), code="credits_visibility_ambiguous", surfaces=list(surfaces))
    return passed(f"credits match in {len(surfaces)} delivery surface(s)", surfaces=list(surfaces))
