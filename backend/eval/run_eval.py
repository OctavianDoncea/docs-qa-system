import argparse
import asyncio
import json
import sys
import httpx
from pathlib import Path
from eval.metrics import keyword_recall, retrieval_hit, refusal_correct

async def _ingest(client: httpx.AsyncClient, base_url: str, repo_url: str) -> int:
    """Ingest the dataset repo"""
    print(f'Ingesting {repo_url}')
    resp = await client.post(f'{base_url}/repos', json={'url': repo_url, 'reingest': True}, timeout=300.0)
    resp.raise_for_status()
    repo = resp.json()
    print(f" repo ID={repo['id']}, {repo['chunk_count']} chunks\n")

    return repo['id']

async def _query(client: httpx.AsyncClient, base_url: str, question: str, repo_id: int) -> dict:
    """Send a query andd consume the SSE stream, reassembling the full answer"""
    answer_parts: list[dict] = []
    sources: list[dict] = []
    low_confidence = False

    async with client.stream('POST', f'{base_url}/query', json={'question': question, 'repo_id': repo_id, 'history': []}, timeout=120.0) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            line = line.strip()
            if not line.startswith('data: '):
                continue
            try:
                event = json.loads(line[6:])
            except json.JSONDecodeError:
                continue

            if event.get('error'):
                answer_parts.append(f'[ERROR] {event["error"]}')
                break
            if not event.get('done') and event.get('content'):
                answer_parts.append(event['content'])
            if event.get('done'):
                sources = event.get('sources', [])
                low_confidence = event.get('low_confidence', False)

    return {
        'answer': ''.join(answer_parts),
        'sources': sources,
        'low_confidence': low_confidence,
    }

async def run(dataset_path: str, base_url: str) -> None:
    data = json.loads(Path(dataset_path).read_text())
    repo_url = data['repo_url']
    cases = data['cases']

    async with httpx.AsyncClient() as client:
        repo_id = await _ingest(client, base_url, repo_url)
        results = []

        for i, case in enumerate(cases, 1):
            print(f"[{i}/{len(cases)}] {case['question'][:60]}")
            out = await _query(client, base_url, case['question'], repo_id)

            kr = keyword_recall(out['answer'], case.get('expected_keywords', []))
            rh = retrieval_hit(out['sources'], case.get('expected_source_contains'))
            rc = refusal_correct(out['answer'], out['low_confidence'], case.get('unanswerable', False))
            results.append({
                'question': case['question'],
                'unanswerable': case.get('unanswerable', False),
                'keyword_recall': kr,
                'retrieval_hit': rh,
                'refusal_correct': rc
            })

    _print_report(results)

def _print_report(results: list[dict]) -> None:
    print('EVAL RESULTS')
    print(f"{'Q':<48}{'KW-rec':>8}{'Hit':>6}{'Refuse':>8}")

    for r in results:
        q = r['question'][:46]
        kr = f'{r["keyword_recall"]:.2f}'
        rh = 'YES' if r['retrieval_hit'] else 'NO'
        rc = 'OK' if r['refusal_correct'] else 'FAIL'
        print(f'{q:<48}{kr:>8}{rh:>6}{rc:>8}')

    answerable = [r for r in results if not r['unanswerable']]
    avg_kr = sum(r['keyword_recall'] for r in answerable) / max(len(answerable), 1)
    hit_rate = sum(r['retrieval_hit'] for r in answerable) / max(len(answerable), 1)
    refusal_acc = sum(r['refusal_correct'] for r in results) / max(len(results), 1)

    print(f'\nAnswerable cases:     {len(answerable)}/{len(results)}')
    print(f'Avg keyword recall:     {avg_kr:.1%}')
    print(f'Retrieval hit rate:     {hit_rate:.1%}')
    print(f'Refusal accuracy:       {refusal_acc:.1%} (across all cases)')

    failures = [r for r in results if not r['refusal_correct'] or not r['retrieval_hit']]
    if failures:
        print(f'\n{len(failures)} case(s) failed retrieval or refusal checks.')
        sys.exit(1)

def main() -> None:
    parser = argparse.ArgumentParser(description='Run the docs-qa eval harness.')
    parser.add_argument('dataset', help='Path to a dataset JSON file')
    parser.add_argument('--base-url', default='http://localhost:8000')
    args = parser.parse_args()

    asyncio.run(run(args.dataset, args.base_url))

if __name__ == '__main__':
    main()