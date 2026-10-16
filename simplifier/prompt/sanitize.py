"""Keeps untrusted motie text inside its data block."""

# The motie text is untrusted data. It is placed between these markers and the
# prompt tells the model never to follow instructions found between them.
TEXT_BEGIN = "<<<MOTIETEKST_BEGIN>>>"
TEXT_END = "<<<MOTIETEKST_EINDE>>>"


def untrusted(value: str) -> str:
    """Removes the markers from external text so it cannot close the data block itself."""
    return value.replace(TEXT_BEGIN, "").replace(TEXT_END, "").strip()
