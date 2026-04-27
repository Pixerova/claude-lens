// lib.rs — Claude Lens Tauri shell
//
// Zero custom Rust. All logic lives in the Python sidecar.
// This file handles:
//   - App startup: launch the sidecar process
//   - Tray icon: menu bar icon with click-to-toggle and right-click menu
//   - Global hotkey: Option+Space to show/hide the overlay window
//   - Window management: always-on-top, position persistence

use std::sync::Mutex;
use tauri::{
    AppHandle, Manager, Runtime,
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    menu::{Menu, MenuItem},
    image::Image,
};
use tauri_plugin_shell::process::CommandChild;
use window_vibrancy::{apply_vibrancy, NSVisualEffectMaterial};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut};

struct SidecarHandle(Mutex<Option<CommandChild>>);

/// Launch Claude.app via the macOS `open` command. Fire-and-forget.
/// macOS-only — revisit if cross-platform support is added.
#[tauri::command]
fn open_claude_app() -> Result<(), String> {
    std::process::Command::new("open")
        .args(["-a", "Claude"])
        .spawn()
        .map(|_| ())
        .map_err(|e| e.to_string())
}

// ── Sidecar ───────────────────────────────────────────────────────────────────

fn start_sidecar(app: &AppHandle) {
    use tauri_plugin_shell::ShellExt;
    let shell = app.shell();
    // The sidecar binary is bundled at binaries/sidecar (configured in tauri.conf.json).
    // In dev mode we spawn the Python process directly instead (see SETUP.md).
    match shell.sidecar("sidecar") {
        Ok(cmd) => {
            match cmd.spawn() {
                Ok((mut rx, child)) => {
                    // Drain the event receiver to prevent the sidecar's stdout/stderr
                    // pipe buffer from filling and blocking its logging calls.
                    tauri::async_runtime::spawn(async move {
                        while rx.recv().await.is_some() {}
                    });
                    if let Some(handle) = app.try_state::<SidecarHandle>() {
                        *handle.0.lock().unwrap() = Some(child);
                    }
                    eprintln!("[claude-lens] Sidecar spawned OK");
                }
                Err(e) => eprintln!("[claude-lens] Sidecar spawn failed: {e}"),
            }
        }
        Err(e) => {
            eprintln!("[claude-lens] Failed to create sidecar command: {e}");
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
        .invoke_handler(tauri::generate_handler![open_claude_app])
        .setup(|app| {
            // 1. Start the Python sidecar
            app.manage(SidecarHandle(Mutex::new(None)));
            start_sidecar(app.handle());

            // Apply macOS vibrancy (under-window blur effect)
            if let Some(window) = app.get_webview_window("main") {
                let _ = apply_vibrancy(&window, NSVisualEffectMaterial::UnderWindowBackground, None, None);
            }

            // 2. Build tray menu (right-click)
            let show_item = MenuItem::with_id(app, "show", "Open claude-lens", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &quit_item])?;

            // 3. Build tray icon
            let tray_icon_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("icons/tray-icon.png");
            let tray_icon = Image::from_path(&tray_icon_path)
                .unwrap_or_else(|_| app.default_window_icon().unwrap().clone());

            TrayIconBuilder::new()
                .icon(tray_icon)
                .icon_as_template(true)
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
        .build(tauri::generate_context!())
        .expect("error while building Claude Lens")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(handle) = app.try_state::<SidecarHandle>() {
                    if let Some(child) = handle.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
        });
}
