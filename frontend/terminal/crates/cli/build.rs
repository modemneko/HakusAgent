use std::path::PathBuf;

fn main() {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    hakus_build_support::declare_rerun_conditions(&manifest_dir);
    embed_windows_icon(&manifest_dir);
    hakus_build_support::emit_build_version(&manifest_dir, env!("CARGO_PKG_VERSION"));
}

#[cfg(windows)]
fn embed_windows_icon(manifest_dir: &PathBuf) {
    let resource = manifest_dir.join("hakus.rc");
    println!("cargo:rerun-if-changed={}", resource.display());
    embed_resource::compile(resource, embed_resource::NONE);
}

#[cfg(not(windows))]
fn embed_windows_icon(_manifest_dir: &PathBuf) {}
