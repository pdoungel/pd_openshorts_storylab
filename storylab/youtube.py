from __future__ import annotations

import re
from .models import StoryProject, YouTubePackage


def _clean(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    return value[:limit].rstrip()


def _stamp(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def build_youtube_package(project: StoryProject, thumbnail_path: str | None = None) -> YouTubePackage:
    """Build editable, YouTube-ready long-form metadata from the approved story/script.

    This deliberately uses no external model: the user can edit every field before
    publishing, while the package is valid enough to take a rendered Story Lab video
    straight into a normal YouTube upload.
    """
    story = project.analysis.story if project.analysis else None
    summary = project.analysis.summary if project.analysis else ""
    angle = project.brief.angle.replace("_", " ")
    title = _clean(project.title, 100)

    description_parts = [
        summary.strip(),
        "",
        f"This video explores {project.title} through a {angle} lens.",
    ]
    if project.brief.question.strip():
        description_parts += ["", f"Question: {project.brief.question.strip()}"]
    if story and story.significance.strip():
        description_parts += ["", story.significance.strip()]

    chapters: list[str] = []
    elapsed = 0.0
    for section in project.script:
        if not section.narration.strip():
            continue
        chapters.append(f"{_stamp(elapsed)} {section.heading}")
        elapsed += max(0.0, section.duration_seconds)

    if chapters and not chapters[0].startswith("00:00"):
        chapters.insert(0, "00:00 Introduction")

    if chapters:
        description_parts += ["", "CHAPTERS", *chapters]

    description = _clean("\n".join(description_parts), 5000)

    raw_tags = [
        project.title,
        project.kind,
        angle,
        "story analysis",
        "film analysis" if project.kind in {"movie", "series", "anime", "episode"} else "documentary",
        *((project.analysis.themes if project.analysis else [])[:8]),
        *((project.analysis.characters if project.analysis else [])[:8]),
        *([insight.title for insight in (project.analysis.insights if project.analysis else []) if insight.title][:8]),
    ]
    tags: list[str] = []
    for tag in raw_tags:
        tag = _clean(tag, 60)
        if tag and tag.lower() not in {x.lower() for x in tags}:
            tags.append(tag)
    while len(", ".join(tags)) > 490 and tags:
        tags.pop()

    return YouTubePackage(
        title=title,
        description=description,
        tags=tags,
        category_id="24" if project.kind in {"movie", "series", "anime", "episode"} else "22",
        language="en",
        privacy_status="private",
        thumbnail_path=thumbnail_path,
        chapters=chapters,
    )
