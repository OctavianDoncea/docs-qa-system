/** Thin wrappers around the backend API. */

async function request(path, options = {}) {
    const res = await fetch(path, options)
    if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try {
            const body = await res.json()
            detail = body.detail || detail
        } catch {
            // response was not JSON
        }
        throw new Error(detail)
    }

    if (res.status === 204) return null
    return res.json()
}

export function getRepos() {
    return request('/repos')
}

export function ingestRepo(url, reingest = false) {
    return request('/repos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, reingest })
    })
}

export function queryRepo(question, repoId) {
    return request('/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, repo_id: repoId })
    })
}

export function deleteRepo(repoId) {
    return request(`/repos/${repoId}`, { method: 'DELETE' })
}