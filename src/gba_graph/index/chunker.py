"""Paragraph-aware chunking with canonical-text offsets."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    start: int
    end: int
    text: str


def chunk_text(text: str, target: int = 800, hard_max: int = 1500) -> list[Chunk]:
    if target <= 0 or hard_max < target:
        raise ValueError("chunk sizes must satisfy 0 < target <= hard_max")
    if not text:
        return []
    paragraphs: list[tuple[int, int, str]] = []
    start = 0
    for part in text.split("\n\n"):
        end = start + len(part)
        if part:
            if len(part) <= hard_max:
                paragraphs.append((start, end, part))
            else:
                offset = 0
                while offset < len(part):
                    split = min(offset + hard_max, len(part))
                    if split < len(part):
                        boundary = part.rfind(" ", offset + target // 2, split)
                        if boundary > offset:
                            split = boundary
                    paragraphs.append((start + offset, start + split, text[start + offset:start + split]))
                    offset = split + (1 if split < len(part) and part[split:split + 1] == " " else 0)
        start = end + 2
    result: list[Chunk] = []
    index = 0
    while index < len(paragraphs):
        group = [paragraphs[index]]
        size = len(group[0][2])
        cursor = index + 1
        while cursor < len(paragraphs) and size + 2 + len(paragraphs[cursor][2]) <= hard_max:
            if size >= target:
                break
            group.append(paragraphs[cursor])
            size += 2 + len(paragraphs[cursor][2])
            cursor += 1
        chunk_start, chunk_end = group[0][0], group[-1][1]
        result.append(Chunk(len(result), chunk_start, chunk_end, text[chunk_start:chunk_end]))
        if cursor >= len(paragraphs):
            break
        # Overlap the final paragraph when it fits the following chunk; otherwise advance.
        if cursor < len(paragraphs) and len(paragraphs[cursor - 1][2]) + 2 + len(paragraphs[cursor][2]) <= hard_max:
            index = max(index + 1, cursor - 1)
        else:
            index = cursor
    return result
