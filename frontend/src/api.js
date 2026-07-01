const BASE = import.meta.env.VITE_API_BASE ?? ''

// Optional API key for write actions (POST /repos, DELETE /repos/:id).
// Leave VITE_API_KEY unset in deployed builds: any VITE_-prefixed value is
// compiled into the public JS bundle and readable by anyone. Manage
// ingest/delete via curl with the real key instead. See DEPLOYMENT, Part 3.
const API_KEY = import.meta.env.VITE_API_KEY ?? ''

function withApiKey(headers = {}) {
    return API_KEY ? { ...headers, 'X-API-Key': API_KEY } : headers
}

async function request(path, options = {}) {
    const res = await fetch(`${BASE}${path}`, options)
    if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try {
            const body = await res.json()
            detail = body.detail || detail
        } catch {}
        throw new Error(detail)
    }
    if (res.status === 204) return null
    return res.json()
}

export const getRepos = () => request('/repos')
export const deleteRepo = (id) => request(`/repos/${id}`, {
    method: 'DELETE',
    headers: withApiKey()
})

export const startIngest = (url, reingest = false) => request('/repos', {
    method: 'POST',
    headers: withApiKey({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ url, reingest })
})

export const pollJob = (jobId) => request(`/repos/jobs/${jobId}`)

export async function* streamQuery(question, repoId, history = []) {
    const res = await fetch(`${BASE}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, repo_id: repoId, history })
    })

    if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try {
            const body = await res.json()
            detail = body.error || detail
        } catch {}
        throw new Error(detail)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''

        for (const part of parts) {
            const line = part.trim()
            if (line.startsWith('data: ')) {
                try {
                    yield JSON.parse(line.slice(6))
                } catch {}
            }
        }
    }
}