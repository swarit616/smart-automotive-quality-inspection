// Bundles the app with esbuild into dist/ (no dev-server proxy: the FastAPI backend serves dist/ in local mode).
import { build, context } from "esbuild";
import { cpSync, mkdirSync, rmSync } from "node:fs";

const watch = process.argv.includes("--watch");
rmSync("dist", { recursive: true, force: true });
mkdirSync("dist", { recursive: true });
cpSync("index.html", "dist/index.html");

const options = {
  entryPoints: ["src/main.tsx"],
  bundle: true,
  outfile: "dist/app.js",
  format: "esm",
  target: "es2022",
  jsx: "automatic",
  minify: !watch,
  sourcemap: watch,
  define: { "process.env.NODE_ENV": JSON.stringify(watch ? "development" : "production") },
  loader: { ".css": "css" },
  logLevel: "info",
};

if (watch) {
  const ctx = await context(options);
  await ctx.watch();
  console.log("watching for changes; open the backend URL (e.g. http://localhost:8000)");
} else {
  await build(options);
}
