"""本地上传文件落盘（V1：`storage/` 目录）。"""

import os
import re
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.errors import ApiError, ErrorCode

STORAGE_ROOT = Path(os.getenv("STORAGE_ROOT", "storage")).resolve()
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))

EXT_TO_FILE_TYPE: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
    ".md": "markdown",
    ".markdown": "markdown",
}

FILE_TYPE_TO_EXT: dict[str, str] = {
    "pdf": ".pdf",
    "docx": ".docx",
    "txt": ".txt",
    "markdown": ".md",
}


def _safe_filename(name: str) -> str:
    base = Path(name or "").name
    if not base or base in (".", ".."):
        return "upload"
    base = re.sub(r"[^a-zA-Z0-9._\-]", "_", base)
    return base[:200] if len(base) > 200 else base


def infer_file_type(filename: str) -> str | None:
    suf = Path(filename).suffix.lower()
    return EXT_TO_FILE_TYPE.get(suf)


async def save_job_upload(job_id: str, upload: UploadFile) -> tuple[str, str, str]:
    """校验并保存上传文件。

    Returns:
        (storage_path, file_name, file_type) — storage_path 相对 STORAGE_ROOT，POSIX 风格。
    """
    raw_name = upload.filename or ""
    if not raw_name.strip():
        raise ApiError(ErrorCode.VALIDATION_ERROR, "filename is required", status_code=400)

    file_type = infer_file_type(raw_name)
    if file_type is None:
        raise ApiError(
            ErrorCode.UNSUPPORTED_FILE_TYPE,
            "unsupported file type; allowed: .pdf, .docx, .txt, .md, .markdown",
            status_code=415,
        )

    display_name = _safe_filename(raw_name)
    ext = FILE_TYPE_TO_EXT[file_type]
    rel_dir = Path("uploads") / job_id
    dest_dir = STORAGE_ROOT / rel_dir
    dest_dir.mkdir(parents=True, exist_ok=True)

    stored_name = f"{uuid4().hex}{ext}"
    rel_path = rel_dir / stored_name
    full_path = STORAGE_ROOT / rel_path

    size = 0
    chunk_size = 1024 * 1024
    try:
        with open(full_path, "wb") as out:
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    full_path.unlink(missing_ok=True)
                    raise ApiError(
                        ErrorCode.FILE_TOO_LARGE,
                        f"file too large; max {MAX_UPLOAD_BYTES} bytes",
                        status_code=413,
                    )
                out.write(chunk)
    except ApiError:
        raise
    except OSError as exc:
        full_path.unlink(missing_ok=True)
        raise ApiError(
            ErrorCode.INTERNAL_ERROR,
            f"failed to save file: {exc}",
            status_code=500,
        ) from exc

    return (str(rel_path).replace("\\", "/"), display_name, file_type)


def absolute_path(storage_path: str | None) -> Path | None:
    """将库中相对路径解析为绝对路径；无效或空返回 None。"""
    if not storage_path:
        return None
    p = (STORAGE_ROOT / storage_path).resolve()
    try:
        p.relative_to(STORAGE_ROOT)
    except ValueError:
        return None
    return p
