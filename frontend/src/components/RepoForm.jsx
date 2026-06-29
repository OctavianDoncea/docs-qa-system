import { useState } from 'react'

const PHASE_LABELS = {
    starting: 'Starting...',
    pending: 'Queued...',
    running: 'Working...',
    fetching: 'Fetching files...',
    chunking: 'Splitting into chunks...',
    embedding: 'Generating embeddings...',
    saving: 'Saving to database...',
    done: 'Done!',
}

export default function RepoForm({ repos, activeRepoId, progress, onIngest, onRepoChange }) {
    const [url, setUrl] = useState('')
    const isIngesting = progress !== null

    const handleSubmit = (e) => {
        e.preventDefault()
        const trimmed = url.trim()
        if (!trimmed || isIngesting) return
        onIngest(trimmed)
        setUrl('')
    }

    return (
        <div className='repo-bar-wrap'>
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
                spellCheck={false}
              />
              <button
                className='btn-ingest'
                type='submit'
                disabled={isIngesting || !url.trim()}
              >
                {isIngesting ? 'Loading...' : 'Load docs'}
              </button>
            </form>
    
            {repos.length > 0 && !isIngesting && (
              <div className='repo-select-wrap'>
                <label className='repo-select-label' htmlFor='repo-select'>Repo</label>
                <select
                  id='repo-select'
                  className='repo-select'
                  value={activeRepoId ?? ''}
                  onChange={(e) => onRepoChange(Number(e.target.value))}
                >
                  {repos.map(r => (
                    <option key={r.id} value={r.id}>{r.name}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
    
          {isIngesting && (
            <div className='progress-wrap'>
              <div className='progress-track'>
                <div
                  className='progress-fill'
                  style={{ width: `${progress.progress}%` }}
                />
              </div>
              <span className='progress-label'>
                {PHASE_LABELS[progress.phase] ?? progress.phase}  {progress.progress}%
              </span>
            </div>
          )}
        </div>
      )
}