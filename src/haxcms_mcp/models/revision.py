"""Revision models (PLAN Phase 3 T3.1; API-REF §4.8, revisions.js read Phase 3).

`GET items/{idOrSlug}/revisions` -> `data = {nodeId, nodeSlug, nodeTitle, count, total,
page, revisions:[{revisionNumber, hash, shortHash, author, authorEmail, timestamp, date,
message}], links}`. `GET .../revisions/{revisionId}` -> `data = {nodeId, nodeSlug,
nodeTitle, revision:{...same fields...}, content, ...}` where `revisionId` MUST be a
7-64 char git hash (the route rejects anything else) and `content` is the stored page
HTML at that commit.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Revision(BaseModel):
    """One git commit touching a page."""

    revision_number: int = 0
    hash: str = ""
    short_hash: str = ""
    author: str = ""
    author_email: str = ""
    timestamp: int = 0
    date: str = ""
    message: str = ""

    @classmethod
    def from_api(cls, record: dict[str, Any]) -> Revision:
        return cls(
            revision_number=int(record.get("revisionNumber") or 0),
            hash=str(record.get("hash") or ""),
            short_hash=str(record.get("shortHash") or ""),
            author=str(record.get("author") or ""),
            author_email=str(record.get("authorEmail") or ""),
            timestamp=int(record.get("timestamp") or 0),
            date=str(record.get("date") or ""),
            message=str(record.get("message") or ""),
        )


class RevisionDetail(BaseModel):
    """One revision's full detail, including the page `content` at that commit."""

    node_id: str = ""
    node_slug: str = ""
    node_title: str = ""
    revision: Revision = Field(default_factory=Revision)
    content: str = ""

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> RevisionDetail:
        raw_revision = data.get("revision")
        return cls(
            node_id=str(data.get("nodeId") or ""),
            node_slug=str(data.get("nodeSlug") or ""),
            node_title=str(data.get("nodeTitle") or ""),
            revision=Revision.from_api(raw_revision if isinstance(raw_revision, dict) else {}),
            content=str(data.get("content") or ""),
        )
