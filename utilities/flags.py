from enum import IntFlag

__all__ = ("ALL_NOTIFICATIONS", "Notification")


class Notification(IntFlag):
    """users.flags bits. Values are stored in the DB; never renumber."""

    VERIFIED = 1
    DENIED = 2
    SPECTACULAR = 4


ALL_NOTIFICATIONS = (
    Notification.VERIFIED,
    Notification.DENIED,
    Notification.SPECTACULAR,
)
