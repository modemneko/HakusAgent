use std::path::PathBuf;

fn main() {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    hakus_build_support::declare_rerun_conditions(&manifest_dir);
    hakus_build_support::emit_build_version(&manifest_dir, env!("CARGO_PKG_VERSION"));
}
