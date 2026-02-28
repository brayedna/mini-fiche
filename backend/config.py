"""
Configuration centrale de l'application Mini Fiche.
Charge les variables d'environnement et définit les constantes du projet.
"""

import os
from dotenv import load_dotenv

# Charger les variables d'environnement depuis le fichier .env à la racine du projet
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# --- Chemins du projet ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
OUTPUT_DIR = os.path.join(BASE_DIR, 'outputs')

# --- API OpenRouter ---
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')
OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', 'anthropic/claude-sonnet-4')
OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'

# --- Serveur Flask ---
BACKEND_PORT = int(os.getenv('BACKEND_PORT', 5000))

# --- Parallélisation ---
MAX_WORKERS = int(os.getenv('MAX_WORKERS', 4))          # Nombre de workers parallèles
CHUNK_MAX_SECTIONS = int(os.getenv('CHUNK_MAX_SECTIONS', 20))  # Sections max par chunk
CHUNK_MAX_CHARS = int(os.getenv('CHUNK_MAX_CHARS', 40000))     # Caractères max par chunk

# --- Extensions de fichiers acceptées ---
ALLOWED_EXTENSIONS = {'.pdf', '.docx'}
