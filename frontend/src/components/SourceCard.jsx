import { useState } from 'react'

export default function SourceCard({ source }) {
    const [expanded, setExpanded] = useState(false)

    return (
        <div className='source-card'>
            <div className='source-header'>
                <span className='source-index'>[{source.index}]</span>
                <span className='source-path'>&gt; {source.file_path}</span>
                <span className='source-score'>{Math.round(source.score * 100)}%</span>
            </div>
            <div className={`source-content ${expanded ? 'expanded' : 'collapsed'}`}>
                {source.content}
            </div>
            <button className='source-expand' onClick={() => setExpanded(e => !e)}>{expanded ? 'Show less' : 'Show more'}</button>
        </div>
    )
}