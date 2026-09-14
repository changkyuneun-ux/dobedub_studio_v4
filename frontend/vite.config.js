import { defineConfig } from "vite";
export default defineConfig({
    base: "/studio/",
    server: {
        proxy: {
            "/api": "http://127.0.0.1:8787",
            "/docs": "http://127.0.0.1:8787"
        }
    }
});
