def keyword_recall(answer: str, expected_keywords: list[str]) -> float:
    """Fraction of expected keywords that appear in the answer."""
    if not expected_keywords:
        return 1.0

    answer_lower = answer.lower()
    hits = sum(1 for kw in expected_keywords if kw.lower() in answer_lower)
    
    return hits / len(expected_keywords)

def retrieval_hit(sources: list[dict], expected_source_contains: str | None) -> bool:
    if not expected_source_contains:
        return True
    needle = expected_source_contains.lower()

    return any(needle in s.get('file_path', '').lower() for s in sources)

def refusal_correct(answer: str, low_confidence: bool, unanswerable: bool) -> bool:
    declined = low_confidence or 'not appear to be covered' in answer.lower() or 'not covered in the documentation' in answer.lower()
    return declined if unanswerable else not declined