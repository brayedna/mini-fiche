"""
Parser pour les fichiers PDF.

Stratégie d'extraction des titres (par priorité) :
1. Sommaire intégré (bookmarks PDF) — le plus fiable quand disponible
2. Analyse typographique + détection LLM — fallback pour PDF sans sommaire
"""

import re
import fitz  # PyMuPDF
import logging
from .base_parser import BaseParser, ParsedDocument, Section
from .llm_heading_detector import detect_headings_with_llm

logger = logging.getLogger('mini_fiche.parser.pdf')


class PdfParser(BaseParser):
    """Parser spécialisé pour les fichiers .pdf"""

    def parse(self, file_path: str) -> ParsedDocument:
        """
        Parse un fichier PDF en extrayant la hiérarchie des titres.
        Tente d'abord le sommaire intégré, puis la détection par LLM.
        """
        doc = fitz.open(file_path)
        logger.info("Fichier chargé — %d pages", len(doc))

        text_blocks = self._extract_text_blocks(doc)
        logger.info("Extraction terminée — %d blocs de texte", len(text_blocks))

        if not text_blocks:
            doc.close()
            return ParsedDocument(raw_text="")

        # Stratégie 1 : sommaire PDF intégré (bookmarks)
        toc = doc.get_toc()
        if len(toc) >= 5:
            logger.info("Sommaire PDF détecté — %d entrées", len(toc))
            toc_pages = self._detect_toc_pages(text_blocks)
            title_index, heading_levels, fused_indices = self._match_toc_to_blocks(
                toc, text_blocks, toc_pages
            )
            if heading_levels:
                # Compléter avec les titres manquants du TOC (ex: "Partie" non bookmarkée)
                self._inject_missing_headings(text_blocks, heading_levels, toc_pages)
                # Compléter avec les sous-sections du sommaire visible (1., a)…)
                extra = self._supplement_from_visible_toc(
                    text_blocks, heading_levels, toc_pages
                )
                fused_indices.update(extra)
                logger.info(
                    "Stratégie : sommaire PDF intégré — %d titres matchés",
                    len(heading_levels),
                )
                # Exclure les blocs des pages sommaire + blocs fusionnés du contenu
                skip_indices = fused_indices
                for i, b in enumerate(text_blocks):
                    if b['page'] in toc_pages and i not in heading_levels:
                        skip_indices.add(i)
                result = self._build_document(
                    text_blocks, heading_levels, title_index, skip_indices
                )
                doc.close()
                return result
            logger.info("Matching du sommaire insuffisant, fallback LLM")

        # Stratégie 2 : détection par LLM (fallback)
        logger.info("Stratégie : détection des titres par LLM")
        title_index, heading_levels = detect_headings_with_llm(text_blocks)
        logger.info("Titres détectés : %d", len(heading_levels))

        result = self._build_document(text_blocks, heading_levels, title_index)
        doc.close()
        return result

    # =========================================================================
    # Stratégie 1 : Sommaire PDF intégré (bookmarks)
    # =========================================================================

    def _match_toc_to_blocks(
        self, toc: list, text_blocks: list, toc_pages: set,
    ) -> tuple[int | None, dict[int, int], set]:
        """
        Matche les entrées du sommaire PDF aux blocs de texte extraits.
        Retourne (title_index, heading_levels, fused_indices) au même format que le LLM.
        fused_indices : indices de blocs consommés par fusion (à exclure du contenu).
        """
        heading_levels = {}
        title_index = None
        fused_indices: set[int] = set()

        for level, title, page in toc:
            target_page = page - 1  # TOC est 1-indexed, text_blocks 0-indexed
            toc_title = self._normalize_text(title)

            if not toc_title:
                continue

            best_match, was_split = self._find_best_match(
                toc_title, target_page, text_blocks, toc_pages
            )

            if best_match is not None:
                # Si le titre était éclaté sur 2 blocs, fusionner dans le texte
                if was_split and best_match + 1 < len(text_blocks):
                    next_text = text_blocks[best_match + 1]['text'].strip()
                    text_blocks[best_match]['text'] = (
                        text_blocks[best_match]['text'].strip() + ' ' + next_text
                    )
                    fused_indices.add(best_match + 1)

                capped_level = min(level, 4)
                heading_levels[best_match] = capped_level

                if title_index is None and capped_level == 1:
                    title_index = best_match

        if title_index is None and heading_levels:
            title_index = min(heading_levels.keys())

        return title_index, heading_levels, fused_indices

    def _find_best_match(
        self, toc_title: str, target_page: int, text_blocks: list, toc_pages: set
    ) -> tuple[int | None, bool]:
        """
        Trouve le bloc de texte qui correspond le mieux à une entrée TOC.
        Retourne (index, was_split) — was_split=True si le titre est éclaté sur 2 blocs.
        Privilégie le match combiné quand un bloc est court (ex: "Chapitre I:").
        """
        for page_offset in (0, 1, -1):
            search_page = target_page + page_offset
            if search_page < 0 or search_page in toc_pages:
                continue

            for i, block in enumerate(text_blocks):
                if block['page'] != search_page:
                    continue

                block_text = self._normalize_text(block['text'])
                if not block_text:
                    continue

                # Match exact
                if block_text == toc_title:
                    return i, False

                # Le bloc est un début du titre TOC — essayer d'abord le match combiné
                if toc_title.startswith(block_text) and len(block_text) >= 2:
                    # Tenter de combiner avec le bloc suivant pour un meilleur match
                    if i + 1 < len(text_blocks) and text_blocks[i + 1]['page'] == search_page:
                        next_text = self._normalize_text(text_blocks[i + 1]['text'])
                        combined = block_text + ' ' + next_text
                        if combined == toc_title or toc_title.startswith(combined):
                            return i, True
                        if combined.startswith(toc_title):
                            return i, True

                    # Fallback : match partiel sur le bloc seul (si assez long)
                    if len(block_text) > 10:
                        return i, False

                # Le bloc commence par le titre TOC (bloc plus long que l'entrée TOC)
                if block_text.startswith(toc_title):
                    return i, False

        return None, False

    def _detect_toc_pages(self, text_blocks: list) -> set:
        """
        Détecte les pages qui font partie du sommaire visible du PDF.
        Une page est considérée sommaire si elle contient beaucoup de lignes
        avec des points de suite (......) typiques d'une table des matières.
        """
        toc_pages = set()
        dot_pattern = re.compile(r'\.{3,}')

        # Compter les lignes avec dots par page
        page_dot_counts = {}
        page_total_counts = {}

        for block in text_blocks:
            page = block['page']
            page_total_counts[page] = page_total_counts.get(page, 0) + 1
            if dot_pattern.search(block['text']):
                page_dot_counts[page] = page_dot_counts.get(page, 0) + 1

        for page, dot_count in page_dot_counts.items():
            total = page_total_counts.get(page, 1)
            # Si >40% des lignes de la page ont des points de suite → page sommaire
            if dot_count > 3 and dot_count / total > 0.4:
                toc_pages.add(page)

        if toc_pages:
            logger.info("Pages sommaire détectées : %s", sorted(toc_pages))

        return toc_pages

    # Patterns de titres structurels majeurs absents des bookmarks PDF
    _MAJOR_HEADING_PATTERN = re.compile(
        r'^(?:Partie|PARTIE|Introduction|INTRODUCTION|Conclusion|CONCLUSION)\s*'
        r'(?:\d+|[IVX]+|première|deuxième|seconde|préliminaire|générale|général)?\s*[:\-—]?\s*$',
        re.IGNORECASE,
    )

    def _inject_missing_headings(
        self, text_blocks: list, heading_levels: dict[int, int],
        toc_pages: set | None = None,
    ) -> None:
        """
        Détecte les titres structurels majeurs (Partie, Introduction...) présents
        dans le texte mais absents des bookmarks PDF, et les injecte dans heading_levels.

        Corrige aussi l'ordre : les gros titres PDF (18pt) sont parfois extraits
        APRÈS les sous-titres qu'ils contiennent (position basse sur la page).
        On les repositionne juste avant le premier heading qui les suit.
        """
        if toc_pages is None:
            toc_pages = self._detect_toc_pages(text_blocks)
        to_inject = []  # Liste de (bloc_original, texte_fusionné)

        for i, block in enumerate(text_blocks):
            if i in heading_levels:
                continue
            if block['page'] in toc_pages:
                continue

            text = block['text'].strip()
            if len(text) > 60:
                continue

            # Bloc gros (taille > corps) + gras + match pattern
            if block.get('is_bold') and block.get('font_size', 0) >= 16:
                if self._MAJOR_HEADING_PATTERN.match(text):
                    # Si le bloc suivant semble être la suite du titre, fusionner
                    if i + 1 < len(text_blocks) and i + 1 not in heading_levels:
                        next_block = text_blocks[i + 1]
                        next_text = next_block['text'].strip()
                        if (next_block['page'] == block['page'] and
                                next_block.get('is_bold') and len(next_text) < 80):
                            text = text + ' ' + next_text
                    to_inject.append((i, text))

        if not to_inject:
            return

        # Décaler tous les niveaux existants d'un cran pour faire de la place au niveau 1
        min_level = min(heading_levels.values())
        if min_level == 1:
            for idx in heading_levels:
                heading_levels[idx] = min(heading_levels[idx] + 1, 4)

        # Injecter chaque titre majeur AVANT le premier heading existant qui le suit
        sorted_headings = sorted(heading_levels.keys())

        for original_idx, title_text in to_inject:
            # Trouver le premier heading TOC qui suit ce bloc dans le document
            insert_idx = original_idx
            for h_idx in sorted_headings:
                if h_idx > original_idx:
                    break
                # Si un heading TOC est sur la même page ou juste avant le bloc injecté,
                # on doit se placer AVANT ce heading
                if h_idx < original_idx and text_blocks[h_idx]['page'] >= text_blocks[original_idx]['page'] - 1:
                    insert_idx = h_idx - 1
                    break

            # Copier le texte fusionné dans le bloc d'insertion
            if insert_idx != original_idx:
                text_blocks[insert_idx] = dict(text_blocks[insert_idx])
                text_blocks[insert_idx]['text'] = title_text
            else:
                text_blocks[original_idx]['text'] = title_text

            heading_levels[insert_idx] = 1
            logger.info(
                "Titre injecté : block[%d] (depuis block[%d]) \"%s\"",
                insert_idx, original_idx, title_text[:60],
            )

        logger.info("%d titre(s) majeur(s) injecté(s) (absents des bookmarks)", len(to_inject))

    # Pattern de sous-sections numérotées/lettrées absentes des bookmarks
    _SUB_HEADING_PATTERN = re.compile(
        r'^(?:'
        r'\d+\.\s*\S'           # 1.La notion, 2.Le fait
        r'|[a-z]\)\s*\S'        # a)Les qualités, b)La garde
        r'|[A-Z]\.\s*[A-Z]'    # C.L'avant projet (lettre majuscule isolée)
        r')',
    )
    # Pattern pour les labels de numérotation isolés (ex: "C." seul sur un bloc)
    _ISOLATED_LABEL_PATTERN = re.compile(
        r'^(?:\d+\.|[a-z]\)|[A-Z]\.)$'
    )

    @staticmethod
    def _compact_text(text: str) -> str:
        """Normalisation agressive : minuscules, sans espaces après numérotation."""
        t = ' '.join(text.split()).strip().lower()
        # Supprimer les espaces après les patterns de numérotation
        # "1. La notion" → "1.la notion", "a) Les qualités" → "a)les qualités"
        t = re.sub(r'^(\d+\.)\s+', r'\1', t)
        t = re.sub(r'^([a-z]\))\s+', r'\1', t)
        t = re.sub(r'^([A-Z]\.)\s+', lambda m: m.group(1).lower(), t)
        return t

    def _supplement_from_visible_toc(
        self, text_blocks: list, heading_levels: dict[int, int], toc_pages: set,
    ) -> set:
        """
        Détecte les sous-sections (1., 2., a), b)…) présentes dans le sommaire
        visible du PDF mais absentes des bookmarks. Les ajoute à heading_levels.
        Retourne les indices de blocs fusionnés (à exclure du contenu).
        """
        # 1. Collecter les textes du sommaire visible (avant les points de suite)
        dot_re = re.compile(r'^(.+?)\s*\.{3,}')
        visible_entries = set()
        for block in text_blocks:
            if block['page'] not in toc_pages:
                continue
            m = dot_re.match(block['text'].strip())
            if m:
                entry = self._compact_text(m.group(1))
                if len(entry) > 2:
                    visible_entries.add(entry)

        if not visible_entries:
            return set()

        # 2. Scanner les blocs de contenu non encore marqués comme headings
        max_level = max(heading_levels.values()) if heading_levels else 4
        sub_level = min(max_level, 4)  # Niveau pour les sous-sections
        added = 0
        fused = set()

        for i, block in enumerate(text_blocks):
            if i in heading_levels or i in fused:
                continue
            if block['page'] in toc_pages:
                continue

            text = block['text'].strip()
            if len(text) > 100:
                continue

            # Cas 1 : label isolé ("C.", "1.", "a)") → fusionner avec bloc suivant
            if self._ISOLATED_LABEL_PATTERN.match(text):
                if i + 1 < len(text_blocks) and i + 1 not in heading_levels:
                    next_block = text_blocks[i + 1]
                    if next_block['page'] == block['page']:
                        combined_text = text + next_block['text'].strip()
                        compact = self._compact_text(combined_text)
                        if compact in visible_entries or any(
                            ve.startswith(compact) for ve in visible_entries
                        ):
                            text_blocks[i]['text'] = text + next_block['text'].strip()
                            fused.add(i + 1)
                            heading_levels[i] = sub_level
                            added += 1
                continue

            if len(text) < 3:
                continue

            # Cas 2 : bloc normal avec pattern de sous-section
            if not self._SUB_HEADING_PATTERN.match(text):
                continue

            compact = self._compact_text(text)

            # Vérifier que ce texte apparaît dans le sommaire visible
            in_toc = compact in visible_entries
            if not in_toc:
                # Essayer un match partiel (texte sur 2 blocs, ou préfixe)
                for ve in visible_entries:
                    if ve.startswith(compact) or compact.startswith(ve):
                        in_toc = True
                        # Fusionner avec le bloc suivant si le titre est éclaté
                        if ve.startswith(compact) and compact != ve:
                            if i + 1 < len(text_blocks) and i + 1 not in heading_levels:
                                next_block = text_blocks[i + 1]
                                if next_block['page'] == block['page']:
                                    combined = compact + ' ' + self._normalize_text(
                                        next_block['text']
                                    )
                                    if ve.startswith(combined):
                                        text_blocks[i]['text'] = (
                                            text + ' ' + next_block['text'].strip()
                                        )
                                        fused.add(i + 1)
                        break

            if in_toc:
                heading_levels[i] = sub_level
                added += 1

        if added > 0:
            logger.info(
                "%d sous-section(s) ajoutée(s) depuis le sommaire visible",
                added,
            )

        return fused

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalise un texte pour la comparaison : espaces multiples → simple, strip."""
        return ' '.join(text.split()).strip().lower()

    def _extract_text_blocks(self, doc) -> list:
        """
        Parcourt chaque page du PDF et extrait les lignes de texte
        avec leurs propriétés typographiques (taille, police, gras).

        Retourne une liste de dicts avec : text, font_size, font_name, is_bold, page
        """
        blocks = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue

                for line in block.get("lines", []):
                    line_text = ""
                    line_font_size = 0
                    line_font_name = ""
                    line_is_bold = False

                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if not text:
                            continue

                        size = round(span.get("size", 0), 1)
                        font = span.get("font", "")
                        bold = (
                            "Bold" in font or
                            "bold" in font.lower() or
                            (span.get("flags", 0) & 2 ** 4) != 0
                        )

                        line_text += span.get("text", "")

                        if size > line_font_size:
                            line_font_size = size
                            line_font_name = font
                            line_is_bold = bold

                    line_text = line_text.strip()
                    if line_text:
                        blocks.append({
                            'text': line_text,
                            'font_size': line_font_size,
                            'font_name': line_font_name,
                            'is_bold': line_is_bold,
                            'page': page_num
                        })

        return blocks

    def _build_document(
        self, text_blocks: list, heading_levels: dict, title_index: int | None,
        skip_indices: set | None = None,
    ) -> ParsedDocument:
        """
        Assemble le ParsedDocument final à partir des blocs de texte
        et des niveaux de titres retournés par le LLM.
        skip_indices : indices de blocs à ignorer (pages sommaire, blocs fusionnés…)
        """
        result = ParsedDocument()
        sections = []
        current_content_lines = []
        raw_lines = []

        if title_index is not None and title_index < len(text_blocks):
            result.title = text_blocks[title_index]['text']

        for i, block in enumerate(text_blocks):
            if skip_indices and i in skip_indices:
                continue

            text = block['text']
            raw_lines.append(text)

            level = heading_levels.get(i)
            if level is not None:
                if sections:
                    sections[-1].content = '\n'.join(current_content_lines)
                current_content_lines = []

                sections.append(Section(title=text, level=level))

                if level == 1 and not result.title:
                    result.title = text
            else:
                current_content_lines.append(text)

        if sections and current_content_lines:
            sections[-1].content = '\n'.join(current_content_lines)

        if not result.title and text_blocks:
            result.title = text_blocks[0]['text']

        result.sections = sections
        result.raw_text = '\n'.join(raw_lines)
        return result
