import argparse
import asyncio
import json
from pathlib import Path
from groq import AsyncGroq
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models import Repo, Chunk
from app.config import get_settings

MIN_CHUNK_CHARS = 200
BATCH_SIZE= 15
#These questions should be declined regardless of the selected repo
GENERIC_UNANSWERABLE = [
    "What's the weather like today?",
    "What's the capital of France?",
    "What's the boiling point of mercury?"
]

async def _get_repo(db, repo_id: int | None, repo_url: str | None) -> Repo:
    if repo_id is not None:
        repo = await db.get(Repo, repo_id)
    else:
        repo = await db.scalar(select(Repo).where(Repo.url == repo_url))
    if not repo:
        raise SystemExit('Repo not found. Ingest it first: POST /repos, then check GET /repos for its id.')
    
    return repo

async def _sample_chunks(db, repo_id: int, n: int) -> list[Chunk]:
    result = await db.execute(
        select(Chunk).where(Chunk.repo_id == repo_id, func.length(Chunk.content) >= MIN_CHUNK_CHARS)
        .order_by(func.random())
        .limit(n)
    )

    return list(result.scalars().all())

async def _generate_cases_for_batch(chunks: list[Chunk], model: str) -> list[dict]:
    settings = get_settings()
    client = AsyncGroq(api_key=settings.groq_api_key)

    passages = '\n\n'.join(f'[{i}] (file: {c.file_path})\n{c.content[:800]}' for i, c in enumerate(chunks))
    prompt = ('For each numbered passage below, write ONE specific question that is answered by that passage alone, '
        'plus 2-4 short keywords that should appear in a correct answer to that question.'
        'Respond with only a JSON object mapping each passage index (as a string) to {"question": "...", "keywords": ["...", "..."].}'
        f'No explanation. no markdown, no code fences.\n\n{passages}'
    )

    try:
        response = await client.chat.completions.create(
            model = model,
            messages = [{'role': 'user', 'content': prompt}],
            max_tokens = 2000,
            temperature = 0.3,
            response_format = {'type': 'json_object'}
        )
        data = json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f'    [warning] batch generation failed, skipping {len(chunks)} chunks: {e}')
        return []

    cases = []
    for i, chunk in enumerate(chunks):
        entry = data.get(str(i))
        if not entry or not entry.get('question'):
            continue
        cases.append({
            'question': entry['question'],
            'expected_keywords': entry.get('keywords', []),
            'expected_source_contains': chunk.file_path,
            'unanswerable': False
        })
    
    return cases

async def generate(repo_id: int | None, repo_url: str | None, num_cases: int, out_path: Path) -> Path:
    settings = get_settings()

    async with AsyncSessionLocal() as db:
        repo = await _get_repo(db, repo_id, repo_url)
        print(f'Generating dataset for {repo.name} (repo_id={repo.id})')

        chunks = await _sample_chunks(db, repo.id, num_cases)
        if not chunks:
            raise SystemExit(f'No chunks of at least {MIN_CHUNK_CHARS} characters found in this repo')
        print(f'Sampled {len(chunks)} chunks, generating questions in batches of {BATCH_SIZE}')

        all_cases: list[dict] = []
        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start : start + BATCH_SIZE]
            cases = await _generate_cases_for_batch(batch, settings.groq_llm_model)
            all_cases.extend(cases)
            print(f'    {len(cases)}/{len(batch)} questions generated (batch {start // BATCH_SIZE + 1})')

        for question in GENERIC_UNANSWERABLE:
            all_cases.append({
                'question': question,
                'expected_keywords': [],
                'expected_source_contains': None,
                'unanswerable': True
            })

        dataset = {'repo_url': repo.url, 'cases': all_cases}
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(dataset, indent=2))

        print(f'\nWrote {len(all_cases)} cases ({len(all_cases) - len(GENERIC_UNANSWERABLE)} generated + {len(GENERIC_UNANSWERABLE)} generic probes) to {out_path}')

        return out_path

def _default_out_path(repo_id: int | None, repo_url: str | None) -> Path:
    """Best effort filename guess before the repo has loaded"""
    slug = (repo_url or f'repo_{repo_id}').rstrip('/').split('/')[-1]
    return Path(__file__).parent / 'datasets' / f'{slug}.json'

def main() -> None:
    parser = argparse.ArgumentParser(description='Generate an eval dataset for any already ingested repo.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--repo-id', type=int, help='Repo ID (see GET /repos)')
    group.add_argument('--repo-url', type=str, help='Repo URL (must already be ingested)')

    parser.add_argument('--num-cases', type=int, default=100, help='Number of generated questions (default: 10)')
    parser.add_argument('--out', type=Path, default=None, help='Output path (default: eval/datasets/<repo-name>.json)')
    parser.add_argument('--run', action='store_true', help='Run the eval harness immediately after generating')
    parser.add_argument('--base-url', default='http://localhost:8000', help='Backend URL, used only with --run')
    args = parser.parse_args()

    out_path = args.out or _default_out_path(args.repo_id, args.repo_url)
    written_path = asyncio.run(generate(args.repo_id, args.repo_url, args.num_cases, out_path))

    if args.run:
        from eval.run_eval import run as run_eval_dataset
        print('\nRunning eval on the generated dataset...\n')
        asyncio.run(run_eval_dataset(str(written_path), args.base_url))

if __name__ == '__main__':
    main()