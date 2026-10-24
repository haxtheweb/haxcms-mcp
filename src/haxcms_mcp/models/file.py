"""FileRecord, FileCollection and UploadResult models (PLAN Phase 5 T5.1).

Live shapes (API-REF §6; `specs/site-spec.yaml` FileRecord / FileCollection /
createFile response):

* `GET files` -> `{count, total, page, files: [FileRecord], orphans: [FileRecord]}`.
  `orphans` flags records whose disk file is gone (non-destructive: files.json is NOT
  mutated for them) and is present on list responses only.
* `GET files/{uuid}` -> one FileRecord `{path, fullUrl, url, mimetype, name, uuid, size,
  dateCreated, width?, height?}`. `url` is site-relative (`files/<name>`); `width`/`height`
  are pixel dimensions for images and absent for everything else. `uuid` is the stable
  files.json UUID (HAXCMS-FILE-SCHEMA-V1).
* `POST files` -> `{file: {path, fullUrl, url, type, name, size, uuid, width?, height?}}` —
  the upload response names the detected MIME `type` instead of `mimetype`; from_api
  accepts either key.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class FileRecord(BaseModel):
    """One site file (list/get/upload all return this shape, modulo the MIME key)."""

    model_config = ConfigDict(extra="allow")

    path: str = ""
    full_url: str = ""
    url: str = ""
    mimetype: str = ""
    name: str = ""
    uuid: str = ""
    size: int = 0
    date_created: int | None = None
    width: int | None = None
    height: int | None = None

    @classmethod
    def from_api(cls, record: dict[str, Any]) -> FileRecord:
        mimetype = record.get("mimetype") or record.get("type") or ""
        width = record.get("width")
        height = record.get("height")
        date_created = record.get("dateCreated")
        return cls(
            path=str(record.get("path") or ""),
            full_url=str(record.get("fullUrl") or ""),
            url=str(record.get("url") or ""),
            mimetype=str(mimetype),
            name=str(record.get("name") or ""),
            uuid=str(record.get("uuid") or ""),
            size=int(record.get("size") or 0),
            date_created=int(date_created) if date_created is not None else None,
            # images: pixel dimensions; absent OR 0 for non-images (spec: nullable)
            width=int(width) if width else None,
            height=int(height) if height else None,
            **{
                key: value
                for key, value in record.items()
                if key
                not in {
                    "path",
                    "fullUrl",
                    "url",
                    "mimetype",
                    "type",
                    "name",
                    "uuid",
                    "size",
                    "dateCreated",
                    "width",
                    "height",
                }
            },
        )


class FileCollection(BaseModel):
    """The `GET files` envelope: `{count, total, page, files, orphans}`."""

    count: int = 0
    total: int = 0
    page: dict[str, Any] = {}
    files: list[FileRecord] = []
    orphans: list[FileRecord] = []

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> FileCollection:
        def records(key: str) -> list[FileRecord]:
            value = data.get(key)
            return (
                [FileRecord.from_api(entry) for entry in value if isinstance(entry, dict)]
                if isinstance(value, list)
                else []
            )

        page = data.get("page")
        return cls(
            count=int(data.get("count") or 0),
            total=int(data.get("total") or 0),
            page=page if isinstance(page, dict) else {},
            files=records("files"),
            orphans=records("orphans"),
        )


class UploadResult(BaseModel):
    """The `POST files` envelope: `{file: FileRecord}` (MIME arrives as `type`)."""

    file: FileRecord | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> UploadResult:
        record = data.get("file")
        return cls(file=FileRecord.from_api(record) if isinstance(record, dict) else None)
