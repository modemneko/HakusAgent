//! Local media attachment commands.

use std::path::{Path, PathBuf};

use crate::commands::CommandResult;
use crate::commands::traits::{CommandInfo, RegisterCommand};
use crate::localization::MessageId;
use crate::tui::app::App;

pub(in crate::commands) const COMMAND_INFO: CommandInfo = CommandInfo {
    name: "attach",
    aliases: &["image", "media", "fujian"],
    usage: "/attach <path>",
    description_id: MessageId::CmdAttachDescription,
};

pub(in crate::commands) struct AttachCmd;

impl RegisterCommand for AttachCmd {
    fn info() -> &'static CommandInfo {
        &COMMAND_INFO
    }

    fn execute(app: &mut App, arg: Option<&str>) -> CommandResult {
        attach(app, arg)
    }
}

fn attach(app: &mut App, arg: Option<&str>) -> CommandResult {
    let Some(raw_path) = arg.map(str::trim).filter(|value| !value.is_empty()) else {
        return CommandResult::error("Usage: /attach <image-or-video-path>");
    };

    let path = resolve_attachment_path(raw_path, &app.workspace);
    let Ok(path) = path.canonicalize() else {
        return CommandResult::error(format!("Attachment not found: {}", path.display()));
    };
    if !path.is_file() {
        return CommandResult::error(format!("Attachment is not a file: {}", path.display()));
    }

    let Some(kind) = media_kind(&path) else {
        return CommandResult::error(
            "Unsupported attachment type. /attach is for image/video paths; use @path for text files or directories.",
        );
    };

    // Validate an image here, not only at send time. The extension check above
    // trusts the filename; this reads the bytes, so a mislabelled, oversized or
    // corrupt file is refused while the user is still looking at the command
    // that caused it — rather than becoming a notice buried in a turn they have
    // already sent.
    if kind == "image"
        && let Err(error) = crate::image_attach::attach_image_from_path(&path)
    {
        return CommandResult::error(error.to_string());
    }

    app.insert_media_attachment(kind, &path, None);
    CommandResult::message(format!("Attached {kind}: {}", path.display()))
}

fn resolve_attachment_path(raw_path: &str, workspace: &Path) -> PathBuf {
    let unquoted = raw_path.trim().trim_matches('"').trim_matches('\'');
    let path = expand_home(unquoted);
    if path.is_absolute() {
        path
    } else {
        workspace.join(path)
    }
}

fn expand_home(path: &str) -> PathBuf {
    if path == "~" {
        if let Some(home) = std::env::var_os("HOME") {
            return PathBuf::from(home);
        }
    } else if let Some(rest) = path.strip_prefix("~/")
        && let Some(home) = std::env::var_os("HOME")
    {
        return PathBuf::from(home).join(rest);
    }
    PathBuf::from(path)
}

fn media_kind(path: &Path) -> Option<&'static str> {
    let ext = path.extension()?.to_str()?.to_ascii_lowercase();
    match ext.as_str() {
        "png" | "jpg" | "jpeg" | "gif" | "webp" | "bmp" | "tif" | "tiff" | "ppm" => Some("image"),
        "mp4" | "mov" | "m4v" | "webm" | "avi" | "mkv" => Some("video"),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::Config;
    use crate::tui::app::TuiOptions;
    use tempfile::TempDir;

    fn app_with_workspace(tmpdir: &TempDir) -> App {
        App::new(
            TuiOptions {
                use_alt_screen: false,
                skills_dir: tmpdir.path().join("skills"),
                memory_path: tmpdir.path().join("memory.md"),
                notes_path: tmpdir.path().join("notes.txt"),
                mcp_config_path: tmpdir.path().join("mcp.json"),
                ..crate::test_support::test_tui_options(tmpdir.path())
            },
            &Config::default(),
        )
    }

    /// A 1x1 PNG. `/attach` now reads the bytes, so the fixture has to be a
    /// real image rather than a plausible filename.
    const PNG_1X1: &[u8] = &[
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44,
        0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00, 0x00, 0x1f,
        0x15, 0xc4, 0x89, 0x00, 0x00, 0x00, 0x0a, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x63, 0x00,
        0x01, 0x00, 0x00, 0x05, 0x00, 0x01, 0x0d, 0x0a, 0x2d, 0xb4, 0x00, 0x00, 0x00, 0x00, 0x49,
        0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
    ];

    #[test]
    fn attach_inserts_image_reference() {
        let tmpdir = TempDir::new().expect("tempdir");
        let image_path = tmpdir.path().join("photo.png");
        std::fs::write(&image_path, PNG_1X1).expect("write image fixture");
        let mut app = app_with_workspace(&tmpdir);

        let result = attach(&mut app, Some("photo.png"));

        assert!(result.message.expect("message").contains("Attached image"));
        assert!(app.input.contains("[Attached image:"));
        let canonical_path = image_path.canonicalize().expect("canonical image path");
        assert!(app.input.contains(&canonical_path.display().to_string()));
    }

    #[test]
    fn attach_rejects_a_png_that_is_not_actually_an_image() {
        // The failure this guards against is a user attaching a file that
        // looks right, the turn going out, and the model reporting it cannot
        // see anything — with no clue why.
        let tmpdir = TempDir::new().expect("tempdir");
        std::fs::write(tmpdir.path().join("photo.png"), b"not actually decoded")
            .expect("write fixture");
        let mut app = app_with_workspace(&tmpdir);

        let result = attach(&mut app, Some("photo.png"));

        let message = result.message.expect("message");
        assert!(
            message.contains("not a PNG, JPEG, GIF or WebP"),
            "{message}"
        );
        assert!(
            app.input.is_empty(),
            "a refused attachment must not reach the composer"
        );
    }

    #[test]
    fn attach_rejects_an_image_over_the_size_limit() {
        let tmpdir = TempDir::new().expect("tempdir");
        let mut oversized = PNG_1X1.to_vec();
        oversized.resize(crate::image_attach::MAX_IMAGE_BYTES + 1, 0);
        std::fs::write(tmpdir.path().join("huge.png"), &oversized).expect("write fixture");
        let mut app = app_with_workspace(&tmpdir);

        let result = attach(&mut app, Some("huge.png"));

        let message = result.message.expect("message");
        assert!(message.contains("per-image limit"), "{message}");
        assert!(app.input.is_empty());
    }

    #[test]
    fn attach_rejects_unsupported_extension() {
        let tmpdir = TempDir::new().expect("tempdir");
        std::fs::write(tmpdir.path().join("notes.txt"), b"text").expect("write fixture");
        let mut app = app_with_workspace(&tmpdir);

        let result = attach(&mut app, Some("notes.txt"));

        assert!(
            result
                .message
                .expect("message")
                .contains("Unsupported attachment type")
        );
        assert!(app.input.is_empty());
    }
}
