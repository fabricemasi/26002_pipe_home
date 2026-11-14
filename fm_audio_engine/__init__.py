"""Infrastructure audio partagée de FM Audio, FM Music et du Board (sans Qt).

- `client` : processus moteur natif (`fmz_audio_engine.exe`), IPC v1, rendu offline ;
- `project` : modèle de projet commun (pistes, clips, notes, tempo, bus), schéma versionné ;
- `media` : identité des médias, révisions immuables, cache PCM, décodage ;
- `peaks` : pyramides min/max pour les waveforms.

Import léger : rien n'est chargé ici (les sous-modules s'importent à la demande).
"""

AUDIO_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg", ".aif", ".aiff", ".m4a")
PROJECT_EXT_AUDIO = ".fmaudio"
PROJECT_EXT_MUSIC = ".fmmusic"
