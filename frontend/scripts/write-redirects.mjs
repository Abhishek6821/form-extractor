// Writes dist/_redirects so Netlify proxies /api/* to the backend (no CORS, no env in the browser).
import { writeFileSync, mkdirSync } from "node:fs";

const backend = (process.env.BACKEND_URL || "").replace(/\/+$/, "");
// Note: the app calls the backend directly when VITE_API_BASE is set (Netlify's proxy times out at ~30 s);
// the /api proxy below stays as a fallback for same-origin calls.
const lines = [];
if (backend) lines.push(`/api/*  ${backend}/:splat  200`);
else console.warn("BACKEND_URL not set: /api will not be proxied (set it in Netlify env vars)");
lines.push("/*  /index.html  200");
mkdirSync("dist", { recursive: true });
writeFileSync("dist/_redirects", lines.join("\n") + "\n");
console.log("dist/_redirects:\n" + lines.join("\n"));
