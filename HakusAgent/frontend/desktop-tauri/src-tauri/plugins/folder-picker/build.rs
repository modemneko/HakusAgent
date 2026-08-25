fn main() {
    tauri_plugin::Builder::new(&["pick_folder", "refresh_folder", "sync_folder"])
        .android_path("android")
        .build();
}

