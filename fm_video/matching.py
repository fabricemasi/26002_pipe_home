"""Matching global SDR dans l'espace d'affichage sRGB, export .cube réutilisable.

Deux modèles explicites : régression polynomiale d'une paire alignée, ou transport
affine de covariance entre scènes différentes. Aucun des deux ne prétend retrouver
l'étalonnage de tournage. Aucun transform OCIO d'affichage n'est incorporé ici.
"""
from dataclasses import dataclass
from pathlib import Path
import os
import tempfile
import numpy as np


def _pixels(image):
    pixels = np.asarray(image,dtype=np.float64)
    if pixels.shape[-1] != 3 or not np.isfinite(pixels).all():
        raise ValueError('Il faut des pixels RGB finis dans [0, 1].')
    if pixels.min() < 0 or pixels.max() > 1:
        raise ValueError('Ce moteur attend du sRGB SDR [0, 1], sans signal HDR.')
    return pixels.reshape(-1,3)


def _features(rgb,degree):
    x = np.asarray(rgb,dtype=np.float64)
    r,g,b = x.T
    base = [r,g,b,np.ones(len(x))]
    if degree == 2:
        base += [r*r,g*g,b*b,r*g,r*b,g*b]
    return np.column_stack(base)


@dataclass
class Match:
    coefficients: np.ndarray
    degree: int
    method: str
    metrics: dict

    def apply(self,rgb,intensity=1.0,clip=True):
        rgb = np.asarray(rgb)
        shape = rgb.shape
        x = rgb.reshape(-1,3)
        result = _features(x,self.degree) @ self.coefficients
        result = x + float(intensity)*(result-x)
        return (np.clip(result,0,1) if clip else result).reshape(shape)


def fit_pair(source,reference,degree=2,regularization=.001):
    """Paire source/résultat ALIGNÉE : ridge vers l'identité, validation réservée.

    Un pixel sur cinq est réservé à l'évaluation. Ces erreurs décrivent la même
    paire, pas une garantie de généralisation à de nouvelles scènes.
    """
    if np.shape(source) != np.shape(reference):
        raise ValueError('La paire alignée doit avoir exactement les mêmes dimensions.')
    x,y = _pixels(source),_pixels(reference)
    ids = np.linspace(0,len(x)-1,min(40000,len(x)),dtype=int)
    x,y = x[ids],y[ids]
    if len(x)<20:
        raise ValueError('La paire doit contenir au moins 20 pixels comparables.')
    degree = 2 if degree == 2 else 1
    features = _features(x,degree)
    identity = np.zeros((features.shape[1],3))
    identity[:3,:] = np.eye(3)
    validation = np.arange(len(x))%5==0
    a,b = features[~validation],y[~validation]
    penalty = max(1e-8,float(regularization))*len(a)
    coefficients = np.linalg.solve(a.T@a+penalty*np.eye(a.shape[1]), a.T@b+penalty*identity)
    predicted = features[validation]@coefficients
    return Match(coefficients,degree,'Paire alignée / polynôme régularisé',dict(
        validation_pixels=int(validation.sum()),
        rgb_rmse=float(np.sqrt(np.mean((np.clip(predicted,0,1)-y[validation])**2))),
        before_rgb_rmse=float(np.sqrt(np.mean((x[validation]-y[validation])**2))),
        out_of_range=float(((predicted<0)|(predicted>1)).any(axis=1).mean())))


def fit_distribution(source,reference):
    """Transport affine des moyennes/covariances (scènes sans correspondances).

    Régularisation spectrale et gains bornés à 1/4..4 pour éviter une amplification
    sans borne quand un canal ou une scène possède très peu de variance.
    """
    x,y = _pixels(source),_pixels(reference)
    if min(len(x),len(y))<20:
        raise ValueError('Les images doivent contenir au moins 20 pixels.')
    x = x[np.linspace(0,len(x)-1,min(40000,len(x)),dtype=int)]
    y = y[np.linspace(0,len(y)-1,min(40000,len(y)),dtype=int)]
    def power(cov,exponent):
        values,vectors = np.linalg.eigh(cov+np.eye(3)*.0001)
        return (vectors*np.maximum(values,.0001)**exponent)@vectors.T
    transform = power(np.cov(x.T),-.5)@power(np.cov(y.T),.5)
    u,s,v = np.linalg.svd(transform)
    transform = (u*np.clip(s,.25,4))@v
    offset = y.mean(0)-x.mean(0)@transform
    coefficients = np.vstack([transform,offset])
    predicted = x@transform+offset
    return Match(coefficients,1,'Scènes différentes / transport de covariance RGB sRGB',dict(
        before_mean_rgb_distance=float(np.linalg.norm(x.mean(0)-y.mean(0))),
        after_mean_rgb_distance=float(np.linalg.norm(np.clip(predicted,0,1).mean(0)-y.mean(0))),
        out_of_range=float(((predicted<0)|(predicted>1)).any(axis=1).mean())))


def export_cube(model,path,size=33,intensity=1.0,cancelled=lambda:False):
    """Écrit rouge le plus rapide ; valide l'interpolation via le lecteur existant."""
    from fm_video.color import Lut
    if size not in (17,33,65,129):
        raise ValueError('Résolutions prises en charge : 17, 33, 65, 129.')
    path = Path(path)
    table = np.empty((size,size,size,3),np.float32)
    grid = np.linspace(0,1,size)
    g,r = np.meshgrid(grid,grid,indexing='ij')
    for b,value in enumerate(grid):
        if cancelled():
            raise InterruptedError('Export annulé')
        pixels = np.stack((r,g,np.full_like(r,value)),-1)
        table[b] = model.apply(pixels,intensity)
    lut = Lut(path,3,size,table,np.zeros(3),np.ones(3),'PIPE FMZ matching SDR')
    samples = np.random.default_rng(918).random((4096,3))
    delta = lut.apply_np(samples)-model.apply(samples,intensity)
    metrics = dict(interpolation_rgb_rmse=float(np.sqrt(np.mean(delta**2))),
                   interpolation_rgb_max=float(np.abs(delta).max()),resolution=size)
    fd,temporary = tempfile.mkstemp(prefix='.matching_',suffix='.cube',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            stream.write('TITLE "PIPE FMZ matching SDR"\n# Input: sRGB encoded SDR [0,1]\n'
                         '# Output: sRGB encoded SDR [0,1]; no OCIO display transform baked\n'
                         '# Model: '+model.method+'\n# Intensity: '+str(intensity)+'\n'
                         '# RGB interpolation RMSE: '+str(metrics['interpolation_rgb_rmse'])+'\n'
                         f'LUT_3D_SIZE {size}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
            for plane in table:
                if cancelled():
                    raise InterruptedError('Export annulé')
                np.savetxt(stream,plane.reshape(-1,3),fmt='%.9f')
        if cancelled():
            raise InterruptedError('Export annulé')
        os.replace(temporary,path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return metrics
