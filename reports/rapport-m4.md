# Rapport — Lab 4 : packaging du modèle

Binôme : Zeyneb Takrouni · Dataset : german-credit · Modèle : `scoring-model` v9

## 1. Comparatif des tailles

| Image | Taille | CVE HIGH + CRITICAL |
|---|---|---|
| `scoring-api:naive` | 2,18 Go | 473 (457 HIGH, 16 CRITICAL) |
| `scoring-api:optimized` | 429 Mo | 46 (46 HIGH, 0 CRITICAL) |
| `scoring-api:bentoml` | 1,41 Go | 124 (123 HIGH, 1 CRITICAL) |

Les tailles sont celles affichées par `docker images` sur ma machine ; elles sont plus
élevées que les ordres de grandeur de l'énoncé (la base `python` et les dépendances ont
grossi), mais le classement est le même. Une première version de `optimized` faisait
535 Mo, au-dessus du seuil de 500 Mo : en supprimant dans le stage builder les dossiers
`tests` de numpy et pandas ainsi que les `__pycache__`, elle est passée à 429 Mo, sans
changer les prédictions (même probabilité avant et après).

## 2. Comparatif des latences

1000 appels par backend après 10 appels de chauffe, x86_64, Python 3.12.15, modèle v9.

| Backend | P50 (ms) | P95 (ms) | P99 (ms) |
|---|---|---|---|
| sklearn_pipeline | 7.588 | 10.845 | 14.008 |
| onnx_python | 0.108 | 0.248 | 0.378 |
| onnx_batch_100 | 0.517 | 0.890 | 1.311 |

Accélération ONNX vs scikit-learn (P50, 1 ligne) : x70,4. Une première exécution, faite
sur une machine moins chargée, donnait 3,5 ms contre 0,06 ms (x57,8) : les valeurs
absolues varient avec la charge de la machine, le rapport reste de l'ordre de x50 à x70.

## 3. Interprétation

- **Pourquoi l'image optimisée est-elle plus petite ?** Elle part de `python:3.12-slim`
  (sans compilateurs ni outils Debian inutiles) au lieu de `python:3.12`. Le build est
  multi-stage : les dépendances sont installées dans un stage builder, et seul le dossier
  `/deps` est copié dans l'image finale. Elle n'embarque que le serveur FastAPI,
  ONNX Runtime, numpy, pandas et pyyaml, sans MLflow, scikit-learn ni skl2onnx. Une
  liste blanche `.dockerignore` limite le contexte de build aux fichiers nécessaires,
  donc ni `.git`, ni `data/`, ni `.env`. Les dossiers de tests et les caches Python sont
  supprimés. L'image naïve copie tout le dépôt (`COPY . /app`), y compris le `.env`
  avec les identifiants S3, et tourne en root.
- **Pourquoi ONNX est-il plus rapide que scikit-learn ?** Pour une seule ligne, le temps
  du pipeline scikit-learn est dominé par son surcoût fixe : validation du DataFrame,
  sélection des colonnes par leur nom, un appel Python par transformateur. ONNX Runtime
  exécute un graphe déjà compilé, prétraitement compris, en code natif. Le mode par lot
  (100 lignes en 0,5 ms) montre que le coût par ligne devient très faible.
- **Que montrent les scans ?** Trivy : l'image `optimized` (base slim) a environ dix fois
  moins de CVE que la `naive` et aucune CRITICAL, alors que `bentoml` en a 124 dont une
  CRITICAL, parce qu'elle embarque davantage de paquets (BentoML, scikit-learn, SciPy,
  compilateurs installés au build). Réduire la surface de l'image réduit le nombre de
  vulnérabilités. ModelScan : le modèle ONNX ne donne aucun problème, mais le fichier
  n'est pas analysé (format non pris en charge) ; il est sûr par construction, puisque
  c'est un graphe protobuf déclaratif sans code exécutable. Sur le pickle piégé,
  ModelScan détecte l'appel à `os.system` (1 problème CRITICAL), alors que le pickle
  sain passe : l'outil repère les appels dangereux, il ne juge pas le modèle.

## 4. Choix recommandé

Je retiens `scoring-api:optimized` (publiée sur `localhost:5001/scoring-api:1.0.0`).
C'est la plus petite (429 Mo, sous l'objectif de 500 Mo), celle qui a le moins de CVE et
aucune CRITICAL, la plus rapide (inférence ONNX, de l'ordre de 0,1 ms par ligne), et la
seule dont le contenu est maîtrisé : utilisateur non-root à UID fixe, healthcheck, labels
reliant l'image à la version du modèle dans le Registry, aucun secret embarqué. Le modèle
est figé dans l'image, donc une image correspond à une version et le rollback consiste à
redéployer l'image précédente. La variante BentoML offre un cadre de service
complet, mais elle est plus lourde (1,41 Go), a plus de CVE dont une CRITICAL, exécute un
pipeline scikit-learn plus lent et renvoie 400 au lieu de 422 sur une requête invalide,
ce qui change le contrat d'API que les labs suivants supposent stable.

## 5. Pistes d'amélioration

- Utiliser une image distroless (ou `python:3.12-slim` avec moins de paquets) pour réduire
  encore la surface d'attaque et le nombre de CVE de la couche système.
- Quantization INT8 : gain de taille et de latence probable sur un gros modèle (forêt,
  réseau), peu utile ici pour une régression logistique de quelques ko.
- Précharger le modèle dans un Init Container, et épingler les images de base par digest
  pour des builds reproductibles.
- Alléger les dépendances : retirer les extras de `uvicorn[standard]` non utilisés et
  remplacer pandas, qui n'est utilisé que pour lire `dataset.yaml` et les données.
- Automatiser en CI/CD (Module 6) : reconstruction à chaque nouveau modèle, scan Trivy
  avec seuil d'échec sur les CVE CRITICAL, et lancement de `make check-m4`.
- Ajouter plusieurs workers uvicorn (ou l'autoscaling du Lab 5) : la latence sous charge
  vient de la file d'attente d'un seul worker, pas du modèle.
