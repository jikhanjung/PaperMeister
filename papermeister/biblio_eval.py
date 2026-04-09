"""Bibliographic extraction evaluation metrics.

Step 3 (P05): functions to compare extracted BiblioResult against ground truth.
"""

import re
import unicodedata


# Default weights for the overall score
DEFAULT_WEIGHTS = {
    'title': 0.35,
    'authors': 0.30,
    'year': 0.15,
    'journal': 0.10,
    'doi': 0.10,
}


def normalize_text(s: str) -> str:
    """Lowercase, NFKC, collapse whitespace, strip basic punctuation."""
    if not s:
        return ''
    s = unicodedata.normalize('NFKC', s)
    s = s.lower()
    s = re.sub(r'[\u2010-\u2015\-]', '-', s)  # unify dashes
    s = re.sub(r'[^\w\s\-]', ' ', s, flags=re.UNICODE)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def string_similarity(a: str, b: str) -> float:
    """Normalized Levenshtein similarity in [0, 1]."""
    a_n, b_n = normalize_text(a), normalize_text(b)
    if not a_n and not b_n:
        return 1.0
    if not a_n or not b_n:
        return 0.0
    dist = levenshtein(a_n, b_n)
    return 1.0 - dist / max(len(a_n), len(b_n))


def title_similarity(gt: str, pred: str) -> float:
    return string_similarity(gt, pred)


def _normalize_author_name(name: str) -> str:
    """Normalize a single author name for comparison.

    Tries to reduce "Last, First" and "First Last" to a comparable form:
    "first last" (lowercased, trimmed). Initials are kept as single letters.
    """
    if not name:
        return ''
    s = unicodedata.normalize('NFKC', name).strip()
    s = re.sub(r'\s+', ' ', s)
    if ',' in s:
        # "Last, First Middle" → "First Middle Last"
        parts = [p.strip() for p in s.split(',', 1)]
        if len(parts) == 2 and parts[1]:
            s = f'{parts[1]} {parts[0]}'
    s = s.lower()
    s = re.sub(r'[^\w\s\-]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _author_match(a: str, b: str) -> bool:
    """Loose match accommodating "First Last", "Last First", "Last, First", initials.

    Strategy: build a set of tokens with length >= 3 for each name. If they share
    at least one such token, consider it a match. This handles ordering variations
    and middle initials cleanly without committing to a "first name vs last name"
    classification.
    """
    na, nb = _normalize_author_name(a), _normalize_author_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ta = {t for t in na.split() if len(t) >= 3}
    tb = {t for t in nb.split() if len(t) >= 3}
    if ta & tb:
        return True
    return False


def authors_score(gt: list, pred: list) -> float:
    """Score in [0, 1] combining count match, presence, and order preservation.

    - 50% weight: fraction of GT authors found in pred (loose match, any position)
    - 30% weight: order preservation (longest common subsequence / len(gt))
    - 20% weight: count similarity (1 - |len(gt)-len(pred)|/max(len))
    """
    if not gt and not pred:
        return 1.0
    if not gt or not pred:
        return 0.0

    # Presence
    matched = [any(_author_match(g, p) for p in pred) for g in gt]
    presence = sum(matched) / len(gt)

    # Order via LCS on indices: map each gt author to first matching pred index
    indices = []
    for g in gt:
        for j, p in enumerate(pred):
            if _author_match(g, p):
                indices.append(j)
                break
    # Longest increasing subsequence length
    def lis_len(seq):
        if not seq:
            return 0
        tails = []
        import bisect
        for x in seq:
            i = bisect.bisect_left(tails, x)
            if i == len(tails):
                tails.append(x)
            else:
                tails[i] = x
        return len(tails)

    order = lis_len(indices) / len(gt) if gt else 0.0

    # Count similarity
    count = 1.0 - abs(len(gt) - len(pred)) / max(len(gt), len(pred))

    return 0.5 * presence + 0.3 * order + 0.2 * count


def year_match(gt, pred) -> bool:
    if gt is None or pred is None:
        return False
    try:
        return int(gt) == int(pred)
    except (TypeError, ValueError):
        return False


def journal_score(gt: str, pred: str) -> float:
    """Fuzzy match accommodating abbreviations vs full names.

    If one is a token-subset of the other, return high score.
    """
    if not gt and not pred:
        return 1.0
    if not gt or not pred:
        return 0.0
    gt_n, pred_n = normalize_text(gt), normalize_text(pred)
    if gt_n == pred_n:
        return 1.0

    sim = string_similarity(gt_n, pred_n)

    # Token-set containment bonus
    gt_tokens = set(gt_n.split())
    pred_tokens = set(pred_n.split())
    if gt_tokens and pred_tokens:
        smaller = gt_tokens if len(gt_tokens) < len(pred_tokens) else pred_tokens
        larger = pred_tokens if smaller is gt_tokens else gt_tokens
        contained = len(smaller & larger) / len(smaller)
        sim = max(sim, 0.5 + 0.5 * contained)

    return sim


def doi_match(gt: str, pred: str) -> bool:
    g = (gt or '').strip().lower()
    p = (pred or '').strip().lower()
    if not g and not p:
        return True   # both missing → no penalty
    if not g or not p:
        return False
    return g == p


def overall_score(gt: dict, pred: dict, weights: dict = None) -> dict:
    """Compute per-field and weighted overall score.

    gt and pred are dicts with keys: title, authors, year, journal, doi.
    """
    w = weights or DEFAULT_WEIGHTS
    scores = {
        'title': title_similarity(gt.get('title', ''), pred.get('title', '')),
        'authors': authors_score(gt.get('authors', []) or [], pred.get('authors', []) or []),
        'year': 1.0 if year_match(gt.get('year'), pred.get('year')) else 0.0,
        'journal': journal_score(gt.get('journal', ''), pred.get('journal', '')),
        'doi': 1.0 if doi_match(gt.get('doi', ''), pred.get('doi', '')) else 0.0,
    }
    overall = sum(scores[k] * w.get(k, 0) for k in scores)
    return {**scores, 'overall': overall}
