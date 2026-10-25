from enum import StrEnum, auto


class CriticData(StrEnum):
    """The JSON keys the critic must answer with. Values match CriticOutput."""

    PASSED = auto()
    CONFIDENCE = auto()
    PROBLEMS = auto()
