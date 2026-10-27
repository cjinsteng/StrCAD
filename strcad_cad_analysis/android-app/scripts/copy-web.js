// copy ../mobile (the web app) into www/ for Capacitor; the service worker is not needed inside the APK
const fs = require("fs"), path = require("path");
const src = path.join(__dirname, "..", "..", "mobile"), dst = path.join(__dirname, "..", "www");
fs.rmSync(dst, { recursive: true, force: true });
fs.cpSync(src, dst, { recursive: true, filter: (p) => !p.endsWith("sw.js") && !p.endsWith("README.md") });
console.log("copied", src, "->", dst);
