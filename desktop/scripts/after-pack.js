const { execSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

function stripAppleDouble(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.name.startsWith("._")) {
      try {
        fs.rmSync(full, { force: true });
      } catch {
        /* ignore */
      }
      continue;
    }
    if (entry.isDirectory()) stripAppleDouble(full);
  }
}

/**
 * Ad-hoc sign the .app so local macOS installs can be opened without a
 * Developer ID. Strip AppleDouble files first (exFAT/Lexar volumes).
 */
exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== "darwin") return;
  const appName = context.packager.appInfo.productFilename;
  const appPath = path.join(context.appOutDir, `${appName}.app`);
  if (!fs.existsSync(appPath)) {
    console.warn(`[after-pack] app not found: ${appPath}`);
    return;
  }
  stripAppleDouble(appPath);
  execSync(`codesign --force --deep --sign - "${appPath}"`, { stdio: "inherit" });
  console.log(`[after-pack] ad-hoc signed ${appPath}`);
};
