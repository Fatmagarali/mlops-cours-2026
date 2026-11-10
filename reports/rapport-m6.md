# Rapport Lab 6 : CI/CD/CT de bout en bout

**Étudiante** : Fatma Garali (ITBS) · **Binôme** : Zeyneb Takrouni · **Dépôt** : Fatmagarali/mlops-cours-2026
**Dataset** : german-credit (7 variables numériques, 13 catégorielles) · **Date de la démo** : 10/11/2026

Le Lab 6 relie trois chaînes qui ne communiquent que par Git : la CI (GitHub Actions), le CD (Argo CD) et le CT (ré-entraînement continu déclenché par une dérive). Une dérive détectée aboutit à un nouveau modèle en production sans commande manuelle.

## 1. Architecture

Schéma des composants :

    CI   git push ──► GitHub Actions : ruff, pytest, build, test de fumée
                         ├─► GHCR : ghcr.io/fatmagarali/mlops-cours-2026/scoring-api:2.1.N
                         └─► commit k8s/overlays/staging (nouveau tag)
    CD   Argo CD lit k8s/overlays/* toutes les 60 s et applique :
                         staging -> namespace scoring-staging (scale-to-zero)
                         prod    -> namespace scoring (canary KServe)
    CT   Evidently ──► webhook (poste) ──► KFP ct-pipeline ──► @champion (MLflow)
                         └─► bot GitOps : commit du modèle ──► CI ──► staging ──► canary prod

Qui pousse, qui tire :

| Flèche | Qui pousse / qui tire | Mécanisme |
|---|---|---|
| Poste → GitHub | Je pousse une branche, la PR est relue par ma binôme | `git push`, PR, fusion sur `main` |
| GitHub → Actions | GitHub déclenche la CI | Événement push / pull_request (filtre `paths`) |
| Actions → GHCR | La CI pousse l'image testée | `GITHUB_TOKEN` (`packages: write`) |
| Actions → Git | La CI pousse le commit du tag de staging | `GITHUB_TOKEN` (`contents: write`), job `deploy-staging` |
| Git → Argo CD | Argo CD tire Git | Interrogation toutes les 60 s (pas de webhook : GitHub ne voit pas mon cluster kind) |
| Argo CD → cluster | Argo CD applique les overlays | `prune` et `selfHeal` activés |
| GHCR → nœuds kind | Les nœuds tirent l'image | Package public (aucun secret) |
| Evidently → MLflow | Le script `detect` pousse le rapport et le lot récent | Expérience `scoring-drift` |
| `detect` → webhook | Le script pousse l'événement de dérive | POST avec jeton Bearer, serveur sur 127.0.0.1 |
| Webhook → KFP | Le webhook soumet le run `ct-pipeline` | API KFP via port-forward (8080) |
| Pods KFP ↔ MLflow | Les pods tirent le lot (`runs:/…`) et poussent le modèle et les alias | Le serveur MLflow fait proxy des artefacts |
| Webhook → Git | Le bot exporte `@champion`, commite le modèle, puis décide du canary | `pipelines/gitops.py` (`release`) |

La CI ne touche jamais au cluster, et le pipeline CT non plus : tout changement de production est un commit dans Git, ce qui donne un historique (`git log -- k8s/overlays/prod`) et permet un retour arrière.

## 2. Temps du cycle

Cycle de la démo automatique (étape 9), du déclenchement à la production à 100 % (heure de Tunis ; les commits du bot sont en UTC, converti ici) :

| Étape | Heure | Durée de l'étape |
|---|---|---|
| Détection de la dérive et envoi au webhook (`detect`) | 22:30:23 | |
| Run KFP `ct-pipeline` (7 étapes) et promotion par la gate | jusqu'à 22:34:22 | 3 min 59 s |
| Commit du modèle v11 par le bot | 22:34:22 | |
| CI GitHub (tests, image, test de fumée, push GHCR) et commit du tag de staging | 22:36:06 | 1 min 44 s |
| Déploiement de staging par Argo CD, vérification `/version` et prédiction, commit du canary 10 % | 22:37:42 | 1 min 36 s |
| Déploiement du canary, analyse de 50 prédictions, commit de la promotion à 100 % | 22:38:50 | 1 min 08 s |

- Du commit du modèle à la production à 100 % : **4 min 28 s**.
- Cycle total de la dérive à la production : **8 min 27 s**.
- Les deux plus longs postes sont le run KFP et la CI. Avec un vrai modèle (plus gros que 11 ko), l'entraînement et le chargement de l'image dominent.

Pour comparaison, le déploiement manuel de l'étape 8 (modèle v10, image 2.1.9) : canary 10 % à 22:21:43 puis promotion à 22:23:48, soit 2 min 05 s entre les deux décisions.

## 3. Gates et décisions

**Gate de données (`validate-data`).** Premier essai de la démo avec une dérive `--factor 2` : l'étape `validate-data` du pipeline CT est restée rouge (aucun ré-entraînement, rien de déployé). Motif relevé dans les logs : la suite `scoring_contract` a échoué sur 2 des 67 contrôles : `expect_column_values_to_be_between(duration)` et `expect_column_values_to_be_between(age)`, soit des valeurs hors des bornes du contrat une fois ces colonnes doublées. La gate a bloqué un lot jugé incohérent avant tout apprentissage, ce qui est le comportement voulu. La démo a été rejouée avec `--factor 1.5`, qui passe la validation.

**Gate de promotion (`promotion_gate`).** Règles : métrique primaire du challenger ≥ seuil de `dataset.yaml`, et coût métier du challenger ≤ coût du champion actuel (tolérance 0). Les deux modèles sont évalués sur les mêmes données récentes, chacun à son propre seuil de décision.

| Run | Challenger | Champion remplacé | Résultat | Chiffres |
|---|---|---|---|---|
| Étape 7 | v10 | v9 | Promu | roc_auc 0,8094 · coût métier 108 |
| Démo (run `11a49001`) | v11 | v10 | Promu | roc_auc 0,8094 · coût métier 108 |

La version promue reçoit les tags `promotion=passed` et `previous_champion`, ce qui permet le retour arrière.

**Canary KServe piloté par Git.**
- Étape 8 (manuel, image 2.1.9) : canary à 10 %. Sur 200 requêtes, 177 réponses en 2.0.0 et 23 en 2.1.9 (environ 11,5 %, attendu 10 %). Aucune erreur, puis promotion à 100 % : 200 réponses sur 200 en 2.1.9.
- Démo (automatique, image 2.1.10) : canary à 10 %, analyse naïve (50 prédictions sur la nouvelle révision, aucune erreur tolérée), puis promotion à 100 %. La prod sert `2.1.10` avec `model_version` 11.
- `selfHeal` : un `kubectl patch` à 50 % sur la prod a été annulé par Argo CD en moins de 70 s. Tout changement de prod passe donc par un commit.

Historique des champions : v9 (Lab 1), v10 (étape 7, seuil de décision 0,318), v11 (démo). Historique des images en prod : 2.0.0, 2.1.9, 2.1.10.

## 4. Points d'attention

**Sécurité du webhook.** Le webhook lance des entraînements et des mises en production : il exige un jeton Bearer (`CT_WEBHOOK_TOKEN`, rangé dans `.env`, jamais dans Git), comparé avec `secrets.compare_digest`. Il n'écoute que sur 127.0.0.1. Il ne lance qu'un ré-entraînement à la fois, avec 10 minutes minimum entre deux, et seulement si au moins 10 % des variables dérivent : une alerte qui boucle ne peut pas lancer dix pipelines. Sans jeton, il répond 401 (vérifié).

**Gate humaine sur le CT.** Aujourd'hui le bot pousse directement sur `main`, sans relecture : seules des gates automatiques protègent la production (gate de données, gate de promotion métrique et coût, tests et test de fumée de la CI, passage par staging, canary à 10 %). Pour un modèle de crédit (haut risque au sens de l'AI Act), il faudrait que le bot ouvre une pull request avec le rapport de la gate, et que la prod n'avance qu'à la fusion.

**Retour arrière.** `gitops canary 0 --push` renvoie tout le trafic à la révision précédente (restée chaude). `gitops rollback --push` restaure aussi l'ancien `@champion`. Le bot revient en arrière tout seul si l'analyse du canary voit une erreur.

**Autres risques.**
- Étiquettes corrompues dans le lot récent : la gate de promotion refuse un modèle sous le seuil (test possible avec `simulate --shuffle-labels`).
- Chaîne d'approvisionnement : l'action tierce `setup-uv` est épinglée par SHA de commit, la CI n'a que les droits nécessaires par job, aucun tag `latest` (un tag par build, immuable).
- Le modèle est dans l'image publique (11 ko) : acceptable ici, à revoir (Git LFS ou stockage) pour un gros modèle.
- Les commits du bot et de la CI arrivent sur `main` sans PR : un commit concurrent peut faire échouer leur push.

**Difficultés rencontrées.**
- `make pf` et `make kfp-ui` se terminaient sans lancer les port-forwards (le `pkill` du Makefile tuait son propre shell) : lancés à la main avec `nohup kubectl … port-forward`.
- KFP était à zéro réplique depuis le Lab 5 : remis à 1 avant le ré-entraînement.
- L'export du modèle échouait (URL présignée `http://s3.storage:8333`, nom interne au cluster) : ajout de `127.0.0.1 s3.storage` dans `/etc/hosts`, à refaire après chaque redémarrage de WSL.
- Sur le cluster, `kubectl get applications` désignait la ressource de Kubeflow : utiliser `applications.argoproj.io`.
- Le téléchargement des images (Argo CD, GHCR) est lent sur ma connexion.
- Le lint de la CI (`ruff`) a échoué sur du code existant : corrigé avant la fusion.

## 5. Différences avec la production

- **Secrets** : un gestionnaire de secrets (Vault, External Secrets) à la place d'un `.env` local ; un jeton GitHub à portée minimale pour le bot.
- **Bot dans le cluster** : le webhook en Deployment, avec une GitHub App limitée au dépôt, au lieu d'un processus sur mon poste.
- **PR et validation humaine** : le bot ouvre une pull request avec le rapport de la gate, relue avant la prod.
- **Webhook Argo CD** : synchronisation instantanée au lieu d'une interrogation toutes les 60 s.
- **Analyse du canary** : comparaison de métriques réelles (erreurs, latence, distribution des scores via Prometheus, Lab 7) au lieu de 50 prédictions naïves ; promotion progressive 10, 50, 100 %.
- **Dérive mesurée sur le trafic** au lieu d'un lot simulé ; étiquettes réelles obtenues avec délai.
- **Audit et traçabilité** : journaux centralisés, signature des images, registre privé, lien entre version du modèle, données et commit.
- **Métriques métier** : suivi du coût métier en production, pas seulement sur le lot de la gate.

## 6. Captures d'écran

- Argo CD : `scoring-prod` et `scoring-staging` en `Synced` / `Healthy`.
- Run KFP `ct-pipeline` réussi (7 étapes vertes) et rapport de la gate de promotion.
- Run KFP avec `validate-data` en rouge (lot `--factor 2`).
- Onglet Actions : workflow « CI scoring » vert (3 jobs).
- Canary : sortie `kubectl get isvc` (PREV 90 / LATEST 10) et répartition 177 / 23.
- `git log` des commits de la démo : `ct: scoring-model v11`, tag de staging, canary 10 %, promotion 100 %.

## Conclusion

Le cycle dérive, ré-entraînement, validation, staging, canary, production s'est déroulé sans intervention humaine après le déclenchement, en 4 min 28 s entre le commit du modèle et la production à 100 %. La production n'est modifiée que par des commits Git, et trois garde-fous protègent le passage en prod : les gates automatiques, le passage par staging et le canary à 10 %. La principale limite est l'absence de relecture humaine sur les commits du bot, qu'une pull request résoudrait.
