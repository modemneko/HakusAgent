//! Calm welcome and ready screens for first run.
//!
//! The welcome is unnumbered and asks nothing: one headline, one supporting
//! sentence, one primary action, one exit. The ready screen closes the flow
//! by handing the user the composer pre-seeded with a first task — Enter
//! opens the product, never another educational surface.

use ratatui::style::{Modifier, Style};
use ratatui::text::{Line, Span};

use crate::localization::MessageId;
use crate::palette;
use crate::tui::app::App;

pub fn lines(app: &App, width: usize) -> Vec<Line<'static>> {
    let mut out = vec![
        headline(app, MessageId::OnboardWelcomeTitle),
        Line::from(""),
    ];
    body(&mut out, app, MessageId::OnboardWelcomeLead, width);
    out
}

pub fn ready_lines(app: &App, width: usize) -> Vec<Line<'static>> {
    let mut out = vec![headline(app, MessageId::OnboardReadyTitle), Line::from("")];
    body(&mut out, app, MessageId::OnboardReadyLead, width);
    // The offline-explore notice is durable onboarding state, not a toast:
    // trust decisions are allowed to replace status_message without hiding
    // that no provider route is connected.
    let notice = if app.onboarding_explore_offline {
        Some(app.tr(MessageId::OnboardOfflineNotice).into_owned())
    } else {
        app.status_message.clone()
    };
    if let Some(message) = notice {
        out.push(Line::from(""));
        out.push(Line::from(Span::styled(
            message,
            Style::default().fg(palette::STATUS_WARNING),
        )));
    }
    out
}

fn headline(app: &App, id: MessageId) -> Line<'static> {
    Line::from(Span::styled(
        app.tr(id).to_string(),
        Style::default()
            .fg(palette::WHALE_HUMAN)
            .add_modifier(Modifier::BOLD),
    ))
}

fn body(out: &mut Vec<Line<'static>>, app: &App, id: MessageId, width: usize) {
    for segment in super::wrap_words(&app.tr(id), width) {
        out.push(Line::from(Span::styled(
            segment,
            Style::default().fg(palette::TEXT_PRIMARY),
        )));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::Config;
    use crate::localization::Locale;
    use crate::tui::app::TuiOptions;
    use std::path::PathBuf;

    fn test_app_with_locale(locale: Locale) -> App {
        let options = TuiOptions {
            ..crate::test_support::test_tui_options(PathBuf::from("."))
        };
        let mut app = App::new(options, &Config::default());
        app.ui_locale = locale;
        app
    }

    fn body(_app: &App, lines: Vec<Line<'static>>) -> String {
        lines
            .into_iter()
            .flat_map(|line| {
                line.spans
                    .into_iter()
                    .map(|span| span.content.to_string())
                    .collect::<Vec<_>>()
            })
            .collect::<Vec<_>>()
            .join("\n")
    }

    #[test]
    fn ready_screen_reads_offline_truth_from_typed_state() {
        let mut app = test_app_with_locale(Locale::En);
        app.onboarding_explore_offline = true;
        app.status_message = Some("Workspace trust was not changed.".to_string());
        let text = body(&app, ready_lines(&app, 70));
        assert!(
            text.contains(app.tr(MessageId::OnboardOfflineNotice).as_ref()),
            "{text}"
        );
        assert!(!text.contains("Workspace trust was not changed."), "{text}");
    }
}
