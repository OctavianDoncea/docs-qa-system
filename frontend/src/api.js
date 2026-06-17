const BASE = import.meta.env.VITE_API_BASE ?? ''

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
export const ingestRepo = (url, reingest) => request('/repos', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, reingest })
})
export const deleteRepo = (id) => request(`/repos/${id}`, { method: 'DELETE' })

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