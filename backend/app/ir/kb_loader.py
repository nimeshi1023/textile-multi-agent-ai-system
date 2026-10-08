"""
Knowledge-base loader: reads the SOP .txt files and parses them into documents.

The files in knowledge_base/docs/ are maintained by hand and are only READ here.
A single file can contain several documents; each starts with a "Document ID:" line:

    Document ID: KB013
    Category: Quality Control
    Title: Quality Rework SOP - Fabric Defects
    Tags: quality, rework, fabric defect
    ------------------------------------------------------------
    <body text>
    ------------------------------------------------------------
"""
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional


DOCS_DIR = Path(__file__).resolve().parents[1] / "knowledge_base" / "docs"

# Bodies longer than this are split on paragraph boundaries (none are today)
MAX_CHUNK_CHARS = 1500

REQUIRED_FIELDS = ["document_id", "category", "title"]

_DOC_START = re.compile(r"(?m)^(?=Document ID:)")
_DASH_LINE = re.compile(r"^\s*-{3,}\s*$")
_FIELD = re.compile(r"^(Document ID|Category|Title|Tags):\s*(.*)$")
_FIELD_NAMES = {"Document ID": "document_id", "Category": "category", "Title": "title", "Tags": "tags"}


class KnowledgeBaseError(ValueError):
    pass


def parse_text(text: str, source_file: str) -> List[Dict]:
    """Parse one file's text into documents (one per "Document ID:" block)."""
    documents = []
    for block in _DOC_START.split(text):
        if not block.strip().startswith("Document ID:"):
            continue  # text before the first document (none in the current files)
        doc = {"document_id": "", "category": "", "title": "", "tags": [], "source_file": source_file}
        lines = block.splitlines()
        body_start = len(lines)
        for i, line in enumerate(lines):
            if _DASH_LINE.match(line):
                body_start = i + 1      # body = everything after the first dash line
                break
            match = _FIELD.match(line.strip())
            if match:
                key, value = _FIELD_NAMES[match.group(1)], match.group(2).strip()
                doc[key] = [t.strip() for t in value.split(",") if t.strip()] if key == "tags" else value

        body_lines = [ln.rstrip() for ln in lines[body_start:] if not _DASH_LINE.match(ln)]
        body = re.sub(r"\n{3,}", "\n\n", "\n".join(body_lines)).strip()
        doc["body"] = body
        documents.append(doc)
    return documents


def split_long_body(doc: Dict) -> List[Dict]:
    """One document = one chunk, unless the body is very long (then split on paragraphs)."""
    if len(doc["body"]) <= MAX_CHUNK_CHARS:
        return [{**doc, "chunk_index": 0}]
    chunks, current = [], ""
    for paragraph in doc["body"].split("\n\n"):
        if current and len(current) + len(paragraph) > MAX_CHUNK_CHARS:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}".strip()
    chunks.append(current)
    return [{**doc, "body": chunk, "chunk_index": i} for i, chunk in enumerate(chunks)]


def validate(documents: List[Dict]) -> None:
    problems = []
    seen: Dict[str, str] = {}
    for doc in documents:
        label = doc.get("document_id") or f"(no ID) in {doc['source_file']}"
        for field in REQUIRED_FIELDS:
            if not doc.get(field):
                problems.append(f"{label}: missing '{field}'")
        if not doc.get("body"):
            problems.append(f"{label}: empty body")
        doc_id = doc.get("document_id")
        if doc_id:
            if doc_id in seen:
                problems.append(f"{doc_id}: duplicate ID in {seen[doc_id]} and {doc['source_file']}")
            else:
                seen[doc_id] = doc["source_file"]
    if problems:
        raise KnowledgeBaseError("Knowledge base problems:\n  - " + "\n  - ".join(problems))


def load_documents(docs_dir: Optional[Path] = None) -> List[Dict]:
    """Read every .txt file (UTF-8, read-only), parse, validate, chunk."""
    docs_dir = Path(docs_dir or DOCS_DIR)
    files = sorted(docs_dir.glob("*.txt")) if docs_dir.is_dir() else []
    if not files:
        raise KnowledgeBaseError(f"No knowledge-base .txt files found in {docs_dir}")
    documents = []
    for path in files:
        documents.extend(parse_text(path.read_text(encoding="utf-8"), path.name))
    validate(documents)
    chunks = []
    for doc in sorted(documents, key=lambda d: d["document_id"]):
        chunks.extend(split_long_body(doc))
    return chunks


def embedding_text(doc: Dict) -> str:
    """Text that is embedded/indexed: title and tags help matching."""
    return f"{doc['title']}. {doc['category']}. Tags: {', '.join(doc['tags'])}. {doc['body']}"


def chunk_id(doc: Dict) -> str:
    return doc["document_id"] if doc.get("chunk_index", 0) == 0 else f"{doc['document_id']}#{doc['chunk_index']}"


def docs_fingerprint(docs_dir: Optional[Path] = None) -> Dict[str, str]:
    """SHA-256 of each knowledge-base file (used to prove the files are never modified)."""
    docs_dir = Path(docs_dir or DOCS_DIR)
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(docs_dir.glob("*.txt"))}


if __name__ == "__main__":
    docs = load_documents()
    print(f"Parsed {len(docs)} documents from {DOCS_DIR}")
    for d in docs:
        print(f"  {chunk_id(d):<7} {d['category']:<24} {d['title']:<55} {len(d['body'])} chars  [{d['source_file']}]")
