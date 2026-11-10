import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "./" so the built app works from any sub-path (GitHub Pages, artifact hosting).
export default defineConfig({ plugins: [react()], base: "./" });
