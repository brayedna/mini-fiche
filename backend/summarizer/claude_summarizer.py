"""
Module de résumé utilisant OpenRouter avec chunking et parallélisation.

Les documents volumineux sont découpés en chunks de sections, puis chaque chunk
est résumé en parallèle par des workers. Les résultats sont ensuite fusionnés
pour reconstruire le résumé complet avec la hiérarchie des titres intacte.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from backend.parsers.base_parser import ParsedDocument, Section
from backend.config import (
    OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL,
    MAX_WORKERS, CHUNK_MAX_SECTIONS, CHUNK_MAX_CHARS,
)

logger = logging.getLogger('mini_fiche.summarizer')

# Prompt système de base pour produire un résumé structuré
_BASE_SYSTEM_PROMPT = """Tu es un assistant spécialisé dans le résumé de cours de droit.
Tu dois produire un résumé clair, concis et fidèle au contenu original.

RÈGLES IMPÉRATIVES :
1. Tu DOIS conserver EXACTEMENT la même hiérarchie de titres que le document original.
   Ne modifie JAMAIS les titres, sous-titres, sections ou sous-sections.
2. Pour chaque section, résume le contenu en gardant les points essentiels.
3. Utilise un style juridique précis et professionnel.
4. Conserve les définitions importantes, les principes clés et les références légales.

FORMAT DE SORTIE :
Retourne le résumé sous forme structurée avec des marqueurs de niveau :
- [H1] pour les titres de niveau 1
- [H2] pour les titres de niveau 2
- [H3] pour les titres de niveau 3
- [H4] pour les titres de niveau 4
- Le contenu résumé suit directement après chaque titre.
- Sépare chaque section par une ligne vide.
"""

# Instructions spécifiques selon le niveau de détail
_DETAIL_INSTRUCTIONS = {
    1: (
        "\nNIVEAU DE DÉTAIL : TRÈS CONCIS\n"
        "- Résume chaque section en 2-3 phrases maximum.\n"
        "- Garde uniquement les définitions clés et les principes fondamentaux.\n"
        "- Pas d'exemples, pas de jurisprudence, pas d'exceptions.\n"
        "- Va droit à l'essentiel.\n"
    ),
    2: (
        "\nNIVEAU DE DÉTAIL : CONCIS\n"
        "- Le résumé doit être suffisamment détaillé pour servir de fiche de révision.\n"
        "- Garde les définitions, principes clés et références légales importantes.\n"
    ),
    3: (
        "\nNIVEAU DE DÉTAIL : DÉTAILLÉ\n"
        "- Produis un résumé approfondi et complet.\n"
        "- Conserve les exemples, les exceptions, la jurisprudence citée.\n"
        "- Inclus les explications détaillées, les conditions d'application.\n"
        "- Le résumé doit être une fiche de révision complète et exhaustive.\n"
    ),
}


def _get_system_prompt(detail_level: int = 2) -> str:
    """Retourne le prompt système adapté au niveau de détail demandé."""
    instruction = _DETAIL_INSTRUCTIONS.get(detail_level, _DETAIL_INSTRUCTIONS[2])
    return _BASE_SYSTEM_PROMPT + instruction


# =========================================================================
# Point d'entrée principal
# =========================================================================

def summarize_document(parsed_doc: ParsedDocument, detail_level: int = 2) -> list[Section]:
    """
    Résume un document parsé en utilisant le chunking et la parallélisation.

    Pipeline :
    1. Découper les sections en chunks de taille raisonnable
    2. Envoyer chaque chunk à un worker parallèle via OpenRouter
    3. Fusionner les résultats dans l'ordre original

    Args:
        parsed_doc: Le document parsé avec ses sections et hiérarchie de titres
        detail_level: Niveau de détail (1=très concis, 2=concis, 3=détaillé)

    Returns:
        Liste de Section contenant les titres originaux et le contenu résumé
    """
    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == 'your_api_key_here':
        raise ValueError(
            "Clé API OpenRouter non configurée. "
            "Renseignez OPENROUTER_API_KEY dans le fichier .env"
        )

    total_sections = len(parsed_doc.sections)
    logger.info(
        "=== Début du résumé : '%s' | %d sections | modèle: %s ===",
        parsed_doc.title, total_sections, OPENROUTER_MODEL,
    )

    # --- Étape 1 : Chunking ---
    chunks = _split_into_chunks(parsed_doc.sections, CHUNK_MAX_SECTIONS, CHUNK_MAX_CHARS)
    logger.info(
        "Chunking terminé : %d chunks créés (max %d sections/chunk)",
        len(chunks), CHUNK_MAX_SECTIONS,
    )
    for i, chunk in enumerate(chunks):
        char_count = sum(len(s.content) for s in chunk)
        logger.info(
            "  Chunk %d/%d : %d sections, ~%d caractères",
            i + 1, len(chunks), len(chunk), char_count,
        )

    # --- Étape 2 : Résumé parallèle ---
    start_total = time.time()

    if len(chunks) == 1:
        logger.info("Un seul chunk — traitement séquentiel")
        all_sections = _summarize_chunk(chunks[0], 1, 1, parsed_doc.title, detail_level)
    else:
        all_sections = _summarize_parallel(chunks, parsed_doc.title, detail_level)

    total_elapsed = time.time() - start_total
    logger.info(
        "=== Résumé terminé : %d sections résumées | temps total: %.1fs ===",
        len(all_sections), total_elapsed,
    )
    return all_sections


# =========================================================================
# Chunking : découpage des sections en blocs
# =========================================================================

def _split_into_chunks(
    sections: list[Section], max_per_chunk: int, max_chars: int = 40000,
) -> list[list[Section]]:
    """
    Découpe la liste de sections en chunks respectant deux limites :
    - max_per_chunk : nombre maximal de sections par chunk
    - max_chars : nombre maximal de caractères de contenu par chunk
    Essaie de couper aux frontières de titres H1/H2 pour garder la cohérence.
    """
    total_chars = sum(len(s.content) for s in sections)
    if len(sections) <= max_per_chunk and total_chars <= max_chars:
        return [sections]

    chunks = []
    current_chunk = []
    current_chars = 0

    for section in sections:
        section_chars = len(section.content)
        current_chunk.append(section)
        current_chars += section_chars

        at_section_limit = len(current_chunk) >= max_per_chunk
        at_char_limit = current_chars >= max_chars

        # Couper quand on atteint une limite ET qu'on est à une frontière H1/H2
        if (at_section_limit or at_char_limit) and section.level <= 2:
            chunks.append(current_chunk)
            current_chunk = []
            current_chars = 0

        # Couper de force si le chunk dépasse 1.5x les limites
        elif (len(current_chunk) >= int(max_per_chunk * 1.5) or
              current_chars >= int(max_chars * 1.5)):
            chunks.append(current_chunk)
            current_chunk = []
            current_chars = 0

    # Dernier chunk restant
    if current_chunk:
        chunks.append(current_chunk)

    return chunks


# =========================================================================
# Parallélisation : traitement concurrent des chunks
# =========================================================================

def _summarize_parallel(
    chunks: list[list[Section]], doc_title: str, detail_level: int = 2
) -> list[Section]:
    """
    Lance les workers en parallèle pour résumer chaque chunk.
    Les résultats sont fusionnés dans l'ordre original des chunks.
    """
    total_chunks = len(chunks)
    workers = min(MAX_WORKERS, total_chunks)
    logger.info(
        "Lancement de %d workers pour %d chunks", workers, total_chunks
    )

    # Dictionnaire {index_chunk: (résultat, durée)} pour garder l'ordre
    results = {}
    chunk_times = {}
    start_total = time.time()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        # Soumettre tous les chunks aux workers
        futures = {
            executor.submit(
                _summarize_chunk, chunk, i + 1, total_chunks, doc_title, detail_level
            ): i
            for i, chunk in enumerate(chunks)
        }

        # Collecter les résultats au fur et à mesure
        for future in as_completed(futures):
            chunk_index = futures[future]
            try:
                chunk_result = future.result()
                results[chunk_index] = chunk_result
                elapsed = time.time() - start_total
                chunk_times[chunk_index] = elapsed
                logger.info(
                    "Worker chunk %d/%d terminé — %d sections résumées (à t+%.1fs)",
                    chunk_index + 1, total_chunks, len(chunk_result), elapsed,
                )
            except Exception as e:
                logger.error(
                    "Worker chunk %d/%d ÉCHOUÉ : %s",
                    chunk_index + 1, total_chunks, str(e),
                )
                results[chunk_index] = []

    elapsed = time.time() - start_total
    logger.info("Tous les workers terminés en %.1fs", elapsed)

    # Résumé des temps par chunk
    for i in sorted(chunk_times):
        logger.info(
            "  Chunk %d/%d : terminé à t+%.1fs",
            i + 1, total_chunks, chunk_times[i],
        )

    # Fusionner dans l'ordre original
    all_sections = []
    for i in range(total_chunks):
        all_sections.extend(results.get(i, []))

    return all_sections


# =========================================================================
# Worker : résumé d'un chunk individuel
# =========================================================================

def _summarize_chunk(
    sections: list[Section],
    chunk_num: int,
    total_chunks: int,
    doc_title: str,
    detail_level: int = 2,
) -> list[Section]:
    """
    Résume un chunk de sections via un appel à OpenRouter.
    Chaque worker appelle cette fonction indépendamment.
    """
    logger.info(
        "[Chunk %d/%d] Envoi à OpenRouter — %d sections",
        chunk_num, total_chunks, len(sections),
    )
    start = time.time()

    # Construire le prompt pour ce chunk
    user_message = _build_chunk_prompt(sections, doc_title, chunk_num, total_chunks, detail_level)
    prompt_chars = len(user_message)
    logger.info(
        "[Chunk %d/%d] Prompt construit — %d caractères",
        chunk_num, total_chunks, prompt_chars,
    )

    # Appel API
    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
    )

    # Adapter max_tokens au niveau de détail
    max_tokens_by_level = {1: 8000, 2: 16000, 3: 24000}
    max_tokens = max_tokens_by_level.get(detail_level, 16000)

    response = client.chat.completions.create(
        model=OPENROUTER_MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": _get_system_prompt(detail_level)},
            {"role": "user", "content": user_message},
        ],
        extra_headers={
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": "Mini Fiche",
        },
    )

    # Extraire les métriques de la réponse
    elapsed = time.time() - start
    response_text = response.choices[0].message.content
    usage = response.usage
    logger.info(
        "[Chunk %d/%d] Réponse reçue en %.1fs — "
        "tokens prompt: %s, tokens réponse: %s, total: %s",
        chunk_num, total_chunks, elapsed,
        getattr(usage, 'prompt_tokens', '?'),
        getattr(usage, 'completion_tokens', '?'),
        getattr(usage, 'total_tokens', '?'),
    )

    # Parser la réponse en sections
    result_sections = _parse_summary_response(response_text)
    logger.info(
        "[Chunk %d/%d] Parsing terminé — %d sections extraites",
        chunk_num, total_chunks, len(result_sections),
    )

    return result_sections


# =========================================================================
# Construction du prompt
# =========================================================================

def _build_chunk_prompt(
    sections: list[Section],
    doc_title: str,
    chunk_num: int,
    total_chunks: int,
    detail_level: int = 2,
) -> str:
    """
    Construit le prompt pour un chunk de sections.
    Inclut le contexte du document et la structure hiérarchique.
    """
    parts = []

    if total_chunks > 1:
        parts.append(
            f"Voici la partie {chunk_num}/{total_chunks} "
            f"d'un cours de droit intitulé : « {doc_title} »\n"
        )
    else:
        parts.append(f"Voici un cours de droit intitulé : « {doc_title} »\n")

    parts.append("Structure du document avec son contenu :\n")

    for section in sections:
        indent = "  " * (section.level - 1)
        level_tag = f"[Niveau {section.level}]"
        parts.append(f"{indent}{level_tag} {section.title}")

        if section.content:
            content = section.content[:3000]
            if len(section.content) > 3000:
                content += "\n[... contenu tronqué]"
            parts.append(f"{indent}Contenu : {content}\n")

    # Instruction finale adaptée au niveau de détail
    _DETAIL_USER_INSTRUCTIONS = {
        1: (
            "\nRésume ce cours en conservant EXACTEMENT la même hiérarchie de titres. "
            "IMPORTANT : sois TRÈS CONCIS. Maximum 2-3 phrases par section. "
            "Garde uniquement les définitions et principes fondamentaux. "
            "Aucun exemple, aucune jurisprudence, aucune exception. "
            "Le résumé total doit être le plus court possible."
        ),
        2: (
            "\nRésume ce cours en conservant EXACTEMENT la même hiérarchie de titres. "
            "Chaque section doit être résumée de manière concise mais complète, "
            "en gardant les définitions, principes clés et références légales importantes."
        ),
        3: (
            "\nRésume ce cours en conservant EXACTEMENT la même hiérarchie de titres. "
            "IMPORTANT : sois DÉTAILLÉ et APPROFONDI. Pour chaque section, "
            "conserve les exemples concrets, les exceptions aux règles, "
            "la jurisprudence citée, les conditions d'application, "
            "et les explications détaillées. Le résumé doit être une fiche "
            "de révision complète et exhaustive. Ne raccourcis pas."
        ),
    }
    parts.append(_DETAIL_USER_INSTRUCTIONS.get(detail_level, _DETAIL_USER_INSTRUCTIONS[2]))

    return '\n'.join(parts)


# =========================================================================
# Parsing de la réponse
# =========================================================================

def _parse_summary_response(response_text: str) -> list[Section]:
    """
    Parse la réponse du modèle pour extraire les sections résumées.
    Cherche les marqueurs [H1]-[H4] pour reconstruire la hiérarchie.
    """
    sections = []
    current_title = ""
    current_level = 1
    current_content_lines = []

    for line in response_text.split('\n'):
        stripped = line.strip()
        heading_level = _detect_heading_marker(stripped)

        if heading_level is not None:
            if current_title:
                sections.append(Section(
                    title=current_title,
                    level=current_level,
                    content='\n'.join(current_content_lines).strip()
                ))

            current_title = stripped
            for marker in ['[H1]', '[H2]', '[H3]', '[H4]']:
                current_title = current_title.replace(marker, '').strip()
            current_level = heading_level
            current_content_lines = []
        else:
            if stripped:
                current_content_lines.append(stripped)

    if current_title:
        sections.append(Section(
            title=current_title,
            level=current_level,
            content='\n'.join(current_content_lines).strip()
        ))

    return sections


def _detect_heading_marker(line: str) -> int | None:
    """Détecte un marqueur de titre [H1]-[H4] dans une ligne."""
    markers = {'[H1]': 1, '[H2]': 2, '[H3]': 3, '[H4]': 4}
    for marker, level in markers.items():
        if marker in line:
            return level
    return None
