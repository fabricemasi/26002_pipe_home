"""Méthodes de colonne : ordre, espaces, titres et bas de colonne."""

from pathlib import Path
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QInputDialog, QStyleOptionViewItem
from app_style import font
import ui_state
from settings_widgets import Menu
from browser_core import ROLE_SPACE_ABOVE, ROLE_SPACE_BELOW, ROLE_PIN_BOTTOM, ROLE_BOTTOM_GAP, ROLE_TITLE_ABOVE, ROLE_PATH, _update_layout_setting, load_layout_settings
from capture_widgets import item_order_key


class ColumnRowsMixin:
    def sync_uniform_sizes(self):
        """Hauteurs de ligne uniformes (optimisation Qt des colonnes a vignettes) SAUF si une ligne a
        un espace au-dessus : Qt donnerait alors a toutes la hauteur de la premiere, et l'espace
        serait pris SUR la ligne (ligne ecrasee, fond et apercu tronques)."""
        if self._async_load and getattr(self, "_rows_known_uniform", False):
            self.list.setUniformItemSizes(True)
            return
        spaced = any(int(self.list.item(i).data(ROLE_SPACE_ABOVE) or 0) or int(self.list.item(i).data(ROLE_SPACE_BELOW) or 0)
                     or self.list.item(i).data(ROLE_PIN_BOTTOM)
                     for i in range(self.list.count()))
        self.list.setUniformItemSizes(not spaced)
    # -- « Positionner au bas de la colonne » (clic droit sur une ligne) --
    # Les lignes marquees (`item_bottom` du .pipeline_layout.json, liste de cles, `item_bottom@<titre>`
    # pour une colonne a plusieurs sources) sont rangees apres les autres et empilees contre le bas :
    # un vide (ROLE_BOTTOM_GAP) pose au-dessus de la premiere comble la place libre de la colonne.

    def _bottom_key(self) -> str:
        return "item_bottom" if self._source_dirs is None else f"item_bottom@{self.column_title}"
    def _item_bottom(self, store: Path | None) -> set:
        if store is None:
            return set()
        keys = self._layout_for(store).get(self._bottom_key())
        return {str(k) for k in keys} if isinstance(keys, list) else set()
    def set_item_bottom(self, item, pinned: bool):
        """Marque (ou demarque) la ligne « au bas de la colonne », enregistre, puis reaffiche."""
        store, _key = self._order_store()
        if store is None:
            return
        key = item_order_key(store, Path(item.data(ROLE_PATH)))
        keys = [k for k in (load_layout_settings(store).get(self._bottom_key()) or []) if k != key]
        if pinned:
            keys.append(key)
        _update_layout_setting(store, self._bottom_key(), keys)
        self.refresh()
        win = self.window()
        if hasattr(win, "_columns_epoch"):
            win._columns_epoch += 1          # captures d'animation perimees : ancienne disposition
    def sync_bottom_gap(self):
        """Recalcule le vide au-dessus de la 1re ligne « au bas de la colonne » = hauteur visible de
        la liste - hauteur de toutes les lignes (jamais negatif : liste plus haute que la colonne =
        lignes simplement a la fin). Appele apres chaque refresh, redimensionnement de la liste et
        changement de hauteur de ligne."""
        if (getattr(self, "_syncing_bottom", False)
                or self._async_load and getattr(self, "_bottom_known_empty", False)):
            return
        lst = self.list
        first = None
        for row in range(lst.count()):
            if lst.item(row).data(ROLE_PIN_BOTTOM):
                first = lst.item(row)
                break
        gap = 0
        if first is not None:
            current = int(first.data(ROLE_BOTTOM_GAP) or 0)
            delegate, option, model = lst.itemDelegate(), QStyleOptionViewItem(), lst.model()
            total = sum(delegate.sizeHint(option, model.index(row, 0)).height() for row in range(lst.count()))
            gap = max(0, lst.viewport().height() - (total - current))
        changed = False
        for row in range(lst.count()):
            item = lst.item(row)
            want = gap if item is first else 0
            if int(item.data(ROLE_BOTTOM_GAP) or 0) != want:
                item.setData(ROLE_BOTTOM_GAP, want or None)
                changed = True
        if changed:
            self._syncing_bottom = True
            try:
                lst.doItemsLayout()
                lst.viewport().update()
            finally:
                self._syncing_bottom = False
    def _spaces_key(self, below: bool = False) -> str:
        name = "item_spaces_below" if below else "item_spaces"
        return name if self._source_dirs is None else f"{name}@{self.column_title}"
    def _item_spaces(self, store: Path | None, below: bool = False) -> dict:
        if store is None:
            return {}
        spaces = self._layout_for(store).get(self._spaces_key(below))
        return spaces if isinstance(spaces, dict) else {}
    def set_item_space(self, item, height: int, below: bool = False):
        """Clic droit > « Ajouter une espace au-dessus / en dessous » : espace de `height` px au-dessus
        (ou en dessous) de la ligne, en direct ; enregistre (`item_spaces` / `item_spaces_below` du
        .pipeline_layout.json, comme l'ordre) au repos."""
        store, _key = self._order_store()
        if store is None:
            return
        item.setData(ROLE_SPACE_BELOW if below else ROLE_SPACE_ABOVE, int(height))
        self.sync_uniform_sizes()
        self.list.doItemsLayout()
        self.sync_bottom_gap()
        self.list.viewport().update()
        key = item_order_key(store, Path(item.data(ROLE_PATH)))
        self._pending_spaces = getattr(self, "_pending_spaces", {})
        self._pending_spaces[(below, key)] = int(height)
        timer = getattr(self, "_space_timer", None)
        if timer is None:
            timer = self._space_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(400)
            timer.timeout.connect(self._save_item_spaces)
        timer.start()
    def _save_item_spaces(self):
        store, _key = self._order_store()
        pending, self._pending_spaces = getattr(self, "_pending_spaces", {}), {}
        if store is None or not pending:
            return
        for below in (False, True):
            changes = {key: height for (side, key), height in pending.items() if side == below}
            if not changes:
                continue
            spaces = dict(self._item_spaces(store, below))
            for key, height in changes.items():
                if height:
                    spaces[key] = height
                else:
                    spaces.pop(key, None)
            _update_layout_setting(store, self._spaces_key(below), spaces)
    # -- Titre au-dessus d'une ligne (dans son espace au-dessus) --
    # Clic droit sur la ligne > « Ajouter un titre au-dessus… » (grise si l'espace est trop petit) ;
    # clic droit sur le titre : renommer, supprimer, changer son style (fenetre flottante Police |
    # Padding, « changement de style a la volee », settings_quick_style.py). Retenu comme l'espace :
    # `item_titles` du .pipeline_layout.json.

    def _titles_key(self) -> str:
        return "item_titles" if self._source_dirs is None else f"item_titles@{self.column_title}"
    def _item_titles(self, store: Path | None) -> dict:
        if store is None:
            return {}
        titles = self._layout_for(store).get(self._titles_key())
        return titles if isinstance(titles, dict) else {}
    def _item_key(self, item) -> str | None:
        store, _key = self._order_store()
        return item_order_key(store, Path(item.data(ROLE_PATH))) if store is not None else None
    def _item_by_key(self, key: str):
        for row in range(self.list.count()):
            item = self.list.item(row)
            if self._item_key(item) == key:
                return item
        return None
    def title_area_hit(self, item, pos) -> bool:
        """Vrai si `pos` (repere du viewport) tombe sur le titre pose au-dessus de `item`."""
        if not item.data(ROLE_TITLE_ABOVE):
            return False
        top = self.list.visualItemRect(item).top() + int(item.data(ROLE_BOTTOM_GAP) or 0)
        return top <= pos.y() < top + int(item.data(ROLE_SPACE_ABOVE) or 0)
    def can_add_title(self, item) -> bool:
        from browser_core import item_title_min_height
        return (self._order_store()[0] is not None and not item.data(ROLE_TITLE_ABOVE)
                and int(item.data(ROLE_SPACE_ABOVE) or 0) >= item_title_min_height())
    def set_item_title(self, key: str, title: dict | None, save_now: bool = True):
        """Pose (ou retire, `title` None) le titre de la ligne `key`, en direct ; enregistre."""
        item = self._item_by_key(key)
        if item is not None:
            item.setData(ROLE_TITLE_ABOVE, title if title else None)
            self.list.viewport().update()
        self._pending_titles = getattr(self, "_pending_titles", {})
        self._pending_titles[key] = title
        if save_now:
            self._save_item_titles()
            return
        timer = getattr(self, "_title_timer", None)
        if timer is None:
            timer = self._title_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(400)
            timer.timeout.connect(self._save_item_titles)
        timer.start()
    def _save_item_titles(self):
        store, _key = self._order_store()
        pending, self._pending_titles = getattr(self, "_pending_titles", {}), {}
        if store is None or not pending:
            return
        titles = dict(self._item_titles(store))
        for key, title in pending.items():
            if title:
                titles[key] = title
            else:
                titles.pop(key, None)
        _update_layout_setting(store, self._titles_key(), titles)
    def _prompt_item_title(self, key: str, current: str = ""):
        text, ok = QInputDialog.getText(self, "Titre" if not current else "Renommer le titre",
                                        "Titre :", text=current)
        if not ok or not text.strip():
            return
        item = self._item_by_key(key)
        title = dict(item.data(ROLE_TITLE_ABOVE) or {}) if item is not None else {}
        title["text"] = text.strip()
        title.setdefault("style", {})
        self.set_item_title(key, title)
    def _open_title_style(self, key: str):
        """« Changement de style a la volee » (settings_quick_style) : Police | Padding, en direct."""
        from browser_core import item_title_style
        from settings_quick_style import QuickStyleWindow, font_padding_specs
        item = self._item_by_key(key)
        if item is None or not item.data(ROLE_TITLE_ABOVE):
            return
        title = dict(item.data(ROLE_TITLE_ABOVE))
        # Une seule a la fois. La fenetre se detruit a sa fermeture (WA_DeleteOnClose) : la reference
        # est oubliee a ce moment (destroyed), sinon fermer l'ancienne levait une erreur et la 2e
        # ouverture n'aboutissait jamais.
        previous, self._title_style_window = getattr(self, "_title_style_window", None), None
        if previous is not None:
            try:
                previous.close()
            except RuntimeError:              # deja detruite
                pass

        def on_style(style: dict, key=key):
            current = self._item_by_key(key)
            if current is None or not current.data(ROLE_TITLE_ABOVE):
                return
            updated = dict(current.data(ROLE_TITLE_ABOVE))
            updated["style"] = style
            self.set_item_title(key, updated, save_now=False)

        window = self._title_style_window = QuickStyleWindow(
            "Titre de ligne", font_padding_specs("title", color_default="#9aa1a7", color_title="Couleur du titre"),
            item_title_style(title.get("style")), title=f"Style du titre « {title.get('text', '')} »",
            settings=ui_state.APPLIED_SETTINGS or None, parent=self.window())
        window.styleChanged.connect(on_style)
        window.destroyed.connect(lambda *_a, w=window: self._forget_title_style_window(w))
        window.move(QCursor.pos() + QPoint(12, 12))
        window.show()
    def _forget_title_style_window(self, window):
        if getattr(self, "_title_style_window", None) is window:
            self._title_style_window = None
    def _title_menu(self, item, pos):
        """Clic droit sur le titre d'une ligne : renommer / supprimer / changer son style."""
        key = self._item_key(item)
        if key is None:
            return
        menu = Menu(self)
        menu.setFont(font(11, 400))
        act_rename = menu.addAction("Renommer le titre…")
        act_delete = menu.addAction("Supprimer le titre")
        act_style = menu.addAction("Changer le style…")
        chosen = menu.exec(self.list.mapToGlobal(pos))
        text = (item.data(ROLE_TITLE_ABOVE) or {}).get("text", "")
        if chosen is act_rename:
            QTimer.singleShot(0, lambda: self._prompt_item_title(key, text))   # apres le relachement du clic
        elif chosen is act_delete:
            self.set_item_title(key, None)
        elif chosen is act_style:
            QTimer.singleShot(0, lambda: self._open_title_style(key))
    def save_item_order(self, paths: list[Path]):
        """Enregistre l'ordre des elements (glisser dans la colonne, voir FileListWidget) dans
        le .pipeline_layout.json du dossier, puis reaffiche la colonne (ligne courante conservee)."""
        store, key = self._order_store()
        if store is None:
            return
        _update_layout_setting(store, key, [item_order_key(store, p) for p in paths])
        self.refresh()
        win = self.window()
        if hasattr(win, "_columns_epoch"):
            win._columns_epoch += 1          # captures d'animation (masquer/replier) perimees : ancien ordre
