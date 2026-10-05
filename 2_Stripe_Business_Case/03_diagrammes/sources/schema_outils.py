"""
Outils de dessin des diagrammes - Stripe Business Case

Production de schémas SVG à placement manuel (grille), convertis en PNG haute résolution.
Charte : bleu marine (#1F3864) et bleus, police Calibri (Carlito, métriquement identique, à défaut),
contrastes conformes aux recommandations d'accessibilité (texte foncé sur fond clair, texte blanc sur
bleu marine).
"""

from xml.sax.saxutils import escape

import cairosvg

BLEU_MARINE = "#1F3864"
BLEU = "#2E75B6"
BLEU_CLAIR = "#DEEBF7"
BLEU_TRES_CLAIR = "#F4F8FC"
GRIS = "#595959"
GRIS_CLAIR = "#F2F2F2"
POLICE = "Calibri, Carlito, sans-serif"

# Couleurs par couche de l'architecture : (bandeau et bordure, fond du bloc, libellé de légende).
# Bandeaux foncés (texte blanc) et fonds clairs (texte foncé) : contrastes suffisants pour la lecture ;
# la couleur n'est jamais le seul repère, chaque bloc portant aussi son domaine écrit en toutes lettres.
COUCHES = {
    "oltp": ("#1F3864", "#DEEBF7", "Base transactionnelle (OLTP)"),
    "olap": ("#375623", "#E2EFDA", "Entrepôt analytique (OLAP)"),
    "nosql": ("#0E6B6B", "#DDF0EF", "Base NoSQL"),
    "flux": ("#C55A11", "#FBE5D6", "Flux temps réel"),
    "ia": ("#7030A0", "#EADCF4", "Intelligence artificielle"),
    "gouvernance": ("#44546A", "#E7EAF0", "Gouvernance et exploitation"),
    "contexte": ("#595959", "#F2F2F2", "Source et utilisateurs"),
}


class Schema:
    def __init__(self, largeur, hauteur, titre, sous_titre=None):
        self.largeur, self.hauteur = largeur, hauteur
        self.fond, self.dessus = [], []
        self.elements = [
            f'<rect x="0" y="0" width="{largeur}" height="{hauteur}" fill="white"/>',
            self._texte(largeur / 2, 48, titre, 30, BLEU_MARINE, gras=True),
        ]
        if sous_titre:
            self.elements.append(self._texte(largeur / 2, 80, sous_titre, 16, GRIS))

    @staticmethod
    def _texte(x, y, texte, taille, couleur, gras=False, ancre="middle", italique=False):
        style = (' font-weight="bold"' if gras else "") + (' font-style="italic"' if italique else "")
        return (f'<text x="{x}" y="{y}" font-family="{POLICE}" font-size="{taille}" fill="{couleur}" '
                f'text-anchor="{ancre}"{style}>{escape(texte)}</text>')

    def zone(self, x, y, l, h, titre):
        """Cadre de regroupement en arrière-plan."""
        self.fond.append(f'<rect x="{x}" y="{y}" width="{l}" height="{h}" rx="14" fill="{GRIS_CLAIR}" '
                         f'stroke="#BFBFBF" stroke-width="1.2" stroke-dasharray="6,4"/>')
        self.fond.append(self._texte(x + 14, y + 24, titre, 15, GRIS, gras=True, ancre="start"))

    def boite(self, x, y, l, h, domaine, titre, lignes=(), couche="oltp"):
        """Bloc à en-tête : domaine (bandeau à la couleur de la couche), titre en gras, lignes de détail."""
        foncee, fond, _ = COUCHES[couche]
        self.elements += [
            f'<rect x="{x}" y="{y}" width="{l}" height="{h}" rx="10" fill="{fond}" stroke="{foncee}" stroke-width="1.8"/>',
            f'<path d="M{x},{y + 26} V{y + 10} Q{x},{y} {x + 10},{y} H{x + l - 10} Q{x + l},{y} {x + l},{y + 10} V{y + 26} Z" fill="{foncee}"/>',
            self._texte(x + l / 2, y + 18, domaine.upper(), 11.5, "white", gras=True),
            self._texte(x + l / 2, y + 50, titre, 17, foncee, gras=True),
        ]
        for i, ligne in enumerate(lignes):
            self.elements.append(self._texte(x + l / 2, y + 72 + i * 18, ligne, 13.5, "#262626"))
        return {"x": x, "y": y, "l": l, "h": h, "cx": x + l / 2, "cy": y + h / 2,
                "haut": y, "bas": y + h, "gauche": x, "droite": x + l}

    def fleche(self, points, libelle=None, position=None, style="donnees", ancre="middle"):
        """Flèche orthogonale passant par une liste de points ; libellé sur fond blanc."""
        couleur, pointilles, epaisseur = {
            "donnees": (BLEU_MARINE, "", 2.0),
            "pilotage": (BLEU, ' stroke-dasharray="9,6"', 2.0),
            "supervision": (GRIS, ' stroke-dasharray="2,5"', 2.0),
            "retour": (BLEU_MARINE, "", 3.2),
        }[style]
        marqueur = f"pointe_{style}"
        chemin = " ".join(f"{'M' if i == 0 else 'L'}{x},{y}" for i, (x, y) in enumerate(points))
        self.dessus.append(f'<path d="{chemin}" fill="none" stroke="{couleur}" stroke-width="{epaisseur}"{pointilles} '
                           f'stroke-linejoin="round" marker-end="url(#{marqueur})"/>')
        if libelle:
            lx, ly = position
            lignes = libelle.split("\n")
            largeur = max(len(l) for l in lignes) * 6.6 + 12
            hauteur = len(lignes) * 16 + 6
            rx = lx - largeur / 2 if ancre == "middle" else (lx - 6 if ancre == "start" else lx - largeur + 6)
            self.dessus.append(f'<rect x="{rx}" y="{ly - 14}" width="{largeur}" height="{hauteur}" rx="4" fill="white" fill-opacity="0.95"/>')
            for i, ligne in enumerate(lignes):
                self.dessus.append(self._texte(lx, ly + i * 16, ligne, 13, couleur, ancre=ancre, italique=(style != "donnees" and style != "retour")))

    def legende(self, x, y, entrees):
        self.elements.append(self._texte(x, y, "Légende", 15, BLEU_MARINE, gras=True, ancre="start"))
        for i, (style, texte) in enumerate(entrees):
            yy = y + 28 + i * 26
            self.fleche([(x, yy), (x + 60, yy)], style=style)
            self.elements.append(self._texte(x + 74, yy + 5, texte, 13.5, "#262626", ancre="start"))

    def table(self, x, y, l, nom, categorie, colonnes, couche="olap", fond=None, hauteur_ligne=22):
        """Table : bandeau (catégorie et nom), puis une ligne par colonne (clé, nom, type, note éventuelle).
        Retourne la géométrie et l'ordonnée du centre de chaque ligne, pour attacher les relations."""
        foncee, fond_defaut, _ = COUCHES[couche]
        fond = fond or fond_defaut
        h = 44 + len(colonnes) * hauteur_ligne + 8
        self.elements += [
            f'<rect x="{x}" y="{y}" width="{l}" height="{h}" rx="6" fill="{fond}" stroke="{foncee}" stroke-width="1.8"/>',
            f'<path d="M{x},{y + 44} V{y + 6} Q{x},{y} {x + 6},{y} H{x + l - 6} Q{x + l},{y} {x + l},{y + 6} V{y + 44} Z" fill="{foncee}"/>',
            self._texte(x + l / 2, y + 16, categorie.upper(), 10.5, "white", gras=True),
            self._texte(x + l / 2, y + 36, nom, 16, "white", gras=True),
        ]
        lignes = {}
        for i, colonne in enumerate(colonnes):
            cle, nom_col, type_col = colonne[:3]
            note = colonne[3] if len(colonne) > 3 else None
            yy = y + 44 + 4 + i * hauteur_ligne + hauteur_ligne / 2
            lignes[nom_col] = yy
            if cle:
                self.elements.append(self._texte(x + 10, yy + 4.5, cle, 11.5, foncee, gras=True, ancre="start"))
            retrait = len(nom_col) - len(nom_col.lstrip(" "))
            self.elements.append(self._texte(x + 48 + retrait * 7, yy + 4.5, nom_col.lstrip(" "), 13, "#262626",
                                             gras=("PK" in cle or cle == "_id"), ancre="start"))
            self.elements.append(self._texte(x + l - 10, yy + 4.5, note or type_col, 11.5, "#C55A11" if note else GRIS,
                                             ancre="end", italique=bool(note)))
        return {"x": x, "y": y, "l": l, "h": h, "cx": x + l / 2, "cy": y + h / 2, "haut": y, "bas": y + h,
                "gauche": x, "droite": x + l, "lignes": lignes}

    def relation(self, points, couleur):
        """Relation un à plusieurs : patte de corbeau au départ (côté plusieurs), double trait à l'arrivée (côté un)."""
        chemin = " ".join(f"{'M' if i == 0 else 'L'}{x},{y}" for i, (x, y) in enumerate(points))
        self.dessus.append(f'<path d="{chemin}" fill="none" stroke="{couleur}" stroke-width="1.8" stroke-linejoin="round" '
                           f'marker-start="url(#plusieurs)" marker-end="url(#un)"/>')

    def note(self, x, y, l, titre, lignes, couleur=BLEU_MARINE):
        h = 34 + len(lignes) * 19 + 8
        self.elements.append(f'<rect x="{x}" y="{y}" width="{l}" height="{h}" rx="8" fill="{GRIS_CLAIR}" stroke="#7F7F7F" stroke-width="1.2"/>')
        self.elements.append(self._texte(x + 12, y + 22, titre, 14.5, couleur, gras=True, ancre="start"))
        for i, ligne in enumerate(lignes):
            retrait = len(ligne) - len(ligne.lstrip(" "))
            self.elements.append(self._texte(x + 12 + retrait * 7, y + 44 + i * 19, ligne.lstrip(" "), 12.5, "#262626", ancre="start"))
        return {"x": x, "y": y, "l": l, "h": h, "bas": y + h}

    def tache(self, x, y, l, h, nom, detail=None, couche="gouvernance"):
        """Petite étape (tâche d'une chaîne de traitement) : nom en gras, précision facultative."""
        foncee, fond, _ = COUCHES[couche]
        self.elements.append(f'<rect x="{x}" y="{y}" width="{l}" height="{h}" rx="8" fill="{fond}" stroke="{foncee}" stroke-width="1.5"/>')
        if detail:
            self.elements.append(self._texte(x + l / 2, y + h / 2 - 3, nom, 13, foncee, gras=True))
            self.elements.append(self._texte(x + l / 2, y + h / 2 + 14, detail, 11.5, "#404040"))
        else:
            self.elements.append(self._texte(x + l / 2, y + h / 2 + 5, nom, 13, foncee, gras=True))
        return {"x": x, "y": y, "l": l, "h": h, "cx": x + l / 2, "cy": y + h / 2, "haut": y, "bas": y + h,
                "gauche": x, "droite": x + l}

    def section(self, x, y, texte):
        self.elements.append(self._texte(x, y, texte, 20, BLEU_MARINE, gras=True, ancre="start"))
        self.elements.append(f'<line x1="{x}" y1="{y + 8}" x2="{self.largeur - x}" y2="{y + 8}" stroke="{BLEU_MARINE}" stroke-width="1.2"/>')

    def legende_couches(self, x, y, couches):
        self.elements.append(self._texte(x, y, "Couches de l'architecture", 15, BLEU_MARINE, gras=True, ancre="start"))
        for i, couche in enumerate(couches):
            foncee, fond, libelle = COUCHES[couche]
            yy = y + 16 + i * 26
            self.elements.append(f'<rect x="{x}" y="{yy}" width="36" height="18" rx="4" fill="{fond}" stroke="{foncee}" stroke-width="1.8"/>')
            self.elements.append(f'<rect x="{x}" y="{yy}" width="36" height="6" rx="2" fill="{foncee}"/>')
            self.elements.append(self._texte(x + 48, yy + 14, libelle, 13.5, "#262626", ancre="start"))

    def svg(self):
        marqueurs = "".join(
            f'<marker id="pointe_{nom}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="{t}" markerHeight="{t}" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
            for nom, c, t in [("donnees", BLEU_MARINE, 7), ("pilotage", BLEU, 7), ("supervision", GRIS, 7), ("retour", BLEU_MARINE, 5.5)])
        # Cardinalités : patte de corbeau (plusieurs) et double trait (un), dessinées dans le sens du trait
        marqueurs += ('<marker id="plusieurs" viewBox="0 0 16 16" refX="0" refY="8" markerWidth="16" markerHeight="16" '
                      'markerUnits="userSpaceOnUse" orient="auto"><path d="M0,1 L15,8 M0,8 L15,8 M0,15 L15,8" '
                      'stroke="#262626" stroke-width="1.6" fill="none"/></marker>'
                      '<marker id="un" viewBox="0 0 16 16" refX="15" refY="8" markerWidth="16" markerHeight="16" '
                      'markerUnits="userSpaceOnUse" orient="auto"><path d="M7,1 L7,15 M11,1 L11,15" stroke="#262626" '
                      'stroke-width="1.6" fill="none"/></marker>')
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.largeur}" height="{self.hauteur}" '
                f'viewBox="0 0 {self.largeur} {self.hauteur}"><defs>{marqueurs}</defs>'
                + "".join(self.fond + self.elements + self.dessus) + "</svg>")

    def enregistrer(self, chemin_sans_extension, echelle=2):
        contenu = self.svg()
        with open(chemin_sans_extension + ".svg", "w", encoding="utf-8") as fichier:
            fichier.write(contenu)
        cairosvg.svg2png(bytestring=contenu.encode("utf-8"), write_to=chemin_sans_extension + ".png", scale=echelle)
