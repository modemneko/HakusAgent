//! Serde structures for the iLink protocol request/response bodies.

use serde::{Deserialize, Serialize};
use serde_json::Value;

// ---------------------------------------------------------------------------
// QR code login
// ---------------------------------------------------------------------------

/// Response from `GET /ilink/bot/get_bot_qrcode`.
#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct QrCodeResponse {
    /// The opaque QR token string (used in subsequent status polls).
    #[serde(default)]
    pub qrcode: String,
    /// Base64-encoded QR code image content (PNG typically).
    #[serde(default)]
    pub qrcode_img_content: String,
}

/// Response from `GET /ilink/bot/get_qrcode_status`.
#[derive(Debug, Clone, Deserialize)]
pub struct QrStatusResponse {
    /// One of: `wait`, `scaned`, `scaned_but_redirect`, `expired`, `confirmed`.
    pub status: String,
    /// Present when `status == "confirmed"`.
    #[serde(default)]
    pub ilink_bot_id: Option<String>,
    /// Present when `status == "confirmed"`.
    #[serde(default)]
    pub bot_token: Option<String>,
    /// Present when `status == "confirmed"` — the API base URL to use.
    #[serde(default)]
    pub baseurl: Option<String>,
    /// Present when `status == "confirmed"` — optional route tag.
    #[serde(default)]
    pub route_tag: Option<String>,
    /// If `status == "scaned_but_redirect"`, provides the redirect host.
    #[serde(default, rename = "redirect_host")]
    pub redirect_host: Option<String>,
}

/// Possible QR login states exposed to callers.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum QrLoginStatus {
    /// QR generated, waiting for scan.
    Waiting,
    /// QR scanned by user, awaiting confirmation.
    Scanned,
    /// Login confirmed — session is ready.
    Confirmed {
        account_id: String,
        bot_token: String,
        base_url: String,
        route_tag: Option<String>,
    },
    /// QR expired — must generate a new one.
    Expired,
    /// Server returned `scaned_but_redirect` — caller should switch base URL
    /// and continue polling.
    Redirect { redirect_host: String },
}

// ---------------------------------------------------------------------------
// Message polling
// ---------------------------------------------------------------------------

/// Request body for `POST /ilink/bot/getupdates`.
#[derive(Debug, Clone, Serialize)]
pub struct GetUpdatesRequest {
    /// Opaque cursor returned by the previous response.
    pub get_updates_buf: String,
    /// Required protocol metadata.
    pub base_info: BaseInfo,
}

impl Default for GetUpdatesRequest {
    fn default() -> Self {
        Self {
            get_updates_buf: String::new(),
            base_info: BaseInfo::default(),
        }
    }
}

/// Response from `POST /ilink/bot/getupdates`.
#[derive(Debug, Clone, Deserialize)]
pub struct GetUpdatesResponse {
    #[serde(default)]
    pub msgs: Vec<WeixinMessage>,
    /// Opaque cursor for the next poll.
    #[serde(default)]
    pub get_updates_buf: Option<String>,
}

/// A single inbound WeChat message from iLink.
#[derive(Debug, Clone, Deserialize)]
pub struct WeixinMessage {
    /// Numeric iLink message type. `2` is a normal user message.
    #[serde(default, alias = "type")]
    pub message_type: i32,
    /// Sender user ID (string in iLink).
    #[serde(default, alias = "from_user")]
    pub from_user_id: Option<String>,
    /// iLink content items.
    #[serde(default)]
    pub item_list: Vec<MessageItem>,
    /// Conversation token required when replying to this message.
    #[serde(default)]
    pub context_token: Option<String>,
    /// Image URL for image messages.
    #[serde(default)]
    pub image: Option<String>,
    /// Server-side message ID.
    #[serde(default, rename = "msg_id")]
    pub msg_id: Option<String>,
    /// Server-side timestamp (seconds).
    #[serde(default, rename = "create_time")]
    pub create_time: Option<i64>,
    /// Raw message payload (passthrough for unknown fields).
    #[serde(flatten)]
    pub extra: Value,
}

impl WeixinMessage {
    /// Extract a stable message ID for deduplication.
    /// Falls back to `from_user:text:create_time` composite.
    pub fn stable_id(&self) -> String {
        if let Some(id) = &self.msg_id {
            if !id.is_empty() {
                return format!("msg_id:{id}");
            }
        }
        let user = self.from_user_id.as_deref().unwrap_or("");
        let ts = self.create_time.unwrap_or(0);
        let text = self.text();
        format!("cmp:{user}:{ts}:{text}")
    }

    /// Sender id.
    pub fn sender_id(&self) -> Option<&str> {
        self.from_user_id.as_deref()
    }

    /// Extract concatenated text items from the message.
    pub fn text(&self) -> String {
        self.item_list
            .iter()
            .filter_map(|item| item.text_item.as_ref())
            .map(|item| item.text.as_str())
            .collect::<Vec<_>>()
            .join("")
    }
}

/// One item in an iLink message body.
#[derive(Debug, Clone, Deserialize)]
pub struct MessageItem {
    #[serde(default, rename = "type")]
    pub item_type: i32,
    #[serde(default)]
    pub text_item: Option<TextItem>,
}

/// Text payload inside a message item.
#[derive(Debug, Clone, Deserialize)]
pub struct TextItem {
    #[serde(default)]
    pub text: String,
}

// ---------------------------------------------------------------------------
// Sending messages
// ---------------------------------------------------------------------------

/// Request body for `POST /ilink/bot/sendmessage`.
#[derive(Debug, Clone, Serialize)]
pub struct SendMessageRequest {
    /// Complete outbound message envelope.
    pub msg: OutboundMessage,
    /// Required base_info wrapper.
    pub base_info: BaseInfo,
}

impl SendMessageRequest {
    pub fn new(from_user: &str, to_user: &str, text: &str, context_token: &str) -> Self {
        Self {
            msg: OutboundMessage {
                from_user_id: from_user.into(),
                to_user_id: to_user.into(),
                client_id: uuid::Uuid::new_v4().to_string(),
                message_type: 2,
                message_state: 2,
                item_list: vec![MessageItemOut {
                    item_type: 1,
                    text_item: TextItemOut { text: text.into() },
                }],
                context_token: context_token.into(),
            },
            base_info: BaseInfo::default(),
        }
    }
}

/// iLink outbound message envelope.
#[derive(Debug, Clone, Serialize)]
pub struct OutboundMessage {
    pub from_user_id: String,
    pub to_user_id: String,
    pub client_id: String,
    pub message_type: i32,
    pub message_state: i32,
    pub item_list: Vec<MessageItemOut>,
    pub context_token: String,
}

/// Outbound text item.
#[derive(Debug, Clone, Serialize)]
pub struct MessageItemOut {
    #[serde(rename = "type")]
    pub item_type: i32,
    pub text_item: TextItemOut,
}

#[derive(Debug, Clone, Serialize)]
pub struct TextItemOut {
    pub text: String,
}

// ---------------------------------------------------------------------------
// Typing indicator
// ---------------------------------------------------------------------------

/// Request body for `POST /ilink/bot/sendtyping`.
#[derive(Debug, Clone, Serialize)]
pub struct SendTypingRequest {
    /// Always `"sendtyping"`.
    pub method: String,
    /// Target user ID.
    pub to_user: String,
    /// Typing status: 1 = typing, 0 = cancel.
    pub typing: u8,
    /// Required base_info wrapper.
    pub base_info: BaseInfo,
}

impl SendTypingRequest {
    pub fn new(to_user: &str, typing: bool) -> Self {
        Self {
            method: "sendtyping".into(),
            to_user: to_user.into(),
            typing: if typing { 1 } else { 0 },
            base_info: BaseInfo::default(),
        }
    }
}

// ---------------------------------------------------------------------------
// Shared structures
// ---------------------------------------------------------------------------

/// `base_info` wrapper required in most request bodies.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BaseInfo {
    pub channel_version: String,
}

impl Default for BaseInfo {
    fn default() -> Self {
        Self {
            channel_version: super::CHANNEL_VERSION.into(),
        }
    }
}

/// Response from `GET /ilink/bot/getconfig`.
#[derive(Debug, Clone, Deserialize)]
pub struct BotConfigResponse {
    #[serde(default, rename = "bot_name")]
    pub bot_name: Option<String>,
    #[serde(default, rename = "bot_type")]
    pub bot_type: Option<String>,
    #[serde(flatten)]
    pub extra: Value,
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/// Unified error type for wechat operations.
#[derive(Debug, thiserror::Error)]
pub enum WechatError {
    #[error("iLink HTTP error: {0}")]
    Http(#[from] reqwest::Error),

    #[error("iLink protocol error: {status} — {body}")]
    Protocol { status: u16, body: String },

    #[error("WeChat not logged in")]
    NotLoggedIn,

    #[error("QR code expired")]
    QrExpired,

    #[error("Login flow cancelled")]
    LoginCancelled,

    #[error("State I/O error: {0}")]
    StateIo(#[from] std::io::Error),

    #[error("State parse error: {0}")]
    StateParse(#[from] serde_json::Error),

    #[error("{0}")]
    Other(String),
}

pub type Result<T> = std::result::Result<T, WechatError>;
