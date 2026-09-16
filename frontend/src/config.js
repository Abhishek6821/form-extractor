// Backend base URL. Netlify's proxy times out at ~30 s, so on the hosted site we call Render directly.
const PROD_API = "https://form-extractor-api.onrender.com";
const fromEnv = import.meta.env.VITE_API_BASE;
const onNetlify = typeof window !== "undefined" && /netlify\.app$/.test(window.location.hostname);
export const API_BASE = fromEnv || (onNetlify ? PROD_API : "/api");
