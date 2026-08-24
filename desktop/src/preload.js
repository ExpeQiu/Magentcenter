const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("agentCenterDesktop", {
  platform: process.platform,
});
