const { app, BrowserWindow, dialog, Menu, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const API_PORT = Number(process.env.PORT || 8013);
const FRONTEND_PORT = Number(process.env.FRONTEND_PORT || 3013);
const API_URL = `http://127.0.0.1:${API_PORT}`;
const FRONTEND_URL = `http://127.0.0.1:${FRONTEND_PORT}`;

const children = [];
let startedByApp = false;
let mainWindow = null;
let logStream = null;

function userHome() {
  return app.getPath("home");
}

function supportDir() {
  return path.join(userHome(), "Library", "Application Support", "AgentCenter");
}

function logsDir() {
  return path.join(userHome(), "Library", "Logs", "AgentCenter");
}

function runtimeRoot() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "runtime");
  }
  return path.join(__dirname, "..", "resources", "runtime");
}

function log(level, msg, extra) {
  const ts = new Date().toISOString();
  const line = extra
    ? `${ts} [${level}] ${msg} ${JSON.stringify(extra)}`
    : `${ts} [${level}] ${msg}`;
  if (logStream) {
    logStream.write(`${line}\n`);
  }
  console.log(line);
}

function prependPath() {
  const extras = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    path.join(userHome(), ".local", "bin"),
    path.join(userHome(), ".npm-global", "bin"),
  ];
  process.env.PATH = `${extras.join(":")}:${process.env.PATH || ""}`;
}

function ensureUserDirs() {
  fs.mkdirSync(path.join(supportDir(), "data"), { recursive: true });
  fs.mkdirSync(logsDir(), { recursive: true });
  const envDst = path.join(supportDir(), ".env");
  const envSrc = path.join(runtimeRoot(), ".env.example");
  if (!fs.existsSync(envDst) && fs.existsSync(envSrc)) {
    fs.copyFileSync(envSrc, envDst);
    log("INFO", "seeded env file", { path: envDst });
  }
}

function loadUserEnv() {
  const envFile = path.join(supportDir(), ".env");
  if (!fs.existsSync(envFile)) return;
  const text = fs.readFileSync(envFile, "utf8");
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const idx = line.indexOf("=");
    if (idx <= 0) continue;
    const key = line.slice(0, idx).trim();
    let value = line.slice(idx + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
}

function childEnv() {
  const dbPath = path.join(supportDir(), "data", "agentcenter.db");
  return {
    ...process.env,
    AGENTCENTER_ROOT: runtimeRoot(),
    AGENTCENTER_GUIDE_DIR: path.join(runtimeRoot(), "guide"),
    AGENTCENTER_DATA_DIR: path.join(supportDir(), "data"),
    AGENTCENTER_LOG_DIR: logsDir(),
    AGENTCENTER_ENV_FILE: path.join(supportDir(), ".env"),
    DATABASE_URL: `sqlite+aiosqlite:///${dbPath}`,
    HOST: "127.0.0.1",
    PORT: String(API_PORT),
    FRONTEND_PORT: String(FRONTEND_PORT),
    PYTHONUNBUFFERED: "1",
  };
}

function pipeChild(name, child) {
  const write = (chunk) => {
    const text = chunk.toString();
    if (logStream) logStream.write(text);
  };
  if (child.stdout) child.stdout.on("data", write);
  if (child.stderr) child.stderr.on("data", write);
  child.on("exit", (code, signal) => {
    log("INFO", `${name} exited`, { code, signal, pid: child.pid });
  });
}

function spawnLogged(name, cmd, args, opts) {
  log("INFO", `spawn ${name}`, { cmd, args, cwd: opts.cwd });
  const child = spawn(cmd, args, { ...opts, stdio: ["ignore", "pipe", "pipe"] });
  children.push(child);
  pipeChild(name, child);
  return child;
}

function httpOk(url) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: 2500 }, (res) => {
      res.resume();
      resolve(res.statusCode >= 200 && res.statusCode < 400);
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function isHealthy() {
  const api = await httpOk(`${API_URL}/api/health`);
  const web = await httpOk(FRONTEND_URL);
  return api && web;
}

async function waitHealthy(timeoutMs = 90000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await isHealthy()) return true;
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

function pythonBin() {
  const packaged = path.join(runtimeRoot(), "python", "bin", "python3");
  if (fs.existsSync(packaged)) return packaged;
  return "python3";
}

function nodeBin() {
  const packaged = path.join(runtimeRoot(), "node", "bin", "node");
  if (fs.existsSync(packaged)) return packaged;
  return process.execPath;
}

function frontendEnv() {
  const env = {
    ...childEnv(),
    PORT: String(FRONTEND_PORT),
    HOSTNAME: "127.0.0.1",
  };
  if (nodeBin() === process.execPath) {
    env.ELECTRON_RUN_AS_NODE = "1";
  }
  return env;
}

function spawnBackend() {
  const backendDir = path.join(runtimeRoot(), "backend");
  const py = pythonBin();
  return spawnLogged(
    "backend",
    py,
    ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(API_PORT)],
    {
      cwd: backendDir,
      env: {
        ...childEnv(),
        PYTHONPATH: backendDir,
      },
    },
  );
}

function spawnFrontend() {
  const frontendDir = path.join(runtimeRoot(), "frontend");
  const serverJs = path.join(frontendDir, "server.js");
  if (!fs.existsSync(serverJs)) {
    throw new Error(`frontend server.js missing: ${serverJs}`);
  }
  return spawnLogged("frontend", nodeBin(), [serverJs], {
    cwd: frontendDir,
    env: frontendEnv(),
  });
}

function stopChildren() {
  if (!startedByApp) return;
  for (const child of children) {
    if (!child.killed && child.pid) {
      try {
        child.kill("SIGTERM");
      } catch {
        /* ignore */
      }
    }
  }
}

function createMenu() {
  const template = [
    {
      label: app.name,
      submenu: [
        { role: "about" },
        { type: "separator" },
        {
          label: "打开配置目录",
          click: () => shell.openPath(supportDir()),
        },
        {
          label: "打开日志",
          click: () => shell.openPath(logsDir()),
        },
        { type: "separator" },
        { role: "quit" },
      ],
    },
    { role: "editMenu" },
    { role: "viewMenu" },
    { role: "windowMenu" },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    title: "AgentCenter",
    backgroundColor: "#0b1220",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  await mainWindow.loadFile(path.join(__dirname, "loading.html"));
}

async function showError(message) {
  log("ERROR", message);
  if (mainWindow && !mainWindow.isDestroyed()) {
    await mainWindow.webContents.executeJavaScript(
      `document.getElementById('status').textContent = ${JSON.stringify(message)}`,
    );
  }
  dialog.showErrorBox("AgentCenter 启动失败", message);
}

async function boot() {
  prependPath();
  ensureUserDirs();
  loadUserEnv();
  const logFile = path.join(logsDir(), "desktop.log");
  logStream = fs.createWriteStream(logFile, { flags: "a" });
  log("INFO", "boot", {
    packaged: app.isPackaged,
    runtime: runtimeRoot(),
    support: supportDir(),
    platform: `${process.platform}-${process.arch}`,
  });

  createMenu();
  await createWindow();

  if (await isHealthy()) {
    log("INFO", "reusing already-running local services");
  } else {
    const runtime = runtimeRoot();
    if (!fs.existsSync(path.join(runtime, "backend", "app", "main.py"))) {
      await showError(
        "未找到打包运行时。请先执行 ./scripts/package-dmg.sh 生成安装包。",
      );
      return;
    }
    startedByApp = true;
    spawnBackend();
    spawnFrontend();
    const ok = await waitHealthy();
    if (!ok) {
      await showError(
        `服务启动超时。请查看日志：${logsDir()}/desktop.log`,
      );
      return;
    }
  }

  log("INFO", "loading UI", { url: FRONTEND_URL });
  await mainWindow.loadURL(FRONTEND_URL);
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
  app.whenReady().then(boot).catch(async (err) => {
    await showError(String(err && err.stack ? err.stack : err));
  });
  app.on("before-quit", stopChildren);
  app.on("window-all-closed", () => {
    stopChildren();
    app.quit();
  });
}
