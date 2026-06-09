import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
    plugins: [react()],
    server: {
        proxy: {
            '/repos': 'http://localhost:8000',
            '/query': 'http://localhost:8000',
            '/health': 'http://localhost:8000',
        }
    }
})