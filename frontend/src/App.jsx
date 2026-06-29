import { useState, useEffect, useRef } from 'react'
import RepoForm from './components/RepoForm'
import Chat from './components/Chat'
import * as api from './api'

const MAX_HISTORY_MESSAGES = 6

function buildHistory(messages) {
    return messages.filter(m => m.role === 'user' || m.role === 'assistant').slice(-MAX_HISTORY_MESSAGES)
        .map(m => ({ role: m.role, content: m.content }))
}

export default function App() {
    const [repos, setRepos] = useState([])
    const [activeRepoId, setActiveRepoId] = useState(null)
    const [messages, setMessages] = useState([])
    const [isQuerying, setIsQuerying] = useState(false)
    const [error, setError] = useState(null)
    const [progress, setProgress] = useState(null)
    const pollRef = useRef(null)

    useEffect(() => {
        api.getRepos().then(data => {
            setRepos(data)
            if (data.length > 0) setActiveRepoId(data[0].id)
        }).catch(() => {})
        return () => { if (pollRef.current) clearTimeout(pollRef.current) }
    }, [])

    const handleDigest = async (url) => {
        setError(null)
        setProgress({ phase: 'starting', progress: 0 })

        try {
            const { job_id } = await api.startIngest(url)

            const poll = async () => {
                try {
                    const job = await api.pollJob(job_id)
                    setProgress({ phase: job.phase ?? job.status, progress: job.progress })

                    if (job.status === 'completed') {
                        setProgress(null)
                        const fresh = await api.getRepos()
                        setRepos(fresh)
                        if (job.repo_id) {
                            setActiveRepoId(job.repo_id)
                            setMessages([])
                        }
                        return
                    }
                    if (job.status === 'failed') {
                        setProgress(null)
                        setError(job.error ?? 'Ingestion failed.')
                        return
                    }
                    pollRef.current = setTimeout(poll, 1000)
                } catch (err) {
                    setProgress(null)
                    setError(err.message)
                }
            }
            poll()
        } catch (err) {
            setProgress(null)
            setError(err.message)
        }
    }

    const handleQuery = async (question) => {
        if (!activeRepoId || isQuerying) return

        const history = buildHistory(messages)

        setMessages(prev => [...prev, { role: 'user', content: question }])
        setIsQuerying(true)

        let firstToken = true

        try {
            for await (const event of api.streamQuery(question, activeRepoId, history)) {
                if (event.error) {
                    setMessages(prev => [...prev, { role: 'error', content: event.error }])
                    break
                }

                if (!event.done && event.content) {
                    if (firstToken) {
                        firstToken = false
                        setMessages(prev => [
                            ...prev, { role: 'assistant', content: event.content, sources: [], streaming: true }
                        ])
                    } else {
                        setMessages(prev => {
                            const rest = prev.slice(0, -1)
                            const last = prev[prev.length - 1]
                            return [...rest, { ...last, content: last.content + event.content }]
                        })
                    }
                }

                if (event.done) {
                    setMessages(prev => {
                        const rest = prev.slice(0, -1)
                        const last = prev[prev.length - 1]
                        if (!last || last.role !== 'assistant') return prev
                        return [...rest, { ...last, sources: event.sources ?? [], searchQuery: event.search_query ?? null, lowConfidence: event.low_confidence ?? false, streaming: false }]
                    })
                }
            }
        } catch (err) {
            setMessages(prev => [...prev, { role: 'error', content: err.message }])
        } finally {
            setIsQuerying(false)
        }
    }

    const handleRepoChange = (repoId) => {
        setActiveRepoId(repoId)
        setMessages([])
        setError(null)
    }

    const activeRepo = repos.find(r => r.id === activeRepoId) ?? null

    return (
        <div className='app'>
            <header className='app-header'>
                <span className='app-logo'>docs-qa</span>
                {activeRepo && (
                    <span className='active-repo'>{activeRepo.name} ({activeRepo.chunk_count} chunks)</span>
                )}
            </header>

            <RepoForm repos={repos} activeRepoId={activeRepoId} progress={progress} onIngest={handleDigest} onRepoChange={handleRepoChange} />

            {error && !progress && (
                <div className='status-banner status-error'>
                    <span>{error}</span>
                    <button onClick={() => setError(null)} aria-label="Dismiss error">x</button>
                </div>
            )}

            <Chat messages={messages} isQuerying={isQuerying} hasRepo={!!activeRepoId} onQuery={handleQuery} />
        </div>
    )
}