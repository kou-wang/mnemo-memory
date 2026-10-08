from enum import StrEnum


class MemoryKind(StrEnum):
    FACT = "FACT"
    PREFERENCE = "PREFERENCE"
    CURRENT_STATE = "CURRENT_STATE"
    EVENT = "EVENT"
    INTENT = "INTENT"


class MemoryStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"
