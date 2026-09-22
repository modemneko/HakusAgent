//! Deterministic JSON argument repair for malformed tool-call inputs.
//!
//! DeepSeek streams `tool_calls.function.arguments` as deltas. Two failure
//! shapes are common: (a) SSE chunk boundary cuts inside a JSON string and
//! reassembly leaves a trailing comma or unclosed brace; (b) some local
//! backends emit literal control characters inside JSON string values.
//!
//! The repair ladder runs five stages before reporting unrecoverable input:
//!
//!  1. Strict parse — done if it parses.
//!  2. Strip literal control chars inside string values.
//!  3. Strip trailing commas before `}` or `]`.
//!  4. Balance braces/brackets (append closers).
//!  5. Strip excess closers if delta is negative.

use serde_json::Value;

/// Maximum raw argument length we'll attempt to repair (1 MiB).
const MAX_ARG_LEN: usize = 1024 * 1024;

#[derive(Debug, thiserror::Error)]
pub enum ArgRepairError {
    #[error("argument exceeded {0} chars; refusing to repair")]
    TooLarge(usize),
    #[error("argument could not be repaired into valid JSON")]
    Unrepairable,
}

/// Repair a raw JSON argument string into a valid `serde_json::Value`.
///
/// Runs the deterministic ladder; on success returns the parsed value.
pub fn repair(raw: &str) -> Result<Value, ArgRepairError> {
    if raw.len() > MAX_ARG_LEN {
        return Err(ArgRepairError::TooLarge(raw.len()));
    }
    let trimmed = raw.trim();
    // Stage 0: strict parse on the original (trimmed) input
    if let Ok(v) = serde_json::from_str(trimmed) {
        return Ok(v);
    }
    // Stage 0b: wrap a bare object-body fragment.
    //
    // Some gateways stream tool-call arguments that lost the opening `{`
    // (SSE chunk boundary or double-encoding), leaving bodies like
    // `"query": "shell git"` or `"path": "a.md", "line": 3`. Those are not
    // valid JSON by themselves, but wrapping them restores the object.
    if looks_like_object_body(trimmed) {
        let wrapped = format!("{{{trimmed}}}");
        if let Ok(v) = serde_json::from_str::<Value>(&wrapped) {
            if v.is_object() {
                return Ok(v);
            }
        }
        // Also try balancing the wrapped form (unclosed string, trailing comma).
        let wrapped_balanced = balance_braces(&strip_trailing_commas(&wrapped), 8);
        if let Ok(v) = serde_json::from_str::<Value>(&wrapped_balanced)
            && v.is_object()
        {
            return Ok(v);
        }
    }
    // Stage 2: strip control chars inside strings
    let mut s = strip_control_chars_in_strings(trimmed);
    if let Ok(v) = serde_json::from_str(&s) {
        return Ok(v);
    }
    // Stage 3: strip trailing commas
    s = strip_trailing_commas(&s);
    if let Ok(v) = serde_json::from_str(&s) {
        return Ok(v);
    }
    // Stage 4: balance braces
    s = balance_braces(&s, 50);
    if let Ok(v) = serde_json::from_str(&s) {
        return Ok(v);
    }
    // Stage 5: strip excess closers
    s = strip_excess_closers(&s);
    if let Ok(v) = serde_json::from_str(&s) {
        return Ok(v);
    }
    // Stage 6: concatenated object-form chunks — keep the last complete one.
    if let Some(v) = last_concatenated_object(&s) {
        return Ok(v);
    }
    // Stage 7: object keys missing their closing quote.
    let mut s = fix_unterminated_keys(&s);
    if let Ok(v) = serde_json::from_str(&s) {
        return Ok(v);
    }
    s = balance_braces(&strip_trailing_commas(&s), 50);
    if let Ok(v) = serde_json::from_str(&s) {
        return Ok(v);
    }
    // Stage 8: dangling `"key":` tail with no value — pad an empty string so
    // the tool's own validation feedback (instead of "malformed arguments")
    // guides the model's retry. Handles both `{"key":` and `{"key":}` (the
    // closer already re-appended by the balance stage above).
    let mut dangling = s.trim_end().to_string();
    if dangling.ends_with(":}") {
        dangling.pop();
    }
    if dangling.ends_with(':') {
        dangling.push_str(" \"\"");
        let dangling = balance_braces(&dangling, 8);
        if let Ok(v) = serde_json::from_str(&dangling) {
            return Ok(v);
        }
    }
    // Stage 8b: trailing junk after the key separator (e.g. a stray reopen
    // quote left by the quote-fix on `{"query:"` + balanced closer). Pad the
    // head through the last colon with an empty-string value.
    if let Some(colon) = s.rfind(':') {
        let head = s[..=colon].trim_end();
        if head.starts_with('{') && !head[1..].contains('{') {
            let candidate = balance_braces(&format!("{head} \"\""), 8);
            if let Ok(v) = serde_json::from_str(&candidate) {
                return Ok(v);
            }
        }
    }
    // Stage 9: bare object-body fragments with no braces at all — the
    // gateway dropped the opening `{` and the value start together
    // (observed on SenseNova/GLM: buffer ends up as `"query": `).
    // Wrap in braces, then repair the wrapped form through the same
    // unterminated-key / dangling-colon / balancing logic.
    if let Some(v) = repair_bare_body(&s) {
        return Ok(v);
    }
    Err(ArgRepairError::Unrepairable)
}

/// Stage 6 helper: recover arguments from concatenated object-form chunks.
///
/// Some gateways (SenseNova serving GLM among them) stream
/// `tool_calls.function.arguments` as an already-parsed JSON *object* that
/// carries the full arguments-so-far on every chunk. Serializing each chunk
/// into the delta pipeline and concatenating leaves `{...}{...}{...}`; the
/// last complete object is the authoritative final arguments.
///
/// Trailing empty objects (`{...}{}`) are skipped: an empty object carries no
/// arguments and would otherwise clobber the real ones, producing spurious
/// "missing required field" tool errors.
fn last_concatenated_object(s: &str) -> Option<Value> {
    if !s.contains("}{") && !s.contains("{}") {
        return None;
    }
    let bytes = s.as_bytes();
    let mut best: Option<Value> = None;
    for (idx, byte) in bytes.iter().enumerate() {
        if *byte != b'{' {
            continue;
        }
        if let Some(segment) = balanced_object_from(s, idx)
            && let Ok(value) = serde_json::from_str::<Value>(&segment)
            && value.is_object()
        {
            // Prefer non-empty objects; among equal "usefulness" keep the
            // latest (full-so-far resend semantics).
            let is_empty = value.as_object().is_some_and(|map| map.is_empty());
            if !is_empty || best.is_none() {
                best = Some(value);
            }
        }
    }
    best
}

/// Stage 9 helper: repair a bare object-body fragment that lost its braces —
/// e.g. `"query": `, `"query": "par`, `"a": 1, "b": `.
///
/// The fragment must start with a quoted key (see [`looks_like_object_body`]).
/// We wrap it in braces and run the wrapped form through unterminated-key
/// fixing, dangling-colon padding, and brace balancing.
fn repair_bare_body(s: &str) -> Option<Value> {
    let trimmed = s.trim();
    if !looks_like_object_body(trimmed) {
        return None;
    }
    // Close an unterminated value string (odd number of unescaped quotes).
    let quote_count = trimmed
        .chars()
        .scan(false, |escaped, ch| {
            let is_quote = !*escaped && ch == '"';
            *escaped = if *escaped {
                false
            } else {
                ch == '\\'
            };
            Some(is_quote)
        })
        .filter(|is_quote| *is_quote)
        .count();
    let closed = if quote_count % 2 == 1 {
        format!("{trimmed}\"")
    } else {
        trimmed.to_string()
    };
    // Pad a dangling `"key":` tail with an empty-string value.
    let padded = match closed.trim_end().strip_suffix(':') {
        Some(head) => format!("{head}: \"\""),
        None => closed,
    };
    let wrapped = format!("{{{padded}}}");
    let balanced = balance_braces(&strip_trailing_commas(&wrapped), 8);
    if let Ok(v) = serde_json::from_str::<Value>(&balanced)
        && v.is_object()
    {
        // A wrapped fragment that only produced an empty object means the
        // body carried no recoverable pairs — not a real repair.
        if !v.as_object().is_some_and(|map| map.is_empty()) {
            return Some(v);
        }
    }
    None
}

/// Extract the balanced `{...}` segment starting at byte offset `start`
/// (which must point at a `{`), honoring string literals.
fn balanced_object_from(s: &str, start: usize) -> Option<String> {
    let mut depth = 0i32;
    let mut in_string = false;
    let mut escape = false;
    for (offset, ch) in s[start..].char_indices() {
        if in_string {
            if escape {
                escape = false;
            } else if ch == '\\' {
                escape = true;
            } else if ch == '"' {
                in_string = false;
            }
            continue;
        }
        match ch {
            '"' => in_string = true,
            '{' => depth += 1,
            '}' => {
                depth -= 1;
                if depth == 0 {
                    return Some(s[start..start + offset + ch.len_utf8()].to_string());
                }
            }
            _ => {}
        }
    }
    None
}

/// Stage 7 helper: re-insert the closing quote of object keys that never
/// received one before the colon.
///
/// GLM-family models occasionally emit tool arguments with the key's closing
/// quote dropped: `{"query: "shell command"}`. Walk the string tracking JSON
/// structure; when a key-position quote (right after `{` or `,` inside an
/// object) reaches an unescaped `:` without a closing `"`, insert one.
fn fix_unterminated_keys(s: &str) -> String {
    let trimmed = s.trim_start();
    if !trimmed.starts_with('{') {
        return s.to_string();
    }
    let chars: Vec<char> = s.chars().collect();
    let mut out = String::with_capacity(s.len() + 4);
    // Bracket stack: only a `{` on top makes the next quote a key position.
    let mut stack: Vec<char> = Vec::new();
    let mut in_string = false;
    let mut escape = false;
    // Scanning a suspect key: an open quote in key position that must close
    // before the first unescaped `:` to stay valid.
    let mut key_scan = false;
    // True right after a key separator `:` — the next quote opens a value,
    // never a key (values may legitimately contain colons).
    let mut value_pos = false;
    for &ch in &chars {
        if in_string {
            if key_scan && !escape && ch == ':' {
                // Unterminated key: close the quote right before the colon
                // (dropping any stray whitespace inside the key).
                while out.ends_with([' ', '\t']) {
                    out.pop();
                }
                out.push('"');
                out.push(':');
                key_scan = false;
                in_string = false;
                value_pos = true;
                continue;
            }
            out.push(ch);
            if escape {
                escape = false;
            } else if ch == '\\' {
                escape = true;
            } else if ch == '"' {
                in_string = false;
                key_scan = false;
            }
            continue;
        }
        match ch {
            '"' => {
                in_string = true;
                key_scan = stack.last() == Some(&'{') && !value_pos;
                out.push(ch);
            }
            '{' | '[' => {
                stack.push(ch);
                value_pos = false;
                out.push(ch);
            }
            '}' | ']' => {
                stack.pop();
                value_pos = false;
                out.push(ch);
            }
            ':' => {
                value_pos = true;
                out.push(ch);
            }
            ',' => {
                value_pos = false;
                out.push(ch);
            }
            _ => out.push(ch),
        }
    }
    out
}

/// Heuristic: the string looks like the *body* of a JSON object rather than
/// a complete value — e.g. `"query": "x"` or `"path": "a", "line": 1`.
///
/// Deliberately conservative: only fires when the trimmed input starts with a
/// double-quoted key and does not start with `{`/`[`/`"` (a bare JSON string)
/// and is not a bare primitive.
fn looks_like_object_body(s: &str) -> bool {
    let t = s.trim_start();
    if t.is_empty() {
        return false;
    }
    // Must start with a quoted key
    if !t.starts_with('"') {
        return false;
    }
    // A complete JSON string value is `"...."` with no trailing colon after it
    // at depth 0. An object body has `"key":` at the start.
    // Find the closing quote of the first key.
    let mut i = 1usize;
    let bytes = t.as_bytes();
    let mut closed = false;
    while i < bytes.len() {
        match bytes[i] {
            b'\\' => i += 2,
            b'"' => {
                closed = true;
                i += 1;
                break;
            }
            _ => i += 1,
        }
    }
    if !closed {
        return false;
    }
    // After the key there must be optional whitespace then `:`
    let rest = t[i..].trim_start();
    rest.starts_with(':')
}

/// Strip ASCII control characters (0x00–0x1F except \t, \n, \r) that appear
/// inside JSON string values. We walk character-by-character tracking whether
/// we're inside a string (between unescaped double-quotes).
fn strip_control_chars_in_strings(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut in_string = false;
    let mut escape = false;
    for ch in s.chars() {
        if escape {
            out.push(ch);
            escape = false;
            continue;
        }
        if ch == '\\' {
            escape = true;
            out.push(ch);
            continue;
        }
        if ch == '"' {
            in_string = !in_string;
            out.push(ch);
            continue;
        }
        if in_string && (ch as u32) < 0x20 && ch != '\t' && ch != '\n' && ch != '\r' {
            // Drop control characters inside strings
            continue;
        }
        out.push(ch);
    }
    out
}

/// Strip trailing commas before `}` or `]`.
fn strip_trailing_commas(s: &str) -> String {
    // Repeatedly replace ",}" and ",]" until stable (handles nested cases).
    let mut out = s.to_string();
    loop {
        let prev = out.clone();
        out = out.replace(",}", "}").replace(",]", "]");
        // Handle trailing comma at end of string
        out = out.trim_end_matches(',').to_string();
        if out == prev {
            break;
        }
    }
    out
}

/// Balance braces and brackets: count `{`/`}` and `[`/`]`, append closers if
/// positive delta (more opens than closes). Caps iterations so a
/// catastrophically broken input doesn't loop forever.
fn balance_braces(s: &str, max_iter: usize) -> String {
    let mut out = s.to_string();
    for _ in 0..max_iter {
        let brace_delta: i32 = out
            .chars()
            .map(|ch| match ch {
                '{' => 1,
                '}' => -1,
                _ => 0,
            })
            .sum();
        let bracket_delta: i32 = out
            .chars()
            .map(|ch| match ch {
                '[' => 1,
                ']' => -1,
                _ => 0,
            })
            .sum();
        if brace_delta <= 0 && bracket_delta <= 0 {
            break;
        }
        // Append needed closers in reverse order (brackets before braces
        // for correct nesting when both are unbalanced).
        for _ in 0..bracket_delta.max(0) {
            out.push(']');
        }
        for _ in 0..brace_delta.max(0) {
            out.push('}');
        }
    }
    out
}

/// Strip excess closers when the delta is negative (more closes than opens).
fn strip_excess_closers(s: &str) -> String {
    let mut brace_depth: i32 = 0;
    let mut bracket_depth: i32 = 0;
    let mut out = String::with_capacity(s.len());
    for ch in s.chars() {
        match ch {
            '}' => {
                if brace_depth > 0 {
                    brace_depth -= 1;
                    out.push(ch);
                }
                // else drop excess closer
            }
            ']' => {
                if bracket_depth > 0 {
                    bracket_depth -= 1;
                    out.push(ch);
                }
            }
            '{' => {
                brace_depth += 1;
                out.push(ch);
            }
            '[' => {
                bracket_depth += 1;
                out.push(ch);
            }
            _ => out.push(ch),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn strict_parse_passes_through() {
        let v = repair(r#"{"path": "hello.txt"}"#).unwrap();
        assert_eq!(v, json!({"path": "hello.txt"}));
    }

    #[test]
    fn repairs_trailing_comma() {
        let v = repair(r#"{"path": "hello.txt",}"#).unwrap();
        assert_eq!(v, json!({"path": "hello.txt"}));
    }

    #[test]
    fn repairs_trailing_comma_in_array() {
        let v = repair(r#"["a", "b",]"#).unwrap();
        assert_eq!(v, json!(["a", "b"]));
    }

    #[test]
    fn repairs_missing_close_brace() {
        let v = repair(r#"{"path": "hello.txt""#).unwrap();
        assert_eq!(v, json!({"path": "hello.txt"}));
    }

    #[test]
    fn repairs_missing_close_bracket() {
        let v = repair(r#"["a", "b""#).unwrap();
        assert_eq!(v, json!(["a", "b"]));
    }

    #[test]
    fn strips_embedded_control_chars() {
        // Raw \x0B (vertical tab) inside a string value
        let raw = "{\"key\": \"val\x0Bue\"}";
        let v = repair(raw).unwrap();
        assert_eq!(v, json!({"key": "value"}));
    }

    #[test]
    fn rejects_empty_string() {
        assert!(matches!(repair(""), Err(ArgRepairError::Unrepairable)));
    }

    #[test]
    fn rejects_gibberish() {
        assert!(matches!(
            repair("not json at all"),
            Err(ArgRepairError::Unrepairable)
        ));
    }

    #[test]
    fn balances_nested_braces() {
        let v = repair(r#"{"outer": {"inner": "val""#).unwrap();
        assert_eq!(v, json!({"outer": {"inner": "val"}}));
    }

    #[test]
    fn strips_excess_closers() {
        let v = repair(r#"{"key": "val"}}"#).unwrap();
        assert_eq!(v, json!({"key": "val"}));
    }

    #[test]
    fn handles_double_encoded_json() {
        // This is a valid JSON string containing a JSON object literal.
        // repair parses it as a string; the engine's existing fallback
        // (parse_tool_input) will unwrap the string and re-parse.
        let v = repair(r#""{\"path\": \"hello.txt\"}""#).unwrap();
        assert_eq!(v, Value::String(r#"{"path": "hello.txt"}"#.to_string()));
    }

    #[test]
    fn oversize_input_rejected() {
        let big = "x".repeat(MAX_ARG_LEN + 1);
        assert!(repair(&big).is_err());
    }

    #[test]
    fn repairs_brace_balance_with_trailing_comma() {
        let v = repair(r#"{"a": 1,"#).unwrap();
        assert_eq!(v, json!({"a": 1}));
    }

    #[test]
    fn keeps_last_of_concatenated_object_chunks() {
        // Object-form gateways resend the full arguments-so-far per chunk.
        let v = repair(r#"{}{"query": "shell command"}"#).unwrap();
        assert_eq!(v, json!({"query": "shell command"}));
        let v = repair(r#"{"query": "s"}{"query": "shell command"}"#).unwrap();
        assert_eq!(v, json!({"query": "shell command"}));
    }

    #[test]
    fn repairs_unterminated_key_quote() {
        let v = repair(r#"{"query: "shell command"}"#).unwrap();
        assert_eq!(v, json!({"query": "shell command"}));
    }

    #[test]
    fn repairs_unterminated_key_with_dangling_colon() {
        let v = repair(r#"{"query:""#).unwrap();
        assert_eq!(v, json!({"query": ""}));
    }

    #[test]
    fn value_strings_with_colons_untouched() {
        let v = repair(r#"{"url": "http://x", "a": 1}"#).unwrap();
        assert_eq!(v, json!({"url": "http://x", "a": 1}));
    }

    #[test]
    fn repairs_trailing_empty_object_in_concatenated_chunks() {
        // Trailing `{}` must not clobber the real arguments.
        let v = repair(r#"{"query": "shell command"}{}"#).unwrap();
        assert_eq!(v, json!({"query": "shell command"}));
    }

    #[test]
    fn repairs_bare_body_dangling_colon_no_braces() {
        // Observed on SenseNova/GLM: `{` and value start both lost.
        let v = repair(r#""query": "#).unwrap();
        assert_eq!(v, json!({"query": ""}));
    }

    #[test]
    fn repairs_bare_body_unclosed_value_string() {
        let v = repair(r#""query": "shell git"#).unwrap();
        assert_eq!(v, json!({"query": "shell git"}));
    }

    #[test]
    fn repairs_bare_body_multiple_pairs() {
        let v = repair(r#""path": "a.md", "line": 3"#).unwrap();
        assert_eq!(v, json!({"path": "a.md", "line": 3}));
    }
}
