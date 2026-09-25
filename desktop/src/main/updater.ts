/**
 * Auto-update against GitHub Releases (electron-builder publishes
 * latest.yml / latest-mac.yml / latest-linux.yml next to the installers).
 *
 * Windows (NSIS) and Linux (AppImage) download and apply. macOS is
 * notify-only until the app is code-signed: Squirrel.Mac refuses to apply
 * an update to an unsigned app, so the shell just points the user at the
 * release page. deb installs have no auto-update either (package manager).
 */

import { existsSync } from "node:fs";
import { join } from "node:path";

import { dialog, shell } from "electron";
import { autoUpdater } from "electron-updater";

import type { Logger } from "./logging";

export interface UpdaterOptions {
  log: Logger;
  isMac: boolean;
  isPackaged: boolean;
  releasesUrl: string;
}

let initialised = false;

export function initUpdater(opts: UpdaterOptions): void {
  if (initialised || !opts.isPackaged) return;
  const { log, isMac, releasesUrl } = opts;
  // electron-builder writes app-update.yml only for real installer targets;
  // `--dir` builds and ad-hoc runs have no feed to check.
  if (!existsSync(join(process.resourcesPath, "app-update.yml"))) {
    log.info("[updater] no app-update.yml in resources (unpacked build); updates disabled");
    return;
  }
  initialised = true;

  autoUpdater.logger = log;
  autoUpdater.autoDownload = !isMac;
  autoUpdater.autoInstallOnAppQuit = !isMac;

  autoUpdater.on("error", (err) => log.warn(`[updater] ${err?.message ?? err}`));
  autoUpdater.on("update-available", async (info) => {
    log.info(`[updater] update available: ${info.version}`);
    if (!isMac) return; // downloads automatically; prompt happens on update-downloaded
    const { response } = await dialog.showMessageBox({
      type: "info",
      title: "Update available",
      message: `OpenCompany ${info.version} is available.`,
      detail: "Automatic updates on macOS are enabled once the app is code-signed. Download the new version from the releases page.",
      buttons: ["Open releases page", "Later"],
      defaultId: 0,
      cancelId: 1,
    });
    if (response === 0) void shell.openExternal(releasesUrl);
  });
  autoUpdater.on("update-downloaded", async (info) => {
    const { response } = await dialog.showMessageBox({
      type: "info",
      title: "Update ready",
      message: `OpenCompany ${info.version} has been downloaded.`,
      detail: "Restart now to install it, or it will be installed the next time you quit.",
      buttons: ["Restart now", "Later"],
      defaultId: 0,
      cancelId: 1,
    });
    if (response === 0) autoUpdater.quitAndInstall();
  });
}

export function checkForUpdates(log: Logger): void {
  if (!initialised) {
    log.info("[updater] disabled in development");
    return;
  }
  autoUpdater.checkForUpdatesAndNotify().catch((err) => log.warn(`[updater] check failed: ${err?.message ?? err}`));
}
