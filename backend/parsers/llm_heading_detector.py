"""
Détection de la hiérarchie des titres par LLM (approche hybride).

1. Pré-filtre les candidats-titres par formatage (taille, gras, souligné, majuscules)
2. Envoie uniquement les candidats au LLM pour attribution des niveaux (1-4)

Cette approche hybride évite d'envoyer des centaines de paragraphes au LLM
et lui permet de se concentrer sur la classification hiérarchique.
"""

import re
import json
import logging
from collections import Counter
from openai import OpenAI
from backend.config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL

logger = logging.getLogger('mini_fiche.parser.llm')

SYSTEM_PROMPT = """\
Tu es un expert en analyse de documents juridiques français (cours, manuels, codes).

On te fournit une liste de paragraphes CANDIDATS-TITRES extraits d'un document,
avec leurs propriétés de formatage et leur indice dans le document original.

Ta tâche : identifier TOUS les TITRES structurels et leur attribuer un niveau (1 à 4).

IMPORTANT : Tu dois couvrir L'INTÉGRALITÉ du document, y compris :
- L'introduction et ses subdivisions (I., II., A., B., 1., 2.)
- Les parties préliminaires avant le corps principal
- Le corps principal (Titre, Chapitre, Section, §)
- La conclusion si présente

MARQUEURS STRUCTURELS À RECONNAÎTRE COMME TITRES :
- Introduction, Conclusion, Préambule
- PARTIE I, PARTIE 1, Partie première...
- TITRE 1, TITRE I, Titre premier...
- CHAPITRE 1, Chapitre I, Chapitre premier...
- Section 1, Section I, SECTION...
- Sous-section, Sous-titre...
- § 1, §1, § 2...
- Numérotations structurelles : I., II., III., A., B., C., 1., 2., 3., a), b)
  (quand ce sont des paragraphes courts avec un titre, PAS des phrases de contenu)

RÈGLES :
1. Les marqueurs ci-dessus sont des TITRES même sans formatage spécial (gras, etc.)
2. EXCLURE les paragraphes longs qui sont du contenu/explication, même en gras
3. EXCLURE les puces (•, –, ◦) et les listes descriptives
4. Identifie le titre principal du document (souvent le premier en gras/gros, ou "Introduction")

RÉPONDS UNIQUEMENT avec un JSON valide, sans markdown, sans texte avant ou après :
{"title": <index ou null>, "headings": {"<index>": <niveau 1-4>, ...}}
"""

MAX_TEXT_LENGTH = 120


def detect_headings_with_llm(paragraphs_meta: list[dict]) -> tuple[int | None, dict[int, int]]:
    """
    Détecte la hiérarchie des titres en combinant pré-filtrage par formatage
    et classification par LLM.

    Args:
        paragraphs_meta: Liste de dicts avec au minimum :
            - text: str
            - font_size: float
            - is_bold: bool
            Optionnel : is_underline, is_uppercase

    Returns:
        (title_index, heading_levels) où :
        - title_index: indice du titre principal du document (ou None)
        - heading_levels: dict {indice_paragraphe: niveau_1_à_4}
    """
    if not paragraphs_meta:
        return None, {}

    # Étape 1 : détecter la taille du corps de texte
    body_size = _detect_body_size(paragraphs_meta)
    logger.info("Taille du corps de texte : %.1fpt", body_size)

    # Étape 2 : pré-filtrer les candidats-titres par formatage
    candidates = _identify_candidates(paragraphs_meta, body_size)
    logger.info(
        "Candidats-titres pré-filtrés : %d / %d paragraphes",
        len(candidates), len(paragraphs_meta),
    )

    if not candidates:
        return None, {}

    # Étape 3 : envoyer les candidats au LLM
    prompt = _build_prompt(paragraphs_meta, candidates, body_size)
    logger.info("Envoi au LLM — %d candidats, prompt: %d chars", len(candidates), len(prompt))

    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
    )

    response = client.chat.completions.create(
        model=OPENROUTER_MODEL,
        max_tokens=4000,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        extra_headers={
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": "Mini Fiche",
        },
    )

    raw = response.choices[0].message.content
    usage = response.usage
    logger.info(
        "Réponse LLM reçue — tokens: prompt=%s, réponse=%s, total=%s",
        getattr(usage, 'prompt_tokens', '?'),
        getattr(usage, 'completion_tokens', '?'),
        getattr(usage, 'total_tokens', '?'),
    )

    title_index, heading_levels = _parse_response(raw)
    logger.info(
        "Titres détectés : %d (titre du document : index %s)",
        len(heading_levels), title_index,
    )

    return title_index, heading_levels


def _detect_body_size(paragraphs_meta: list[dict]) -> float:
    """Identifie la taille de police du corps de texte (la plus fréquente, pondérée par longueur)."""
    size_counter = Counter()
    for p in paragraphs_meta:
        size = p.get('font_size', 0)
        if size > 0:
            size_counter[size] += len(p['text'])

    if not size_counter:
        return 11.0

    return size_counter.most_common(1)[0][0]


# Marqueurs structurels qui sont toujours des candidats-titres,
# même sans formatage spécial (gras, taille, etc.)
STRUCTURAL_PATTERNS = [
    r'^(?:PARTIE|Partie)\s+',
    r'^(?:TITRE|Titre)\s+',
    r'^(?:SOUS-TITRE|Sous-titre)\s+',
    r'^(?:CHAPITRE|Chapitre)\s+',
    r'^(?:SECTION|Section)\s+',
    r'^(?:SOUS-SECTION|Sous-section)\s+',
    r'^§\s*\d',
    r'^(?:PARAGRAPHE|Paragraphe)\s+',
    r'^(?:INTRODUCTION|Introduction)\s*$',
    r'^(?:CONCLUSION|Conclusion)\s*(?:\s|$)',
    # Numérotations structurelles (I., A., 1., a., a))
    r'^(?:I{1,3}|IV|VI{0,3}|IX|X{1,3})\s*[\.\)—–\-:]\s',
    r'^[A-Z]\s*[\.\)—–\-]\s',
    r'^[a-z]\s*[\.\)—–\-]\s',
    r'^\d{1,2}\s*[\.\)°—–\-]\s',
]


def _has_structural_marker(text: str) -> bool:
    """Vérifie si le texte commence par un marqueur structurel juridique."""
    stripped = text.strip()
    return any(re.match(p, stripped) for p in STRUCTURAL_PATTERNS)


def _identify_candidates(paragraphs_meta: list[dict], body_size: float) -> list[int]:
    """
    Pré-filtre les candidats-titres par formatage OU par marqueur structurel.
    Un candidat est un paragraphe court qui :
    - a un formatage différent du corps de texte (gras, taille, majuscules)
    - OU commence par un marqueur structurel (PARTIE, §, I., A., etc.)
    """
    candidates = []

    for i, p in enumerate(paragraphs_meta):
        text = p['text']

        # Trop long pour être un titre
        if len(text) > 200:
            continue

        is_bold = p.get('is_bold', False)
        is_underline = p.get('is_underline', False)
        is_uppercase = p.get('is_uppercase', False)
        font_size = p.get('font_size', 0)

        # Candidat par formatage
        has_formatting = (
            font_size > body_size + 0.5 or
            is_bold or
            is_uppercase or
            (is_underline and font_size >= body_size)
        )

        # Candidat par marqueur structurel (§, I., A., PARTIE, etc.)
        has_marker = _has_structural_marker(text)

        if has_formatting or has_marker:
            candidates.append(i)

    return candidates


def _build_prompt(
    paragraphs_meta: list[dict],
    candidates: list[int],
    body_size: float,
) -> str:
    """
    Construit le prompt avec uniquement les candidats-titres.
    Inclut le contexte sur la taille du corps de texte.
    """
    lines = [f"Corps de texte : {body_size}pt\n"]
    lines.append("Candidats-titres (indice | taille | attributs | texte) :\n")

    for i in candidates:
        p = paragraphs_meta[i]
        text = p['text']
        if len(text) > MAX_TEXT_LENGTH:
            text = text[:MAX_TEXT_LENGTH] + "..."

        size = p.get('font_size', 0)
        attrs = []
        if p.get('is_bold'):
            attrs.append('BOLD')
        if p.get('is_underline'):
            attrs.append('UNDERLINE')
        if p.get('is_uppercase'):
            attrs.append('UPPER')

        attrs_str = ' '.join(attrs) if attrs else '-'
        lines.append(f'[{i}] {size}pt | {attrs_str} | "{text}"')

    return '\n'.join(lines)


def _parse_response(raw: str) -> tuple[int | None, dict[int, int]]:
    """
    Parse la réponse JSON du LLM.
    Gère les cas où le LLM entoure le JSON de markdown (```json ... ```).
    """
    cleaned = raw.strip()

    # Retirer les blocs markdown si présents
    if cleaned.startswith('```'):
        lines = cleaned.split('\n')
        lines = [l for l in lines if not l.strip().startswith('```')]
        cleaned = '\n'.join(lines)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error("Impossible de parser la réponse JSON du LLM: %s", cleaned[:500])
        return None, {}

    title_index = data.get('title')
    if title_index is not None:
        title_index = int(title_index)

    headings_raw = data.get('headings', {})
    heading_levels = {}
    for idx_str, level in headings_raw.items():
        try:
            idx = int(idx_str)
            lvl = min(int(level), 4)
            if lvl >= 1:
                heading_levels[idx] = lvl
        except (ValueError, TypeError):
            continue

    return title_index, heading_levels
