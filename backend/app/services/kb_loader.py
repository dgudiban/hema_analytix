"""Load knowledge-base markdown files into retrieval chunks.

Chunk format: sections starting with `## id: <chunk-id>`, followed by
`## title:`, `## biomarker_id:` / `## category:` metadata lines. All other
lines form the chunk text.
"""
from dataclasses import dataclass
from pathlib import Path

from app.utils.paths import project_root

KNOWLEDGE_DIR = project_root() / "data" / "knowledge"


@dataclass
class Chunk:
    id: str
    title: str
    text: str
    biomarker_id: str | None = None
    category: str | None = None


def _parse_file(path: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    current: dict | None = None
    body: list[str] = []

    def flush():
        if current and current.get("id"):
            chunks.append(
                Chunk(
                    id=current["id"],
                    title=current.get("title", current["id"]),
                    text="\n".join(body).strip(),
                    biomarker_id=current.get("biomarker_id"),
                    category=current.get("category"),
                )
            )

    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line.startswith("## id:"):
            flush()
            current, body = {"id": line.split("## id:", 1)[1].strip()}, []
        elif line.startswith("## ") and current is not None:
            key, _, value = line[3:].partition(":")
            current[key.strip()] = value.strip()
        elif current is not None and line:
            body.append(line)
    flush()
    return chunks


def load_chunks() -> list[Chunk]:
    """Load every chunk from every .md file in data/knowledge/."""
    chunks: list[Chunk] = []
    if not KNOWLEDGE_DIR.is_dir():
        return chunks
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        chunks.extend(_parse_file(path))
    return chunks
