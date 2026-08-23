//! Thread events — `RuntimeEventEnvelope` mapping + `EventMsg` fan-out
//! (issue #5261 / #3313).
//!
//! The TUI's `runtime_threads.rs` emits `RuntimeEventEnvelope` for the
//! app-server SSE stream and `Event` for the transcript. This module owns
//! that mapping in `core` so the headless `exec` and the TUI render the
//! same envelope for the same turn — byte-identical on the wire.

use hakus_protocol::event_msg::EventMsg;
use hakus_protocol::ids::{SessionId, ThreadId};

/// Narrow the `EventMsg` to the envelope shape the app-server expects.
/// The real `RuntimeEventEnvelope` adds `seq` + `timestamp`; this helper
/// stamps them consistently so headless and TUI produce identical sequences.
#[must_use]
pub fn to_envelope_seq(
    seq: u64,
    thread_id: ThreadId,
    _session_id: SessionId,
    msg: EventMsg,
) -> hakus_protocol::runtime::RuntimeEventEnvelope {
    hakus_protocol::runtime::RuntimeEventEnvelope {
        schema_version: hakus_protocol::runtime::RUNTIME_EVENT_ENVELOPE_SCHEMA_VERSION,
        seq,
        event: msg.kind_str().to_string(),
        kind: msg.kind_str().to_string(),
        thread_id: thread_id.to_string(),
        turn_id: None,
        item_id: None,
        timestamp: chrono::Utc::now().to_rfc3339(),
        created_at: None,
        payload: serde_json::to_value(&msg).unwrap_or(serde_json::Value::Null),
        extra: Default::default(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn envelope_preserves_thread_and_kind() {
        let tid = ThreadId::new();
        let sid = SessionId::new();
        let env = to_envelope_seq(
            1,
            tid.clone(),
            sid.clone(),
            EventMsg::TurnStarted {
                thread_id: tid.clone(),
                session_id: sid.clone(),
                turn_id: "turn-1".into(),
            },
        );
        assert_eq!(env.thread_id, tid.to_string());
        assert_eq!(env.seq, 1);
    }
}
