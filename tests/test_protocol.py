"""
Unit tests for hakus.protocol — typed event/Op protocol.

Covers:
  - P0.2 协议层单测缺失 (Phase 7 遗留)

Tests grouped:
  1. Event immutability (frozen + slots)
  2. Event dataclass basic construction
  3. Event to_dict / from_dict round-trips (wire format)
  4. EVENT_TYPE_REGISTRY completeness and dispatch
  5. Op immutability and construction
  6. OP_TYPE_REGISTRY completeness
  7. Op to_dict / from_dict round-trips
  8. parse_reflection_response: pure JSON / markdown fence / embedded / malformed
  9. Op queue put/get order (FIFO semantics)
 10. AgentEventType / OpType enum values
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import pytest

from hakus.protocol import (
    # Events
    AgentEvent,
    AgentEventType,
    ActivityChanged,
    Cancelled,
    OrchestratorPhaseChanged,
    ReasoningDelta,
    ReflectionCompleted,
    ReflectionDecision,
    ReflectionStarted,
    TextDelta,
    TokenUsage,
    ToolCallFinished,
    ToolCallStarted,
    TurnCompleted,
    TurnFailed,
    TurnStarted,
    # Ops
    ApprovalOp,
    FollowUpOp,
    InterruptOp,
    Op,
    OpType,
    # Serialization
    EVENT_TYPE_REGISTRY,
    OP_TYPE_REGISTRY,
    deserialize_event,
    deserialize_op,
    parse_reflection_response,
    serialize_event,
    serialize_op,
)


# ============================================================
# 1. Event immutability (frozen + slots)
# ============================================================


class TestEventImmutability:
    def test_text_delta_is_frozen(self):
        ev = TextDelta(text="hi")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ev.text = "bye"  # type: ignore[misc]

    def test_tool_call_finished_is_frozen(self):
        ev = ToolCallFinished(call_id="c1", name="bash", result="ok", success=True)
        with pytest.raises(dataclasses.FrozenInstanceError):
            ev.call_id = "c2"  # type: ignore[misc]

    def test_turn_completed_is_frozen(self):
        ev = TurnCompleted(content="done", tool_calls=(), iterations=1)
        with pytest.raises(dataclasses.FrozenInstanceError):
            ev.iterations = 999  # type: ignore[misc]

    def test_turn_failed_is_frozen(self):
        ev = TurnFailed(code="model_error", error="boom")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ev.error = "ok"  # type: ignore[misc]

    def test_cancelled_is_frozen(self):
        ev = Cancelled(reason="user", partial_content="...")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ev.reason = "system"  # type: ignore[misc]

    def test_event_slots_no_dict(self):
        """frozen + slots=True should reject __dict__ assignment."""
        ev = TextDelta(text="x")
        with pytest.raises(AttributeError):
            ev.__dict__["extra"] = 1  # type: ignore[attr-defined]


# ============================================================
# 2. Event basic construction (defaults)
# ============================================================


class TestEventDefaults:
    def test_turn_started_defaults(self):
        ev = TurnStarted()
        assert ev.event_type == AgentEventType.TURN_STARTED
        assert ev.turn_id == ""
        assert ev.model == ""

    def test_text_delta_defaults(self):
        ev = TextDelta()
        assert ev.event_type == AgentEventType.TEXT_DELTA
        assert ev.text == ""

    def test_tool_call_started_defaults(self):
        ev = ToolCallStarted()
        assert ev.event_type == AgentEventType.TOOL_CALL_STARTED
        assert ev.call_id == ""
        assert ev.name == ""
        assert ev.arguments == {}

    def test_tool_call_finished_defaults(self):
        ev = ToolCallFinished()
        assert ev.event_type == AgentEventType.TOOL_CALL_FINISHED
        assert ev.success is True
        assert ev.duration == 0.0
        assert ev.arguments == {}

    def test_activity_changed_tool_name_optional(self):
        ev = ActivityChanged(phase="thinking")
        assert ev.tool_name is None
        assert ev.detail == ""

    def test_turn_completed_iterations_zero_by_default(self):
        ev = TurnCompleted()
        assert ev.iterations == 0
        assert ev.input_tokens == 0
        assert ev.output_tokens == 0
        assert ev.tool_calls == ()
        assert ev.compressed is False

    def test_reflection_decision_defaults(self):
        d = ReflectionDecision()
        assert d.done is True
        assert d.reason == ""
        assert d.need == ""


# ============================================================
# 3. Event to_dict / from_dict round-trips
# ============================================================


class TestEventRoundTrips:
    @pytest.mark.parametrize("ev", [
        TurnStarted(turn_id="t1", model="deepseek"),
        TextDelta(text="hello"),
        ReasoningDelta(text="thinking..."),
        ToolCallStarted(call_id="c1", name="bash", arguments={"cmd": "ls"}),
        ToolCallFinished(call_id="c1", name="bash", result="a.py\nb.py", success=True, duration=0.3),
        ToolCallFinished(call_id="c2", name="write", result="Error: bad", success=False),
        OrchestratorPhaseChanged(phase="developing", detail="working"),
        ActivityChanged(phase="tool_use", detail="bash", tool_name="bash"),
        TokenUsage(input_tokens=10, output_tokens=20),
        TurnCompleted(content="all done", tool_calls=(), iterations=2, input_tokens=100, output_tokens=200, compressed=True),
        TurnFailed(code="model_error", error="api timeout"),
        Cancelled(reason="user_pressed_escape", partial_content="half done"),
        ReflectionStarted(iteration=1, tool_names=("bash", "read_file")),
        ReflectionCompleted(decision=ReflectionDecision(done=False, reason="need more", need="bash")),
    ])
    def test_round_trip(self, ev):
        d = serialize_event(ev)
        # The serialized dict must include the event_type field
        assert d["event_type"] == ev.event_type.value
        restored = deserialize_event(d)
        # The restored event should be the same type
        assert type(restored) is type(ev)
        # ...and carry the same field values
        for f in dataclasses.fields(ev):
            assert getattr(restored, f.name) == getattr(ev, f.name), (
                f"Field {f.name} mismatch for {type(ev).__name__}"
            )

    def test_tool_call_started_arguments_round_trip(self):
        ev = ToolCallStarted(call_id="c1", name="read_file", arguments={"path": "/tmp/a.txt", "n": 5})
        restored = deserialize_event(serialize_event(ev))
        assert restored.arguments == {"path": "/tmp/a.txt", "n": 5}

    def test_round_trip_preserves_type_tag(self):
        ev = TextDelta(text="x")
        d = serialize_event(ev)
        assert d["event_type"] == "text_delta"
        # json.dumps should succeed (wire-format compat)
        json.dumps(d)


# ============================================================
# 4. EVENT_TYPE_REGISTRY
# ============================================================


class TestEventTypeRegistry:
    def test_registry_built_at_import(self):
        assert isinstance(EVENT_TYPE_REGISTRY, dict)
        assert len(EVENT_TYPE_REGISTRY) >= 10

    def test_all_event_types_have_registry_entry(self):
        """Every AgentEventType value should resolve to a class."""
        for et in AgentEventType:
            cls = EVENT_TYPE_REGISTRY.get(et.value)
            assert cls is not None, f"No class registered for {et.value}"
            assert issubclass(cls, AgentEvent)

    def test_registry_class_constructible(self):
        """Every registered class should be constructible (zero args)."""
        for et, cls in EVENT_TYPE_REGISTRY.items():
            instance = cls()  # type: ignore[call-arg]
            assert instance.event_type.value == et

    def test_deserialize_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown event_type"):
            deserialize_event({"event_type": "totally_made_up"})

    def test_deserialize_missing_type_raises(self):
        with pytest.raises(ValueError, match="missing 'event_type'"):
            deserialize_event({"text": "no type field"})

    def test_deserialize_non_dict_raises(self):
        with pytest.raises(ValueError, match="must be a dict"):
            deserialize_event("not a dict")  # type: ignore[arg-type]


# ============================================================
# 5. Op immutability
# ============================================================


class TestOpImmutability:
    def test_interrupt_op_is_frozen(self):
        op = InterruptOp(reason="user")
        with pytest.raises(dataclasses.FrozenInstanceError):
            op.reason = "system"  # type: ignore[misc]

    def test_approval_op_is_frozen(self):
        op = ApprovalOp(call_id="c1", decision="once")
        with pytest.raises(dataclasses.FrozenInstanceError):
            op.decision = "deny"  # type: ignore[misc]

    def test_follow_up_op_is_frozen(self):
        op = FollowUpOp(text="hi")
        with pytest.raises(dataclasses.FrozenInstanceError):
            op.text = "bye"  # type: ignore[misc]

    def test_interrupt_op_default_reason(self):
        op = InterruptOp()
        assert op.reason == "user_pressed_escape"

    def test_approval_op_default_decision(self):
        op = ApprovalOp()
        assert op.decision == "deny"


# ============================================================
# 6. OP_TYPE_REGISTRY
# ============================================================


class TestOpTypeRegistry:
    def test_registry_built_at_import(self):
        assert isinstance(OP_TYPE_REGISTRY, dict)
        assert len(OP_TYPE_REGISTRY) >= 3

    def test_all_op_types_have_registry_entry(self):
        for ot in OpType:
            cls = OP_TYPE_REGISTRY.get(ot.value)
            assert cls is not None, f"No class registered for {ot.value}"
            assert issubclass(cls, Op)

    def test_registry_class_constructible(self):
        for ot, cls in OP_TYPE_REGISTRY.items():
            instance = cls()  # type: ignore[call-arg]
            assert instance.op_type.value == ot

    def test_deserialize_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown op_type"):
            deserialize_op({"op_type": "totally_made_up"})


# ============================================================
# 7. Op to_dict / from_dict round-trips
# ============================================================


class TestOpRoundTrips:
    @pytest.mark.parametrize("op", [
        InterruptOp(reason="user_pressed_escape"),
        InterruptOp(reason="timeout"),
        ApprovalOp(call_id="bash:rm -rf /", decision="once"),
        ApprovalOp(call_id="write:/etc/passwd", decision="session"),
        ApprovalOp(call_id="bash:ls", decision="deny"),
        FollowUpOp(text="wait, also do X"),
    ])
    def test_round_trip(self, op):
        d = serialize_op(op)
        assert d["op_type"] == op.op_type.value
        restored = deserialize_op(d)
        assert type(restored) is type(op)
        for f in dataclasses.fields(op):
            assert getattr(restored, f.name) == getattr(op, f.name)


# ============================================================
# 8. parse_reflection_response — 4 boundary inputs
# ============================================================


class TestParseReflectionResponse:
    """Reflection LLM JSON parsing. The four interesting cases from
    the original spec §3.3 are: pure JSON, markdown-fenced JSON,
    JSON embedded in prose, and malformed (fallback to done=True)."""

    def test_pure_json(self):
        d = parse_reflection_response('{"done": false, "reason": "need more", "need": "bash"}')
        assert d.done is False
        assert d.reason == "need more"
        assert d.need == "bash"

    def test_pure_json_done_true(self):
        d = parse_reflection_response('{"done": true, "reason": "all good"}')
        assert d.done is True
        assert d.reason == "all good"
        assert d.need == ""  # default

    def test_markdown_fenced_json(self):
        """Strips ```json ... ``` fence."""
        text = '```json\n{"done": false, "reason": "x", "need": "bash"}\n```'
        d = parse_reflection_response(text)
        assert d.done is False
        assert d.need == "bash"

    def test_markdown_fenced_no_lang(self):
        """Strips ``` ... ``` fence (no language tag)."""
        text = '```\n{"done": true, "reason": "ok"}\n```'
        d = parse_reflection_response(text)
        assert d.done is True
        assert d.reason == "ok"

    def test_json_embedded_in_prose(self):
        """The model wrote 'the answer is {...}' — extract the block."""
        text = 'Looking at the result, I think the answer is {"done": true, "reason": "complete"}.'
        d = parse_reflection_response(text)
        assert d.done is True
        assert d.reason == "complete"

    def test_malformed_returns_done_true(self):
        """Safety fallback: malformed JSON should not loop forever."""
        d = parse_reflection_response("not json at all")
        assert d.done is True
        assert d.reason == "parse_failed"

    def test_empty_response_returns_done_true(self):
        d = parse_reflection_response("")
        assert d.done is True
        assert d.reason == "empty_response"

    def test_none_response_returns_done_true(self):
        d = parse_reflection_response(None)  # type: ignore[arg-type]
        assert d.done is True
        assert d.reason == "empty_response"

    def test_json_missing_done_field_defaults_true(self):
        d = parse_reflection_response('{"reason": "looks good"}')
        assert d.done is True
        assert d.reason == "looks good"

    def test_json_non_dict_returns_done_true(self):
        d = parse_reflection_response('[1, 2, 3]')
        assert d.done is True
        assert d.reason == "parse_failed"

    def test_need_field_normalized_to_string(self):
        """If 'need' is a number or null, coerce to string."""
        d = parse_reflection_response('{"done": false, "need": 42, "reason": "x"}')
        assert d.need == "42"

    def test_done_field_coerced_to_bool(self):
        d = parse_reflection_response('{"done": "yes", "reason": "x"}')
        assert d.done is True  # bool("yes") is True


# ============================================================
# 9. Op queue put/get order (FIFO)
# ============================================================


class TestOpQueueOrder:
    """Op queue semantics — frontends push Ops back; the agent
    consumes them in order. This test verifies the asyncio.Queue
    contract that the protocol relies on."""

    def test_fifo_ordering(self):
        q: asyncio.Queue[Op] = asyncio.Queue()
        q.put_nowait(InterruptOp(reason="a"))
        q.put_nowait(ApprovalOp(call_id="c1", decision="once"))
        q.put_nowait(FollowUpOp(text="hi"))

        async def drain():
            return [q.get_nowait() for _ in range(3)]

        ops = asyncio.run(drain())
        assert isinstance(ops[0], InterruptOp)
        assert ops[0].reason == "a"
        assert isinstance(ops[1], ApprovalOp)
        assert ops[1].call_id == "c1"
        assert isinstance(ops[2], FollowUpOp)
        assert ops[2].text == "hi"

    def test_isinstance_dispatch(self):
        """The core event loop pattern: ``if isinstance(op, InterruptOp)``."""
        ops: list[Op] = [
            ApprovalOp(call_id="x", decision="deny"),  # Not for us
            InterruptOp(reason="user"),
        ]
        interrupt = next((op for op in ops if isinstance(op, InterruptOp)), None)
        assert interrupt is not None
        assert interrupt.reason == "user"

    def test_put_nowait_full_fails_cleanly(self):
        """Bounded queue should raise QueueFull (not silent corruption)."""
        q: asyncio.Queue[Op] = asyncio.Queue(maxsize=2)
        q.put_nowait(InterruptOp())
        q.put_nowait(InterruptOp())
        with pytest.raises(asyncio.QueueFull):
            q.put_nowait(InterruptOp(), )


# ============================================================
# 10. Enum stability (wire-format compatibility)
# ============================================================


class TestEnumValues:
    """The string value of each enum member is the wire-format
    discriminator. Renaming a value is a breaking change."""

    def test_event_type_values(self):
        assert AgentEventType.TURN_STARTED.value == "turn_started"
        assert AgentEventType.TEXT_DELTA.value == "text_delta"
        assert AgentEventType.TOOL_CALL_STARTED.value == "tool_call_started"
        assert AgentEventType.TOOL_CALL_FINISHED.value == "tool_call_finished"
        assert AgentEventType.TURN_COMPLETED.value == "turn_completed"
        assert AgentEventType.TURN_FAILED.value == "turn_failed"
        assert AgentEventType.CANCELLED.value == "cancelled"

    def test_op_type_values(self):
        assert OpType.INTERRUPT.value == "interrupt"
        assert OpType.APPROVAL.value == "approval"
        assert OpType.FOLLOW_UP.value == "follow_up"

    def test_event_type_str_inherits_str(self):
        """AgentEventType is a str-Enum — it should compare equal to its value."""
        assert AgentEventType.TURN_STARTED == "turn_started"

    def test_op_type_str_inherits_str(self):
        assert OpType.INTERRUPT == "interrupt"
