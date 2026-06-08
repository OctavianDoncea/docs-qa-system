import base64
import logging
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

SUPPORTED_EXTENSIONS = {'.md', '.mdx', '.rst', '.txt'}
SKIP_PREFIXES = ('node_modules/', '.github/', 'vendor/', '__pycache__/', '.git/', 'test/', 'tests/', 'spec/', 'specs/')
MAX_FILES = 50

def parse_github_url(url: str) -> tuple[str, str]:
    url = url.rstrip('/')
    if 'github.com' in url:
        parts = url.split('github.com/')[-1].split('/')
    else:
        parts = url.split('/')
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError(f'Cannot parse GitHub URL: {url!r}\nExpected format: https://github.com/owner/repo')
    
    return parts[0], parts[1]

def _is_doc_file(path: str) -> bool:
    lower = path.lower()
    if any(lower.startswith(p) for p in SKIP_PREFIXES):
        return False
    
    return lower.endswith(tuple(SUPPORTED_EXTENSIONS))

async def fetch_repo_docs(url: str) -> list[dict[str, str]]:
    """Fetch documentation files from a public GitHub repository."""
    owner, repo = parse_github_url(url)

    headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    token = settings.github_token.strip()
    if token and token != 'your_github_token':
        headers['Authorization'] = f'Bearer {token}'

    async with httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=True) as client:
        # 1. fetch the full recursive file tree
        tree_url = f'https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1'
        resp = await client.get(tree_url)

        if resp.status_code == 404:
            raise ValueError(f'Repository not found: {owner}/{repo}')
        if resp.status_code == 403:
            raise ValueError('GitHub API rate limit reached. Add a personal access token as GITHUB_TOKEN in .env (Settings -> Developer settings -> Personal access tokens -> Tokens (classic))')
        resp.raise_for_status()

        tree_data = resp.json()

        # 2. filter to supported doc files
        doc_items = [item for item in tree_data.get('tree', []) if item['type'] == 'blob' and _is_doc_file(item['path'])][:MAX_FILES]

        if not doc_items:
            return []

        logger.info(f'Found {len(doc_items)} doc files in {owner}/{repo}')

        # 3. fetch content for each file via the blobs API
        files: list[dict[str, str]] = []
        for item in doc_items:
            try:
                blob_url = f'https://api.github.com/repos/{owner}/{repo}/git/blobs/{item['sha']}'
                blob_resp = await client.get(blob_url)
                blob_resp.raise_for_status()

                # GitHub base64 encodes the content with newlines
                raw_b64 = blob_resp.json()['content'].replace('\n', '')
                content = base64.b64decode(raw_b64).decode('utf-8', errors='replace')

                if content.strip():
                    files.append({'path': item['path'], 'content': content})
            except Exception as e:
                logger.warning(f"Skipping {item['path']} (HTTP {e.response.status_code})")
            except Exception as e:
                logger.warning(f"Skipping {item['path']}: {e}")
        
        return files