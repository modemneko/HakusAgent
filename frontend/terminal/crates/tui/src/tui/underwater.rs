//! Coherent shell grammar for the underwater TUI.
//!
//! This module owns phase, responsive density, the empty-state composition,
//! and the compact header/footer fact budget. Product data still belongs to
//! [`App`]; this is only its terminal projection. Keeping these decisions in
//! one place prevents the default UI from drifting back into a header +
//! sidebar + dashboard + footer composition with four owners for one fact.

use std::borrow::Cow;

use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use ratatui::{
    buffer::Buffer,
    layout::Rect,
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Paragraph, Widget},
};
use unicode_width::UnicodeWidthStr;

use crate::config::HeaderItem;
use crate::localization::{Locale, MessageId, tr};
use crate::palette::{ChromeInk, chrome_style};
use crate::tui::{
    app::{App, AppMode, OnboardingState},
    approval::ApprovalMode,
    footer_ui::format_token_count_compact,
    views::ModalKind,
};

/// Responsive density tier. It changes how much truth is shown, never the
/// underlying state grammar.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ShellTier {
    Compact,
    Normal,
    Wide,
}

const LAUNCH_ROWS: [(MessageId, &str); 6] = [
    (MessageId::LaunchMenuWork, "Enter"),
    (MessageId::LaunchMenuChat, "C"),
    (MessageId::LaunchMenuResumeSession, "Ctrl+R"),
    (MessageId::LaunchMenuNewWorktree, "Ctrl+N"),
    (MessageId::LaunchMenuChangelog, "Ctrl+L"),
    (MessageId::LaunchMenuQuit, "Ctrl+Q"),
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LaunchAction {
    None,
    NewSession,
    NewChat,
    CreateWorktree(String),
    Resume,
    Changelog,
    Quit,
}

impl LaunchAction {
    /// Session-only mode selected by a launch choice. The event loop applies
    /// this with `App::set_mode`, never the startup-default-writing selector.
    #[must_use]
    pub const fn session_mode(&self) -> Option<AppMode> {
        match self {
            Self::NewSession => Some(AppMode::Agent),
            Self::NewChat => Some(AppMode::Plan),
            _ => None,
        }
    }
}

/// Translate launch-menu input into one product action. Direct reliable keys
/// and row navigation share this path, so the printed key column cannot drift
/// away from the handler.
pub fn handle_launch_key(
    launch: &mut crate::tui::app::LaunchState,
    key: KeyEvent,
    locale: Locale,
) -> LaunchAction {
    if let Some(input) = launch.worktree_input.as_mut() {
        return match key.code {
            KeyCode::Esc => {
                launch.worktree_input = None;
                launch.status = None;
                LaunchAction::None
            }
            KeyCode::Enter => {
                let name = input.trim().to_string();
                launch.worktree_input = None;
                LaunchAction::CreateWorktree(name)
            }
            KeyCode::Backspace => {
                input.pop();
                LaunchAction::None
            }
            KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                launch.worktree_input = None;
                launch.status = None;
                LaunchAction::None
            }
            KeyCode::Char(ch)
                if !key.modifiers.intersects(
                    KeyModifiers::CONTROL | KeyModifiers::ALT | KeyModifiers::SUPER,
                ) =>
            {
                input.push(ch);
                LaunchAction::None
            }
            _ => LaunchAction::None,
        };
    }

    let direct = match key.code {
        KeyCode::Char('c') | KeyCode::Char('C')
            if !key
                .modifiers
                .intersects(KeyModifiers::CONTROL | KeyModifiers::ALT | KeyModifiers::SUPER) =>
        {
            Some(1)
        }
        KeyCode::Char('r') if key.modifiers.contains(KeyModifiers::CONTROL) => Some(2),
        KeyCode::Char('n') if key.modifiers.contains(KeyModifiers::CONTROL) => Some(3),
        KeyCode::Char('l') if key.modifiers.contains(KeyModifiers::CONTROL) => Some(4),
        KeyCode::Char('q') if key.modifiers.contains(KeyModifiers::CONTROL) => Some(5),
        _ => None,
    };
    if let Some(selected) = direct {
        launch.selected = selected;
    } else {
        match key.code {
            KeyCode::Up | KeyCode::Char('k') => {
                launch.selected = launch.selected.saturating_sub(1);
                return LaunchAction::None;
            }
            KeyCode::Down | KeyCode::Char('j') => {
                launch.selected = (launch.selected + 1).min(LAUNCH_ROWS.len() - 1);
                return LaunchAction::None;
            }
            KeyCode::Enter => {}
            _ => return LaunchAction::None,
        }
    }

    match launch.selected {
        0 => LaunchAction::NewSession,
        1 => LaunchAction::NewChat,
        2 => LaunchAction::Resume,
        3 if launch.worktree_available => {
            launch.worktree_input = Some(String::new());
            launch.status = Some(tr(locale, MessageId::LaunchWorktreePrompt).into_owned());
            LaunchAction::None
        }
        3 => {
            launch.status = Some(tr(locale, MessageId::LaunchWorktreeNeedsGit).into_owned());
            LaunchAction::None
        }
        4 => LaunchAction::Changelog,
        5 => LaunchAction::Quit,
        _ => LaunchAction::None,
    }
}

impl ShellTier {
    #[must_use]
    pub fn for_area(area: Rect) -> Self {
        if area.width < 60 || area.height < 16 {
            Self::Compact
        } else if area.width < 110 || area.height < 30 {
            Self::Normal
        } else {
            Self::Wide
        }
    }

    #[must_use]
    pub fn for_chrome_width(width: u16) -> Self {
        if width < 60 {
            Self::Compact
        } else if width < 110 {
            Self::Normal
        } else {
            Self::Wide
        }
    }
}

/// Perceptual session phase. Every treatment reads from this same enum so a
/// footer cannot say `idle` while the transcript is asking for approval.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ShellPhase {
    Idle,
    Typing,
    Working,
    /// A live verification pass (tests/checks/lints). Same clock family as
    /// `Working` but rendered as the metered braille tick — checking, not
    /// searching (ocean state model).
    Verifying,
    Waiting,
    Approval,
    Done,
    Failed,
}

/// The one truthful verb shown while a turn is live. This deliberately stays
/// smaller than the tool taxonomy: the phase strip only needs to distinguish
/// hidden reasoning, read-shaped exploration, other tool use, verification,
/// and generic model work. It never exposes reasoning text or tool arguments.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum LiveActivityKind {
    Working,
    Compacting,
    AutoCompacting,
    Reasoning,
    Reading,
    UsingTool,
    Verifying,
}

/// Bounded projection of live turn activity. Completed entries are ignored,
/// so an `ActiveCell` retained until `TurnCompleted` cannot keep the shell in a
/// false working state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct LiveActivity {
    kind: LiveActivityKind,
    running_tools: usize,
}

impl LiveActivity {
    #[must_use]
    pub(crate) fn from_app(app: &App) -> Self {
        let tools = running_tool_facts(app);
        let kind = if app
            .active_compaction
            .as_ref()
            .is_some_and(|compaction| compaction.auto)
        {
            LiveActivityKind::AutoCompacting
        } else if app.active_compaction.is_some() {
            LiveActivityKind::Compacting
        } else if tools.verifying {
            LiveActivityKind::Verifying
        } else if tools.count > 0 && tools.all_reading {
            LiveActivityKind::Reading
        } else if tools.count > 0 {
            LiveActivityKind::UsingTool
        } else if app.streaming_thinking_active_entry.is_some() {
            LiveActivityKind::Reasoning
        } else {
            LiveActivityKind::Working
        };
        Self {
            kind,
            running_tools: tools.count,
        }
    }

    #[must_use]
    pub(crate) fn kind(self) -> LiveActivityKind {
        self.kind
    }

    #[must_use]
    pub(crate) fn running_tool_count(self) -> usize {
        self.running_tools
    }

    #[must_use]
    fn is_explicit(self) -> bool {
        !matches!(self.kind, LiveActivityKind::Working)
    }

    #[must_use]
    fn label(self, locale: Locale) -> Cow<'static, str> {
        match self.kind {
            LiveActivityKind::Working => tr(locale, MessageId::PhaseWorking),
            LiveActivityKind::Compacting => tr(locale, MessageId::ContextManualCompacting),
            LiveActivityKind::AutoCompacting => tr(locale, MessageId::ContextAutoCompacting),
            LiveActivityKind::Reasoning => tr(locale, MessageId::PhaseReasoning),
            LiveActivityKind::Reading => tr(locale, MessageId::PhaseReading),
            LiveActivityKind::UsingTool => tr(locale, MessageId::PhaseUsingTool),
            LiveActivityKind::Verifying => tr(locale, MessageId::PhaseVerifying),
        }
    }
}

#[derive(Debug, Clone, Copy)]
struct RunningToolFacts {
    count: usize,
    all_reading: bool,
    verifying: bool,
}

impl Default for RunningToolFacts {
    fn default() -> Self {
        Self {
            count: 0,
            all_reading: true,
            verifying: false,
        }
    }
}

impl RunningToolFacts {
    fn observe(&mut self, reading: bool, verifying: bool) {
        self.count = self.count.saturating_add(1);
        self.all_reading &= reading;
        self.verifying |= verifying;
    }
}

const WORKING_BUBBLE_FRAMES: [&str; 8] = ["⠀", "⢀", "⣀", "⣄", "⣤", "⣦", "⣶", "⣿"];
const COMPLETION_BREATH_MS: u128 = 800;
const COMPLETION_RELEASE_MS: u128 = 560;
/// Signal Cut hero mark. The Whale Teams roster (CWC 2026-08-15) reads
/// head-left, blunt nose, swept dorsal on an arched back, a short tail stock
/// that stays body mass (`▙▄▄▞`) and rises into the attached crown fluke
/// `▚△▞`. The fluke's notch `△` sits directly above the rising stock tip
/// `▞`, so the tail reads as one continuous animal instead of a bar with a
/// shape floating past it. The belly carries one cyan current cut. The glyph
/// vocabulary is the one `whales::art` uses for the six-role portraits.
const IDLE_WHALE_SPOUT_ROW: &str = "    ˚";
const IDLE_WHALE_ROWS: [&str; 3] = ["  ▗▄▄▟▄▄▄▄▄▖  ▚△▞", " ▐█·████████▙▄▄▞", "  ▝▀▀▀▀▀▀▀▀▘"];

/// Soft variant: same silhouette, one body cell shorter, blush around the eye
/// and a sparkle beside the spout.
const UWU_IDLE_WHALE_SPOUT_ROW: &str = "    ˚✦";
const UWU_IDLE_WHALE_ROWS: [&str; 3] = ["  ▗▄▄▟▄▄▄▄▖  ▚△▞", " ▐█░·░█████▙▄▄▞", "  ▝▀▀▀▀▀▀▀▘"];

/// The belly row is the mark's cyan current cut, not gold body mass; it holds
/// still while the caustic sweep travels across the gold rows above it.
const IDLE_WHALE_CURRENT_ROW: usize = 2;

const IDLE_SHIMMER_CYCLE_MS: u128 = 4_000;
const IDLE_SHIMMER_SWEEP_FRACTION: f32 = 0.32;
const IDLE_SHIMMER_BAND_HALF_WIDTH: f32 = 0.38;
const IDLE_SHIMMER_STRENGTH: f32 = 0.33;

/// The build-version string the header renders. An unstamped local build uses
/// the build script's development marker while CI/release carries its source
/// stamp; the header always reports that real build provenance.
fn shell_build_version() -> Cow<'static, str> {
    Cow::Borrowed(env!("HAKUS_BUILD_VERSION"))
}

impl ShellPhase {
    #[must_use]
    pub fn from_app(app: &App) -> Self {
        Self::from_app_with_activity(app, LiveActivity::from_app(app))
    }

    #[must_use]
    pub(crate) fn from_app_with_activity(app: &App, activity: LiveActivity) -> Self {
        if matches!(
            app.view_stack.top_kind(),
            Some(ModalKind::Approval | ModalKind::Elevation | ModalKind::UserInput)
        ) {
            return Self::Approval;
        }
        if matches!(
            activity.kind(),
            LiveActivityKind::Compacting | LiveActivityKind::AutoCompacting
        ) {
            // A typed CompactionStarted event is newer and more specific than
            // a prior turn's failed projection. Keep the recovery operation
            // visible until its matching terminal event arrives.
            return Self::Working;
        }
        if app.turn_error_posted
            || matches!(app.runtime_turn_status.as_deref(), Some("failed" | "error"))
        {
            return Self::Failed;
        }
        if app.pending_user_input_prompt.is_some()
            || app
                .task_panel
                .iter()
                .any(|task| matches!(task.status.as_str(), "waiting" | "needs_user"))
        {
            return Self::Waiting;
        }
        if app.is_loading
            || matches!(app.runtime_turn_status.as_deref(), Some("in_progress"))
            || activity.is_explicit()
        {
            if activity.kind() == LiveActivityKind::Verifying {
                return Self::Verifying;
            }
            return Self::Working;
        }
        if !app.input.is_empty() {
            return Self::Typing;
        }
        if matches!(app.runtime_turn_status.as_deref(), Some("completed")) {
            return Self::Done;
        }
        Self::Idle
    }

    #[must_use]
    pub fn label(self, locale: Locale) -> Cow<'static, str> {
        match self {
            Self::Idle => tr(locale, MessageId::PhaseIdle),
            Self::Typing => tr(locale, MessageId::PhaseDraft),
            Self::Working => tr(locale, MessageId::PhaseWorking),
            Self::Verifying => tr(locale, MessageId::PhaseVerifying),
            Self::Waiting | Self::Approval => tr(locale, MessageId::PhaseWaitingOnYou),
            Self::Done => tr(locale, MessageId::PhaseDone),
            Self::Failed => tr(locale, MessageId::PhaseFailed),
        }
    }

    #[must_use]
    pub fn color(self, app: &App) -> Color {
        phase_ink(self).color(&app.ui_theme)
    }
}

/// Status-bar phase ink. Failure red is only `Failed`.
#[must_use]
pub(crate) fn phase_ink(phase: ShellPhase) -> ChromeInk {
    match phase {
        ShellPhase::Idle => ChromeInk::Metadata,
        ShellPhase::Done => ChromeInk::Outcome,
        ShellPhase::Typing => ChromeInk::Identity,
        // Verifying shares the live seafoam hue; the tick-vs-bubble
        // marker carries the checking/searching distinction.
        ShellPhase::Working | ShellPhase::Verifying => ChromeInk::Active,
        ShellPhase::Waiting | ShellPhase::Approval => ChromeInk::Waiting,
        ShellPhase::Failed => ChromeInk::Failure,
    }
}

/// Exhaustive on purpose: a new [`AppMode`] must be handed a Policy ink
/// deliberately rather than inheriting act's by falling through a wildcard.
fn header_mode_ink(mode: AppMode) -> ChromeInk {
    match mode {
        AppMode::Plan => ChromeInk::PolicyPlan,
        AppMode::Operate => ChromeInk::PolicyOperate,
        // YOLO stays Policy, not Failure — the header must not spend red
        // on a selected mode. It wears the act badge because `mode_label`
        // resolves it to act; the posture it implies is the permission
        // chip's Cognition ink, not this one.
        AppMode::Agent | AppMode::Auto | AppMode::Yolo => ChromeInk::PolicyAct,
    }
}

fn header_permission_ink(mode: ApprovalMode) -> ChromeInk {
    match mode {
        ApprovalMode::Suggest | ApprovalMode::Never => ChromeInk::PermissionAsk,
        ApprovalMode::Auto => ChromeInk::PermissionAutoReview,
        ApprovalMode::Bypass => ChromeInk::PermissionFullAccess,
    }
}

fn header_fg(app: &App, ink: ChromeInk) -> Style {
    chrome_style(&app.ui_theme, ink)
}

/// Summarize only tools whose lifecycle is actually `Running`. A read label
/// is earned only when every running entry is read/exploration-shaped; mixed
/// work stays the neutral `using tool`. Verification wins because it is the
/// existing stronger promise made by the phase strip.
fn running_tool_facts(app: &App) -> RunningToolFacts {
    use crate::tui::history::{HistoryCell, ToolCell, ToolStatus};
    use crate::tui::widgets::tool_card::{ToolFamily, tool_family_for_name};

    let mut facts = RunningToolFacts::default();
    let Some(active) = app.active_cell.as_ref() else {
        return facts;
    };
    for cell in active.entries() {
        let HistoryCell::Tool(tool) = cell else {
            continue;
        };
        match tool {
            ToolCell::Exec(exec) if exec.status == ToolStatus::Running => {
                facts.observe(false, exec_is_verification(&exec.command));
            }
            ToolCell::Generic(generic) if generic.status == ToolStatus::Running => {
                let family = tool_family_for_name(&generic.name);
                facts.observe(
                    matches!(family, ToolFamily::Read | ToolFamily::Find),
                    family == ToolFamily::Verify || generic.name == "read_lints",
                );
            }
            ToolCell::Exploring(exploring) => {
                for entry in &exploring.entries {
                    if entry.status == ToolStatus::Running {
                        facts.observe(true, false);
                    }
                }
            }
            ToolCell::WebSearch(search) if search.status == ToolStatus::Running => {
                facts.observe(true, false);
            }
            other if other.status() == Some(ToolStatus::Running) => {
                facts.observe(false, false);
            }
            _ => {}
        }
    }
    facts
}

fn exec_is_verification(command: &str) -> bool {
    let trimmed = command.trim_start();
    let mut tokens = trimmed.split_whitespace();
    let first = tokens.next().unwrap_or("");
    let second = tokens.next().unwrap_or("");
    match first {
        "cargo" => matches!(second, "test" | "check" | "clippy" | "nextest"),
        "go" => matches!(second, "test" | "vet"),
        "npm" | "pnpm" | "yarn" | "bun" => matches!(second, "test" | "lint" | "check"),
        "make" => matches!(second, "test" | "check" | "lint"),
        "python" | "python3" => trimmed.contains("-m pytest") || trimmed.contains("-m unittest"),
        "pytest" | "jest" | "vitest" | "tsc" | "eslint" | "ruff" | "mypy" | "clippy-driver"
        | "golangci-lint" | "shellcheck" => true,
        _ => false,
    }
}

fn completion_elapsed_ms(app: &App) -> Option<u128> {
    if !app.motion_policy().allows_decorative() {
        return None;
    }
    app.ocean_completion_started_at
        .map(|started| started.elapsed().as_millis())
        .filter(|elapsed| *elapsed < COMPLETION_BREATH_MS)
}

/// Truthful window-title activity verb for the OSC-0 whale animation.
///
/// Uses short English fragments (with fixed-width ellipsis) so alt-tabbed
/// sessions stay legible without depending on the full localized phase strip.
#[must_use]
pub(crate) fn title_activity_verb(app: &App) -> &'static str {
    let activity = LiveActivity::from_app(app);
    let phase = ShellPhase::from_app_with_activity(app, activity);
    match phase {
        ShellPhase::Waiting | ShellPhase::Approval => "waiting on you…",
        ShellPhase::Verifying => "verifying…",
        ShellPhase::Done => "done",
        ShellPhase::Failed => "failed",
        ShellPhase::Typing => "drafting…",
        ShellPhase::Idle => "idle",
        ShellPhase::Working => match activity.kind() {
            LiveActivityKind::Compacting | LiveActivityKind::AutoCompacting => {
                "compacting context…"
            }
            LiveActivityKind::Reasoning => "reasoning…",
            LiveActivityKind::Reading => "reading…",
            LiveActivityKind::UsingTool => "using tool…",
            LiveActivityKind::Verifying => "verifying…",
            LiveActivityKind::Working => "working…",
        },
    }
}

/// Push the current shell phase into the terminal title whale animation.
pub(crate) fn sync_title_activity(app: &App) {
    crate::tui::notifications::set_title_motion_enabled(
        app.motion_policy().allows_decorative() && app.status_indicator != "off",
    );
    // Keep the `[title] …` window-title prefix in step with the session and
    // config defaults; change detection inside makes this free when nothing
    // moved.
    crate::tui::notifications::set_title_prefix(app.window_title_prefix());
    if app.is_loading
        || matches!(
            ShellPhase::from_app(app),
            ShellPhase::Working
                | ShellPhase::Verifying
                | ShellPhase::Waiting
                | ShellPhase::Approval
                | ShellPhase::Typing
        )
    {
        crate::tui::notifications::set_title_activity_verb(title_activity_verb(app));
    }
}

pub(crate) fn phase_marker_with_activity(
    app: &App,
    phase: ShellPhase,
    activity: LiveActivity,
) -> (&'static str, Cow<'static, str>) {
    let locale = app.ui_locale;
    match phase {
        ShellPhase::Idle => ("·", phase.label(locale)),
        ShellPhase::Typing => ("›", phase.label(locale)),
        ShellPhase::Working => {
            // The footer and the live tool card share one wall-clock cadence,
            // so the two primary liveness marks never look like unrelated
            // spinners. The shared helper also preserves the 400ms
            // "motion is earned" delay and reduced/still fallback.
            let policy = app.motion_policy();
            let animated = crate::tui::spinner::braille_spinner_frame(app.turn_started_at, false);
            let earned = app.turn_started_at.is_none_or(|started| {
                started.elapsed().as_millis()
                    >= u128::from(crate::tui::spinner::LIVE_MARKER_DELAY_MS)
            });
            let frame = policy.spinner_glyph(animated, earned);
            (frame, activity.label(locale))
        }
        ShellPhase::Verifying => {
            // Metered braille tick on the shared live clock — checking, not
            // searching. Reduced motion holds the legible mid frame.
            let policy = app.motion_policy();
            let animated = crate::tui::spinner::verification_tick_frame(app.turn_started_at, false);
            let earned = app.turn_started_at.is_none_or(|started| {
                started.elapsed().as_millis()
                    >= u128::from(crate::tui::spinner::LIVE_MARKER_DELAY_MS)
            });
            let frame = policy.spinner_glyph(animated, earned);
            (frame, phase.label(locale))
        }
        ShellPhase::Waiting | ShellPhase::Approval => ("◆", phase.label(locale)),
        ShellPhase::Done => match completion_elapsed_ms(app) {
            Some(elapsed) if elapsed < COMPLETION_RELEASE_MS => {
                let index = ((elapsed / 140) as usize + 4).min(WORKING_BUBBLE_FRAMES.len() - 1);
                (
                    WORKING_BUBBLE_FRAMES[index],
                    tr(locale, MessageId::PhaseFinishing),
                )
            }
            _ => (crate::tui::glyphs::DONE, phase.label(locale)),
        },
        ShellPhase::Failed => (crate::tui::glyphs::FAILED, phase.label(locale)),
    }
}

fn mode_label(locale: Locale, mode: AppMode) -> Cow<'static, str> {
    match mode {
        AppMode::Agent | AppMode::Auto | AppMode::Yolo => tr(locale, MessageId::ChipModeAct),
        AppMode::Plan => tr(locale, MessageId::ChipModePlan),
        AppMode::Operate => tr(locale, MessageId::ChipModeOperate),
    }
}

/// Permission chip words. This maps from the typed [`ApprovalMode`] state —
/// never from the English `permission_chip_label()` strings — so localizing
/// (or rewording) the upstream chip labels can never silently break the chip.
fn permission_label(app: &App) -> Cow<'static, str> {
    let locale = app.ui_locale;
    if app.mode == AppMode::Plan {
        return tr(locale, MessageId::ChipPermissionReadOnly);
    }
    let approval = match app.approval_mode {
        ApprovalMode::Suggest => tr(locale, MessageId::ChipPermissionAsk),
        ApprovalMode::Auto => tr(locale, MessageId::ChipPermissionAuto),
        // Keep the effective permission explicit. `bypass` is an
        // implementation detail and, more importantly, can imply that
        // repository law no longer applies. Full Access never bypasses
        // constitution rules. This is **tool-approval posture**, not
        // filesystem scope — see filesystem_scope_label.
        ApprovalMode::Bypass => tr(locale, MessageId::ChipPermissionFullAccess),
        ApprovalMode::Never => tr(locale, MessageId::ChipPermissionNever),
    };
    // Append filesystem scope so "Full Access" (approval) is never confused
    // with unrestricted disk writes.
    let fs = filesystem_scope_label(app);
    Cow::Owned(format!("{approval} · {fs}"))
}

/// Always-legible effective filesystem scope for the shell chrome.
#[must_use]
fn filesystem_scope_label(app: &App) -> Cow<'static, str> {
    // Spelled out because the old `fs:` prefix read as an unexplained
    // acronym (user report, 2026-07-23): this chip states which files the
    // session may write.
    let policy = crate::core::authority::sandbox_policy_for_turn(
        app.mode,
        app.approval_mode,
        app.configured_sandbox_mode.as_deref(),
        &app.workspace,
    );
    // A policy is an intent; enforcement needs a backend. On default Linux
    // (bubblewrap is opt-in) and on all Windows there is none, and this chip
    // used to say "files: workspace" while nothing restricted anything
    // (2026-08-04 audit). Say "unenforced" rather than name a boundary that
    // is not applied. `DangerFullAccess` is already honest, and
    // `ExternalSandbox` is enforced by the external runner, not by us.
    let unenforced = app.sandbox_backend.is_none()
        && !matches!(
            policy,
            crate::sandbox::SandboxPolicy::DangerFullAccess
                | crate::sandbox::SandboxPolicy::ExternalSandbox { .. }
        );
    match policy {
        crate::sandbox::SandboxPolicy::ReadOnly if unenforced => {
            Cow::Borrowed("files: read-only (unenforced)")
        }
        crate::sandbox::SandboxPolicy::ReadOnly => Cow::Borrowed("files: read-only"),
        crate::sandbox::SandboxPolicy::DangerFullAccess => Cow::Borrowed("files: full disk"),
        crate::sandbox::SandboxPolicy::ExternalSandbox { .. } => {
            Cow::Borrowed("files: external sandbox")
        }
        crate::sandbox::SandboxPolicy::WorkspaceWrite { .. } if unenforced => {
            Cow::Borrowed("files: workspace (unenforced)")
        }
        crate::sandbox::SandboxPolicy::WorkspaceWrite { .. } => Cow::Borrowed("files: workspace"),
    }
}

fn span_width(spans: &[Span<'_>]) -> usize {
    spans.iter().map(|span| span.content.width()).sum()
}

fn truncate_to_width(text: &str, width: usize) -> String {
    if text.width() <= width {
        return text.to_string();
    }
    if width == 0 {
        return String::new();
    }
    if width <= 3 {
        return ".".repeat(width);
    }
    let mut result = String::new();
    let mut used = 0;
    for ch in text.chars() {
        let ch_width = unicode_width::UnicodeWidthChar::width(ch).unwrap_or(0);
        if used + ch_width + 1 > width {
            break;
        }
        result.push(ch);
        used += ch_width;
    }
    result.push('…');
    result
}

fn render_launch_line(area: Rect, buf: &mut Buffer, y: u16, spans: Vec<Span<'static>>) {
    if y >= area.height {
        return;
    }
    Paragraph::new(Line::from(spans)).render(
        Rect {
            x: area.x,
            y: area.y.saturating_add(y),
            width: area.width,
            height: 1,
        },
        buf,
    );
}

fn render_launch_content_line(
    area: Rect,
    buf: &mut Buffer,
    y: u16,
    inset: u16,
    spans: Vec<Span<'static>>,
) {
    if y >= area.height {
        return;
    }
    let inset = inset.min(area.width / 2);
    Paragraph::new(Line::from(spans)).render(
        Rect {
            x: area.x.saturating_add(inset),
            y: area.y.saturating_add(y),
            width: area.width.saturating_sub(inset.saturating_mul(2)),
            height: 1,
        },
        buf,
    );
}

fn launch_has_detail(area: Rect) -> bool {
    area.width >= 60 && area.height >= 22
}

fn launch_content_start(_area: Rect) -> u16 {
    // Keep the decision block anchored just below the shell header at every
    // detailed size. Vertically centering it made a wide terminal look like
    // an old fixed-height menu floating in decorative emptiness.
    3
}

fn launch_row_y(area: Rect, index: usize) -> u16 {
    const DETAIL_ROW_OFFSETS: [u16; 6] = [4, 7, 11, 12, 15, 16];
    let start = launch_content_start(area);
    if launch_has_detail(area) {
        start.saturating_add(DETAIL_ROW_OFFSETS[index])
    } else {
        start.saturating_add(u16::try_from(index).unwrap_or(0))
    }
}

fn launch_workspace_name(app: &App) -> String {
    app.workspace
        .file_name()
        .and_then(|name| name.to_str())
        .filter(|name| !name.is_empty())
        .map_or_else(
            || crate::utils::display_path(&app.workspace),
            str::to_string,
        )
}

/// Render the distinct pre-session choice state. This screen contains no
/// transcript, composer, dashboard, or post-launch whale: each row dispatches
/// to real session/worktree machinery before the idle ocean is entered.
pub fn render_launch_screen(area: Rect, buf: &mut Buffer, app: &App) {
    if area.width == 0 || area.height == 0 {
        return;
    }
    Block::default()
        .style(Style::default().bg(app.ui_theme.surface_bg))
        .render(area, buf);
    let width = usize::from(area.width);
    let version = format!("v{}", shell_build_version());
    let workspace_budget = width.saturating_sub(version.width() + 6);
    let workspace = truncate_to_width(
        &crate::utils::display_path(&app.workspace),
        workspace_budget,
    );
    let mut header = vec![
        Span::styled(
            "cw",
            Style::default()
                .fg(app.ui_theme.accent_primary)
                .add_modifier(Modifier::BOLD),
        ),
        Span::raw("  "),
        Span::styled(workspace, Style::default().fg(app.ui_theme.text_muted)),
    ];
    let gap = width.saturating_sub(span_width(&header) + version.width());
    header.push(Span::raw(" ".repeat(gap)));
    header.push(Span::styled(
        version,
        Style::default().fg(app.ui_theme.text_hint),
    ));
    render_launch_line(area, buf, 0, header);
    if area.height > 1 {
        render_launch_line(
            area,
            buf,
            1,
            vec![Span::styled(
                "─".repeat(width),
                Style::default().fg(app.ui_theme.border),
            )],
        );
    }

    if launch_has_detail(area) {
        let content_start = launch_content_start(area);
        render_launch_content_line(
            area,
            buf,
            content_start,
            2,
            vec![Span::styled(
                tr(app.ui_locale, MessageId::LaunchStartTitle).into_owned(),
                Style::default()
                    .fg(app.ui_theme.text_body)
                    .add_modifier(Modifier::BOLD),
            )],
        );
        let workspace_id = if app.launch.worktree_available {
            MessageId::LaunchWorkspaceGitReady
        } else {
            MessageId::LaunchWorkspaceFolderReady
        };
        render_launch_content_line(
            area,
            buf,
            content_start.saturating_add(1),
            2,
            vec![Span::styled(
                tr(app.ui_locale, workspace_id).replace("{name}", &launch_workspace_name(app)),
                Style::default().fg(app.ui_theme.text_soft),
            )],
        );
        let provider_id = if app.onboarding_needs_api_key {
            MessageId::LaunchProviderSetupNeeded
        } else {
            MessageId::LaunchProviderConfigured
        };
        render_launch_content_line(
            area,
            buf,
            content_start.saturating_add(2),
            2,
            vec![Span::styled(
                tr(app.ui_locale, provider_id).into_owned(),
                Style::default().fg(if app.onboarding_needs_api_key {
                    app.ui_theme.warning
                } else {
                    app.ui_theme.success
                }),
            )],
        );
        for (row, description_id) in [
            (launch_row_y(area, 0), MessageId::LaunchWorkDescription),
            (launch_row_y(area, 1), MessageId::LaunchChatDescription),
        ] {
            render_launch_content_line(
                area,
                buf,
                row.saturating_add(1),
                4,
                vec![Span::styled(
                    tr(app.ui_locale, description_id).into_owned(),
                    Style::default().fg(app.ui_theme.text_muted),
                )],
            );
        }
        for (row, heading_id) in [
            (launch_row_y(area, 2), MessageId::LaunchGroupContinue),
            (launch_row_y(area, 4), MessageId::LaunchGroupMore),
        ] {
            render_launch_content_line(
                area,
                buf,
                row.saturating_sub(1),
                2,
                vec![Span::styled(
                    tr(app.ui_locale, heading_id).into_owned(),
                    Style::default()
                        .fg(app.ui_theme.text_hint)
                        .add_modifier(Modifier::BOLD),
                )],
            );
        }
    }

    for (index, (label_id, key)) in LAUNCH_ROWS.iter().enumerate() {
        let y = launch_row_y(area, index);
        if y >= area.height.saturating_sub(3) {
            break;
        }
        let selected = app.launch.selected == index;
        let mut label = tr(app.ui_locale, *label_id).into_owned();
        if index == 3 && !app.launch.worktree_available {
            label.push_str(&format!(
                " · {}",
                tr(app.ui_locale, MessageId::LaunchMenuUnavailable)
            ));
        }
        if index == 2 {
            label.push_str(&format!(
                " · {}",
                tr(app.ui_locale, MessageId::LaunchMenuSavedCount)
                    .replace("{count}", &app.launch.workspace_session_count.to_string())
            ));
        }
        let prefix = if selected { "▸ " } else { "  " };
        let key_width = key.width();
        let content_width = width.saturating_sub(4);
        let label_budget = content_width.saturating_sub(prefix.width() + key_width + 2);
        let label = truncate_to_width(&label, label_budget);
        let fill = content_width.saturating_sub(prefix.width() + label.width() + key_width);
        let row_style = if selected {
            crate::tui::menu_style::theme_selected_row_style(&app.ui_theme)
        } else if index == 3 && !app.launch.worktree_available {
            Style::default().fg(app.ui_theme.text_dim)
        } else {
            Style::default().fg(app.ui_theme.text_body)
        };
        let key_style = if selected {
            row_style
        } else {
            Style::default().fg(app.ui_theme.text_hint)
        };
        render_launch_content_line(
            area,
            buf,
            y,
            2,
            vec![
                Span::styled(prefix, row_style),
                Span::styled(label, row_style),
                Span::styled(" ".repeat(fill), row_style),
                Span::styled(*key, key_style),
            ],
        );
    }

    if area.height < 3 {
        return;
    }
    let rule_y = area.height.saturating_sub(3);
    render_launch_line(
        area,
        buf,
        rule_y,
        vec![Span::styled(
            "─".repeat(width),
            Style::default().fg(app.ui_theme.border),
        )],
    );
    let prompt = if let Some(input) = app.launch.worktree_input.as_deref() {
        format!(
            "{}  {}{}",
            tr(app.ui_locale, MessageId::LaunchWorktreeNameLabel),
            input,
            if app.low_motion { "_" } else { "▌" }
        )
    } else if let Some(status) = app.launch.status.as_deref() {
        status.to_string()
    } else if area.width < 60 {
        format!(
            "j/k:{} · Enter:{}",
            tr(app.ui_locale, MessageId::LaunchHintMove),
            tr(app.ui_locale, MessageId::LaunchHintOpen)
        )
    } else {
        tr(app.ui_locale, MessageId::LaunchTipFlags).into_owned()
    };
    render_launch_line(
        area,
        buf,
        area.height.saturating_sub(2),
        vec![Span::styled(
            truncate_to_width(&prompt, width),
            Style::default().fg(if app.launch.status.is_some() {
                app.ui_theme.text_muted
            } else {
                app.ui_theme.text_hint
            }),
        )],
    );

    let workspace_kind = tr(
        app.ui_locale,
        if app.launch.worktree_available {
            MessageId::LaunchWorkspaceGitShort
        } else {
            MessageId::LaunchWorkspaceFolderShort
        },
    );
    let provider = tr(
        app.ui_locale,
        if app.onboarding_needs_api_key {
            MessageId::LaunchProviderSetupShort
        } else {
            MessageId::LaunchProviderConfiguredShort
        },
    );
    let status = format!(
        "{} · {workspace_kind} · {provider}",
        launch_workspace_name(app)
    );
    render_launch_line(
        area,
        buf,
        area.height.saturating_sub(1),
        vec![Span::styled(
            truncate_to_width(&status, width),
            Style::default().fg(app.ui_theme.text_dim),
        )],
    );
}

/// Record the launch row rects immediately after the launch frame is painted.
/// The coordinates mirror the renderer's responsive row placement exactly.
pub fn record_launch_row_areas(area: Rect, launch: &mut crate::tui::app::LaunchState) {
    launch.row_areas.clear();
    for index in 0..LAUNCH_ROWS.len() {
        let y = launch_row_y(area, index);
        if y >= area.height.saturating_sub(3) {
            break;
        }
        launch.row_areas.push(Rect {
            x: area.x.saturating_add(2),
            y: area.y.saturating_add(y),
            width: area.width.saturating_sub(4),
            height: 1,
        });
    }
}

fn compact_tokens(tokens: i64) -> String {
    if tokens >= 1_000_000 {
        format!("{:.1}M", tokens as f64 / 1_000_000.0)
    } else if tokens >= 1_000 {
        format!("{:.0}K", tokens as f64 / 1_000.0)
    } else {
        tokens.to_string()
    }
}

fn session_token_breakdown(app: &App) -> Option<Span<'static>> {
    app.header_items.contains(&HeaderItem::Tokens).then(|| {
        Span::styled(
            format!(
                "{} in · {} cch · {} out",
                format_token_count_compact(u64::from(app.session.total_input_tokens)),
                format_token_count_compact(u64::from(app.session.total_cache_hit_tokens)),
                format_token_count_compact(u64::from(app.session.total_output_tokens)),
            ),
            header_fg(app, ChromeInk::Info),
        )
    })
}

/// Append one right-hand chrome element, inserting the two-space separator
/// only between elements so an absent element never leaves trailing padding.
fn push_chrome(spans: &mut Vec<Span<'static>>, span: Span<'static>) {
    if !spans.is_empty() {
        spans.push(Span::raw("  "));
    }
    spans.push(span);
}

/// Render the one-line shell header. Immediate operating posture and workspace
/// truth live here; quieter route identity lives beside the phase footer.
pub fn render_header(area: Rect, buf: &mut Buffer, app: &App) {
    let git_status = crate::tui::git_status::cached_status();
    render_header_with_git_status(area, buf, app, &git_status);
}

fn render_header_with_git_status(
    area: Rect,
    buf: &mut Buffer,
    app: &App,
    git_status: &crate::tui::git_status::GitStatusSnapshot,
) {
    if area.width == 0 || area.height == 0 {
        return;
    }
    let tier = ShellTier::for_chrome_width(area.width);
    Block::default()
        .style(Style::default().bg(app.ui_theme.header_bg))
        .render(area, buf);

    let mode_color = header_mode_ink(app.mode).color(&app.ui_theme);
    // Match the composer's warm top edge exactly: Ask amber, Auto-Review
    // Signal Gold, and Full Access coral.
    let permission_color = header_permission_ink(app.approval_mode).color(&app.ui_theme);
    let dim = header_fg(app, ChromeInk::MetadataDim);
    // `status_indicator` owns the single header mark. It used to be filtered
    // against the literal "cw" because the header also hardcoded a leading
    // "cw" span, and `header_status_indicator_frame` collapses `cw`, the
    // legacy `whale` opt-in, and unknown values onto that same mark — so the
    // filter silently discarded three of the setting's four documented values
    // and left `off` with nothing to turn off (#5512). There is one mark now,
    // and this setting decides what occupies it.
    let status_indicator = crate::tui::widgets::header_status_indicator_frame(
        (!app.low_motion && app.fancy_animations)
            .then_some(app.turn_started_at)
            .flatten(),
        &app.status_indicator,
    );
    let mut left = Vec::new();
    if let Some(indicator) = status_indicator {
        left.push(Span::styled(
            indicator,
            header_fg(app, ChromeInk::Identity).add_modifier(Modifier::BOLD),
        ));
        left.push(Span::raw("  "));
    }
    left.push(Span::styled(
        mode_label(app.ui_locale, app.mode),
        Style::default().fg(mode_color),
    ));
    // Permission is safety state, not optional chrome. Compact terminals shed
    // auxiliary detail, but keep mode and the effective posture.
    left.push(Span::styled(" · ", dim));
    left.push(Span::styled(
        permission_label(app),
        Style::default().fg(permission_color),
    ));
    // Active-goal chip (#39): the ocean shell has no sidebar, so the topbar
    // is the only always-on surface where a goal set via `create_goal` can
    // live. Objective truncated to a fixed budget; terminal goals render
    // nothing. The cramped-layout rebuild below keeps the chip in `suffix`.
    let goal_chip =
        crate::tui::footer_ui::active_goal_chip_state(app).map(|(objective, paused)| {
            let budget = if paused { 22 } else { 26 };
            let flat = objective.trim().replace(['\n', '\r'], " ");
            let text = if paused {
                format!("goal paused {}", truncate_to_width(&flat, budget))
            } else {
                format!("goal {}", truncate_to_width(&flat, budget))
            };
            let color = if paused {
                ChromeInk::Attention.color(&app.ui_theme)
            } else {
                ChromeInk::Active.color(&app.ui_theme)
            };
            (text, color)
        });
    if let Some((text, color)) = &goal_chip {
        left.push(Span::styled(" · ", dim));
        left.push(Span::styled(
            text.clone(),
            Style::default().fg(*color).add_modifier(Modifier::BOLD),
        ));
    }
    // Workflow-run chip (#5040): the same `WorkflowPanel::top_bar_chip` the
    // classic header shows, so a collapsed run stays visible on the ocean
    // shell too. No workflow panel means no chip. The cramped-layout rebuild
    // below keeps the chip in `suffix` alongside the goal chip.
    let workflow_chip = app
        .workflow_panel
        .as_ref()
        .map(|panel| (panel.top_bar_chip(), ChromeInk::Info.color(&app.ui_theme)));
    if let Some((text, color)) = &workflow_chip {
        left.push(Span::styled(" · ", dim));
        left.push(Span::styled(
            text.clone(),
            Style::default().fg(*color).add_modifier(Modifier::BOLD),
        ));
    }
    // Update-available chip (#14): a quiet, persistent affordance set once by
    // the startup version check. Gets the workflow chip's treatment: last in
    // the left cluster, the route label yields its budget first, and the chip
    // drops cleanly when even a minimal chip cannot fit — never a modal,
    // never mid-chip clipping.
    let update_chip = app
        .update_available
        .as_ref()
        .map(|label| (label.clone(), ChromeInk::Attention.color(&app.ui_theme)));
    if let Some((text, color)) = &update_chip {
        left.push(Span::styled(" · ", dim));
        left.push(Span::styled(
            text.clone(),
            Style::default().fg(*color).add_modifier(Modifier::BOLD),
        ));
    }

    let context_meter = (tier != ShellTier::Compact)
        .then(|| crate::tui::ui::context_usage_snapshot(app))
        .flatten()
        .map(|(used, max, percent)| {
            let filled = ((percent / 100.0) * 5.0).ceil().clamp(0.0, 5.0) as usize;
            Span::styled(
                format!(
                    "{}/{} [{}{}] {:.0}%",
                    compact_tokens(used),
                    compact_tokens(i64::from(max)),
                    "▰".repeat(filled),
                    "▱".repeat(5usize.saturating_sub(filled)),
                    percent
                ),
                header_fg(app, ChromeInk::Info),
            )
        });
    let token_breakdown = (tier != ShellTier::Compact)
        .then(|| session_token_breakdown(app))
        .flatten();
    let version = (tier == ShellTier::Wide).then(|| {
        Span::styled(
            format!("v{}", shell_build_version()),
            header_fg(app, ChromeInk::MetadataHint),
        )
    });
    // Cached repository/worktree status only — never probe from the render path.
    // Background refresh is scheduled from the event loop / idle ticks.
    let git_label = crate::tui::git_status::chrome_label(git_status).map(|label| {
        let max_width = match tier {
            ShellTier::Compact => 24,
            ShellTier::Normal => 36,
            ShellTier::Wide => 52,
        };
        Span::styled(
            truncate_to_width(&label, max_width),
            header_fg(app, crate::tui::git_status::chrome_ink()),
        )
    });

    // Baseline right-hand chrome: git, context meter, version.
    let mut right = Vec::new();
    if let Some(git_label) = git_label.clone() {
        push_chrome(&mut right, git_label);
    }
    if let Some(context_meter) = context_meter.clone() {
        push_chrome(&mut right, context_meter);
    }
    if let Some(version) = version.clone() {
        push_chrome(&mut right, version);
    }

    // The mark leads the header and carries its own two-space gutter, so it
    // costs `width + 2` when present and nothing at all when `off` (#5512).
    let indicator_width = status_indicator.map_or(0, |indicator| indicator.width() + 2);
    let minimum_left_width = indicator_width
        .saturating_add(mode_label(app.ui_locale, app.mode).width())
        .saturating_add(3 + permission_label(app).width());
    let available = usize::from(area.width);
    // The optional token breakdown is the only elidable element: it is added
    // between the git label and the context meter when the terminal is wide
    // enough to keep the whole baseline plus the guaranteed-left minimum.
    if let Some(token_breakdown) = token_breakdown {
        let mut enhanced_right = Vec::new();
        if let Some(git_label) = git_label.clone() {
            push_chrome(&mut enhanced_right, git_label);
        }
        push_chrome(&mut enhanced_right, token_breakdown);
        if let Some(context_meter) = context_meter.clone() {
            push_chrome(&mut enhanced_right, context_meter);
        }
        if let Some(version) = version.clone() {
            push_chrome(&mut enhanced_right, version);
        }
        let enhanced_width = span_width(&enhanced_right);
        let gap = usize::from(enhanced_width > 0);
        if minimum_left_width
            .saturating_add(gap)
            .saturating_add(enhanced_width)
            <= available
        {
            right = enhanced_right;
        }
    }

    let right_width = span_width(&right);
    let left_budget = available.saturating_sub(right_width + usize::from(right_width > 0));
    if span_width(&left) > left_budget {
        let mode = mode_label(app.ui_locale, app.mode);
        let permission = permission_label(app);
        let mut compact_left = Vec::new();
        if let Some(indicator) = status_indicator {
            compact_left.push(Span::styled(
                indicator,
                header_fg(app, ChromeInk::Identity).add_modifier(Modifier::BOLD),
            ));
            compact_left.push(Span::raw("  "));
        }
        compact_left.push(Span::styled(mode, Style::default().fg(mode_color)));
        compact_left.push(Span::styled(" · ", dim));
        compact_left.push(Span::styled(
            permission,
            Style::default().fg(permission_color),
        ));
        // The goal chip survives cramped layouts too — it is operator state,
        // not decoration. The route label yields its budget first (down to
        // nothing, as it always has); below that the goal itself truncates,
        // and when even a minimal chip cannot fit it drops rather than
        // clipping mid-word (#39).
        // Same accounting as the baseline pass: the mark leads and owns its
        // gutter, so it is `width + 2` present and 0 when `off` (#5512).
        let base_fixed = span_width(&compact_left);
        if let Some((text, color)) = &goal_chip {
            let goal_room = left_budget.saturating_sub(base_fixed).saturating_sub(3);
            if goal_room >= 8 {
                compact_left.push(Span::styled(" · ", dim));
                compact_left.push(Span::styled(
                    truncate_to_width(text, goal_room),
                    Style::default().fg(*color).add_modifier(Modifier::BOLD),
                ));
            }
        }
        // The workflow chip (#5040) is operator state too, so it gets the
        // goal chip's treatment: whatever room remains after the chips ahead
        // of it, clean truncation, and a clean drop when even a minimal chip
        // cannot fit. The route label still yields its budget first.
        if let Some((text, color)) = &workflow_chip {
            let workflow_room = left_budget
                .saturating_sub(span_width(&compact_left))
                .saturating_sub(3);
            if workflow_room >= 8 {
                compact_left.push(Span::styled(" · ", dim));
                compact_left.push(Span::styled(
                    truncate_to_width(text, workflow_room),
                    Style::default().fg(*color).add_modifier(Modifier::BOLD),
                ));
            }
        }
        // The update chip (#14) gets the same treatment, last in line: it is
        // useful, but it yields to every piece of operator state ahead of it.
        if let Some((text, color)) = &update_chip {
            let update_room = left_budget
                .saturating_sub(span_width(&compact_left))
                .saturating_sub(3);
            if update_room >= 8 {
                compact_left.push(Span::styled(" · ", dim));
                compact_left.push(Span::styled(
                    truncate_to_width(text, update_room),
                    Style::default().fg(*color).add_modifier(Modifier::BOLD),
                ));
            }
        }
        left = compact_left;
    }
    let left_width = span_width(&left);
    let gap = available.saturating_sub(left_width + right_width);
    left.push(Span::raw(" ".repeat(gap)));
    left.extend(right);
    let title_area = Rect { height: 1, ..area };
    Paragraph::new(Line::from(left)).render(title_area, buf);
    if area.height > 1 {
        let rule_area = Rect {
            y: area.y.saturating_add(1),
            height: 1,
            ..area
        };
        Paragraph::new(Line::from(Span::styled(
            "─".repeat(usize::from(area.width)),
            Style::default().fg(app.ui_theme.border),
        )))
        .render(rule_area, buf);
    }
}

/// Render the fixed one-line phase band.
///
/// Ocean placement (above vs below the composer) is owned by
/// [`crate::tui::phase_strip`]; this entry point only paints the band so
/// classic callers and tests keep a stable name.
pub fn render_footer(area: Rect, buf: &mut Buffer, app: &mut App) {
    crate::tui::phase_strip::render(area, buf, app);
}

/// The transcript rows the idle brand mark needs before it will draw at all.
///
/// This is [`ShellTier::for_area`]'s `Compact` floor, named so the *layout*
/// can honour it before the frame is split. Anything that reserves rows above
/// the transcript must subtract against this constant rather than guess, or
/// the reservation and the render gate drift and the mark is evicted by
/// chrome that was sized without knowing the mark existed.
pub(crate) const AMBIENT_MIN_CHAT_HEIGHT: u16 = 16;
/// Companion column floor, same reasoning as [`AMBIENT_MIN_CHAT_HEIGHT`].
pub(crate) const AMBIENT_MIN_CHAT_WIDTH: u16 = 60;

/// Build the post-launch idle composition: brand, workspace context, and one
/// direct invitation. Commands stay in the command surface instead of reading
/// like onboarding homework.
///
/// Expressed in terms of the ambient floor constants so the layout rule that
/// reserves the rows and the gate that spends them cannot disagree. (The old
/// spelling also tested `height >= 14 && width >= 28`, which was dead: the
/// tier check already demands 16 rows and 60 columns.)
#[must_use]
pub(crate) fn empty_state_mark_visible(area: Rect) -> bool {
    area.height >= AMBIENT_MIN_CHAT_HEIGHT && area.width >= AMBIENT_MIN_CHAT_WIDTH
}

#[must_use]
pub(crate) fn decorative_shell_motion_enabled(app: &App) -> bool {
    app.motion_policy().allows_decorative()
        && !app.attention_hold_active()
        && app.onboarding == OnboardingState::None
        && !app.launch.visible
        && app.view_stack.is_empty()
}

#[must_use]
fn idle_mark_animation_enabled(app: &App) -> bool {
    decorative_shell_motion_enabled(app) && matches!(ShellPhase::from_app(app), ShellPhase::Idle)
}

/// Raised-cosine caustic band for the idle whale. The 4s cycle spends roughly
/// 1.3s crossing the mark and parks off-screen for the remainder, so the brand
/// has a clear moment of life without becoming looping chrome.
#[must_use]
fn idle_mark_shine_opacity(diagonal: f32, elapsed_ms: u128) -> f32 {
    let cycle_progress = (elapsed_ms % IDLE_SHIMMER_CYCLE_MS) as f32 / IDLE_SHIMMER_CYCLE_MS as f32;
    let sweep_progress = (cycle_progress / IDLE_SHIMMER_SWEEP_FRACTION).min(1.0);
    let band_position =
        -IDLE_SHIMMER_BAND_HALF_WIDTH + sweep_progress * (1.0 + 2.0 * IDLE_SHIMMER_BAND_HALF_WIDTH);
    let distance = (diagonal - band_position).abs();
    if distance >= IDLE_SHIMMER_BAND_HALF_WIDTH {
        return 0.0;
    }
    let raised_cosine =
        0.5 * (1.0 + (std::f32::consts::PI * distance / IDLE_SHIMMER_BAND_HALF_WIDTH).cos());
    IDLE_SHIMMER_STRENGTH * raised_cosine
}

#[must_use]
fn idle_mark_color(base: Color, highlight: Color, opacity: f32) -> Color {
    if opacity <= 0.0 {
        return base;
    }
    match (base, highlight) {
        (Color::Rgb(..), Color::Rgb(..)) => crate::palette::blend(highlight, base, opacity),
        // Named/terminal-owned colors cannot be blended truthfully. Hold the
        // stable brand color instead of flashing the entire mark at full ink.
        _ => base,
    }
}

fn idle_whale_is_uwu(app: &App) -> bool {
    app.ui_theme.name == "uwu"
}

fn idle_whale_spout_row(app: &App) -> &'static str {
    if idle_whale_is_uwu(app) {
        UWU_IDLE_WHALE_SPOUT_ROW
    } else {
        IDLE_WHALE_SPOUT_ROW
    }
}

fn idle_whale_rows(app: &App) -> [&'static str; 3] {
    if idle_whale_is_uwu(app) {
        UWU_IDLE_WHALE_ROWS
    } else {
        IDLE_WHALE_ROWS
    }
}

/// Signal Current cyan owns the spout and the belly cut. It resolves through
/// the same Whale Teams ink the `/fleet` portraits use, so every theme gets
/// the brand cyan lifted to the secondary-chrome contrast floor rather than a
/// per-theme guess.
fn idle_whale_current_color(app: &App) -> Color {
    crate::tui::whales::WhaleInk::from_theme(&app.ui_theme).current
}

fn idle_whale_row_spans(
    text: &'static str,
    row: usize,
    elapsed_ms: u128,
    animated: bool,
    base: Color,
    highlight: Color,
    eye: Color,
) -> Vec<Span<'static>> {
    let rows = IDLE_WHALE_ROWS.len() as f32;
    let cols = IDLE_WHALE_ROWS
        .iter()
        .map(|line| line.chars().count())
        .max()
        .unwrap_or(1) as f32;
    let mut spans = Vec::new();
    let mut run = String::new();
    let mut run_color = None;

    for (column, ch) in text.chars().enumerate() {
        let diagonal = (column as f32 + (rows - 1.0 - row as f32)) / (cols + rows);
        let color = if matches!(ch, '·' | '░' | '✦' | '△') {
            // Soft uwu blush/sparkle and the quiet crown-fluke center use the
            // eye/sakura channel; classic otherwise only has the eye dot.
            eye
        } else if animated {
            idle_mark_color(
                base,
                highlight,
                idle_mark_shine_opacity(diagonal, elapsed_ms),
            )
        } else {
            base
        };
        if run_color != Some(color) {
            if let Some(previous) = run_color {
                spans.push(Span::styled(
                    std::mem::take(&mut run),
                    Style::default().fg(previous),
                ));
            }
            run_color = Some(color);
        }
        run.push(ch);
    }
    if let Some(previous) = run_color {
        spans.push(Span::styled(run, Style::default().fg(previous)));
    }
    spans
}

#[must_use]
fn idle_whale_block_width(spout: &str, rows: &[&str]) -> usize {
    std::iter::once(spout)
        .chain(rows.iter().copied())
        .map(UnicodeWidthStr::width)
        .max()
        .unwrap_or(0)
}

pub fn empty_state_lines(app: &App, area: Rect) -> Vec<Line<'static>> {
    if area.width == 0 || area.height == 0 {
        return Vec::new();
    }
    let width = usize::from(area.width);
    let tier = ShellTier::for_area(area);
    let mut lines = vec![Line::from(""); usize::from(area.height / 4)];
    if empty_state_mark_visible(area) {
        let animated = idle_mark_animation_enabled(app);
        let elapsed_ms = app.ocean_started_at.elapsed().as_millis();
        let spout = idle_whale_spout_row(app);
        let rows = idle_whale_rows(app);
        let current = idle_whale_current_color(app);
        let mut mark = vec![vec![Span::styled(spout, Style::default().fg(current))]];
        // Soft uwu: sakura blush/sparkle glyphs; classic keeps body peach + text eye.
        let highlight = if idle_whale_is_uwu(app) {
            app.ui_theme.accent_primary
        } else {
            app.ui_theme.text_body
        };
        mark.extend(rows.iter().enumerate().map(|(row, text)| {
            // The belly cut is water, not chrome: it holds the flat brand cyan
            // while the caustic sweep travels across the gold body above it.
            let is_current = row == IDLE_WHALE_CURRENT_ROW;
            idle_whale_row_spans(
                text,
                row,
                elapsed_ms,
                animated && !is_current,
                if is_current {
                    current
                } else {
                    app.ui_theme.accent_action
                },
                app.ui_theme.text_body,
                highlight,
            )
        }));
        // The spout, head, belly, peduncle, and flukes are one drawing. Give
        // every row the same outer inset so the authored offsets survive;
        // centering each row independently shears the silhouette apart.
        let block_inset =
            " ".repeat(width.saturating_sub(idle_whale_block_width(spout, &rows)) / 2);
        for row in mark {
            let mut spans = vec![Span::raw(block_inset.clone())];
            spans.extend(row);
            lines.push(Line::from(spans));
        }
        lines.push(Line::from(""));
    }

    let identity = crate::tui::workspace_context::identity_from_context(
        &app.workspace,
        app.workspace_context.as_deref(),
    );
    let workspace = crate::utils::display_path(&app.workspace);
    let branch = identity.branch.as_deref().map_or_else(
        || tr(app.ui_locale, MessageId::EmptyStateNoGit),
        |branch| Cow::Owned(branch.to_string()),
    );
    let context = if tier == ShellTier::Compact {
        branch.into_owned()
    } else {
        format!(
            "{workspace} · {branch} · {} {}",
            tr(app.ui_locale, MessageId::EmptyStateMcpLabel),
            app.mcp_configured_count
        )
    };
    let brand = "Hakus";
    let brand_inset = " ".repeat(width.saturating_sub(brand.width()) / 2);
    lines.push(Line::from(Span::styled(
        format!("{brand_inset}{brand}"),
        Style::default()
            .fg(app.ui_theme.text_body)
            .add_modifier(Modifier::BOLD),
    )));
    let context = truncate_to_width(&context, width);
    let inset = " ".repeat(width.saturating_sub(context.width()) / 2);
    lines.push(Line::from(Span::styled(
        format!("{inset}{context}"),
        Style::default().fg(app.ui_theme.text_soft),
    )));
    if area.height >= 4 {
        lines.push(Line::from(""));
        let prompt = tr(app.ui_locale, MessageId::EmptyStatePrompt);
        let prompt = truncate_to_width(prompt.as_ref(), width);
        let inset = " ".repeat(width.saturating_sub(prompt.width()) / 2);
        lines.push(Line::from(Span::styled(
            format!("{inset}{prompt}"),
            Style::default().fg(app.ui_theme.text_body),
        )));
    }
    lines
}
