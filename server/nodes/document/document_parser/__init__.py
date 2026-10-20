"""Document Parser — Wave 11.D.7 inlined.

Dual-purpose since the CartolaTax remediation (2026-10): the node stays a
first-class graph step (fileDownloader chains) and is also invokable as an
AI tool (`document_parser`) for quick text verification. Workspace-relative
paths resolve against the workflow workspace with containment; legacy
absolute-path behaviour is unchanged when no workspace is in context.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.logging import get_logger
from services.plugin import (
    ActionNode,
    NodeContext,
    NodeUserError,
    Operation,
    TaskQueue,
)

logger = get_logger(__name__)


def _workspace_root(ctx: NodeContext) -> Optional[Path]:
    """Workspace directory for this execution, or None when absent.

    Reuses services.media.workspace.workspace_root so the resolution order
    (typed attr, then ctx.raw) stays identical to every other workspace
    consumer; its NodeUserError is downgraded to None because the parser
    still has a legacy no-workspace contract (graph tests, absolute paths).
    """
    if ctx is None:
        return None
    from services.media.workspace import workspace_root

    try:
        return workspace_root(ctx)
    except NodeUserError:
        return None


def _resolve_input_path(ctx: NodeContext, raw: str) -> Path:
    """Resolve an input path against the workflow workspace when one exists.

    Without a workspace in the execution context the legacy behaviour is
    untouched: absolute paths pass through and relative paths resolve
    against the process cwd. With a workspace, every path goes through
    services.media.resolve_media — no ``..`` / ``~`` / symlink escapes
    outside the workspace (the same containment rule as file_read / the
    vision tool).
    """
    if _workspace_root(ctx) is None:
        return Path(raw)
    from services.media.workspace import resolve_media

    return resolve_media(raw, ctx=ctx)


def _parse_file_sync(path: Path, parser: str) -> str:
    """Synchronous file parsing — runs in thread pool."""
    if parser == "pypdf":
        from pypdf import PdfReader

        return "\n\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)
    if parser == "marker":
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict

        converter = PdfConverter(artifact_dict=create_model_dict())
        result = converter(str(path))
        return result.markdown if hasattr(result, "markdown") else str(result)
    if parser == "unstructured":
        from unstructured.partition.auto import partition

        return "\n\n".join(str(el) for el in partition(str(path)))
    if parser == "docx":
        # python-docx reads .docx (Word) — paragraphs and tables in document
        # order via iter_inner_content(). Table rows flatten to one line per
        # row with cells joined by " | ", which keeps row alignment readable
        # in an LLM-facing text block. Empty cells/paragraphs are skipped.
        from docx import Document as _open_docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = _open_docx(str(path))
        lines: list[str] = []
        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                text = block.text.strip()
                if text:
                    lines.append(text)
            elif isinstance(block, Table):
                for row in block.rows:
                    cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                    if any(cells):
                        lines.append(" | ".join(cells))
        return "\n".join(lines)
    if parser == "beautifulsoup":
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(path.read_text(errors="ignore"), "html.parser")
        for s in soup(["script", "style"]):
            s.decompose()
        return soup.get_text(separator="\n")
    raise ValueError(f"Unknown parser: {parser}")


class DocumentParserParams(BaseModel):
    parser: Literal["pypdf", "marker", "unstructured", "docx", "beautifulsoup"] = Field(
        default="pypdf",
        description="Parser backend. pypdf is fast; marker uses GPU OCR; unstructured handles multi-format; docx reads Word files (paragraphs + tables); beautifulsoup for HTML.",
    )
    file_path: str = Field(
        default="",
        description="Single file path (takes precedence over input_dir). Workspace-relative paths resolve inside the workflow workspace.",
    )
    input_dir: str = Field(
        default="",
        description="Directory to scan for files matching file_pattern.",
    )
    file_pattern: str = Field(
        default="*.pdf",
        description="Glob pattern for input_dir scan (e.g. *.pdf, *.html).",
    )

    model_config = ConfigDict(extra="ignore")


class DocumentParserOutput(BaseModel):
    documents: Optional[list] = None
    parsed_count: Optional[int] = None
    failed: Optional[list] = None

    model_config = ConfigDict(extra="allow")


class DocumentParserNode(ActionNode):
    type = "documentParser"
    display_name = "Document Parser"
    subtitle = "Parse to Text"
    group = ("document", "tool")
    description = "Parse documents to text using configurable parsers"
    component_kind = "square"
    tool_name = "document_parser"
    tool_description = (
        "Extract text from a workspace document (PDF, HTML, DOCX, ...). "
        "Pass a workspace-relative file_path (e.g. "
        "'attachments/cartola.pdf') or input_dir + file_pattern. Returns "
        "the WHOLE document as ONE text block — no per-page split and NO "
        "OCR: scanned/image-only pages yield empty text (length 0), so "
        "check lengths before trusting the content. Use for quick text "
        "verification; page-level indexing belongs to shell tools."
    )
    handles = (
        {"name": "input-main", "kind": "input", "position": "left", "label": "Input", "role": "main"},
        {"name": "output-main", "kind": "output", "position": "right", "label": "Output", "role": "main"},
    )
    annotations = {"destructive": False, "readonly": True, "open_world": False}
    task_queue = TaskQueue.DEFAULT
    usable_as_tool = True
    # usable_as_tool auto-hides the canvas handles; this node must stay
    # wirable on the canvas (fileDownloader chains) as well as callable
    # as a tool — same opt-out as tikhubAction.
    hide_input_handle = False
    hide_output_handle = False

    Params = DocumentParserParams
    Output = DocumentParserOutput

    @Operation("parse")
    async def parse(self, ctx: NodeContext, params: DocumentParserParams) -> DocumentParserOutput:
        parser = params.parser
        explicit_path = params.file_path
        input_dir = params.input_dir
        file_pattern = params.file_pattern or "*.pdf"

        paths: list[Path] = []
        if explicit_path:
            paths.append(_resolve_input_path(ctx, explicit_path))
        if input_dir:
            resolved_dir = _resolve_input_path(ctx, input_dir)
            if resolved_dir.exists():
                paths.extend(resolved_dir.glob(file_pattern))

        if not paths:
            return DocumentParserOutput(documents=[], parsed_count=0, failed=[])

        documents, failed = [], []
        for path in paths:
            try:
                content = await asyncio.to_thread(_parse_file_sync, path, parser)
                documents.append(
                    {
                        "source": str(path),
                        "filename": path.name,
                        "content": content,
                        "length": len(content),
                        "parser": parser,
                    }
                )
            except Exception as e:
                failed.append({"file": str(path), "error": str(e)})

        return DocumentParserOutput(
            documents=documents,
            parsed_count=len(documents),
            failed=failed,
        )
