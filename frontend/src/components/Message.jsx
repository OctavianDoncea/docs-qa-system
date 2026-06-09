import { useState } from 'react'
import SourceCard from './SourceCard'

export default function Message({ message }) {
    const [sourcesOpen, setSourcesOpen] = useState(false)

    if (message.role == 'user') {
        return (
            <div className='message message-user'>
                <div className='bubble bubble-user'>{message.content}</div>
            </div>
        )
    }

    if (message.role == 'error') {
        return (
            <div className='message message-error'>
                <div className='bubble bubble-error'>{message.content}</div>
            </div>
        )
    }

    const hasSources = message.sources?.length > 0

    return (
        <div className='message message-assistant'>
            <div className='bubble bubble-assistant'>
                <div className='answer-text'>{message.content}</div>
                {hasSources && (
                    <div className='sources'>
                        <button className='sources-toggle' onClick={() => setSourcesOpen(e => !e)}>
                            <span className='toggle-arrow'>{sourceOpen ? '▾' : '▸'}</span>
                            {message.sources.length} source{message.sources.length !== 1 ? 's' : ''}
                        </button>
                        {sourcesOpen && (
                            <div className='sources-list'>
                                {message.sources.map(s => (
                                    <SourceCard key={s.index} source={s} />
                                ))}
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}