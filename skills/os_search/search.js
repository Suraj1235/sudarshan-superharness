#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

// Safety net: ensure unhandled async errors always produce JSON for the LLM
process.on('unhandledRejection', (err) => {
    console.error(JSON.stringify({ error: (err && err.message) || "Unknown async error in search.js" }));
    process.exit(1);
});

const query = process.argv.slice(2).join(' ');
const MIN_DELAY_MS = 2000; // 2-second rate limit
const SEARXNG_URL = process.env.SEARXNG_URL || 'http://127.0.0.1:8080';
const MAX_RETRIES = 1;
const RETRY_DELAY_MS = 3000;

if (!query) {
    console.error(JSON.stringify({ error: "No query provided. Usage: node search.js 'your search query'" }));
    process.exit(1);
}

// Ensure rate limiting (Cross-process)
async function enforceRateLimit() {
    const tmpDir = require('os').tmpdir();
    const LOCK_FILE = path.join(tmpDir, 'os_search_last_run.txt');
    try {
        if (fs.existsSync(LOCK_FILE)) {
            const lastRun = parseInt(fs.readFileSync(LOCK_FILE, 'utf8'));
            const now = Date.now();
            const diff = now - lastRun;
            if (diff < MIN_DELAY_MS) {
                const waitTime = MIN_DELAY_MS - diff;
                await new Promise(resolve => setTimeout(resolve, waitTime));
            }
        }
    } catch (e) {
        // Fallback if file read fails
    }
    fs.writeFileSync(LOCK_FILE, Date.now().toString());
}

// Check if SearXNG is reachable before searching
async function healthCheck() {
    try {
        const response = await fetch(`${SEARXNG_URL}/healthz`, {
            signal: AbortSignal.timeout(5000)
        });
        return response.ok;
    } catch (e) {
        return false;
    }
}

async function searchWithRetry(attempt = 0) {
    const searchUrl = `${SEARXNG_URL}/search?q=${encodeURIComponent(query)}&format=json`;
    const response = await fetch(searchUrl, {
        headers: { 'User-Agent': 'SudarshanOS/16.9 (Search Sovereign)' },
        signal: AbortSignal.timeout(15000)
    });

    if (!response.ok) {
        if ((response.status === 502 || response.status === 503) && attempt < MAX_RETRIES) {
            console.error(`WARN: SearXNG returned ${response.status}. Retrying in ${RETRY_DELAY_MS / 1000}s... (attempt ${attempt + 1}/${MAX_RETRIES})`);
            await new Promise(resolve => setTimeout(resolve, RETRY_DELAY_MS));
            return searchWithRetry(attempt + 1);
        }
        throw new Error(`SearXNG Error: HTTP ${response.status}`);
    }

    return response.json();
}

async function search() {
    try {
        await enforceRateLimit();

        // Pre-flight: check if SearXNG is alive
        const alive = await healthCheck();
        if (!alive) {
            console.error(JSON.stringify({
                error: "[SYSTEM: SEARXNG_OFFLINE] SearXNG is unreachable at " + SEARXNG_URL + ". " +
                    "ACTION REQUIRED: Ensure Docker/OrbStack is running and execute: " +
                    "cd infrastructure/searxng && docker-compose up -d"
            }));
            process.exit(1);
        }

        const data = await searchWithRetry();

        // Map SearXNG format to our standard OS format
        const results = (data.results || []).slice(0, 10).map(r => ({
            title: r.title,
            url: r.url,
            snippet: r.content || r.snippet || ""
        }));

        console.log(JSON.stringify({
            query,
            engine: "Sovereign-SearXNG",
            count: results.length,
            results
        }, null, 2));

    } catch (error) {
        if (error.name === 'TimeoutError' || error.cause?.code === 'UND_ERR_CONNECT_TIMEOUT') {
            console.error(JSON.stringify({
                error: "[SYSTEM: SEARXNG_TIMEOUT] SearXNG connection timed out at " + SEARXNG_URL + ". " +
                    "The container may be starting up. Retry in 10 seconds or check: docker ps"
            }));
        } else if (error.cause?.code === 'ECONNREFUSED') {
            console.error(JSON.stringify({
                error: "[SYSTEM: SEARXNG_OFFLINE] Connection refused at " + SEARXNG_URL + ". " +
                    "Docker container is not running. Execute: cd infrastructure/searxng && docker-compose up -d"
            }));
        } else {
            console.error(JSON.stringify({ error: error.message }));
        }
        process.exit(1);
    }
}

search();