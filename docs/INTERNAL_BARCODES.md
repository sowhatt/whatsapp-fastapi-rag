# Codes-barres internes Whatzabi Shop

Depuis la liste Stock / Produits, cliquer sur « Code-barres / étiquettes ».
La première ouverture génère et conserve le code. Les suivantes réutilisent
le même code et permettent la réimpression. Choisir de 1 à 200 étiquettes.

Identité : `WZ` suivi de l'identifiant produit sur 12 chiffres, encodé en
Code 128. Le code tient dans la colonne existante `product_barcodes.barcode`
de 14 caractères. Aucun changement de schéma ni table supplémentaire.
Les identifiants produit étant globaux dans cette base, les codes générés
sont uniques dans cette instance Whatzabi. Ce ne sont pas des références GS1.

Le code fabricant est conservé en parallèle. Prix et stock ne sont pas
encodés dans le symbole ; la vente consulte les données actuelles de la
boutique active. Générer et imprimer ne modifie aucun stock.

Formats PDF : A4 avec 18 emplacements de 58 × 40 mm par page, ou une page
thermique de 58 × 40 mm par étiquette. Les étiquettes portent le nom et le
code, sans prix. Imprimer à 100 % sans ajustement. La compatibilité avec
une imprimante physique doit être vérifiée sur le matériel pilote.

## API

- `POST /pwa/catalog/products/{product_id}/internal-barcode` : génération
  idempotente, nom, code et aperçu SVG ; permission `product.update`.
- `GET /pwa/catalog/products/{product_id}/internal-barcode/labels.pdf` :
  réimpression d'un code existant ; `copies=1..200`, `layout=a4|thermal` ;
  permission `product.read`.
- Les recherches catalogue et vente acceptent les codes WZ et les anciens
  codes numériques. Un code WZ inconnu renvoie 404 sans référentiel externe.
- L'association manuelle d'un code WZ est refusée. Les codes internes ne
  sont pas publiés dans le référentiel mutualisé.

Les routes réutilisent l'authentification PWA et exigent une boutique active.
Les produits sont explicitement filtrés par commerçant. La génération
verrouille la ligne produit avec `SELECT FOR UPDATE` sur PostgreSQL pour
sérialiser les demandes simultanées du même produit.

## Vérification

```bash
python -m pip install -r requirements-barcode-tests.txt
DATABASE_URL=sqlite:// python -m pytest tests/test_internal_barcodes.py tests/test_smart_catalog_service.py -q
node --check app/pwa/internal-barcode.js
node --check app/pwa/smart-catalog.js
node --check app/pwa/app.js
node --check app/pwa/sw.js
```

25 tests passent : authentification, permissions, isolation commerçant,
absence de boutique, génération répétée, conservation des stocks et du
code fabricant, prix courant, stock par boutique, contrôle des entrées et
bornes d'impression. Les PDF A4 et thermiques sont rendus puis décodés
avec ZXing. Les tests HTTP montent les routeurs catalogue et vente avec
la véritable dépendance d'authentification, dans une application de test.

Limites de validation : aucune concurrence PostgreSQL ni imprimante réelle
n'a été testée ici ; l'application complète n'a pas été lancée sur Railway.

## Intégration

Cette proposition part du commit `f72a9f8088aeaf9b74804944e8a3d0100e6bf5c7`
de `feat/cart-negotiated-price` (10 octobre 2026). Vérifier les éventuelles
modifications locales plus récentes avant intégration. Installer les
dépendances puis tester sur un environnement de staging isolé.
Le service worker et les versions des scripts sont mis à jour.
La proposition n'a pas été déployée et ne modifie pas Whatzabi Online.
