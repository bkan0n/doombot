from utilities.flags import ALL_NOTIFICATIONS, Notification


def test_bit_values_match_legacy_data() -> None:
    # Stored users.flags values from the old repo must decode identically.
    assert Notification.VERIFIED == 1
    assert Notification.DENIED == 2
    assert Notification.SPECTACULAR == 4


def test_membership() -> None:
    flags = Notification(5)
    assert Notification.VERIFIED in flags
    assert Notification.SPECTACULAR in flags
    assert Notification.DENIED not in flags


def test_all_notifications_covers_every_flag() -> None:
    combined = Notification(0)
    for flag in ALL_NOTIFICATIONS:
        combined |= flag
    assert combined == Notification(7)
