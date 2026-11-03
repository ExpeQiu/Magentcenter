//! AgentCenter 桌面壳。窗口关闭不停止后台节点服务（Core + Node Agent）。

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
static NODE_AGENT: Mutex<Option<Child>> = Mutex::new(None);
static STARTED_BY_APP: AtomicBool = AtomicBool::new(false);

fn support_dir() -> PathBuf {
    dirs_support()
}

fn dirs_support() -> PathBuf {
    home_dir().join("Library/Application Support/AgentCenter")
}

fn data_dir() -> PathBuf {
    support_dir().join("data")
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

fn warn_protocol(app: &AppHandle) {
    let Ok(response) = ureq::get(API_HEALTH).timeout(Duration::from_secs(2)).call() else {
        return;
    };
    let Ok(body) = response.into_string() else {
        return;
    };
    if body.contains("\"protocol_version\":2") || body.contains("\"protocol_version\": 2") {
        return;
    }
    if body.contains("protocol_version") {
        set_status(
            app,
            "节点协议版本不兼容，请升级节点服务。关闭窗口不会停止正在运行的任务。",
        );
    }
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
    let _ = fs::create_dir_all(data_dir());
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
        home_dir().join(".npm-global/bin").display().to_string(),
        home_dir().join(".local/bin").display().to_string(),
        "/opt/homebrew/bin".to_string(),
        "/usr/local/bin".to_string(),
    ];
    let old = std::env::var("PATH").unwrap_or_default();
    let mut parts = extras.to_vec();
    parts.push(old);
    std::env::set_var("PATH", parts.join(":"));
}

fn write_pid(name: &str, pid: u32) {
    let _ = fs::create_dir_all(data_dir());
    let path = data_dir().join(format!("{name}.pid"));
    if let Err(e) = fs::write(&path, format!("{pid}\n")) {
        desktop_log(&format!("write {name}.pid failed err={e}"));
    }
    if name == "core" {
        let _ = fs::write(data_dir().join("agentcenter.pid"), format!("{pid}\n"));
        let _ = fs::write(data_dir().join("sidecar.pid"), format!("{pid}\n"));
    }
}

fn clear_pid(name: &str) {
    let _ = fs::remove_file(data_dir().join(format!("{name}.pid")));
    if name == "core" {
        let _ = fs::remove_file(data_dir().join("agentcenter.pid"));
        let _ = fs::remove_file(data_dir().join("sidecar.pid"));
    }
}

fn stop_pid(pid: i32) {
    #[cfg(unix)]
    {
        unsafe {
            libc::killpg(pid, libc::SIGTERM);
        }
        thread::sleep(Duration::from_millis(400));
        unsafe {
            libc::killpg(pid, libc::SIGKILL);
        }
        unsafe {
            libc::kill(pid, libc::SIGTERM);
        }
    }
}

fn stop_named(mutex: &Mutex<Option<Child>>, name: &str) {
    let mut guard = match mutex.lock() {
        Ok(g) => g,
        Err(_) => return,
    };
    if let Some(mut child) = guard.take() {
        desktop_log(&format!("stop {name} pid={}", child.id()));
        stop_pid(child.id() as i32);
        let _ = child.kill();
        let _ = child.wait();
        clear_pid(name);
        return;
    }
    let path = data_dir().join(format!("{name}.pid"));
    if let Ok(raw) = fs::read_to_string(&path) {
        if let Ok(pid) = raw.trim().parse::<i32>() {
            desktop_log(&format!("stop {name} from pidfile pid={pid}"));
            stop_pid(pid);
            clear_pid(name);
        }
    }
    if name == "core" {
        for legacy in ["sidecar", "agentcenter"] {
            let p = data_dir().join(format!("{legacy}.pid"));
            if let Ok(raw) = fs::read_to_string(&p) {
                if let Ok(pid) = raw.trim().parse::<i32>() {
                    desktop_log(&format!("stop legacy {legacy} pid={pid}"));
                    stop_pid(pid);
                    let _ = fs::remove_file(&p);
                }
            }
        }
    }
}

fn stop_all_services() {
    stop_named(&NODE_AGENT, "node-agent");
    stop_named(&BACKEND, "core");
    STARTED_BY_APP.store(false, Ordering::SeqCst);
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

    let db = data_dir().join("agentcenter.db");
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
        .env("AGENTCENTER_DATA_DIR", data_dir())
        .env("AGENTCENTER_LOG_DIR", logs_dir())
        .env("AGENTCENTER_ENV_FILE", support_dir().join(".env"))
        .env("AGENTCENTER_STATIC_DIR", runtime.join("frontend"))
        .env("DEPLOY_PROFILE", "full")
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
        "spawn core python={} backend={}",
        python.display(),
        backend.display()
    ));
    cmd.spawn().map_err(|e| e.to_string())
}

fn env_wants_node_agent() -> bool {
    let env_path = support_dir().join(".env");
    let Ok(raw) = fs::read_to_string(env_path) else {
        return false;
    };
    let mut enroll = false;
    let mut start_flag = String::from("auto");
    for line in raw.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some((k, v)) = line.split_once('=') {
            let key = k.trim();
            let val = v.trim().trim_matches('"').trim_matches('\'');
            if key == "FLEET_ENROLL_TOKEN" && !val.is_empty() {
                enroll = true;
            }
            if key == "START_NODE_AGENT" {
                start_flag = val.to_ascii_lowercase();
            }
        }
    }
    match start_flag.as_str() {
        "on" | "1" | "true" | "yes" => true,
        "off" | "0" | "false" | "no" => false,
        _ => enroll,
    }
}

fn spawn_node_agent(runtime: &Path) -> Result<Child, String> {
    let python = runtime.join("python/bin/python3");
    let fleet_src = runtime.join("fleet-edge/src");
    let node_src = runtime.join("node-agent/src");
    if !node_src.join("agentcenter_node/main.py").is_file() {
        // 开发态：相对仓库
        let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|p| p.parent())
            .map(|p| p.to_path_buf())
            .unwrap_or_else(|| PathBuf::from("."));
        return spawn_node_agent_at(&python, &repo.join("fleet-edge/src"), &repo.join("node-agent/src"));
    }
    spawn_node_agent_at(&python, &fleet_src, &node_src)
}

fn spawn_node_agent_at(python: &Path, fleet_src: &Path, node_src: &Path) -> Result<Child, String> {
    if !python.is_file() {
        return Err(format!("python missing for node-agent: {}", python.display()));
    }
    let log_file = logs_dir().join("node-agent.log");
    let log = File::create(&log_file).map_err(|e| e.to_string())?;
    let err = log.try_clone().map_err(|e| e.to_string())?;
    let path = format!(
        "{}:{}:{}",
        node_src.display(),
        fleet_src.display(),
        std::env::var("PYTHONPATH").unwrap_or_default()
    );
    let mut cmd = Command::new(python);
    cmd.arg("-m")
        .arg("agentcenter_node.main")
        .env("PYTHONUNBUFFERED", "1")
        .env("PYTHONPATH", path)
        .env("AGENTCENTER_URL", format!("http://127.0.0.1:{API_PORT}"))
        .env("AGENTCENTER_DATA_DIR", data_dir())
        .env("AGENTCENTER_ENV_FILE", support_dir().join(".env"))
        .stdout(Stdio::from(log))
        .stderr(Stdio::from(err));

    // 从用户 .env 注入 enroll token
    if let Ok(raw) = fs::read_to_string(support_dir().join(".env")) {
        for line in raw.lines() {
            let line = line.trim();
            if let Some((k, v)) = line.split_once('=') {
                let key = k.trim();
                if key == "FLEET_ENROLL_TOKEN" || key == "FLEET_MOCK" || key == "FLEET_RUNTIMES" {
                    cmd.env(key, v.trim().trim_matches('"').trim_matches('\''));
                }
            }
        }
    }

    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0);
    }

    desktop_log("spawn node-agent");
    cmd.spawn().map_err(|e| e.to_string())
}

fn maybe_start_node_agent(runtime: &Path) {
    if !env_wants_node_agent() {
        desktop_log("node-agent skipped (no enroll token / START_NODE_AGENT=off)");
        return;
    }
    match spawn_node_agent(runtime) {
        Ok(child) => {
            write_pid("node-agent", child.id());
            if let Ok(mut g) = NODE_AGENT.lock() {
                *g = Some(child);
            }
            desktop_log("node-agent started");
        }
        Err(e) => desktop_log(&format!("node-agent spawn failed err={e}")),
    }
}

fn set_status(app: &AppHandle, text: &str) {
    let js = format!(
        "var el=document.getElementById('status'); if(el) el.textContent={}",
        serde_json_string(text)
    );
    eval_main(app, &js);
}

fn serde_json_string(text: &str) -> String {
    let escaped = text
        .replace('\\', "\\\\")
        .replace('\'', "\\'")
        .replace('\n', " ");
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
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let url = format!("{API_HOME}?ac={stamp}");
    desktop_log(&format!("navigate ui url={url}"));
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        let Some(window) = handle.get_webview_window("main") else {
            desktop_log("navigate skipped: main window missing");
            return;
        };
        if let Err(e) = window.clear_all_browsing_data() {
            desktop_log(&format!("clear webview cache failed err={e}"));
        }
        let handle2 = handle.clone();
        thread::spawn(move || {
            thread::sleep(Duration::from_millis(400));
            let handle3 = handle2.clone();
            let _ = handle2.run_on_main_thread(move || {
                let Some(window) = handle3.get_webview_window("main") else {
                    return;
                };
                match url.parse::<tauri::Url>() {
                    Ok(parsed) => {
                        if let Err(e) = window.navigate(parsed) {
                            desktop_log(&format!("navigate failed err={e}"));
                        }
                    }
                    Err(e) => desktop_log(&format!("bad ui url err={e}")),
                }
            });
        });
    });
}

fn boot(app: AppHandle) {
    prepend_path();
    let runtime = runtime_root(&app);
    desktop_log(&format!("boot runtime={}", runtime.display()));
    ensure_user_dirs(&runtime);

    if api_ok() {
        desktop_log("reuse existing api");
        maybe_start_node_agent(&runtime);
        warn_protocol(&app);
        set_status(
            &app,
            "检测到已运行的节点服务，正在打开控制台。关闭窗口不会停止任务。",
        );
        navigate_home(&app);
        return;
    }

    set_status(&app, "正在启动本地核心…");
    match spawn_backend(&runtime) {
        Ok(child) => {
            write_pid("core", child.id());
            STARTED_BY_APP.store(true, Ordering::SeqCst);
            if let Ok(mut g) = BACKEND.lock() {
                *g = Some(child);
            }
        }
        Err(e) => {
            desktop_log(&format!("spawn failed err={e}"));
            set_status(
                &app,
                &format!("启动失败：{e}。请查看 ~/Library/Logs/AgentCenter/desktop.log"),
            );
            return;
        }
    }

    let start = Instant::now();
    while start.elapsed() < Duration::from_secs(90) {
        if api_ok() {
            maybe_start_node_agent(&runtime);
            warn_protocol(&app);
            navigate_home(&app);
            return;
        }
        thread::sleep(Duration::from_millis(400));
    }
    desktop_log("core health timeout");
    set_status(
        &app,
        "启动超时。请查看 ~/Library/Logs/AgentCenter/sidecar.log",
    );
}

#[tauri::command]
fn stop_node_service() -> String {
    desktop_log("explicit stop Core + Node Agent");
    stop_all_services();
    "stopped".to_string()
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![stop_node_service])
        .setup(|app| {
            let handle = app.handle().clone();
            thread::spawn(move || boot(handle));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building AgentCenter")
        .run(|_app, event| {
            if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
                desktop_log("window closed; node service keeps running");
            }
        });
}
