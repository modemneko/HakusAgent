//! Low-level iLink HTTP client.

use crate::models::*;
use crate::state::{AccountState, WechatState};
use crate::{
    AUTH_TYPE, ILINK_APP_ID, ILINK_BASE, ILINK_CLIENT_VERSION,
    MAX_MSG_LENGTH, POLL_TIMEOUT_SECS, QR_EXPIRY_CHECK_SECS,
    USER_AGENT,
};
use base64::Engine;
use reqwest::header::{HeaderMap, HeaderValue, AUTHORIZATION, CONTENT_TYPE, USER_AGENT as UA_HEADER};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::RwLock;

/// A full-featured iLink client with built-in state persistence.
#[derive(Debug, Clone)]
pub struct IlLinkClient {
    http: reqwest::Client,
    state: Arc<WechatState>,
    /// Memoized account credentials (read from disk or set after login).
    account: Arc<RwLock<Option<AccountState>>>,
    /// Memoized per-user context tokens (for getupdates pagination).
    user_contexts: Arc<RwLock<HashMap<String, String>>>,
}

impl IlLinkClient {
    /// Create a new client with a given state directory.
    /// The HTTP client uses rustls (no native TLS dependency).
    pub fn new(state_dir: std::path::PathBuf) -> Self {
        // Install ring crypto provider for rustls.
        let _ = rustls::crypto::ring::default_provider().install_default();

        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(POLL_TIMEOUT_SECS + 10))
            .build()
            .expect("failed to build reqwest client");

        let state = WechatState::new(state_dir);
        let account = Arc::new(RwLock::new(
            state.load_account().ok().flatten(),
        ));
        let user_contexts = Arc::new(RwLock::new(
            state.load_user_contexts().unwrap_or_default(),
        ));

        Self {
            http,
            state: Arc::new(state),
            account,
            user_contexts,
        }
    }

    /// Create a client using the default state directory.
    pub fn with_default_state() -> Self {
        Self::new(WechatState::default_dir())
    }

    /// Borrow a shared reference to the state manager.
    pub fn state(&self) -> &WechatState {
        &self.state
    }

    // -- Auth helpers --------------------------------------------------------

    /// Returns `true` if we have persisted credentials.
    pub async fn is_logged_in(&self) -> bool {
        let acc = self.account.read().await;
        acc.as_ref().is_some_and(|a| !a.is_empty())
    }

    /// Read-only snapshot of the current account state.
    pub async fn account_snapshot(&self) -> Option<AccountState> {
        self.account.read().await.clone()
    }

    /// The base URL to use for API calls. After login this may differ
    /// from `ILINK_BASE` if the server returned a `redirect_host`.
    async fn base_url(&self) -> String {
        self.account
            .read()
            .await
            .as_ref()
            .map(|a| a.base_url.clone())
            .unwrap_or_else(|| ILINK_BASE.into())
    }

    /// Build the common header set for authenticated requests.
    async fn auth_headers(&self) -> Result<HeaderMap> {
        let acc = self.account.read().await;
        let acc = acc.as_ref().ok_or(WechatError::NotLoggedIn)?;

        let mut headers = HeaderMap::new();
        headers.insert(UA_HEADER, HeaderValue::from_static(USER_AGENT));
        headers.insert("iLink-App-Id", HeaderValue::from_static(ILINK_APP_ID));
        headers.insert(
            "iLink-App-ClientVersion",
            HeaderValue::from_str(&ILINK_CLIENT_VERSION.to_string()).map_err(|e| WechatError::Other(e.to_string()))?,
        );
        headers.insert("AuthorizationType", HeaderValue::from_static(AUTH_TYPE));
        headers.insert(
            AUTHORIZATION,
            HeaderValue::from_str(&format!("Bearer {}", acc.bot_token)).map_err(|e| WechatError::Other(e.to_string()))?,
        );
        // Random X-WECHAT-UIN: base64(random u32).
        let uin_bytes = rand::random::<u32>().to_le_bytes();
        let uin_b64 = base64::engine::general_purpose::STANDARD.encode(uin_bytes);
        headers.insert(
            "X-WECHAT-UIN",
            HeaderValue::from_str(&uin_b64).map_err(|e| WechatError::Other(e.to_string()))?,
        );
        headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
        Ok(headers)
    }

    /// Build headers for unauthenticated QR requests (no auth).
    fn qr_headers() -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(UA_HEADER, HeaderValue::from_static(USER_AGENT));
        headers.insert("iLink-App-Id", HeaderValue::from_static(ILINK_APP_ID));
        headers.insert(
            "iLink-App-ClientVersion",
            HeaderValue::from_str(&ILINK_CLIENT_VERSION.to_string()).unwrap_or_else(|_| HeaderValue::from_static("0")),
        );
        headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
        headers
    }

    // -- QR code -------------------------------------------------------------

    /// `GET /ilink/bot/get_bot_qrcode?bot_type=3`
    pub async fn get_qrcode(&self) -> Result<QrCodeResponse> {
        let url = format!("{ILINK_BASE}/ilink/bot/get_bot_qrcode?bot_type=3");
        let resp = self
            .http
            .get(&url)
            .headers(Self::qr_headers())
            .send()
            .await?;

        if !resp.status().is_success() {
            let status = resp.status().as_u16();
            let body = resp.text().await.unwrap_or_default();
            return Err(WechatError::Protocol { status, body });
        }
        let data: QrCodeResponse = resp.json().await?;
        tracing::info!(qrcode = %data.qrcode, "WeChat: QR code obtained");
        Ok(data)
    }

    /// `GET /ilink/bot/get_qrcode_status?qrcode=<token>`
    /// Performs a single (non-polling) status check.
    pub async fn get_qrcode_status(&self, qrcode_token: &str) -> Result<QrStatusResponse> {
        let url = format!(
            "{ILINK_BASE}/ilink/bot/get_qrcode_status?qrcode={qrcode_token}"
        );
        let resp = self
            .http
            .get(&url)
            .headers(Self::qr_headers())
            .timeout(Duration::from_secs(QR_EXPIRY_CHECK_SECS + 5))
            .send()
            .await?;

        if !resp.status().is_success() {
            let status = resp.status().as_u16();
            let body = resp.text().await.unwrap_or_default();
            return Err(WechatError::Protocol { status, body });
        }
        Ok(resp.json().await?)
    }

    // -- Message polling -----------------------------------------------------

    /// `POST /ilink/bot/getupdates` — long-poll for new messages.
    /// Returns the list of new messages and an updated context token.
    pub async fn get_updates(&self, user_id: Option<&str>) -> Result<GetUpdatesResponse> {
        let base = self.base_url().await;
        let url = format!("{base}/ilink/bot/getupdates");
        let headers = self.auth_headers().await?;

        // Resolve context_token for this user (if known).
        let context_token = if let Some(uid) = user_id {
            self.user_contexts.read().await.get(uid).cloned()
        } else {
            None
        };

        let body = GetUpdatesRequest {
            method: "getupdates".into(),
            context_token,
        };
        // ensure_ascii=false is the serde default; compact formatting.
        let body_json = serde_json::to_string(&body)?;

        tracing::debug!("WeChat: polling getupdates...");
        let resp = self
            .http
            .post(&url)
            .headers(headers)
            .body(body_json)
            .timeout(Duration::from_secs(POLL_TIMEOUT_SECS + 10))
            .send()
            .await?;

        if !resp.status().is_success() {
            let status = resp.status().as_u16();
            let body = resp.text().await.unwrap_or_default();
            return Err(WechatError::Protocol { status, body });
        }

        let result: GetUpdatesResponse = resp.json().await?;

        // Persist the updated context token.
        if let (Some(uid), Some(token)) = (user_id, &result.context_token) {
            if !token.is_empty() {
                self.user_contexts
                    .write()
                    .await
                    .insert(uid.into(), token.clone());
                if let Err(e) = self.state.save_user_context(uid, token) {
                    tracing::warn!("WeChat: failed to persist context_token: {e}");
                }
            }
        }

        tracing::debug!(count = result.msgs.len(), "WeChat: received messages");
        Ok(result)
    }

    /// Convenience: poll once and extract text messages with sender info.
    pub async fn poll_text_messages(
        &self,
    ) -> Result<Vec<(String, String, String)>> {
        let resp = self.get_updates(None).await?;
        let mut out = Vec::new();
        for msg in &resp.msgs {
            if msg.msg_type == "text" {
                let user = msg.from_user.clone().unwrap_or_default();
                let text = msg.text.clone().unwrap_or_default();
                let id = msg.stable_id();
                out.push((user, text, id));
            }
        }
        Ok(out)
    }

    // -- Send messages -------------------------------------------------------

    /// Send a text message.  Long texts are automatically chunked at
    /// `MAX_MSG_LENGTH` characters.
    pub async fn send_text(&self, to_user: &str, text: &str) -> Result<()> {
        let base = self.base_url().await;
        let headers = self.auth_headers().await?;

        if text.len() <= MAX_MSG_LENGTH {
            let req = SendMessageRequest::new(to_user, text);
            let body = serde_json::to_string(&req)?;
            self.post_json(&format!("{base}/ilink/bot/sendmessage"), &headers, &body)
                .await?;
        } else {
            // Chunk the message.
            for (i, chunk) in text.as_bytes().chunks(MAX_MSG_LENGTH).enumerate() {
                let chunk_str = String::from_utf8_lossy(chunk);
                let req = SendMessageRequest::new(to_user, &chunk_str);
                let body = serde_json::to_string(&req)?;
                self.post_json(&format!("{base}/ilink/bot/sendmessage"), &headers, &body)
                    .await?;
                // Brief pause between chunks to avoid rate-limiting.
                if i + MAX_MSG_LENGTH < text.len() {
                    tokio::time::sleep(Duration::from_millis(500)).await;
                }
            }
        }
        tracing::info!(to = %to_user, len = text.len(), "WeChat: message sent");
        Ok(())
    }

    /// Send a typing indicator.
    pub async fn send_typing(&self, to_user: &str, typing: bool) -> Result<()> {
        let base = self.base_url().await;
        let headers = self.auth_headers().await?;
        let req = SendTypingRequest::new(to_user, typing);
        let body = serde_json::to_string(&req)?;
        self.post_json(
            &format!("{base}/ilink/bot/sendtyping"),
            &headers,
            &body,
        )
        .await
    }

    /// `GET /ilink/bot/getconfig` — retrieve bot configuration.
    pub async fn get_config(&self) -> Result<BotConfigResponse> {
        let base = self.base_url().await;
        let headers = self.auth_headers().await?;
        let url = format!("{base}/ilink/bot/getconfig");
        let resp = self.http.get(&url).headers(headers).send().await?;

        if !resp.status().is_success() {
            let status = resp.status().as_u16();
            let body = resp.text().await.unwrap_or_default();
            return Err(WechatError::Protocol { status, body });
        }
        Ok(resp.json().await?)
    }

    // -- Login / logout ------------------------------------------------------

    /// Save credentials after a successful QR login.
    pub async fn save_login(&self, account_id: String, bot_token: String, base_url: String, route_tag: Option<String>) -> Result<()> {
        let state = AccountState {
            account_id,
            bot_token,
            base_url,
            route_tag,
        };
        self.state.save_account(&state)?;
        *self.account.write().await = Some(state);
        Ok(())
    }

    /// Update the base URL (e.g. after a `scaned_but_redirect` response).
    pub async fn set_base_url(&self, new_url: String) {
        let mut acc = self.account.write().await;
        if let Some(ref mut a) = *acc {
            a.base_url = new_url;
        }
    }

    /// Logout: clear credentials from memory and disk.
    pub async fn logout(&self) -> Result<()> {
        self.state.clear_account()?;
        *self.account.write().await = None;
        self.user_contexts.write().await.clear();
        tracing::info!("WeChat: logged out");
        Ok(())
    }

    // -- Internal ------------------------------------------------------------

    async fn post_json(&self, url: &str, headers: &HeaderMap, body: &str) -> Result<()> {
        let resp = self
            .http
            .post(url)
            .headers(headers.clone())
            .body(body.to_owned())
            .send()
            .await?;

        if !resp.status().is_success() {
            let status = resp.status().as_u16();
            let resp_body = resp.text().await.unwrap_or_default();
            return Err(WechatError::Protocol {
                status,
                body: resp_body,
            });
        }
        Ok(())
    }
}
