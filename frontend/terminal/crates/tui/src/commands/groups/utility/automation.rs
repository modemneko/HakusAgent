//! Operator controls for durable scheduled automations.

use crate::commands::CommandResult;
use crate::commands::traits::{CommandInfo, RegisterCommand};
use crate::localization::{Locale, MessageId, tr};
use crate::tui::app::{App, AppAction, AutomationAction};

pub(in crate::commands) const COMMAND_INFO: CommandInfo = CommandInfo {
    name: "automation",
    aliases: &["automations", "scheduled"],
    usage: "/automation [list|show <id>|pause <id>|resume <id>|delete <id> [--confirm <token>]|run <id>]",
    description_id: MessageId::CmdAutomationDescription,
};

pub(in crate::commands) struct AutomationCmd;

impl RegisterCommand for AutomationCmd {
    fn info() -> &'static CommandInfo {
        &COMMAND_INFO
    }

    fn execute(app: &mut App, arg: Option<&str>) -> CommandResult {
        automation(app.ui_locale, arg)
    }
}

fn automation(locale: Locale, args: Option<&str>) -> CommandResult {
    let raw = args.unwrap_or("").trim();
    if raw.is_empty() || raw.eq_ignore_ascii_case("list") {
        return action(AutomationAction::List);
    }

    let mut parts = raw.split_whitespace();
    let verb = parts.next().unwrap_or("").to_ascii_lowercase();

    match verb.as_str() {
        "show" | "status" => single_id(locale, &mut parts, AutomationAction::Show),
        "pause" => single_id(locale, &mut parts, AutomationAction::Pause),
        "resume" => single_id(locale, &mut parts, AutomationAction::Resume),
        "delete" | "remove" | "rm" => delete(locale, &mut parts),
        "run" | "trigger" => single_id(locale, &mut parts, AutomationAction::Run),
        _ => usage_error(locale),
    }
}

fn single_id<'a>(
    locale: Locale,
    parts: &mut impl Iterator<Item = &'a str>,
    make_action: fn(String) -> AutomationAction,
) -> CommandResult {
    let Some(id) = parts.next() else {
        return usage_error(locale);
    };
    if parts.next().is_some() {
        return usage_error(locale);
    }
    action(make_action(id.to_string()))
}

fn delete<'a>(locale: Locale, parts: &mut impl Iterator<Item = &'a str>) -> CommandResult {
    let Some(id) = parts.next() else {
        return usage_error(locale);
    };
    let confirmation = match (parts.next(), parts.next(), parts.next()) {
        (None, None, None) => None,
        (Some(flag), Some(token), None) if flag.eq_ignore_ascii_case("--confirm") => {
            Some(token.to_string())
        }
        _ => return usage_error(locale),
    };
    action(AutomationAction::Delete {
        id: id.to_string(),
        confirmation,
    })
}

fn usage_error(locale: Locale) -> CommandResult {
    CommandResult::error(tr(locale, MessageId::AutomationUsage).into_owned())
}

fn action(action: AutomationAction) -> CommandResult {
    CommandResult::action(AppAction::Automation(action))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parsed(args: Option<&str>) -> Option<AutomationAction> {
        match automation(Locale::En, args).action {
            Some(AppAction::Automation(action)) => Some(action),
            _ => None,
        }
    }

    #[test]
    fn parses_list_show_and_mutations() {
        assert_eq!(parsed(None), Some(AutomationAction::List));
        assert_eq!(parsed(Some("list")), Some(AutomationAction::List));
        assert_eq!(
            parsed(Some("show auto_1")),
            Some(AutomationAction::Show("auto_1".to_string()))
        );
        assert_eq!(
            parsed(Some("pause auto_1")),
            Some(AutomationAction::Pause("auto_1".to_string()))
        );
        assert_eq!(
            parsed(Some("resume auto_1")),
            Some(AutomationAction::Resume("auto_1".to_string()))
        );
        assert_eq!(
            parsed(Some("delete auto_1")),
            Some(AutomationAction::Delete {
                id: "auto_1".to_string(),
                confirmation: None,
            })
        );
        assert_eq!(
            parsed(Some("run auto_1")),
            Some(AutomationAction::Run("auto_1".to_string()))
        );
    }

    #[test]
    fn accepts_operator_aliases() {
        assert_eq!(
            parsed(Some("status auto_1")),
            Some(AutomationAction::Show("auto_1".to_string()))
        );
        assert_eq!(
            parsed(Some("rm auto_1")),
            Some(AutomationAction::Delete {
                id: "auto_1".to_string(),
                confirmation: None,
            })
        );
        assert_eq!(
            parsed(Some("trigger auto_1")),
            Some(AutomationAction::Run("auto_1".to_string()))
        );
    }

    #[test]
    fn validates_missing_ids_and_unknown_actions() {
        for verb in ["show", "pause", "resume", "delete", "run", "unknown"] {
            let result = automation(Locale::En, Some(verb));
            assert!(result.message.is_some(), "{verb} should show usage");
            assert!(result.action.is_none());
        }
    }

    #[test]
    fn delete_confirmation_is_explicit_and_exact() {
        assert_eq!(
            parsed(Some("delete auto_1 --confirm receipt")),
            Some(AutomationAction::Delete {
                id: "auto_1".to_string(),
                confirmation: Some("receipt".to_string()),
            })
        );
        for invalid in [
            "delete auto_1 --confirm",
            "delete auto_1 receipt",
            "delete auto_1 --confirm receipt extra",
        ] {
            let result = automation(Locale::En, Some(invalid));
            assert!(result.is_error, "{invalid} should be rejected");
            assert!(result.action.is_none());
        }
    }
}
