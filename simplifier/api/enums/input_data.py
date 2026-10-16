from enum import auto, StrEnum

class InputData(StrEnum):
    TITLE = auto()
    SUBMITTERS = auto()
    VOTE_DATE = auto()
    VOTE_OUTCOME = auto()
    VOTES_FOR = auto()
    VOTES_FOR_TOTAL = auto()
    VOTES_AGAINST = auto()
    VOTES_AGAINST_TOTAL = auto()
    TOPICS = auto()
    TEXT_BEGIN = auto()
    TEXT_END = auto()
    TEXT = auto()