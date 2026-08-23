//! WeChat ClawBot command group.

//! Exposes `/wechat login|status|logout|send <user> <text>|poll`.

//! The command emits [`AppAction::WeChat(WeChatAction)`] variants which are
//! handled in the UI event loop where the live `IlLinkClient` can be
//! accessed.

use crate::commands::CommandResult;
use crate::commands::traits::{CommandInfo, RegisterCommand};
use crate::localization::MessageId;
use crate::tui::app::{App, AppAction};
use crate::tui::app::types::WeChatAction;

// ---------------------------------------------------------------------------
// CommandInfo constants
// ---------------------------------------------------------------------------

pub(in crate::commands) const WECHAT_INFO: CommandInfo = CommandInfo {
    name: "wechat",
    aliases: &["wx", "weixin", "wechat-clawbot"],
    usage: "/wechat <login|status|logout|send|poll>",
    description_id: MessageId::CmdWechatDescription,
};

// ---------------------------------------------------------------------------
// Command structs
// ---------------------------------------------------------------------------

pub(in crate::commands) struct WeChatCmd;

impl RegisterCommand for WeChatCmd {
    fn info() -> &'static CommandInfo {
        &WECHAT_INFO
    }
    fn execute(app: &mut App, arg: Option<&str>) -> CommandResult {
        wechat(app, arg)
    }
}

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

pub fn wechat(app: &mut App, arg: Option<&str>) -> CommandResult {
    let sub = arg.unwrap_or("").trim();

    match sub {
        "" | "help" => {
            let help = [
                "WeChat ClawBot (iLink protocol)",
                "",
                "Usage:",
                "  /wechat login     Start QR code login flow",
                "  /wechat status    Show current login status",
                "  /wechat logout    Clear saved credentials",
                "  /wechat send <user> <text>  Send a text message",
                "  /wechat poll      Poll once for new messages",
            ];
            let msg = help.join("\n");
            CommandResult::message(msg)
        }
        "login" => {
            CommandResult::action(AppAction::WeChat(WeChatAction::StartLogin))
        }
        "status" => {
            CommandResult::action(AppAction::WeChat(WeChatAction::ShowStatus))
        }
        "logout" => {
            CommandResult::action(AppAction::WeChat(WeChatAction::Logout))
        }
        "send" => {
            // The arg after "send" is expected as: <user_id> <text>
            // But since execute() only receives the first arg token,
            // we emit an action that the UI layer can handle with full context.
            CommandResult::action(AppAction::WeChat(WeChatAction::Send {
                to_user: String::new(),
                text: String::new(),
            }))
        }
        "poll" => {
            CommandResult::action(AppAction::WeChat(WeChatAction::Poll))
        }
        _ => {
            CommandResult::error(format!(
                "Unknown subcommand: /wechat {sub}. Use /wechat help for usage."
            ))
        }
    }
}
