"""
Rendu de tableaux alignés pour WhatsApp.

WhatsApp ne sait pas afficher de vraies cellules colorées (aucune
messagerie ne le permet dans un simple message texte) — mais un bloc
encadré de trois apostrophes inverses (```) force un affichage en
police à chasse fixe, ce qui permet de vrais alignements de colonnes.
Pour le signal "feu tricolore", on utilise des émojis (🔴🟡🟢) en
préfixe de ligne : c'est l'équivalent le plus proche d'une vraie
couleur de cellule que la plateforme autorise.
"""


def render_table(headers: list[str], rows: list[list[str]], right_align: set[int] | None = None) -> str:
    """
    headers : libellés de colonnes.
    rows : chaque ligne est une liste de chaînes, dans le même ordre
        que headers. Une ligne peut avoir plus de colonnes que headers
        si un préfixe (ex. émoji feu tricolore) est ajouté séparément
        par l'appelant — dans ce cas, préférer placer le préfixe DANS
        la première cellule plutôt qu'en colonne à part, pour ne pas
        fausser le calcul de largeur.
    right_align : indices de colonnes à aligner à droite (montants,
        nombres). Les autres colonnes sont alignées à gauche.
    """
    right_align = right_align or set()
    largeurs = []
    for i, entete in enumerate(headers):
        largeur = len(entete)
        for row in rows:
            if i < len(row):
                largeur = max(largeur, len(row[i]))
        largeurs.append(largeur)

    def _format_row(cells: list[str]) -> str:
        parts = []
        for i, cell in enumerate(cells):
            largeur = largeurs[i] if i < len(largeurs) else len(cell)
            if i in right_align:
                parts.append(f"{cell:>{largeur}}")
            else:
                parts.append(f"{cell:<{largeur}}")
        return " ".join(parts).rstrip()

    lignes = [_format_row(headers)]
    lignes.append("-" * len(lignes[0]))
    for row in rows:
        lignes.append(_format_row(row))

    return "```\n" + "\n".join(lignes) + "\n```"
