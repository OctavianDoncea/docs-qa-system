import { useState, useRef, useEffect } from 'react'
import Message from './Message'

export default function Chat({ messages, isQuerying, hasRepo, onQuery }) {
    const [input, setInput] = useState('')
    const bottomRef = useRef(null)

    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [messages.length, isQuerying])

    const handleSubmit = (e) => {
        e.preventDefault()
        const q = input.trim()
        if (!q || isQuerying || !hasRepo) return
        onQuery(q)
        setInput('')
    }

    const lastMsg = messages[messages.length - 1]
    const isStreaming = lastMsg?.role === 'assistant' && lastMsg?.streaming === true

    return (
        <div className='chat'>
            <div className='message-list'>
                {!hasRepo && messages.length === 0 && (
                    <div className='empty-state'>
                        <strong>No repository loaded</strong>
                        Paste a GitHub URL above and click "Load docs" to start.
                    </div>
                )}
                {hasRepo && messages.length === 0 && (
                    <div className='empty-state'>
                        Ask anything about the loaded documentation.
                    </div>
                )}
                {messages.map((msg, i) => (
                    <Message key={i} message={msg} />
                ))}

                {isQuerying && !isStreaming && (
                    <div className='typing-indicator' aria-label='Thinking'>
                        <span /><span /><span />
                    </div>
                )}

                <div ref={bottomRef}></div>
            </div>
            <form className='chat-form' onSubmit={handleSubmit}>
                <input
                    className='chat-input-failed'
                    type='text'
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder={hasRepo ? 'Ask a question about the docs' : 'Load a repo first'}
                    disabled={!hasRepo || isQuerying}
                    aria-label='Question input'
                />
                <button className='btn-send' type='submit' disabled={!hasRepo || isQuerying || !input.trim()} aria-label='Send'>
                    <svg viewbox='0 0 24 24' width='15' height='15' fill='none' stroke='currentColor' strokeWidth='2.5' strokeLinecap='round' strokeLinejoin='round'>
                        <line x1='22' y1='2' x2='11' y2='13' />
                        <polygon points='22 2 15 22 11 13 2 9 22 2' />
                    </svg>                    
                </button>
            </form>
        </div>
    )
}