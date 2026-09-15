"""Lossless preparation of model text for the browser's bounded send controls."""

import re


def browser_length(text):
    # The extension measures UTF-16 code units, including two units per emoji.
    return sum(2 if ord(char) > 0xFFFF else 1 for char in text)


def prepare_segments(parts):
    """Return up to three short messages, or None for manual review; never clip."""
    result = []
    for part in parts:
        remaining = part.strip()
        while browser_length(remaining) > 400:
            size, end = 0, 0
            for char in remaining:
                size += browser_length(char)
                if size > 400:
                    break
                end += 1
            prefix = remaining[:end]
            boundaries = list(re.finditer(r"[。！？](?:[\s]*)|[.!?](?:\s+)|\n+", prefix))
            if not boundaries:
                boundaries = list(re.finditer(r"\s+", prefix))
            if not boundaries:
                return None  # Do not cut a URL, identifier or unbroken word.
            cut = boundaries[-1].end()
            result.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        if remaining:
            result.append(remaining)
    # Keep the model's useful paragraph boundaries unless there are too many.
    while len(result) > 3:
        adjacent = next((i for i in range(len(result) - 1)
                         if browser_length(result[i] + "\n\n" + result[i + 1]) <= 400), None)
        if adjacent is None:
            return None
        result[adjacent:adjacent + 2] = [result[adjacent] + "\n\n" + result[adjacent + 1]]
    return result or None
