//! Convenience helpers for the native iLink client.

use crate::client::IlLinkClient;
use crate::models::Result;

/// Send a text message using the context token learned from polling.
pub async fn send_text(client: &IlLinkClient, user_id: &str, text: &str) -> Result<()> {
    client.send_text(user_id, text).await
}

/// One inbound text message normalized for higher-level integrations.
#[derive(Debug, Clone)]
pub struct InboundMessage {
    pub user_id: String,
    pub text: String,
    pub message_id: String,
}

/// Poll indefinitely and invoke `on_message` for each inbound text message.
pub async fn poll_loop(
    client: &IlLinkClient,
    mut on_message: impl FnMut(InboundMessage),
) -> Result<()> {
    loop {
        let response = client.get_updates().await?;
        for message in response.msgs {
            let Some(user_id) = message.sender_id() else {
                continue;
            };
            let text = message.text();
            if text.is_empty() {
                continue;
            }
            on_message(InboundMessage {
                user_id: user_id.to_string(),
                text,
                message_id: message.stable_id(),
            });
        }
    }
}
