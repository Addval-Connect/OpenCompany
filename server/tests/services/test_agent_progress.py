from services.agent_progress import (
    NoProgressGuard,
    REASON_CONSECUTIVE,
    REASON_IDENTICAL,
)


def test_identical_unusable_call_stops_on_second_repeat():
    guard = NoProgressGuard()
    failures = [("data", '{"content": ')]

    assert guard.observe(failures=failures, executable=False) is None
    assert guard.observe(failures=failures, executable=False) == REASON_IDENTICAL


def test_consecutive_unusable_steps_stop_on_third_turn():
    guard = NoProgressGuard()

    assert guard.observe(failures=[("unknown", "")], executable=False) is None
    assert guard.observe(failures=[("other", "")], executable=False) is None
    assert (
        guard.observe(failures=[("third", "")], executable=False)
        == REASON_CONSECUTIVE
    )


def test_executable_call_resets_both_counters():
    guard = NoProgressGuard()
    failures = [("data", '{"content": ')]

    assert guard.observe(failures=failures, executable=False) is None
    assert guard.observe(failures=[], executable=True) is None
    assert guard.observe(failures=failures, executable=False) is None
    assert guard.observe(failures=failures, executable=False) == REASON_IDENTICAL
    assert guard.consecutive == 2


def test_message_does_not_echo_raw_arguments():
    guard = NoProgressGuard()
    guard.observe(failures=[("data", "SECRET-RAW-ARGS")], executable=False)
    message = guard.message(REASON_CONSECUTIVE)

    assert "SECRET-RAW-ARGS" not in message
    assert "nothing from those calls was executed" in message
