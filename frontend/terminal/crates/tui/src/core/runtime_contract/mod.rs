//! Versioned contracts shared by interactive, headless, Fleet, and evaluation
//! adapters.
//!
//! This module is intentionally independent of rendering and provider clients.
//! It gives the Core-profile experiments a typed place to converge before any
//! candidate becomes the product default.

pub mod budget;
pub mod context;
pub mod ledger;
pub mod manifest;
pub mod model;
pub mod profile;
pub mod progress;
pub mod retry;
pub mod terminal;
pub mod termination;
pub mod work;

/// Schema shared by the initial Core runtime contracts.
pub const RUNTIME_CONTRACT_SCHEMA_VERSION: u32 = 1;
