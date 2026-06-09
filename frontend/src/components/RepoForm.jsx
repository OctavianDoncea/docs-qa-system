import { useState } from 'react'

export default function RepoForm({ repos, activeRepoId, isIngesting, onIngest, onRepoChange }) {
    const [url, setUrl] = useState('')

    const handleSubmit = (e) => {
        e.preventDefault()
        const trimmed = url.trim()
        if (!trimmed) return
        onIngest(trimmed)
        setUrl('')
    }

    return (
        <div className='repo-bar'>
            <form className='repo-form' onSubmit={handleSubmit}>
                <input
                    className='repo-input'
                    type='text'
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder='github.com/owner/repo'
                    disabled={isIngesting}
                    aria-label='GitHub repository URL'
                    spellcheck={false}
                />
                <button className='btn-ingest' type='submit' disabled={isIngesting || !url.trim()}>
                    {isIngesting ? (
                        <>
                            <span className='spinner' />
                            Ingesting...
                        </>
                    ) : ('Load docs')}
                </button>
            </form>

            {repos.length > 0 && (
                <div>
                    <label className='repo-select-label' htmlFor='repo-select'>
                        Repo
                    </label>
                    <select id='repo-select' className='repo-select' value={activeRepoId ?? ''} onChange={e => onRepoChange(Number(e.target.value))}>
                        {repos.map(r => (
                            <option key={r.id} value={r.id}>
                                {r.name}
                            </option>
                        ))}
                    </select>
                </div>
            )}
        </div>
    )
}