"""
Shared project storage management for OpenShorts and future project types.

This module deliberately contains no Shorts-specific processing logic.
Story Lab can reuse the same service for source/temporary-file management.
"""

import glob
import json
import os
import re
import shutil
from typing import Dict, List, Optional


# Files that represent resumable/in-progress processing state.
_STATE_FILES = {
    ".resume.json",
    ".transcript_checkpoint.json",
}

# Clearly temporary/intermediate artifacts.
_TEMP_PREFIXES = (
    "temp_",
    "autosubs_",
)

# Derived video prefixes are NOT automatically deleted because one of them
# may currently be the canonical/active version of a clip.
_DERIVED_PREFIXES = (
    "subtitled_",
    "hooked_",
    "hook_",
    "recut_",
)


def _safe_under(base_dir: str, relative: str) -> Optional[str]:
    """Resolve a relative path under base_dir, rejecting path traversal."""
    base = os.path.realpath(base_dir)
    target = os.path.realpath(os.path.join(base, relative))
    if target == base or target.startswith(base + os.sep):
        return target
    return None


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            total += _file_size(os.path.join(root, name))
    return total


def locate_source(
    job_id: str,
    upload_dir: str,
    output_dir: str,
) -> Optional[str]:
    """
    Locate the original source video for a project.

    Upload jobs:
        uploads/{job_id}_*

    URL/download jobs:
        output/{job_id}/{source_video from metadata}
    """
    matches = [
        path
        for path in glob.glob(
            os.path.join(upload_dir, f"{glob.escape(job_id)}_*")
        )
        if os.path.isfile(path)
        and not os.path.basename(path).startswith("thumb_")
    ]

    if matches:
        # A project should normally have one source upload. If there are
        # multiple matches, use the oldest stable match rather than guessing
        # based on filename content.
        return sorted(matches, key=os.path.getmtime)[0]

    job_dir = _safe_under(output_dir, job_id)
    if not job_dir or not os.path.isdir(job_dir):
        return None

    try:
        metadata_files = glob.glob(
            os.path.join(job_dir, "*_metadata.json")
        )
        for metadata_path in metadata_files:
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            source_name = metadata.get("source_video")
            if not source_name:
                continue

            candidate = _safe_under(job_dir, os.path.basename(source_name))
            if candidate and os.path.isfile(candidate):
                return candidate
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass

    return None


def _canonical_clip_names(
    job_dir: str,
    metadata_path: str,
) -> set:
    """
    Return files that must be preserved because they are canonical/active
    generated clips.

    Uses the same naming convention as OpenShorts' _canonical_clip_file(),
    including derived caption/hook/recut chains.
    """
    protected = set()

    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return protected

    shorts = metadata.get("shorts") or []

    base_name = os.path.basename(metadata_path).replace(
        "_metadata.json", ""
    )

    for index in range(len(shorts)):
        clean = f"{base_name}_clip_{index + 1}.mp4"

        # The clean clip itself is always protected.
        clean_path = os.path.join(job_dir, clean)
        if os.path.isfile(clean_path):
            protected.add(os.path.realpath(clean_path))

        # Match the same derived families used by _canonical_clip_file().
        patterns = (
            f"subtitled_*_{clean}",
            f"recut_*_{clean}",
            f"hooked_*_{clean}",
            f"hook_{clean}",
        )

        derived = []
        for pattern in patterns:
            derived.extend(glob.glob(os.path.join(job_dir, pattern)))

        if derived:
            newest = max(derived, key=os.path.getmtime)
            if os.path.isfile(newest):
                protected.add(os.path.realpath(newest))

    return protected


def inspect_project(
    job_id: str,
    upload_dir: str,
    output_dir: str,
) -> Dict:
    """Return a storage inventory without deleting anything."""
    job_dir = _safe_under(output_dir, job_id)

    if not job_dir or not os.path.isdir(job_dir):
        raise FileNotFoundError(f"Project not found: {job_id}")

    source = locate_source(job_id, upload_dir, output_dir)

    metadata_files = glob.glob(
        os.path.join(job_dir, "*_metadata.json")
    )

    protected = set()
    for metadata_path in metadata_files:
        protected.update(
            _canonical_clip_names(job_dir, metadata_path)
        )

    source_real = os.path.realpath(source) if source else None

    temporary = []
    derived = []
    preserved = []

    for root, _dirs, files in os.walk(job_dir):
        for filename in files:
            path = os.path.join(root, filename)
            real = os.path.realpath(path)
            size = _file_size(path)

            if source_real and real == source_real:
                continue

            if filename in _STATE_FILES:
                temporary.append((path, size, "state"))

            elif filename.startswith(_TEMP_PREFIXES):
                temporary.append((path, size, "temporary"))

            elif filename.startswith(_DERIVED_PREFIXES):
                if real in protected:
                    preserved.append((path, size, "active-derived"))
                else:
                    derived.append((path, size, "old-derived"))

            elif filename.endswith(".layout.json"):
                preserved.append((path, size, "layout"))

            elif filename.endswith("_metadata.json"):
                preserved.append((path, size, "metadata"))

            elif real in protected:
                preserved.append((path, size, "canonical"))

            else:
                preserved.append((path, size, "other"))

    source_size = _file_size(source) if source else 0

    return {
        "job_id": job_id,
        "source": {
            "exists": bool(source),
            "filename": os.path.basename(source) if source else None,
            "size_bytes": source_size,
        },
        "project_size_bytes": _dir_size(job_dir),
        "temporary_files": [
            {
                "filename": os.path.relpath(path, job_dir),
                "size_bytes": size,
                "kind": kind,
            }
            for path, size, kind in temporary
        ],
        "old_derived_files": [
            {
                "filename": os.path.relpath(path, job_dir),
                "size_bytes": size,
                "kind": kind,
            }
            for path, size, kind in derived
        ],
        "preserved_files": [
            {
                "filename": os.path.relpath(path, job_dir),
                "size_bytes": size,
                "kind": kind,
            }
            for path, size, kind in preserved
        ],
    }


def delete_source(
    job_id: str,
    upload_dir: str,
    output_dir: str,
) -> Dict:
    """Delete only the original source video."""
    source = locate_source(job_id, upload_dir, output_dir)

    if not source:
        return {
            "deleted": False,
            "freed_bytes": 0,
            "filename": None,
        }

    size = _file_size(source)
    os.remove(source)

    return {
        "deleted": True,
        "freed_bytes": size,
        "filename": os.path.basename(source),
    }


def clean_project(
    job_id: str,
    upload_dir: str,
    output_dir: str,
) -> Dict:
    """
    Remove the source and clearly disposable intermediate/state files.

    Generated clips, active derived clips, metadata and layout information
    remain untouched.
    """
    inventory = inspect_project(job_id, upload_dir, output_dir)

    deleted = []
    freed = 0

    # Source can live outside the job directory.
    source = locate_source(job_id, upload_dir, output_dir)
    if source and os.path.isfile(source):
        size = _file_size(source)
        os.remove(source)
        deleted.append({
            "filename": os.path.basename(source),
            "kind": "source",
            "size_bytes": size,
        })
        freed += size

    job_dir = _safe_under(output_dir, job_id)
    if not job_dir:
        raise FileNotFoundError(f"Project not found: {job_id}")

    for item in inventory["temporary_files"]:
        relative = item["filename"]
        target = _safe_under(job_dir, relative)

        if not target or not os.path.isfile(target):
            continue

        size = _file_size(target)
        os.remove(target)

        deleted.append({
            "filename": relative,
            "kind": item["kind"],
            "size_bytes": size,
        })
        freed += size

    return {
        "cleaned": True,
        "freed_bytes": freed,
        "deleted_files": deleted,
        "remaining_project_size_bytes": _dir_size(job_dir),
    }
