"""Méthodes de colonne : création et opérations sur fichiers."""

import shutil
from pathlib import Path
from PySide6.QtCore import QFile
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QLineEdit, QMessageBox
from browser_core import ROLE_PATH, _prompt_capture_thumbnail, _prompt_change_thumbnail, _prompt_reset_thumbnail, add_shortcut, load_shortcuts, save_shortcuts


class ColumnFileOperationsMixin:
    def _create_folder(self):
        name, ok = QInputDialog.getText(
            self, "Nouveau dossier", "Nom du dossier :", QLineEdit.Normal, "Nouveau dossier"
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if any(ch in name for ch in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Nouveau dossier", "Le nom contient des caracteres interdits.")
            return
        target_dir = self.directory
        if self._source_dirs is not None and self._source_labels and len(self._source_dirs) > 1:
            # Colonne IN/OVER/OUT (contenu FUSIONNE de plusieurs colonnes de
            # set, voir __init__/PipelineBrowser.update_preview_stack) :
            # `self.directory` n'est qu'un repli parmi plusieurs sources
            # possibles — demande a QUEL NIVEAU (quelle colonne de set
            # actuellement affichee) ce nouveau dossier doit reellement
            # etre cree sur le disque, plutot que de choisir silencieusement
            # le premier — voir la remarque de l'utilisateur, "je veux
            # pouvoir creer des repertoires dans les colonnes in over et
            # out. quand c'est le cas, je veux que le soft me demande a
            # quel niveau (quelle colonne) il doit les enregistrer".
            choice, ok_level = QInputDialog.getItem(
                self, "Nouveau dossier", "A quel niveau enregistrer ce dossier ?",
                self._source_labels, 0, False,
            )
            if not ok_level:
                return
            target_dir = self._source_dirs[self._source_labels.index(choice)]
        new_path = target_dir / name
        if new_path.exists():
            QMessageBox.warning(self, "Nouveau dossier", f"« {name} » existe deja.")
            return
        try:
            # parents=True : `target_dir` (repli sur un NIVEAU DE SET
            # choisi, voir ci-dessus) peut lui-meme ne pas encore exister
            # (in/over/out jamais cree pour ce niveau precis) — voir la
            # remarque de l'utilisateur, capture a l'appui, "il y a un
            # probleme quand on cree un repertoire alors que la hierarchie
            # n'est pas encore creee ... que toute la hierarchie soit
            # creee en meme temps que le repertoire" (WinError 3, "chemin
            # d'acces introuvable").
            new_path.mkdir(parents=True)
        except OSError as exc:
            QMessageBox.warning(self, "Nouveau dossier", f"Impossible de creer le dossier :\n{exc}")
            return
        self.refresh()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_PATH) == str(new_path):
                self.list.setCurrentItem(it)
                break
    def _create_text_file(self):
        """"Nouveau document texte" (voir _on_context_menu) : cree un fichier
        .txt vierge, MEME mecanique que _create_folder (nom/caracteres
        interdits/choix du niveau pour une colonne IN/OVER/OUT fusionnee/
        creation des dossiers parents manquants) — voir la remarque de
        l'utilisateur, "dans les colonnes ou le texte est permis, merci
        d'ajouter une option 'nouveau document texte' qui permet de creer
        un fichier txt vierge"."""
        name, ok = QInputDialog.getText(
            self, "Nouveau document texte", "Nom du fichier :", QLineEdit.Normal, "Nouveau document texte"
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if any(ch in name for ch in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Nouveau document texte", "Le nom contient des caracteres interdits.")
            return
        if not name.lower().endswith(".txt"):
            name += ".txt"
        target_dir = self.directory
        if self._source_dirs is not None and self._source_labels and len(self._source_dirs) > 1:
            choice, ok_level = QInputDialog.getItem(
                self, "Nouveau document texte", "A quel niveau enregistrer ce fichier ?",
                self._source_labels, 0, False,
            )
            if not ok_level:
                return
            target_dir = self._source_dirs[self._source_labels.index(choice)]
        new_path = target_dir / name
        if new_path.exists():
            QMessageBox.warning(self, "Nouveau document texte", f"« {name} » existe deja.")
            return
        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_text("", encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Nouveau document texte", f"Impossible de creer le fichier :\n{exc}")
            return
        self.refresh()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_PATH) == str(new_path):
                self.list.setCurrentItem(it)
                break
    def _create_board_file(self, name: str | None = None):
        """« Créer un mro » (voir _on_context_menu) : un board vierge (paquet board/, JSON), meme mecanique que
        _create_text_file (nom, caracteres interdits, niveau d'une colonne fusionnee) ; il est selectionne,
        le double-clic l'ouvre dans l'appli."""
        import fm_board as board
        if name is None:
            name, ok = QInputDialog.getText(self, "Créer un mro", "Nom du board :", QLineEdit.Normal, "Nouveau board")
            if not ok:
                return None
        name = (name or "").strip()
        if not name:
            return None
        if any(ch in name for ch in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Créer un mro", "Le nom contient des caracteres interdits.")
            return None
        if not name.lower().endswith(board.EXTENSION):
            name += board.EXTENSION
        target_dir = self.directory
        if self._source_dirs is not None and self._source_labels and len(self._source_dirs) > 1:
            choice, ok_level = QInputDialog.getItem(
                self, "Créer un mro", "A quel niveau enregistrer ce board ?", self._source_labels, 0, False)
            if not ok_level:
                return None
            target_dir = self._source_dirs[self._source_labels.index(choice)]
        new_path = target_dir / name
        if new_path.exists():
            QMessageBox.warning(self, "Créer un mro", f"« {name} » existe deja.")
            return None
        try:
            board.create_board_file(new_path)
        except OSError as exc:
            QMessageBox.warning(self, "Créer un mro", f"Impossible de creer le board :\n{exc}")
            return None
        self.refresh()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_PATH) == str(new_path):
                self.list.setCurrentItem(it)
                break
        return new_path
    def _add_shortcut(self):
        """"Ajouter un raccourci" (voir _on_context_menu, ROLE_IS_SHORTCUT/
        load_shortcuts/add_shortcut) : va chercher un fichier ou un
        repertoire n'importe ou sur le disque et l'affiche comme s'il etait
        physiquement dans ce dossier."""
        target_dir = self.directory
        if self._source_dirs is not None and self._source_labels and len(self._source_dirs) > 1:
            # MEME choix de niveau que _create_folder, MEME raison (colonne
            # IN/OVER/OUT, contenu fusionne de plusieurs colonnes de set).
            choice, ok_level = QInputDialog.getItem(
                self, "Ajouter un raccourci", "A quel niveau enregistrer ce raccourci ?",
                self._source_labels, 0, False,
            )
            if not ok_level:
                return
            target_dir = self._source_dirs[self._source_labels.index(choice)]
        kind, accepted = QInputDialog.getItem(
            self, "Ajouter un raccourci", "Type de raccourci :",
            ("Fichier", "Répertoire"), 0, False,
        )
        if not accepted:
            return
        if kind == "Répertoire":
            selected = QFileDialog.getExistingDirectory(self, "Choisir un répertoire", str(target_dir))
        else:
            selected, _unused = QFileDialog.getOpenFileName(
                self, "Choisir un fichier", str(target_dir), "Tous les fichiers (*)")
        if not selected:
            return
        chosen_path = Path(selected)
        if not chosen_path.exists():
            return
        if chosen_path == target_dir or chosen_path.parent == target_dir:
            QMessageBox.warning(self, "Ajouter un raccourci", "Cet élément est deja ici.")
            return
        add_shortcut(target_dir, chosen_path)
        self.refresh()
    def _change_thumbnail(self, path: Path):
        _prompt_change_thumbnail(self, path, lambda: self.list.viewport().update())
    def _capture_thumbnail(self, path: Path):
        _prompt_capture_thumbnail(self, path, lambda: self.list.viewport().update())
    def _reset_thumbnail(self, path: Path):
        _prompt_reset_thumbnail(self, path, lambda: self.list.viewport().update())
    def _unique_dest_path(self, src: Path, dest_dir: Path | None = None) -> Path:
        """Chemin de destination dans `dest_dir` (par defaut ce dossier), en
        evitant les collisions (« nom - copie », « nom - copie (2) », ...)."""
        dest_dir = dest_dir if dest_dir is not None else self.directory
        dest = dest_dir / src.name
        if not dest.exists():
            return dest
        stem, suffix = (src.stem, src.suffix) if src.is_file() else (src.name, "")
        candidate = dest_dir / f"{stem} - copie{suffix}"
        i = 2
        while candidate.exists():
            candidate = dest_dir / f"{stem} - copie ({i}){suffix}"
            i += 1
        return candidate
    def _paste_items(self):
        mime = QApplication.clipboard().mimeData()
        if not mime.hasUrls():
            return
        last_dest = None
        errors = []
        for url in mime.urls():
            src = Path(url.toLocalFile())
            if not src.exists():
                continue
            dest = self._unique_dest_path(src)
            try:
                if src.is_dir():
                    shutil.copytree(src, dest)
                else:
                    shutil.copy2(src, dest)
                last_dest = dest
            except OSError as exc:
                errors.append(f"{src.name} : {exc}")
        if errors:
            QMessageBox.warning(self, "Coller", "Impossible de coller :\n" + "\n".join(errors))
        self.refresh()
        if last_dest:
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it.data(ROLE_PATH) == str(last_dest):
                    self.list.setCurrentItem(it)
                    break
    def _rename_shortcut(self, path: Path, shown: str):
        """Change le nom AFFICHE d'un raccourci (cle `name` de .pipeline_shortcuts.json) ; le dossier
        cible n'est jamais renomme. Nom vide = retour au nom du dossier."""
        new_name, ok = QInputDialog.getText(
            self, "Renommer le raccourci", "Nom affiché :", QLineEdit.Normal, shown
        )
        if not ok:
            return
        new_name = new_name.strip()
        for source in (self._source_dirs if self._source_dirs is not None else [self.directory]):
            shortcuts = load_shortcuts(source)
            changed = False
            for sc in shortcuts:
                if sc.get("target") == str(path):
                    if new_name and new_name != path.name:
                        sc["name"] = new_name
                    else:
                        sc.pop("name", None)
                    changed = True
            if changed:
                save_shortcuts(source, shortcuts)
        self.refresh()
    def delete_path(self, path: Path) -> bool:
        """« Supprimer » : apres confirmation (settings_dialogs.confirm), le fichier / dossier va a la
        CORBEILLE ; si elle le refuse (certains disques reseau), une 2e confirmation propose de le
        supprimer definitivement. Ligne ouverte (colonnes a sa suite) : refermee d'abord, comme un
        re-clic. Retourne True si l'element a disparu."""
        from settings_dialogs import confirm
        kind = "ce dossier et tout son contenu" if path.is_dir() else "ce fichier"
        if not confirm(self, "Supprimer", path.name, f"Mettre {kind} à la corbeille ?", [str(path)], "Supprimer"):
            return False
        current = self.list.currentItem()
        win = self.window()
        if current is not None and current.data(ROLE_PATH) == str(path) and hasattr(win, "on_reclicked"):
            win.on_reclicked(self)
        if not QFile.moveToTrash(str(path)) and path.exists():
            if not confirm(self, "Supprimer", path.name,
                           "La corbeille refuse cet élément. Le supprimer DÉFINITIVEMENT (sans retour possible) ?",
                           [str(path)], "Supprimer définitivement"):
                return False
            try:
                shutil.rmtree(path) if path.is_dir() else path.unlink()
            except OSError as exc:
                QMessageBox.warning(self, "Supprimer", f"Impossible de supprimer :\n{exc}")
                return False
        self.refresh_all()
        return not path.exists()
    def _rename_item(self, path: Path):
        new_name, ok = QInputDialog.getText(
            self, "Renommer", "Nouveau nom :", QLineEdit.Normal, path.name
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == path.name:
            return
        if any(ch in new_name for ch in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Renommer", "Le nom contient des caracteres interdits.")
            return
        new_path = path.with_name(new_name)
        if new_path.exists():
            QMessageBox.warning(self, "Renommer", f"« {new_name} » existe deja.")
            return
        try:
            path.rename(new_path)
        except OSError as exc:
            QMessageBox.warning(self, "Renommer", f"Impossible de renommer :\n{exc}")
            return
        # Un raccourci pointant vers ce dossier doit suivre son nouveau nom.
        for source in (self._source_dirs if self._source_dirs is not None else [self.directory]):
            shortcuts = load_shortcuts(source)
            if any(sc.get("target") == str(path) for sc in shortcuts):
                for sc in shortcuts:
                    if sc.get("target") == str(path):
                        sc["target"] = str(new_path)
                save_shortcuts(source, shortcuts)
        self.refresh()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_PATH) == str(new_path):
                self.list.setCurrentItem(it)
                break
