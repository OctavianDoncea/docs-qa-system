import { useState, useEffect } from 'react'
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
    const [isIngesting, setIsIngesting] = useState(false)
    const [isQuerying, setIsQuerying] = useState(false)
    const [error, setError] = useState(null)

    useEffect(() => {
        api.getRepos().then(data => {
            setRepos(data)
            if (data.length > 0) setActiveRepoId(data[0].id)
        }).catch(() => {})
    }, [])

    const handleDigest = async (url) => {
        setIsIngesting(true)
        setError(null)
        try {
            const repo = await api.ingestRepo(url)
            setRepos(prev => [repo, ...prev.filter(r => r.id !== repo.id)])
            setActiveRepoId(repo.id)
            setMessages([])
        } catch (err) {
            setError(err.message)
        } finally {
            setIsIngesting(false)
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
                        return [...rest, { ...last, sources: event.sources ?? [], searchQuery: event.search_query ?? null, streaming: false }]
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
                    <span className='active-repo'>{activeRepo.name} - {activeRepo.chunk_count} chunks</span>
                )}
            </header>

            <RepoForm repos={repos} activeRepoId={activeRepoId} isIngesting={isIngesting} onIngest={handleDigest} onRepoChange={handleRepoChange} />

            {isIngesting && (
                <div className='status-banner status-info'>
                    <span className='spinner' style={{ borderTopColor: 'var(--info-fg)', borderColor: 'var(--info-br)' }}></span>
                    Ingesting documentation. This will take 20-60 seconds.
                </div>
            )}

            {error && !isIngesting && (
                <div className='status-banner status-error'>
                    <span>{error}</span>
                    <button onClick={() => setError(null)} aria-label="Dismiss error">x</button>
                </div>
            )}

            <Chat messages={messages} isQuerying={isQuerying} hasRepo={!!activeRepoId} onQuery={handleQuery} />
        </div>
    )
}