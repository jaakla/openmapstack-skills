"""Manifest-bound delivery credits, shared by HTML and QGIS renderers.

Capture one completion instant after the analysis and use it for views and the
run record before hashing. These helpers do not inspect the clock or the user.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

from .project import get_in


def declared(project: dict) -> bool:
    block = project.get("project") or {}
    return isinstance(block, dict) and ("author" in block or "generated_with" in block)


def _http_url(value: object) -> bool:
    if not isinstance(value, str) or any(char.isspace() for char in value):
        return False
    try:
        parsed = urlsplit(value)
        parsed.port  # Reject malformed or out-of-range ports as well as hosts.
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def instant(value: object) -> datetime:
    """Accept an ISO datetime only when it explicitly identifies a UTC offset."""
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("analysis timestamp must include a UTC offset")
    return result


def declaration_errors(project: dict) -> list[str]:
    if not declared(project):
        return []
    block = project.get("project") or {}
    errors = []
    author, toolkit = block.get("author"), block.get("generated_with")
    if not isinstance(author, dict):
        errors.append("project.author must declare name and email")
    else:
        name, email = author.get("name"), author.get("email")
        if not isinstance(name, str) or not name.strip() or re.search(r"\bTODO\b|TODO[-_]", name, re.I):
            errors.append("project.author.name must be nonblank and not a placeholder")
        if not isinstance(email, str) or not re.fullmatch(r"[^\s@<>?&#]+@[^\s@<>?&#]+\.[^\s@<>?&#]+", email):
            errors.append("project.author.email must be an email address")
        if "url" in author and not _http_url(author["url"]):
            errors.append("project.author.url must be an absolute HTTP(S) URL")
    if not isinstance(toolkit, dict) or toolkit.get("tool") != "OpenMapStack" or not _http_url(toolkit.get("url")):
        errors.append("project.generated_with must declare tool: OpenMapStack and an absolute HTTP(S) url")
    return errors


def credit_payload(project: dict, *, completed_at: str | None = None) -> dict:
    """Use the canonical completion time, with a labeled pre-run fallback."""
    errors = declaration_errors(project)
    if not declared(project) or errors:
        raise ValueError("; ".join(errors) or "delivery credits are not declared")
    latest = get_in(project, "runs", "latest")
    fallback = completed_at is None and not latest
    value = completed_at if completed_at is not None else (
        latest.get("completed_at") if latest else get_in(project, "project", "updated_at"))
    timestamp = instant(value).isoformat()
    return {"author": dict(project["project"]["author"]),
            "generated_with": dict(project["project"]["generated_with"]),
            "analysis_at": timestamp, "fallback": fallback}


def html_credits(payload: dict) -> str:
    """Static semantic HTML; labels can be translated, values remain inspectable."""
    esc = html.escape
    author, tool = payload["author"], payload["generated_with"]
    timestamp = payload["analysis_at"]
    fallback = " (project updated time; no canonical run yet)" if payload["fallback"] else ""
    website = (f' · <a data-oms-credit="author-url" href="{esc(author["url"], quote=True)}">Author website</a>'
               if author.get("url") else "")
    return (f'<section data-openmapstack-credits aria-label="Delivery credits">'
            f'<p>Generated with AI using the free <a data-oms-credit="toolkit" href="{esc(tool["url"], quote=True)}">OpenMapStack</a> toolkit.</p>'
            f'<p>Analysis made: <time data-oms-credit="analysis" datetime="{esc(timestamp, quote=True)}">{esc(timestamp)}</time>{fallback}</p>'
            f'<p>Author: <a data-oms-credit="author" href="mailto:{quote(author["email"], safe="@+.-_")}">{esc(author["name"])} ({esc(author["email"])})</a>{website}</p></section>')


def qgis_credits(xml: str, payload: dict) -> str:
    """Add desktop-visible abstract/author/links, retaining other provenance."""
    root = ET.fromstring(xml)
    metadata = root.find("projectMetadata")
    if metadata is None:
        metadata = ET.SubElement(root, "projectMetadata")
    abstract = metadata.find("abstract")
    if abstract is None:
        abstract = ET.SubElement(metadata, "abstract")
    author, toolkit = payload["author"], payload["generated_with"]
    text = ("Generated with AI using the free OpenMapStack toolkit.\n"
            f"Analysis made: {payload['analysis_at']}" +
            (" (project updated time; no canonical run yet)" if payload["fallback"] else "") +
            f"\nAuthor: {author['name']} ({author['email']}).")
    previous = abstract.text or ""
    # Replacing a managed header is idempotent and removes stale timestamps.
    if previous.startswith("Generated with AI using the free OpenMapStack toolkit.\nAnalysis made:"):
        previous = "\n".join(previous.splitlines()[3:]).lstrip()
    abstract.text = text + ("\n" + previous if previous else "")
    field = metadata.find("author")
    if field is None:
        field = ET.SubElement(metadata, "author")
    field.text = f"{author['name']} ({author['email']})"
    links = metadata.find("links")
    if links is None:
        links = ET.SubElement(metadata, "links")
    managed = {"OpenMapStack toolkit", "Author email", "Author website"}
    for link in list(links):
        if link.get("name") in managed:
            links.remove(link)
    values = [("OpenMapStack toolkit", toolkit["url"]), ("Author email", "mailto:" + quote(author["email"], safe="@+.-_"))]
    if author.get("url"):
        values.append(("Author website", author["url"]))
    for name, url in values:
        ET.SubElement(links, "link", name=name, type="WWW:LINK", url=url, description=name, format="", mimeType="")
    return ET.tostring(root, encoding="unicode")


def write_qgis_credits(path: Path, payload: dict) -> None:
    """Update the QGS member while preserving other QGZ members and ZIP dates."""
    if path.suffix.lower() == ".qgs":
        path.write_text(qgis_credits(path.read_text(encoding="utf-8"), payload), encoding="utf-8")
        return
    with zipfile.ZipFile(path) as archive:
        members = [(info, archive.read(info)) for info in archive.infolist()]
    qgs = [info for info, _ in members if info.filename.endswith(".qgs")]
    if len(qgs) != 1:
        raise ValueError("QGZ must contain exactly one QGS member")
    with zipfile.ZipFile(path, "w") as archive:
        for info, data in members:
            if info == qgs[0]:
                data = qgis_credits(data.decode("utf-8"), payload).encode("utf-8")
            archive.writestr(info, data)
