from datetime import datetime

from manmabot_v1.schedule import ScheduleTask
from manmabot_v1.schedule_clock import ScheduleSession


def _task(task_id: str, account: str, start: str, end: str, **kwargs) -> ScheduleTask:
    return ScheduleTask(
        id=task_id,
        name=task_id,
        enabled=kwargs.get("enabled", True),
        account_id=account,
        start_time=start,
        end_time=end,
        time_mode="window",
        weekdays=kwargs.get("weekdays", [0]),
    )


def test_exact_window_then_next_account():
    first = _task("one", "acc-1", "00:00:00", "11:59:00")
    second = _task("two", "acc-2", "12:00:00", "23:59:00")
    session = ScheduleSession()
    session.arm()
    morning = datetime(2026, 9, 21, 10, 0, 0)  # Monday
    started = session.tick(morning, [first, second], randomize_minutes=0)
    assert started.kind == "begin"
    assert started.task_id == "one"
    assert started.switch_at == datetime(2026, 9, 21, 11, 59, 0)

    notice = session.tick(datetime(2026, 9, 21, 11, 54, 0), [first, second])
    assert notice.kind == "notify"
    assert session.active_id == "one"
    again = session.tick(datetime(2026, 9, 21, 11, 54, 30), [first, second])
    assert again.kind == "idle"
    assert session.notified is True

    left = session.tick(datetime(2026, 9, 21, 11, 59, 0), [first, second])
    assert left.kind == "handover"
    assert left.task_id is None

    afternoon = session.tick(datetime(2026, 9, 21, 12, 0, 0), [first, second])
    assert afternoon.kind == "begin"
    assert afternoon.task_id == "two"
    assert afternoon.switch_at == datetime(2026, 9, 21, 23, 59, 0)


def test_randomize_shifts_only_the_end():
    first = _task("one", "acc-1", "00:00:00", "11:59:00")
    second = _task("two", "acc-2", "12:00:00", "23:59:00")
    early = ScheduleSession()
    early.arm()
    early.tick(
        datetime(2026, 9, 21, 10, 0, 0),
        [first, second],
        randomize_minutes=10,
        rng=lambda _low, _high: -10,
    )
    assert early.switch_at == datetime(2026, 9, 21, 11, 49, 0)
    left = early.tick(datetime(2026, 9, 21, 11, 49, 0), [first, second], randomize_minutes=10)
    assert left.kind == "handover"
    assert left.task_id is None
    assert early.tick(datetime(2026, 9, 21, 11, 50, 0), [first, second]).kind == "idle"

    late = ScheduleSession()
    late.arm()
    late.tick(
        datetime(2026, 9, 21, 10, 0, 0),
        [first, second],
        randomize_minutes=20,
        rng=lambda _low, _high: 20,
    )
    assert late.switch_at == datetime(2026, 9, 21, 12, 19, 0)
    still = late.tick(
        datetime(2026, 9, 21, 12, 0, 0),
        [first, second],
        randomize_minutes=20,
        rng=lambda _low, _high: 20,
    )
    assert still.kind == "idle"
    assert still.task_id == "one"
    handed = late.tick(
        datetime(2026, 9, 21, 12, 19, 0),
        [first, second],
        randomize_minutes=20,
        rng=lambda _low, _high: 20,
    )
    assert handed.kind == "handover"
    assert handed.task_id == "two"


def test_disabled_and_wrong_weekday_are_skipped():
    monday = _task("one", "acc-1", "00:00:00", "11:59:00", enabled=False)
    sunday = _task("two", "acc-2", "00:00:00", "23:59:00", weekdays=[6])
    session = ScheduleSession()
    session.arm()
    decision = session.tick(datetime(2026, 9, 21, 10, 0, 0), [monday, sunday])
    assert decision.kind == "idle"
    assert session.active_id is None


def test_disabling_the_running_schedule_hands_over():
    first = _task("one", "acc-1", "00:00:00", "12:00:00")
    second = _task("two", "acc-2", "00:00:00", "23:59:00")
    session = ScheduleSession()
    session.arm()
    now = datetime(2026, 9, 21, 10, 0, 0)
    assert session.tick(now, [first, second]).task_id == "one"
    first.enabled = False
    handed = session.tick(now, [first, second])
    assert handed.kind == "handover"
    assert handed.task_id == "two"


def test_negative_offset_never_ends_before_the_start():
    task = _task("one", "acc-1", "11:00:00", "11:05:00")
    session = ScheduleSession()
    session.arm()
    decision = session.tick(
        datetime(2026, 9, 21, 11, 0, 0),
        [task],
        randomize_minutes=20,
        rng=lambda _low, _high: -20,
    )
    assert decision.kind == "begin"
    assert decision.switch_at == datetime(2026, 9, 21, 11, 0, 1)


def test_randomize_setting_round_trip():
    import uuid
    from manmabot_v1.paths import USERDATA, ensure_userdata
    from manmabot_v1.schedule import ScheduleStore

    ensure_userdata()
    path = USERDATA / f"test-schedules-{uuid.uuid4().hex}.json"
    try:
        store = ScheduleStore(path)
        store.randomize_enabled = True
        store.randomize_minutes = 20
        task = _task("one", "acc-1", "00:00:00", "11:59:00")
        store.save([task])
        loaded = ScheduleStore(path)
        rows = loaded.load()
        assert loaded.randomize_enabled is True
        assert loaded.randomize_minutes == 20
        assert rows[0].enabled is True
        rows[0].enabled = False
        loaded.save(rows)
        again = ScheduleStore(path)
        restored = again.load()
        assert restored[0].enabled is False
        assert again.randomize_enabled is True
    finally:
        path.unlink(missing_ok=True)


def test_turning_randomize_off_uses_the_nominal_end():
    task = _task("one", "acc-1", "00:00:00", "11:59:00")
    session = ScheduleSession()
    session.arm()
    session.tick(
        datetime(2026, 9, 21, 10, 0, 0),
        [task],
        randomize_minutes=10,
        rng=lambda _low, _high: 10,
    )
    assert session.switch_at == datetime(2026, 9, 21, 12, 9, 0)
    session.tick(datetime(2026, 9, 21, 10, 5, 0), [task], randomize_minutes=0)
    assert session.switch_at == datetime(2026, 9, 21, 11, 59, 0)
