//! AgentCenter 桌面壳：原生窗口 + FastAPI sidecar。关窗即停 API。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent};

const API_PORT: u16 = 8013;
const API_HEALTH: &str = "http://127.0.0.1:8013/api/health";
const API_HOME: &str = "http://127.0.0.1:8013/";

static BACKEND: Mutex<Option<Child>> = Mutex::new(None);
static STARTED_BY_APP: AtomicBool = AtomicBool::new(false);

fn support_dir() -> PathBuf {
    dirs_support()
}

fn dirs_support() -> PathBuf {
    home_dir().join("Library/Application Support/AgentCenter")
}

fn logs_dir() -> PathBuf {
    home_dir().join("Library/Logs/AgentCenter")
}

fn home_dir() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/tmp"))
}

fn desktop_log(msg: &str) {
    let _ = fs::create_dir_all(logs_dir());
    if let Ok(mut f) = OpenOptions::new()
        .create(true)
        .append(true)
        .open(logs_dir().join("desktop.log"))
    {
        let _ = writeln!(f, "{} {}", chrono_like_now(), msg);
    }
    eprintln!("{msg}");
}

fn chrono_like_now() -> String {
    // 避免额外依赖；ISO 近似即可
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format!("ts={secs}")
}

fn api_ok() -> bool {
    ureq::get(API_HEALTH)
        .timeout(Duration::from_secs(2))
        .call()
        .ok()
        .map(|r| (200..400).contains(&r.status()))
        .unwrap_or(false)
}

fn runtime_root(app: &AppHandle) -> PathBuf {
    if cfg!(debug_assertions) {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("runtime")
    } else {
        app.path()
            .resource_dir()
            .unwrap_or_else(|_| PathBuf::from("."))
            .join("runtime")
    }
}

fn ensure_user_dirs(runtime: &Path) {
    let _ = fs::create_dir_all(support_dir().join("data"));
    let _ = fs::create_dir_all(logs_dir());
    let env_dst = support_dir().join(".env");
    let env_src = runtime.join(".env.example");
    if !env_dst.exists() && env_src.is_file() {
        if let Err(e) = fs::copy(&env_src, &env_dst) {
            desktop_log(&format!("seed env failed err={e}"));
        } else {
            desktop_log(&format!("seeded env path={}", env_dst.display()));
        }
    }
}

fn prepend_path() {
    let extras = [
        "/opt/homebrew/bin".to_string(),
        "/usr/local/bin".to_string(),
        home_dir().join(".local/bin").display().to_string(),
        home_dir().join(".npm-global/bin").display().to_string(),
    ];
    let old = std::env::var("PATH").unwrap_or_default();
    let mut parts = extras.to_vec();
    parts.push(old);
    std::env::set_var("PATH", parts.join(":"));
}

fn spawn_backend(runtime: &Path) -> Result<Child, String> {
    let python = runtime.join("python/bin/python3");
    let backend = runtime.join("backend");
    if !python.is_file() {
        return Err(format!("python missing: {}", python.display()));
    }
    if !backend.join("app/main.py").is_file() {
        return Err(format!("backend missing: {}", backend.display()));
    }
    let log_file = logs_dir().join("sidecar.log");
    let log = File::create(&log_file).map_err(|e| e.to_string())?;
    let err = log.try_clone().map_err(|e| e.to_string())?;

    let db = support_dir().join("data/agentcenter.db");
    let mut cmd = Command::new(&python);
    cmd.current_dir(&backend)
        .arg("-m")
        .arg("uvicorn")
        .arg("app.main:app")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(API_PORT.to_string())
        .env("PYTHONUNBUFFERED", "1")
        .env("PYTHONPATH", &backend)
        .env("AGENTCENTER_ROOT", runtime)
        .env("AGENTCENTER_GUIDE_DIR", runtime.join("guide"))
        .env("AGENTCENTER_DATA_DIR", support_dir().join("data"))
        .env("AGENTCENTER_LOG_DIR", logs_dir())
        .env("AGENTCENTER_ENV_FILE", support_dir().join(".env"))
        .env("AGENTCENTER_STATIC_DIR", runtime.join("frontend"))
        .env(
            "DATABASE_URL",
            format!("sqlite+aiosqlite:///{}", db.display()),
        )
        .stdout(Stdio::from(log))
        .stderr(Stdio::from(err));

    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0);
    }

    desktop_log(&format!(
        "spawn sidecar python={} backend={}",
        python.display(),
        backend.display()
    ));
    cmd.spawn().map_err(|e| e.to_string())
}

fn stop_backend() {
    if !STARTED_BY_APP.load(Ordering::SeqCst) {
        return;
    }
    let mut guard = match BACKEND.lock() {
        Ok(g) => g,
        Err(_) => return,
    };
    if let Some(mut child) = guard.take() {
        desktop_log(&format!("stop sidecar pid={}", child.id()));
        #[cfg(unix)]
        {
            let pid = child.id() as i32;
            unsafe {
                libc::killpg(pid, libc::SIGTERM);
            }
            thread::sleep(Duration::from_millis(400));
            unsafe {
                libc::killpg(pid, libc::SIGKILL);
            }
        }
        let _ = child.kill();
        let _ = child.wait();
    }
    STARTED_BY_APP.store(false, Ordering::SeqCst);
}

fn set_status(app: &AppHandle, text: &str) {
    let js = format!(
        "var el=document.getElementById('status'); if(el) el.textContent={}",
        serde_json_string(text)
    );
    eval_main(app, &js);
}

fn serde_json_string(text: &str) -> String {
    let escaped = text.replace('\\', "\\\\").replace('\'', "\\'").replace('\n', " ");
    format!("'{escaped}'")
}

fn eval_main(app: &AppHandle, js: &str) {
    let handle = app.clone();
    let script = js.to_string();
    let _ = app.run_on_main_thread(move || {
        if let Some(w) = handle.get_webview_window("main") {
            let _ = w.eval(&script);
        }
    });
}

fn navigate_home(app: &AppHandle) {
    desktop_log("navigate ui");
    eval_main(
        app,
        &format!("window.location.replace('{API_HOME}')"),
    );
}

fn boot(app: AppHandle) {
    prepend_path();
    let runtime = runtime_root(&app);
    desktop_log(&format!("boot runtime={}", runtime.display()));
    ensure_user_dirs(&runtime);

    if api_ok() {
        desktop_log("reuse existing api");
        set_status(&app, "检测到已运行的 API，正在打开控制台…");
        navigate_home(&app);
        return;
    }

    set_status(&app, "正在启动 FastAPI sidecar…");
    match spawn_backend(&runtime) {
        Ok(child) => {
            STARTED_BY_APP.store(true, Ordering::SeqCst);
            if let Ok(mut g) = BACKEND.lock() {
                *g = Some(child);
            }
        }
        Err(e) => {
            desktop_log(&format!("spawn failed err={e}"));
            set_status(&app, &format!("启动失败：{e}。请查看 ~/Library/Logs/AgentCenter/desktop.log"));
            return;
        }
    }

    let start = Instant::now();
    while start.elapsed() < Duration::from_secs(90) {
        if api_ok() {
            navigate_home(&app);
            return;
        }
        thread::sleep(Duration::from_millis(400));
    }
    desktop_log("sidecar health timeout");
    set_status(
        &app,
        "启动超时。请查看 ~/Library/Logs/AgentCenter/sidecar.log",
    );
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let handle = app.handle().clone();
            thread::spawn(move || boot(handle));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building AgentCenter")
        .run(|_app, event| {
            if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
                stop_backend();
            }
        });
}
