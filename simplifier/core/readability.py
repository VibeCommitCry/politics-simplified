"""Flesch-Douma reading ease of the original motie and of the simplified detail."""

import textstat

from ..api.schemas import Detail, Readability

# With language "nl", textstat's Flesch reading ease uses the Douma formula.
textstat.set_lang("nl")


def flesch_douma(text: str) -> float:
    return float(textstat.flesch_reading_ease(text))


def detail_text(detail: Detail) -> str:
    """The three prose sections; the word list is not running text and would skew the score."""
    return "\n\n".join([detail.waar_gaat_het_over, detail.wat_betekent_het_voor_jou, detail.wat_is_er_besloten])


def readability(original: str, detail: Detail) -> Readability:
    return Readability(before=flesch_douma(original), after=flesch_douma(detail_text(detail)))
