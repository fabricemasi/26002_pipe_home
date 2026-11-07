"""File des points du curseur entre les ÉVÈNEMENTS et le moteur de trait (SANS Qt).

Problème mesuré (page 2480 x 3508 au zoom d'ajustement, 25 %) : la main parcourt 4 fois plus de pixels de document par
seconde qu'à 100 %, et le moteur coûte ~0,4 ms par tampon (24 px) à ~15 ms (300 px doux). Appelé directement dans
le gestionnaire de souris, il retardait chaque évènement : le cercle de brosse avait 70 ms de retard médian (150 ms au
P95), jusqu'à 250 ms avec une brosse de 300 px, et sautait par saccades.

Ici, chaque évènement ne fait que déposer son point dans la file ; le moteur travaille ensuite PAR TRANCHES DE TEMPS
(`run(feed, budget_ms)`), le cercle étant repeint entre deux tranches. Garanties :
- charge légère : tout passe dans la première tranche, point par point, comme avant (mêmes appels, même ordre) ;
- charge lourde : un long segment est coupé en sous-segments RECTILIGNES (pression et horodatage interpolés linéairement),
  les tampons restent sur la même droite avec le même pas ; le trait suit le curseur avec un léger retard au lieu de le
  retarder ; rien n'est jamais perdu ni sauté ;
- `run(feed, None)` vide toute la file (relâchement, annulation) ;
- le coût est mesuré (ms par pixel de chemin, moyenne glissante) : aucun réglage à la main."""
from __future__ import annotations

import math
import time
from collections import deque

MIN_SPLIT_PX = 2.0          # un segment plus court n'est jamais coupé
MIN_SLICE_MS = 0.8          # temps restant en dessous duquel on rend la main (au moins un pas par tranche)
SMOOTHING = 0.3             # poids de la dernière mesure dans le coût glissant


class StrokeFeed:
    def __init__(self, clock=time.perf_counter):
        self.clock = clock
        self.queue: deque = deque()
        self.fed = None                     # dernier point donné au moteur : (x, y, pression, t)
        self.px_ms = 0.0                    # coût mesuré du moteur, ms par pixel de chemin (0 = pas encore mesuré)
        self.splits = 0                     # (tests, mesures) sous-segments créés

    # -- état --
    def start(self, x, y, pressure, t=None):
        self.queue.clear()
        self.fed = (float(x), float(y), float(pressure), t)
        self.px_ms = 0.0

    def clear(self):
        self.queue.clear()

    def pending(self) -> bool:
        return bool(self.queue)

    def push(self, x, y, pressure, t=None):
        self.queue.append((float(x), float(y), float(pressure), t))

    def note(self, x, y, pressure, t=None):
        """Un point donné au moteur sans passer par la file (mode direct) : la prochaine coupe part de là."""
        self.fed = (float(x), float(y), float(pressure), t)

    def lag_ms(self) -> float:
        """Travail estimé de ce qui reste dans la file (retard du trait sur le curseur)."""
        if self.fed is None or not self.queue or self.px_ms <= 0.0:
            return 0.0
        x0, y0 = self.fed[0], self.fed[1]
        total = 0.0
        for x, y, _p, _t in self.queue:
            total += math.hypot(x - x0, y - y0)
            x0, y0 = x, y
        return total * self.px_ms

    # -- travail --
    def run(self, feed, budget_ms) -> bool:
        """Donne des points au moteur (`feed(x, y, pression, t)`) pendant `budget_ms` (None = tout). Rend True quand la file
        est vide. Au moins un pas est fait à chaque appel, même avec un budget minuscule."""
        deadline = None if budget_ms is None else self.clock() + budget_ms / 1000.0
        stepped = False
        while self.queue:
            x, y, p, t = self.queue[0]
            fx, fy, fp, ft = self.fed
            dist = math.hypot(x - fx, y - fy)
            whole = True
            f = 1.0
            if deadline is not None and self.px_ms > 0.0 and dist >= MIN_SPLIT_PX:
                left = (deadline - self.clock()) * 1000.0
                if stepped and left < MIN_SLICE_MS:
                    break
                cost = dist * self.px_ms
                if cost > left:
                    whole = False
                    f = max(min(left / cost, 0.95), MIN_SPLIT_PX / dist)
            elif stepped and deadline is not None and self.clock() >= deadline:
                break
            if whole:
                self.queue.popleft()
                point = (x, y, p, t)
            else:
                self.splits += 1
                tt = t if (t is None or ft is None) else ft + (t - ft) * f
                point = (fx + (x - fx) * f, fy + (y - fy) * f, fp + (p - fp) * f, tt)
            started = self.clock()
            feed(*point)
            spent = (self.clock() - started) * 1000.0
            self.fed = point
            stepped = True
            walked = math.hypot(point[0] - fx, point[1] - fy)
            if walked >= MIN_SPLIT_PX:
                sample = spent / walked
                self.px_ms = sample if self.px_ms <= 0.0 else self.px_ms + (sample - self.px_ms) * SMOOTHING
            if deadline is not None and self.clock() >= deadline:
                break
        return not self.queue
