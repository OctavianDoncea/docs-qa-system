import { useState } from 'react'
import SourceCard from './SourceCard'
import ReactMarkdown from 'react-markdown'

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

    const isStreaming = message.streaming === true
    const hasSources = !isStreaming && (message.sources?.length ?? 0) > 0

    return (
        <div className='message message-assistant'>
            <div className='bubble bubble-assistant'>
                <div className='answer-text'>
                    <ReactMarkdown>{message.content}</ReactMarkdown>
                    {isStreaming && <span className='stream-cursor' aria-hidden='true'></span>}
                </div>
                
                {!isStreaming && message.searchQuery && (
                    <div className='search-query-note'>
                        Searched docs as: <em>&ldquo;{message.searchQuery}&rdquo;</em>
                    </div>
                )}
                
                {hasSources && (
                    <div className='sources'>
                        <button className='sources-toggle' onClick={() => setSourcesOpen(e => !e)}>
                            <svg width='10' height='10' viewBox='0 0 10 10' fill='currentColor'
                                style={{ transform: sourcesOpen ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }}
                            >
                                <polygon points='2,1 8,5 2,9' />
                            </svg>
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