/**
 * HTTP commands for the Flow canvas node.
 *
 * The WebView CSP deliberately keeps `connect-src` at `'self'` (it is the one
 * thing that prevents a script injection from exfiltrating user data), so a
 * Flow "HTTP request" node cannot use `fetch`. This command performs the
 * request on the Rust side with reqwest instead — no CSP change, no CORS, and
 * full control over headers.
 *
 * reqwest is already compiled into the app (see embedded_backend.rs), so this
 * adds no new dependency.
 */

use std::collections::HashMap;
use std::time::Duration;

#[derive(serde::Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct HttpResponse {
    pub status: u16,
    pub ok: bool,
    pub headers: HashMap<String, String>,
    pub body: String,
    /// Parsed JSON when the response is JSON, otherwise null.
    pub json: Option<serde_json::Value>,
}

const DEFAULT_TIMEOUT_SECS: u64 = 15;
const MAX_TIMEOUT_SECS: u64 = 120;
/// Cap the response body so a huge payload cannot bloat the graph state.
const MAX_BODY_BYTES: usize = 512 * 1024;

fn method_from_str(raw: &str) -> Result<reqwest::Method, String> {
    match raw.trim().to_ascii_uppercase().as_str() {
        "GET" => Ok(reqwest::Method::GET),
        "POST" => Ok(reqwest::Method::POST),
        "PUT" => Ok(reqwest::Method::PUT),
        "PATCH" => Ok(reqwest::Method::PATCH),
        "DELETE" => Ok(reqwest::Method::DELETE),
        "HEAD" => Ok(reqwest::Method::HEAD),
        other => Err(format!("Unsupported HTTP method: {other}")),
    }
}

fn is_https_or_loopback(url: &str) -> bool {
    let lower = url.trim().to_ascii_lowercase();
    lower.starts_with("https://")
        || lower.starts_with("http://127.0.0.1")
        || lower.starts_with("http://localhost")
        || lower.starts_with("http://[::1]")
}

/// Perform one HTTP request. Returns status/headers/body (JSON parsed when
/// possible) rather than throwing, so the Flow node can branch on the result.
#[tauri::command]
pub async fn http_request(
    method: String,
    url: String,
    headers: Option<HashMap<String, String>>,
    body: Option<String>,
    timeout_secs: Option<u64>,
    allow_insecure_http: Option<bool>,
) -> Result<HttpResponse, String> {
    // Plain HTTP to a remote host is opt-in: it is trivially tamperable.
    if !allow_insecure_http.unwrap_or(false) && !is_https_or_loopback(&url) {
        return Err(
            "Refusing plain HTTP to a remote host. Use https, or enable the node's insecure-http option."
                .to_string(),
        );
    }

    let verb = method_from_str(&method)?;
    let timeout = Duration::from_secs(
        timeout_secs
            .unwrap_or(DEFAULT_TIMEOUT_SECS)
            .clamp(1, MAX_TIMEOUT_SECS),
    );

    let mut request = reqwest::Client::new()
        .request(verb, &url)
        .timeout(timeout);

    for (key, value) in headers.unwrap_or_default() {
        request = request.header(key, value);
    }
    if let Some(raw) = body {
        if !raw.is_empty() {
            request = request.body(raw);
        }
    }

    let response = request
        .send()
        .await
        .map_err(|e| format!("Request failed: {e}"))?;

    let status = response.status().as_u16();
    let mut header_map = HashMap::new();
    for (name, value) in response.headers().iter() {
        header_map.insert(
            name.as_str().to_string(),
            value.to_str().unwrap_or_default().to_string(),
        );
    }

    let bytes = response
        .bytes()
        .await
        .map_err(|e| format!("Failed to read response body: {e}"))?;
    let truncated = bytes.len() > MAX_BODY_BYTES;
    let body_text = if truncated {
        String::from_utf8_lossy(&bytes[..MAX_BODY_BYTES]).to_string()
    } else {
        String::from_utf8_lossy(&bytes).to_string()
    };
    let body_text = if truncated {
        format!("{body_text}\n…[truncated at {} bytes]", MAX_BODY_BYTES)
    } else {
        body_text
    };

    let json = serde_json::from_str::<serde_json::Value>(&body_text).ok();

    Ok(HttpResponse {
        status,
        ok: (200..300).contains(&status),
        headers: header_map,
        body: body_text,
        json,
    })
}
