const http = require("http");
const fs = require("fs");
const path = require("path");
const root = path.join(process.cwd(), "dist");
const mime = { ".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml", ".ico": "image/x-icon" };
const server = http.createServer((req, res) => {
  let reqPath = decodeURIComponent((req.url || "/").split("?")[0]);
  if (reqPath === "/") reqPath = "/index.html";
  let filePath = path.join(root, reqPath);
  if (!filePath.startsWith(root)) { res.statusCode = 403; res.end("Forbidden"); return; }
  fs.readFile(filePath, (err, data) => {
    if (err) {
      fs.readFile(path.join(root, "index.html"), (indexErr, indexData) => {
        if (indexErr) { res.statusCode = 404; res.end("Not found"); return; }
        res.setHeader("Content-Type", "text/html; charset=utf-8");
        res.end(indexData);
      });
      return;
    }
    const ext = path.extname(filePath).toLowerCase();
    res.setHeader("Content-Type", (mime[ext] || "application/octet-stream") + (ext === ".html" ? "; charset=utf-8" : ""));
    res.end(data);
  });
});
server.listen(4173, "127.0.0.1", () => console.log("STATIC_SERVER_OK http://127.0.0.1:4173"));
