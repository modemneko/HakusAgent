//! Utility command area: attachments, background tasks, jobs, MCP, network
//! inspection, and self-update.

mod attachment;
mod automation;
mod jobs;
mod mcp;
mod network;
mod task;
mod update;

use crate::commands::traits::{Command, CommandGroup, FunctionCommand, RegisterCommand};

pub struct UtilityCommands;

impl CommandGroup for UtilityCommands {
    fn commands(&self) -> &'static [Box<dyn Command>] {
        cached_command_list!(vec![
            Box::new(FunctionCommand::new(
                attachment::AttachCmd::info(),
                attachment::AttachCmd::execute,
            )),
            Box::new(FunctionCommand::new(
                automation::AutomationCmd::info(),
                automation::AutomationCmd::execute,
            )),
            Box::new(FunctionCommand::new(
                task::TaskCmd::info(),
                task::TaskCmd::execute,
            )),
            Box::new(FunctionCommand::new(
                jobs::JobsCmd::info(),
                jobs::JobsCmd::execute,
            )),
            Box::new(FunctionCommand::new(
                mcp::McpCmd::info(),
                mcp::McpCmd::execute,
            )),
            Box::new(FunctionCommand::new(
                network::NetworkCmd::info(),
                network::NetworkCmd::execute,
            )),
            Box::new(FunctionCommand::new(
                update::UpdateCmd::info(),
                update::UpdateCmd::execute,
            )),
        ])
    }
}
