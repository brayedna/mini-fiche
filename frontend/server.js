/**
 * Serveur Express — Frontend Mini Fiche
 *
 * Sert l'interface web et fait le relais avec l'API Flask backend
 * pour l'upload des fichiers et le téléchargement des résumés.
 */

const express = require('express');
const multer = require('multer');
const axios = require('axios');
const FormData = require('form-data');
const fs = require('fs');
const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '..', '.env') });

const app = express();

// --- Configuration ---
const FRONTEND_PORT = process.env.FRONTEND_PORT || 3000;
const BACKEND_URL = `http://localhost:${process.env.BACKEND_PORT || 5000}`;

// Moteur de templates EJS
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));

// Parser les champs texte des formulaires multipart
app.use(express.urlencoded({ extended: false }));

// Fichiers statiques (CSS, JS client)
app.use(express.static(path.join(__dirname, 'public')));

// Configuration de multer pour l'upload temporaire des fichiers
const upload = multer({
  dest: path.join(__dirname, '..', 'uploads'),
  limits: { fileSize: 50 * 1024 * 1024 }, // Limite à 50 Mo
  fileFilter: (_req, file, cb) => {
    const allowedExtensions = ['.pdf', '.docx'];
    const ext = path.extname(file.originalname).toLowerCase();
    if (allowedExtensions.includes(ext)) {
      cb(null, true);
    } else {
      cb(new Error(`Format non supporté : ${ext}. Seuls .pdf et .docx sont acceptés.`));
    }
  },
});

// --- Routes ---

/** Page d'accueil — formulaire d'upload */
app.get('/', (_req, res) => {
  res.render('index', { error: null, success: null });
});

/**
 * Traitement de l'upload : envoie le fichier au backend Flask,
 * attend le résumé, puis redirige vers le téléchargement.
 */
app.post('/upload', upload.single('file'), async (req, res) => {
  if (!req.file) {
    return res.render('index', {
      error: 'Veuillez sélectionner un fichier PDF ou DOCX.',
      success: null,
    });
  }

  const filePath = req.file.path;

  try {
    // Construire le formulaire multipart pour le backend Flask
    const form = new FormData();
    form.append('file', fs.createReadStream(filePath), {
      filename: req.file.originalname,
      contentType: req.file.mimetype,
    });

    // Transmettre le niveau de détail (1=très concis, 2=concis, 3=détaillé)
    const detailLevel = req.body.detail_level || '2';
    form.append('detail_level', detailLevel);

    // Envoyer au backend Flask
    const response = await axios.post(`${BACKEND_URL}/api/summarize`, form, {
      headers: form.getHeaders(),
      timeout: 300000, // 5 minutes — le résumé IA peut prendre du temps
    });

    const { file_id, download_name, original_title, sections_count } = response.data;

    res.render('index', {
      error: null,
      success: {
        file_id,
        original_title,
        sections_count,
        download_url: `/download/${file_id}?name=${encodeURIComponent(download_name)}`,
      },
    });
  } catch (err) {
    // Extraire le message d'erreur du backend si disponible
    const backendError = err.response?.data?.error;
    const errorMessage = backendError || `Erreur : ${err.message}`;
    res.render('index', { error: errorMessage, success: null });
  } finally {
    // Nettoyer le fichier temporaire uploadé
    if (fs.existsSync(filePath)) {
      fs.unlinkSync(filePath);
    }
  }
});

/**
 * Téléchargement du résumé — relais vers le backend Flask
 */
app.get('/download/:fileId', async (req, res) => {
  try {
    // Transmettre le query param "name" au backend pour le nom du fichier
    const nameParam = req.query.name ? `?name=${encodeURIComponent(req.query.name)}` : '';
    const response = await axios.get(
      `${BACKEND_URL}/api/download/${req.params.fileId}${nameParam}`,
      { responseType: 'stream' }
    );

    res.setHeader('Content-Type', response.headers['content-type']);
    res.setHeader('Content-Disposition', response.headers['content-disposition']);
    response.data.pipe(res);
  } catch {
    res.status(404).send('Fichier non trouvé. Le résumé a peut-être expiré.');
  }
});

// --- Démarrage du serveur ---
app.listen(FRONTEND_PORT, () => {
  console.log(`🌐 Frontend Mini Fiche : http://localhost:${FRONTEND_PORT}`);
  console.log(`🔗 Backend attendu sur : ${BACKEND_URL}`);
});
