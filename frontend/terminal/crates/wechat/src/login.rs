//! QR login state machine.

use base64::Engine;
use crate::client::IlLinkClient;
use crate::models::{QrLoginStatus, QrStatusResponse, WechatError};
use crate::QR_POLL_INTERVAL_SECS;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tokio::sync::Notify;
use tokio::time::{Duration, sleep};

/// A handle to an in-progress QR login flow.
///
/// The flow runs in the background.  Callers can:
/// 1. Read the initial QR data via [`LoginHandle::qr_data`].
/// 2. Wait for completion via [`LoginHandle::wait`].
/// 3. Cancel via [`LoginHandle::cancel`].
#[derive(Debug)]
pub struct LoginHandle {
    /// The raw `qrcode` token string.
    pub qr_token: String,
    /// Base64-encoded QR image content.
    pub qr_image_b64: String,
    /// Notified when the login completes or is cancelled.
    done: Arc<Notify>,
    /// Shared cancellation flag.
    cancelled: Arc<AtomicBool>,
    /// Final status (set on completion).
    status: Arc<tokio::sync::Mutex<Option<QrLoginStatus>>>,
}

impl LoginHandle {
    /// Block until the login flow finishes, returning the final status.
    /// If cancelled, returns `Err(WechatError::LoginCancelled)`.
    pub async fn wait(&self) -> crate::models::Result<QrLoginStatus> {
        self.done.notified().await;
        let mut guard = self.status.lock().await;
        guard.take().ok_or(WechatError::LoginCancelled)
    }

    /// Cancel the login flow.
    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::Relaxed);
        self.done.notify_waiters();
    }

    /// Whether the flow has been cancelled.
    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::Relaxed)
    }

    /// Read the current status (non-blocking).
    pub async fn current_status(&self) -> Option<QrLoginStatus> {
        self.status.lock().await.clone()
    }
}

/// Start a QR login flow on `client`.
///
/// 1. Calls `get_bot_qrcode` to obtain the QR data.
/// 2. Spawns a background task that polls `get_qrcode_status`
///    until the user scans, confirms, or the QR expires.
/// 3. On confirmation, persists credentials via `client.save_login()`.
/// 4. Returns a [`LoginHandle`] the caller can use to wait or cancel.
pub async fn start_qr_login(client: &IlLinkClient) -> crate::models::Result<LoginHandle> {
    let qr_resp = client.get_qrcode().await?;

    // The SDK sometimes returns a URL instead of base64 image data.
    // Convert URL to a base64 PNG using the `qrcode` crate if available,
    // or just use the raw content as-is.
    let qr_image_b64 = if !qr_resp.qrcode_img_content.is_empty() {
        qr_resp.qrcode_img_content.clone()
    } else if qr_resp.qrcode.starts_with("http") {
        // No image content, but we have a URL — the TUI command
        // layer will render a text-based QR from the token instead.
        base64::engine::general_purpose::STANDARD
            .encode(qr_resp.qrcode.as_bytes())
    } else {
        qr_resp.qrcode.clone()
    };

    let done = Arc::new(Notify::new());
    let cancelled = Arc::new(AtomicBool::new(false));
    let status: Arc<tokio::sync::Mutex<Option<QrLoginStatus>>> =
        Arc::new(tokio::sync::Mutex::new(None));

    let client_handle = client.clone();
    let qr_token = qr_resp.qrcode.clone();
    let done_clone = done.clone();
    let cancelled_clone = cancelled.clone();
    let status_clone = status.clone();

    // Spawn the background poll loop.
    tokio::spawn(async move {
        loop {
            if cancelled_clone.load(Ordering::Relaxed) {
                return;
            }

            match client_handle.get_qrcode_status(&qr_token).await {
                Ok(resp) => {
                    let parsed = parse_qr_status(resp);
                    match &parsed {
                        QrLoginStatus::Waiting => {
                            // Still waiting for scan.
                        }
                        QrLoginStatus::Scanned => {
                            // Scanned but not confirmed yet.
                            let mut s = status_clone.lock().await;
                            *s = Some(parsed);
                        }
                        QrLoginStatus::Confirmed {
                            account_id,
                            bot_token,
                            base_url,
                            route_tag,
                        } => {
                            // Login success!
                            if let Err(e) = client_handle
                                .save_login(
                                    account_id.clone(),
                                    bot_token.clone(),
                                    base_url.clone(),
                                    route_tag.clone(),
                                )
                                .await
                            {
                                tracing::error!("WeChat: failed to save login: {e}");
                            }
                            let mut s = status_clone.lock().await;
                            *s = Some(parsed);
                            done_clone.notify_waiters();
                            return;
                        }
                        QrLoginStatus::Expired => {
                            let mut s = status_clone.lock().await;
                            *s = Some(QrLoginStatus::Expired);
                            done_clone.notify_waiters();
                            return;
                        }
                        QrLoginStatus::Redirect { redirect_host } => {
                            // Switch to the redirect host and continue polling.
                            let new_url = format!("https://{redirect_host}");
                            client_handle.set_base_url(new_url).await;
                        }
                    }
                }
                Err(e) => {
                    tracing::warn!("WeChat: QR status poll error: {e}");
                }
            }

            sleep(Duration::from_secs(QR_POLL_INTERVAL_SECS)).await;
        }
    });

    Ok(LoginHandle {
        qr_token: qr_resp.qrcode,
        qr_image_b64,
        done,
        cancelled,
        status,
    })
}

/// Map the raw `QrStatusResponse` into a typed `QrLoginStatus`.
fn parse_qr_status(resp: QrStatusResponse) -> QrLoginStatus {
    match resp.status.as_str() {
        "wait" => QrLoginStatus::Waiting,
        "scaned" => QrLoginStatus::Scanned,
        "scaned_but_redirect" => QrLoginStatus::Redirect {
            redirect_host: resp.redirect_host.unwrap_or_default(),
        },
        "expired" => QrLoginStatus::Expired,
        "confirmed" => {
            QrLoginStatus::Confirmed {
                account_id: resp
                    .ilink_bot_id
                    .unwrap_or_default(),
                bot_token: resp.bot_token.unwrap_or_default(),
                base_url: resp
                    .baseurl
                    .unwrap_or_else(|| crate::ILINK_BASE.into()),
                route_tag: resp.route_tag,
            }
        }
        other => {
            tracing::warn!("WeChat: unknown QR status: {other}");
            QrLoginStatus::Waiting
        }
    }
}
