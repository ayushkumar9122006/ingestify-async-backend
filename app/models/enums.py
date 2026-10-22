from enum import Enum


class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"


class JobStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskPriority(str, Enum):
    DEFAULT = "default"
    HIGH = "high-priority"
