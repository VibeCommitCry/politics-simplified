"""Keeps untrusted motie text inside its data block."""

# The motie text is untrusted data. It is placed between these markers and the
# prompt tells the model never to follow instructions found between them.
TEXT_BEGIN = "<<<MOTIETEKST_BEGIN>>>"
TEXT_END = "<<<MOTIETEKST_EINDE>>>"

# Model output (the writer's answer, the critic's problems) is untrusted too.
ANSWER_BEGIN = "<<<ANTWOORD_BEGIN>>>"
ANSWER_END = "<<<ANTWOORD_EINDE>>>"

MARKERS = (TEXT_BEGIN, TEXT_END, ANSWER_BEGIN, ANSWER_END)


def untrusted(value: str) -> str:
    """Removes the markers from external text so it cannot close a data block itself."""
    for marker in MARKERS:
        value = value.replace(marker, "")
    return value.strip()
