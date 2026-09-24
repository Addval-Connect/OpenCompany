import { Menu, type MenuItemConstructorOptions, app, shell } from "electron";

export interface MenuHooks {
  logsDir: string;
  dataDir: string;
  checkForUpdates: () => void;
  openAbout: () => void;
}

export function installMenu(hooks: MenuHooks): void {
  const isMac = process.platform === "darwin";
  const template: MenuItemConstructorOptions[] = [];

  if (isMac) {
    template.push({
      label: app.name,
      submenu: [
        { label: `About ${app.name}`, click: hooks.openAbout },
        { type: "separator" },
        { label: "Check for Updates...", click: hooks.checkForUpdates },
        { type: "separator" },
        { role: "hide" },
        { role: "hideOthers" },
        { role: "unhide" },
        { type: "separator" },
        { role: "quit" },
      ],
    });
  }

  template.push({
    label: "File",
    submenu: [isMac ? { role: "close" } : { role: "quit" }],
  });

  template.push({
    label: "Edit",
    submenu: [
      { role: "undo" },
      { role: "redo" },
      { type: "separator" },
      { role: "cut" },
      { role: "copy" },
      { role: "paste" },
      { role: "selectAll" },
    ],
  });

  const view: MenuItemConstructorOptions[] = [
    { role: "reload" },
    { role: "forceReload" },
    { type: "separator" },
    { role: "resetZoom" },
    { role: "zoomIn" },
    { role: "zoomOut" },
    { type: "separator" },
    { role: "togglefullscreen" },
  ];
  if (!app.isPackaged) view.splice(2, 0, { role: "toggleDevTools" });
  template.push({ label: "View", submenu: view });

  template.push({
    label: "Help",
    submenu: [
      { label: "Open Logs Folder", click: () => void shell.openPath(hooks.logsDir) },
      { label: "Open Data Folder", click: () => void shell.openPath(hooks.dataDir) },
      { type: "separator" },
      { label: "Check for Updates...", click: hooks.checkForUpdates },
      { label: "OpenCompany Website", click: () => void shell.openExternal("https://opencompany.sh") },
      ...(isMac ? [] : [{ type: "separator" } as MenuItemConstructorOptions, { label: `About ${app.name}`, click: hooks.openAbout }]),
    ],
  });

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}
