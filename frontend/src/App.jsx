import { useState, useEffect } from 'react'
import RepoForm from './components/RepoForm'
import Chat from './components/Chat'
import * as api from './api'

export default function App() {
    const [repos, setRepos] = useState([])
    const [activeRepoId, setActiveRepoId] = useState(null)
    const [messages, setMessages] = useState([])
    const [isIngesting, setIsIngesting] = useState(false)
    const [isQuerying, setIsQuerying] = useState(false)
    const [error, setError] = useState(null)

    useEffect(() => {
        api.getRepos()
        .then(data => {
            setRepos(data)
            if (data.length > 0) setActiveRepoId(data[0].id)
        })
        .catch(() => {

        })
    }, [])

    const handleIngest = async (url) => {
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
        setMessages(prev => [...prev, { role: 'user', content: question }])
        setIsQuerying(true)
        try {
            const result = await api.queryRepo(question, activeRepoId)
            setMessages(prev => [
                ...prev,
                { role: 'assistant', content: result.answer, sources: result.sources }
            ])
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
                <span className='app-logo'>Docs Q&A</span>
                {activeRepo && (
                    <span className='active-repo'>{activeRepo.name} - {activeRepo.chunk_count} chunks</span>
                )}
            </header>

            <RepoForm 
                repos={repos}
                activeRepoId={activeRepoId}
                isIngesting={isIngesting}
                onIngest={handleIngest}
                onRepoChange={handleRepoChange}
            />

            {isIngesting && (
                <div className='status-banner status-info'>
                    <span className='spinner' style={{ borderTopColor: 'var(--info-fg)', borderColor: 'var(--info-br)' }}></span>
                    Ingesting documentation. This will take 20-60 seconds.
                </div>
            )}

            {error && !isIngesting && (
                <div className='status-banner status-error'>
                    <span>{error}</span>
                    <button onClick={() => setError(null)} aria-label='Dismiss error'>x</button>
                </div>
            )}

            <Chat 
                messages={messages}
                isQuerying={isQuerying}
                hasRepo={!!activeRepo}
                onQuery={handleQuery}
            />
        </div>
    )
}