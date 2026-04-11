// lib.rs — Claude Lens Tauri shell
//
// Zero custom Rust. All logic lives in the Python sidecar.
// This file handles:
//   - App startup: launch the sidecar process
//   - Tray icon: menu bar icon with click-to-toggle and right-click menu
//   - Global hotkey: Option+Space to show/hide the overlay window
//   - Window management: always-on-top, position persistence

use tauri::{
    AppHandle, Manager, Runtime,
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    menu::{Menu, MenuItem},
};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut};

// ── Sidecar ───────────────────────────────────────────────────────────────────

fn start_sidecar(app: &AppHandle) {
    use tauri_plugin_shell::ShellExt;
    let shell = app.shell();
    // The sidecar binary is bundled at binaries/sidecar (configured in tauri.conf.json).
    // In dev mode we spawn the Python process directly instead (see SETUP.md).
    match shell.sidecar("sidecar") {
        Ok(cmd) => {
            let _ = cmd.spawn();
        }
        Err(e) => {
            eprintln!("[claude-lens] Failed to start sidecar: {e}");
        }
    }
}

// ── Window helpers ────────────────────────────────────────────────────────────

fn toggle_window<R: Runtime>(app: &AppHandle<R>) {
    if let Some(window) = app.get_webview_window("main") {
        if window.is_visible().unwrap_or(false) {
            let _ = window.hide();
        } else {
            let _ = window.show();
            let _ = window.set_focus();
        }
    }
}

fn show_window<R: Runtime>(app: &AppHandle<R>) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

// ── App entry ─────────────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .setup(|app| {
            // 1. Start the Python sidecar
            start_sidecar(app.handle());

            // 2. Build tray menu (right-click)
            let show_item = MenuItem::with_id(app, "show", "Open Claude Lens", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &quit_item])?;

            // 3. Build tray icon
            TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("Claude Lens")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => show_window(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    // Left-click on menu bar icon → toggle the overlay
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        toggle_window(tray.app_handle());
                    }
                })
                .build(app)?;

            // 4. Register global hotkey: Option+Space
            let handle = app.handle().clone();
            let shortcut = Shortcut::new(Some(Modifiers::ALT), Code::Space);
            app.global_shortcut().on_shortcut(shortcut, move |_app, _shortcut, _event| {
                toggle_window(&handle);
            })?;

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Claude Lens");
}
