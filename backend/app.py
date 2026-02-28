"""
Point d'entrée de l'API Flask — Backend Mini Fiche.

Expose les endpoints REST pour :
- Upload de fichiers PDF/DOCX
- Lancement du résumé (parsing → résumé IA → génération DOCX)
- Téléchargement du résumé généré

Tous les traitements sont loggés dans la console pour le suivi en temps réel.
"""

import os
import sys
import uuid
import time
import logging

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

# Ajouter le dossier parent au path pour les imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import UPLOAD_DIR, OUTPUT_DIR, ALLOWED_EXTENSIONS, BACKEND_PORT
from backend.parsers.docx_parser import DocxParser
from backend.parsers.pdf_parser import PdfParser
from backend.summarizer.claude_summarizer import summarize_document
from backend.generators.docx_generator import generate_summary_docx

# =========================================================================
# Configuration du logging avec couleurs
# =========================================================================

class ColorFormatter(logging.Formatter):
    """Formatter avec couleurs ANSI pour distinguer les modules et niveaux."""

    # Couleurs ANSI
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

    # Couleurs par niveau
    LEVEL_COLORS = {
        logging.DEBUG:    '\033[36m',     # Cyan
        logging.INFO:     '\033[32m',     # Vert
        logging.WARNING:  '\033[33m',     # Jaune
        logging.ERROR:    '\033[31m',     # Rouge
        logging.CRITICAL: '\033[1;31m',   # Rouge gras
    }

    # Couleurs par module
    MODULE_COLORS = {
        'mini_fiche.api':        '\033[1;34m',  # Bleu gras
        'mini_fiche.parser.docx': '\033[1;35m', # Magenta gras
        'mini_fiche.parser.pdf':  '\033[1;35m', # Magenta gras
        'mini_fiche.summarizer':  '\033[1;36m', # Cyan gras
    }

    def format(self, record):
        # Couleur du niveau
        lvl_color = self.LEVEL_COLORS.get(record.levelno, '')
        level = f"{lvl_color}{record.levelname:<7}{self.RESET}"

        # Couleur du module
        mod_color = self.MODULE_COLORS.get(record.name, '\033[37m')
        module = f"{mod_color}{record.name}{self.RESET}"

        # Timestamp en gris
        ts = f"{self.DIM}{self.formatTime(record, self.datefmt)}{self.RESET}"

        # Message — les séparateurs (===) en jaune gras
        msg = record.getMessage()
        if msg.startswith('===') or msg.startswith('=' * 10):
            msg = f"\033[1;33m{msg}{self.RESET}"
        elif msg.startswith('[1/3]'):
            msg = f"\033[1;35m{msg}{self.RESET}"  # Magenta — parsing
        elif msg.startswith('[2/3]'):
            msg = f"\033[1;36m{msg}{self.RESET}"  # Cyan — résumé IA
        elif msg.startswith('[3/3]'):
            msg = f"\033[1;32m{msg}{self.RESET}"  # Vert — génération
        elif msg.startswith('[Chunk'):
            msg = f"\033[36m{msg}{self.RESET}"     # Cyan — chunks
        elif msg.startswith('PIPELINE'):
            msg = f"\033[1;32m{msg}{self.RESET}"   # Vert gras — bilan
        elif msg.startswith('NOUVEAU'):
            msg = f"\033[1;33m{msg}{self.RESET}"   # Jaune gras — nouveau
        elif 'ÉCHOUÉ' in msg or 'Erreur' in msg:
            msg = f"\033[1;31m{msg}{self.RESET}"   # Rouge gras — erreurs

        return f"{ts} {level} {module} — {msg}"


handler = logging.StreamHandler()
handler.setFormatter(ColorFormatter(datefmt='%H:%M:%S'))
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger('mini_fiche.api')

# =========================================================================
# Application Flask
# =========================================================================

app = Flask(__name__)
CORS(app)

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


@app.route('/api/health', methods=['GET'])
def health_check():
    """Endpoint de vérification que le serveur est opérationnel."""
    return jsonify({"status": "ok", "message": "Backend Mini Fiche opérationnel"})


@app.route('/api/summarize', methods=['POST'])
def summarize():
    """
    Endpoint principal : pipeline complet avec logs détaillés.
    Upload → Parsing → Chunking → Résumé IA (parallèle) → Génération DOCX
    """
    pipeline_start = time.time()

    # --- Validation du fichier uploadé ---
    if 'file' not in request.files:
        return jsonify({"error": "Aucun fichier envoyé"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Nom de fichier vide"}), 400

    _, ext = os.path.splitext(file.filename)
    ext = ext.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({
            "error": f"Format non supporté : {ext}. Formats acceptés : .pdf, .docx"
        }), 400

    # --- Sauvegarde temporaire ---
    file_id = str(uuid.uuid4())
    original_name = os.path.splitext(file.filename)[0]  # Nom sans extension
    safe_filename = f"{file_id}{ext}"
    upload_path = os.path.join(UPLOAD_DIR, safe_filename)
    file.save(upload_path)
    file_size = os.path.getsize(upload_path)

    logger.info("=" * 60)
    logger.info("NOUVEAU RÉSUMÉ — fichier: %s (%d Ko)", file.filename, file_size // 1024)
    logger.info("=" * 60)

    try:
        # --- Étape 1 : Parsing ---
        step_start = time.time()
        logger.info("[1/3] PARSING — format: %s", ext)

        if ext == '.pdf':
            parser = PdfParser()
        else:
            parser = DocxParser()

        parsed_doc = parser.parse(upload_path)

        if not parsed_doc.sections:
            logger.error("Aucune section extraite — abandon")
            return jsonify({
                "error": "Impossible d'extraire la structure du document. "
                         "Vérifiez que le fichier contient du texte formaté."
            }), 422

        raw_text_len = len(parsed_doc.raw_text)
        logger.info(
            "[1/3] PARSING TERMINÉ en %.1fs — titre: '%s' | "
            "%d sections | %d caractères de texte brut",
            time.time() - step_start,
            parsed_doc.title,
            len(parsed_doc.sections),
            raw_text_len,
        )

        # Log de la hiérarchie détectée
        level_counts = {}
        for s in parsed_doc.sections:
            level_counts[s.level] = level_counts.get(s.level, 0) + 1
        logger.info(
            "[1/3] Hiérarchie détectée : %s",
            " | ".join(f"H{k}: {v}" for k, v in sorted(level_counts.items())),
        )

        # --- Étape 2 : Résumé IA (avec chunking + workers) ---
        step_start = time.time()
        detail_level = int(request.form.get('detail_level', 2))
        detail_labels = {1: 'très concis', 2: 'concis', 3: 'détaillé'}
        logger.info(
            "[2/3] RÉSUMÉ IA — envoi au modèle via OpenRouter (niveau: %s)",
            detail_labels.get(detail_level, 'concis'),
        )

        summary_sections = summarize_document(parsed_doc, detail_level=detail_level)

        if not summary_sections:
            logger.error("Aucune section résumée retournée — abandon")
            return jsonify({
                "error": "Le résumé n'a pas pu être généré. Réessayez."
            }), 500

        # Fusionner : garantir que toutes les sections originales sont présentes
        summary_sections = _merge_sections(parsed_doc.sections, summary_sections)

        logger.info(
            "[2/3] RÉSUMÉ TERMINÉ en %.1fs — %d sections résumées",
            time.time() - step_start,
            len(summary_sections),
        )

        # --- Étape 3 : Génération DOCX ---
        step_start = time.time()
        logger.info("[3/3] GÉNÉRATION DOCX — sommaire + contenu")

        output_filename = f"resume_{file_id}.docx"
        download_name = f"resume_{original_name}.docx"
        output_path = os.path.join(OUTPUT_DIR, output_filename)

        generate_summary_docx(
            title=parsed_doc.title,
            sections=summary_sections,
            output_path=output_path
        )

        output_size = os.path.getsize(output_path)
        logger.info(
            "[3/3] DOCX GÉNÉRÉ en %.1fs — %s (%d Ko)",
            time.time() - step_start,
            output_filename,
            output_size // 1024,
        )

        # --- Bilan final ---
        total_elapsed = time.time() - pipeline_start
        logger.info("=" * 60)
        logger.info(
            "PIPELINE COMPLET en %.1fs — %s → %d sections résumées → %s",
            total_elapsed,
            file.filename,
            len(summary_sections),
            output_filename,
        )
        logger.info("=" * 60)

        return jsonify({
            "success": True,
            "message": "Résumé généré avec succès",
            "file_id": file_id,
            "filename": output_filename,
            "download_name": download_name,
            "original_title": parsed_doc.title,
            "sections_count": len(summary_sections),
            "elapsed_seconds": round(total_elapsed, 1),
        })

    except ValueError as e:
        logger.error("Erreur de configuration : %s", str(e))
        return jsonify({"error": str(e)}), 400

    except Exception as e:
        logger.exception("Erreur inattendue dans le pipeline")
        return jsonify({"error": f"Erreur lors du traitement : {str(e)}"}), 500

    finally:
        if os.path.exists(upload_path):
            os.remove(upload_path)


def _normalize(text: str) -> str:
    """Normalise un titre pour la comparaison."""
    return ' '.join(text.split()).strip().lower()


def _merge_sections(
    original: list, summarized: list
) -> list:
    """
    Fusionne les sections résumées avec les sections originales.
    Garantit que toutes les sections originales apparaissent dans le résultat.
    Les sections manquées par le LLM gardent leur contenu original (tronqué).
    """
    from backend.parsers.base_parser import Section

    # Index des sections résumées par titre normalisé
    summary_map = {}
    for s in summarized:
        key = _normalize(s.title)
        summary_map[key] = s

    merged = []
    matched = 0
    kept_original = 0

    for orig in original:
        key = _normalize(orig.title)

        # Chercher un match exact ou partiel dans les résumés
        match = summary_map.get(key)
        if not match:
            # Essayer un match partiel (le LLM peut légèrement modifier le titre)
            for skey, sval in summary_map.items():
                if key in skey or skey in key:
                    match = sval
                    break

        if match:
            merged.append(match)
            matched += 1
        else:
            # Garder la section originale avec contenu tronqué
            content = orig.content[:1500] if orig.content else ""
            merged.append(Section(
                title=orig.title,
                level=orig.level,
                content=content,
            ))
            kept_original += 1

    if kept_original > 0:
        logger.info(
            "Fusion : %d sections résumées matchées, %d sections originales conservées",
            matched, kept_original,
        )

    return merged


@app.route('/api/download/<file_id>', methods=['GET'])
def download(file_id):
    """Téléchargement du résumé généré."""
    output_filename = f"resume_{file_id}.docx"
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    if not os.path.exists(output_path):
        return jsonify({"error": "Fichier non trouvé"}), 404

    # Nom de téléchargement passé en query param par le frontend
    download_name = request.args.get('name', output_filename)
    logger.info("Téléchargement : %s → %s", output_filename, download_name)

    return send_file(
        output_path,
        as_attachment=True,
        download_name=download_name,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )


if __name__ == '__main__':
    logger.info("Backend Mini Fiche démarré sur http://localhost:%d", BACKEND_PORT)
    app.run(host='0.0.0.0', port=BACKEND_PORT, debug=True)
