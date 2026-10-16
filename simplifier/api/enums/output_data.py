from enum import StrEnum, auto


class OutputData(StrEnum):
    """The JSON keys the writer must answer with. Values match WriterOutput, so Symfony's contract stays fixed."""

    HOOK = auto()
    DETAIL = auto()
    WAAR_GAAT_HET_OVER = auto()
    WAT_BETEKENT_HET_VOOR_JOU = auto()
    WAT_IS_ER_BESLOTEN = auto()
    MOEILIJKE_WOORDEN = auto()
    WOORD = auto()
    BETEKENIS = auto()
    TOPICS = auto()
    RELEVANCE = auto()
