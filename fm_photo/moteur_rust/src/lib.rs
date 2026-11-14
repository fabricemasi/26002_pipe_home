//! Moteur photo de PIPE FMZ : exécution parallèle (rayon) des opérations de `fm_photo`.
//!
//! La RÉFÉRENCE reste `fm_photo/operations.py` et `fm_photo/couleur.py` : ce fichier refait les mêmes calculs,
//! dans le même ordre d'opérations flottantes (pas de multiplication-addition fusionnée, mêmes accumulations),
//! et `tests/test_photo_rust.py` mesure l'écart. Python transmet une demande (JSON : opérations complètes,
//! matrice de sortie, coefficients de luminance) et un tampon de pixels lu SANS copie ; le calcul se fait hors du
//! verrou Python ; l'annulation est un appelable Python interrogé entre les bandes de calcul.

use pyo3::buffer::PyBuffer;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use rayon::prelude::*;
use serde_json::Value;
use std::sync::{Arc, Mutex};

const TRONCATURE: f64 = 4.0;
const BANDES: usize = 16;

/// Opérations que ce moteur sait exécuter : (identifiant, version de l'algorithme).
const OPERATIONS: [(&str, u64); 2] = [("exposition", 1), ("diffusion", 1)];

struct Annule;

enum Operation {
    Exposition { gain: f32 },
    Diffusion { quantite: f32, seuil: f32, rayon: f64, teinte: [f32; 3] },
}

struct Demande {
    operations: Vec<Operation>,
    luminance: [f32; 3],
    matrice: [f32; 9],
    transfert: String,
}

fn nombre(valeur: &Value, cle: &str) -> Result<f64, String> {
    valeur.get(cle).and_then(Value::as_f64).ok_or_else(|| format!("paramètre absent ou non numérique : {cle}"))
}

fn triplet(valeur: &Value, cle: &str, taille: usize) -> Result<Vec<f32>, String> {
    let liste = valeur.get(cle).and_then(Value::as_array).ok_or_else(|| format!("liste absente : {cle}"))?;
    if liste.len() != taille {
        return Err(format!("{cle} : {taille} valeurs attendues"));
    }
    liste.iter().map(|v| v.as_f64().map(|x| x as f32).ok_or_else(|| format!("{cle} : valeur non numérique"))).collect()
}

fn lire_demande(texte: &str) -> Result<Demande, String> {
    let racine: Value = serde_json::from_str(texte).map_err(|e| format!("demande illisible : {e}"))?;
    let mut operations = Vec::new();
    for entree in racine.get("operations").and_then(Value::as_array).ok_or("operations absentes")? {
        let nom = entree.get("op").and_then(Value::as_str).ok_or("op absent")?;
        let version = entree.get("version").and_then(Value::as_u64).unwrap_or(1);
        let params = entree.get("params").ok_or("params absents")?;
        match (nom, version) {
            ("exposition", 1) => {
                // Même gain que la référence : float32(2.0 ** ev), puissance calculée en double.
                operations.push(Operation::Exposition { gain: 2.0f64.powf(nombre(params, "ev")?) as f32 });
            }
            ("diffusion", 1) => {
                let teinte = triplet(params, "teinte", 3)?;
                operations.push(Operation::Diffusion {
                    quantite: nombre(params, "quantite")? as f32,
                    seuil: nombre(params, "seuil")? as f32,
                    rayon: nombre(params, "rayon")?,
                    teinte: [teinte[0], teinte[1], teinte[2]],
                });
            }
            _ => return Err(format!("opération non prise en charge par le moteur Rust : {nom} v{version}")),
        }
    }
    let luminance = triplet(&racine, "luminance", 3)?;
    let matrice = triplet(&racine, "matrice", 9)?;
    let transfert = racine.get("transfert").and_then(Value::as_str).unwrap_or("srgb").to_string();
    if !["srgb", "gamma_2_2", "romm", "lineaire"].contains(&transfert.as_str()) {
        return Err(format!("transfert inconnu : {transfert}"));
    }
    Ok(Demande {
        operations,
        luminance: [luminance[0], luminance[1], luminance[2]],
        matrice: matrice.try_into().map_err(|_| "matrice : 9 valeurs attendues".to_string())?,
        transfert,
    })
}

struct Image {
    largeur: usize,
    hauteur: usize,
    pixels: Vec<f32>, // R, V, B entrelacés
}

/// Réduction entière par moyenne de blocs (référence : `operations.reduire`) : somme des lignes du bloc, puis
/// des colonnes, en simple précision ; division par le nombre de pixels présents, en double.
fn reduire(source: &[f32], largeur: usize, hauteur: usize, facteur: usize) -> Image {
    let (l, h) = (largeur.div_ceil(facteur), hauteur.div_ceil(facteur));
    let mut pixels = vec![0f32; l * h * 3];
    pixels.par_chunks_mut(l * 3).enumerate().for_each_init(
        || vec![0f32; largeur * 3],
        |lignes, (by, sortie)| {
            let (y0, y1) = (by * facteur, ((by + 1) * facteur).min(hauteur));
            lignes.copy_from_slice(&source[y0 * largeur * 3..(y0 + 1) * largeur * 3]);
            for y in y0 + 1..y1 {
                let ligne = &source[y * largeur * 3..(y + 1) * largeur * 3];
                for (somme, valeur) in lignes.iter_mut().zip(ligne) {
                    *somme += *valeur;
                }
            }
            for bx in 0..l {
                let (x0, x1) = (bx * facteur, ((bx + 1) * facteur).min(largeur));
                let compte = ((y1 - y0) * (x1 - x0)) as f64;
                for c in 0..3 {
                    let mut somme = lignes[x0 * 3 + c];
                    for x in x0 + 1..x1 {
                        somme += lignes[x * 3 + c];
                    }
                    sortie[bx * 3 + c] = (somme as f64 / compte) as f32;
                }
            }
        },
    );
    Image { largeur: l, hauteur: h, pixels }
}

/// Noyau gaussien 1D normalisé, coupé à 4 sigma (référence : `operations.noyau_gaussien`).
fn noyau_gaussien(sigma: f64) -> Vec<f32> {
    let rayon = (TRONCATURE * sigma).ceil() as i64;
    let brut: Vec<f64> = (-rayon..=rayon).map(|p| (-0.5 * (p as f64 / sigma).powi(2)).exp()).collect();
    let somme: f64 = brut.iter().sum();
    brut.iter().map(|v| (v / somme) as f32).collect()
}

/// Flou séparable exact, bords prolongés par répétition : passe verticale puis horizontale, une addition par
/// prise du noyau dans l'ordre des prises (comme la référence). `arret` est interrogé entre les bandes.
fn flou(image: &mut Image, sigma: f64, arret: &dyn Fn() -> bool) -> Result<(), Annule> {
    if sigma <= 0.0 {
        return Ok(());
    }
    let noyau = noyau_gaussien(sigma);
    let rayon = noyau.len() / 2;
    let (largeur, hauteur) = (image.largeur, image.hauteur);
    let pas = largeur * 3;
    let lignes_par_bande = hauteur.div_ceil(BANDES).max(1);

    let source = &image.pixels;
    let mut vertical = vec![0f32; source.len()];
    for (rang, bande) in vertical.chunks_mut(lignes_par_bande * pas).enumerate() {
        let premiere = rang * lignes_par_bande;
        bande.par_chunks_mut(pas).enumerate().for_each(|(dy, sortie)| {
            let y = premiere + dy;
            for (prise, poids) in noyau.iter().enumerate() {
                let sy = (y + prise).saturating_sub(rayon).min(hauteur - 1);
                let ligne = &source[sy * pas..(sy + 1) * pas];
                for (somme, valeur) in sortie.iter_mut().zip(ligne) {
                    *somme += *poids * *valeur;
                }
            }
        });
        if arret() {
            return Err(Annule);
        }
    }

    for bande in vertical.chunks_mut(lignes_par_bande * pas) {
        bande.par_chunks_mut(pas).for_each_init(
            || vec![0f32; (largeur + 2 * rayon) * 3],
            |etendue, ligne| {
                for x in 0..largeur + 2 * rayon {
                    let sx = x.saturating_sub(rayon).min(largeur - 1);
                    etendue[x * 3..x * 3 + 3].copy_from_slice(&ligne[sx * 3..sx * 3 + 3]);
                }
                ligne.fill(0.0);
                for (prise, poids) in noyau.iter().enumerate() {
                    let decale = &etendue[prise * 3..prise * 3 + pas];
                    for (somme, valeur) in ligne.iter_mut().zip(decale) {
                        *somme += *poids * *valeur;
                    }
                }
            },
        );
        if arret() {
            return Err(Annule);
        }
    }
    image.pixels = vertical;
    Ok(())
}

fn diffusion(image: &mut Image, quantite: f32, seuil: f32, sigma: f64, teinte: [f32; 3], luminance: [f32; 3],
             arret: &dyn Fn() -> bool) -> Result<(), Annule> {
    if quantite == 0.0 || sigma <= 0.0 {
        return Ok(());
    }
    let mut halo = Image { largeur: image.largeur, hauteur: image.hauteur, pixels: vec![0f32; image.pixels.len()] };
    halo.pixels.par_chunks_mut(3).zip(image.pixels.par_chunks(3)).for_each(|(sortie, pixel)| {
        let y = pixel[0] * luminance[0] + pixel[1] * luminance[1] + pixel[2] * luminance[2];
        let part = (y - seuil).max(0.0) / y.max(1e-6);
        for c in 0..3 {
            sortie[c] = pixel[c] * part;
        }
    });
    flou(&mut halo, sigma, arret)?;
    image.pixels.par_chunks_mut(3).zip(halo.pixels.par_chunks(3)).for_each(|(pixel, diffuse)| {
        for c in 0..3 {
            pixel[c] += quantite * diffuse[c] * teinte[c];
        }
    });
    Ok(())
}

fn encoder(lineaire: f32, transfert: &str) -> f32 {
    // Appelé sur des valeurs déjà bornées à [0, 1] : la symétrie impaire de la référence n'intervient pas.
    match transfert {
        "srgb" => {
            if lineaire <= 0.0031308 { lineaire * 12.92 } else { 1.055 * lineaire.powf((1.0f64 / 2.4) as f32) - 0.055 }
        }
        "romm" => {
            if lineaire < (1.0f64 / 512.0) as f32 { lineaire * 16.0 } else { lineaire.powf((1.0f64 / 1.8) as f32) }
        }
        "gamma_2_2" => lineaire.powf((256.0f64 / 563.0) as f32),
        _ => lineaire,
    }
}

/// Linéaire de travail -> codes entiers de l'espace de sortie (matrice, écrêtage à [0, 1], transfert, arrondi au
/// pair le plus proche comme `numpy.rint`). `canaux` = 3 (RVB) ou 4 (RVB + 255).
fn coder(image: &Image, demande: &Demande, bits: u32, canaux: usize) -> Vec<u8> {
    let m = &demande.matrice;
    let maximum = ((1u32 << bits) - 1) as f32;
    let octets = if bits > 8 { 2 } else { 1 };
    let mut sortie = vec![0u8; image.largeur * image.hauteur * canaux * octets];
    sortie.par_chunks_mut(canaux * octets).zip(image.pixels.par_chunks(3)).for_each(|(code, pixel)| {
        for c in 0..canaux {
            let valeur = if c < 3 {
                let lineaire = pixel[0] * m[c * 3] + pixel[1] * m[c * 3 + 1] + pixel[2] * m[c * 3 + 2];
                let encodee = encoder(lineaire.clamp(0.0, 1.0), &demande.transfert).clamp(0.0, 1.0);
                (encodee * maximum).round_ties_even() as u32
            } else {
                maximum as u32
            };
            if octets == 2 {
                code[c * 2..c * 2 + 2].copy_from_slice(&(valeur as u16).to_ne_bytes());
            } else {
                code[c] = valeur as u8;
            }
        }
    });
    sortie
}

struct Tampon(*const f32, usize);
unsafe impl Send for Tampon {}
unsafe impl Sync for Tampon {}
impl Tampon {
    /// Valable tant que la vue Python d'où vient le pointeur est gardée, et que personne n'écrit dedans.
    unsafe fn tranche(&self) -> &[f32] {
        std::slice::from_raw_parts(self.0, self.1)
    }
}

struct Reduite {
    cle: u64,
    facteur: usize,
    image: Arc<Image>,
}

/// Moteur : garde les images réduites des sources nommées par une clé (cache borné en octets, les moins
/// récemment servies partent d'abord). Les pixels source restent dans le tableau numpy de l'appelant.
#[pyclass]
struct Moteur {
    budget: usize,
    reduites: Mutex<Vec<Reduite>>,
}

impl Moteur {
    fn reduite(&self, cle: Option<u64>, facteur: usize, source: &[f32], largeur: usize, hauteur: usize) -> Arc<Image> {
        if let Some(cle) = cle {
            let mut cache = self.reduites.lock().unwrap();
            if let Some(rang) = cache.iter().position(|r| r.cle == cle && r.facteur == facteur) {
                let trouvee = cache.remove(rang);
                let image = trouvee.image.clone();
                cache.push(trouvee);
                return image;
            }
        }
        let image = Arc::new(reduire(source, largeur, hauteur, facteur));
        if let Some(cle) = cle {
            let mut cache = self.reduites.lock().unwrap();
            cache.push(Reduite { cle, facteur, image: image.clone() });
            let mut total: usize = cache.iter().map(|r| r.image.pixels.len() * 4).sum();
            while total > self.budget && cache.len() > 1 {
                total -= cache.remove(0).image.pixels.len() * 4;
            }
        }
        image
    }
}

#[pymethods]
impl Moteur {
    #[new]
    #[pyo3(signature = (budget_octets = 536870912))]
    fn new(budget_octets: usize) -> Self {
        Moteur { budget: budget_octets, reduites: Mutex::new(Vec::new()) }
    }

    /// Rend `pixels` (tampon float32 contigu, hauteur x largeur x 3, linéaire de travail) selon `demande` (JSON),
    /// à l'échelle 1 / `facteur`. `sortie` : « rgbx8 », « code8 », « code16 » ou « lineaire » (float32).
    /// Renvoie (octets, largeur, hauteur), ou None si `annule()` est devenu vrai.
    #[pyo3(signature = (pixels, largeur, hauteur, demande, facteur, sortie, annule = None, cle = None))]
    #[allow(clippy::too_many_arguments)]
    fn rendre<'py>(&self, py: Python<'py>, pixels: &Bound<'py, PyAny>, largeur: usize, hauteur: usize, demande: &str,
                   facteur: usize, sortie: &str, annule: Option<Py<PyAny>>, cle: Option<u64>)
                   -> PyResult<Option<(Bound<'py, PyBytes>, usize, usize)>> {
        let demande = lire_demande(demande).map_err(PyValueError::new_err)?;
        if facteur == 0 || largeur == 0 || hauteur == 0 {
            return Err(PyValueError::new_err("dimensions ou facteur nuls"));
        }
        if !["rgbx8", "code8", "code16", "lineaire"].contains(&sortie) {
            return Err(PyValueError::new_err(format!("sortie inconnue : {sortie}")));
        }
        let vue: PyBuffer<f32> = PyBuffer::get(pixels)?;
        if !vue.is_c_contiguous() || vue.item_count() != largeur * hauteur * 3 {
            return Err(PyValueError::new_err("pixels : tampon float32 contigu de hauteur x largeur x 3 attendu"));
        }
        let tampon = Tampon(vue.buf_ptr() as *const f32, vue.item_count());
        let arret = || match &annule {
            None => false,
            Some(rappel) => Python::attach(|py| rappel.bind(py).call0().and_then(|r| r.is_truthy()).unwrap_or(false)),
        };
        let resultat = py.detach(|| -> Result<(Vec<u8>, usize, usize), Annule> {
            // `vue` garde le tableau vivant pendant tout le calcul ; il n'est lu que par ce moteur.
            let source = unsafe { tampon.tranche() };
            let mut image = if facteur == 1 {
                Image { largeur, hauteur, pixels: source.to_vec() }
            } else {
                let reduite = self.reduite(cle, facteur, source, largeur, hauteur);
                Image { largeur: reduite.largeur, hauteur: reduite.hauteur, pixels: reduite.pixels.clone() }
            };
            let echelle = 1.0 / facteur as f64;
            for operation in &demande.operations {
                if arret() {
                    return Err(Annule);
                }
                match operation {
                    Operation::Exposition { gain } => image.pixels.par_iter_mut().for_each(|v| *v *= *gain),
                    Operation::Diffusion { quantite, seuil, rayon, teinte } => {
                        let sigma = rayon / 100.0 * largeur as f64 * echelle;
                        diffusion(&mut image, *quantite, *seuil, sigma, *teinte, demande.luminance, &arret)?;
                    }
                }
            }
            if arret() {
                return Err(Annule);
            }
            let octets = match sortie {
                "rgbx8" => coder(&image, &demande, 8, 4),
                "code8" => coder(&image, &demande, 8, 3),
                "code16" => coder(&image, &demande, 16, 3),
                _ => image.pixels.iter().flat_map(|v| v.to_ne_bytes()).collect(),
            };
            Ok((octets, image.largeur, image.hauteur))
        });
        drop(vue);
        match resultat {
            Err(Annule) => Ok(None),
            Ok((octets, l, h)) => Ok(Some((PyBytes::new(py, &octets), l, h))),
        }
    }

    /// Oublie les images réduites d'une source (clé libérée par l'appelant).
    fn oublier(&self, cle: u64) {
        self.reduites.lock().unwrap().retain(|r| r.cle != cle);
    }
}

/// Opérations exécutables : liste de (identifiant, version).
#[pyfunction]
fn operations() -> Vec<(String, u64)> {
    OPERATIONS.iter().map(|(nom, version)| (nom.to_string(), *version)).collect()
}

#[pymodule]
fn fm_photo_moteur(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<Moteur>()?;
    module.add_function(wrap_pyfunction!(operations, module)?)?;
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
