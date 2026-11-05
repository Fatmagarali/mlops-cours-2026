# Rapport Lab 5 — Serving du modèle de scoring avec KServe

## 1. Résumé

Le modèle de scoring (image `scoring-api`, FastAPI + ONNX Runtime, Lab 4) est déployé en
InferenceService KServe en mode Knative, dans le cluster kind du cours, derrière la passerelle
Kourier (`http://localhost:30080`, en-tête `Host`). L'autoscaler Knative (KPA) pilote entre 0 et
5 pods selon le débit (cible 200 req/s par pod). Le service sert le modèle champion
(version 9) avec le seuil métier 0.3182, identique à celui du run MLflow. Une version 2.0.0 a
été déployée en canary 90/10, vérifiée expérimentalement, puis promue à 100 %.

## 2. Benchmark de latence

Charge : utilisateurs virtuels rejouant de vraies lignes de `test.csv` (`POST /predict`, attente
0,1 à 0,3 s entre deux requêtes), Locust sur 4 processus (`--processes 4`).
Durées : 100 users 2 min, 500 users 3 min, 1000 users 3 min.

| Run | Requêtes | RPS | P50 (ms) | P95 (ms) | P99 (ms) | Erreurs (%) |
|---|---|---|---|---|---|---|
| run_100 | 57573 | 479.4 | 4 | 8 | 12 | 0.00 |
| run_500 | 301422 | 1672.9 | 75 | 180 | 340 | 0.01 |
| run_1000 | 276418 | 1531.1 | 410 | 620 | 1100 | 0.00 |

**Analyse.** À 100 utilisateurs, le service est à l'aise (P99 = 12 ms, 479 req/s).
À 500 utilisateurs, le débit atteint 1673 req/s (P99 = 340 ms). Entre 500 et 1000 utilisateurs, le débit ne progresse plus (1673 → 1531 req/s) alors que le P99 passe de 340 à 1100 ms : le système sature. Le RPS max observé est d'environ 1673 req/s.
Le modèle n'est pas en cause (≈ 0,07 ms d'inférence ONNX) : le coût est dans HTTP, JSON et Python.
Au total, 39 requêtes ont échoué sur les trois runs (déconnexions et 502 pendant les
montées en charge, quand de nouveaux pods démarrent) : le taux d'erreur est très faible mais
n'est pas nul.

**Limite du banc d'essai.** Locust, les pods, Kourier et Knative partagent les mêmes cœurs
(WSL2 sur un laptop). Un premier essai avec un seul processus Locust plafonnait vers
1 000 req/s ; avec 4 processus, le même service dépasse 1 500 req/s : le plafond initial venait
en grande partie du générateur de charge. Les valeurs absolues restent un ordre de grandeur.

## 3. Scale-up observé

| Run | Pods max (ACTUALSCALE) | CPU max d'un `kserve-container` | Délai pour atteindre ce nombre de pods |
|---|---|---|---|
| run_100 | 5 | 757 m (limite 1 000 m) | ≈ 0 s après le début des relevés |
| run_500 | 5 | 981 m (limite 1 000 m) | ≈ 23 s après le début des relevés |
| run_1000 | 1 | 973 m (limite 1 000 m) | ≈ 0 s après le début des relevés |

Les CPU sont ceux des pods remontés par metrics-server (relevés toutes les 5 s) ; les pods tout
juste créés ne sont pas encore échantillonnés.

**Scale-to-zero.** Configuration : `minReplicas: 0`, fenêtre de 60 s, délai de réduction de 30 s.
Sans trafic, le dernier pod disparaît environ 2 minutes après la dernière requête.

| Mesure | Temps |
|---|---|
| Premier appel après retour à zéro pod (démarrage à froid) | 6,02 s |
| Appel suivant (service chaud) | 3,8 ms |

Le démarrage à froid inclut la planification du pod, le lancement d'uvicorn, le chargement du
modèle ONNX et les sondes. Pour une API appelée pendant un parcours de demande de crédit,
`minReplicas: 1` aux heures ouvrées évite cette attente ; c'est le choix retenu pour le canary.

## 4. Analyse canary

Déploiement de l'image `scoring-api:2.0.0` avec `canaryTrafficPercent: 10` : la révision
précédente (`00002`, image 1.0.0) conserve 90 % du trafic, la nouvelle (`00003`) en reçoit 10 %.
Les deux versions restent chaudes (`minReplicas: 1`).

| Version | Réponses (200 requêtes vers `/metadata`) | Part observée | Part cible |
|---|---|---|---|
| 1.0.0 | 187 | 93,5 % | 90 % |
| 2.0.0 | 13 | 6,5 % | 10 % |

**Conclusion.** Pour 200 requêtes, l'écart-type attendu du nombre de réponses v2 est d'environ
4,2 (√(200 × 0,1 × 0,9)). L'écart entre 13 observées et 20 attendues vaut environ 1,6 écart-type :
il est compatible avec le hasard de l'échantillonnage, donc le split 90/10 est cohérent. Un
échantillon plus grand réduirait cette variance. Les adresses dédiées (`latest-…`, `prev-…`)
renvoient bien les versions 2.0.0 et 1.0.0. La v2 a ensuite été promue à 100 %
(`canaryTrafficPercent: 100`) ; la révision `00002` reste disponible pour un retour arrière
(`canaryTrafficPercent: 0`).

La promotion a été faite manuellement avec `kubectl patch` : l'état du cluster s'écarte de ce
qui est dans Git. Les Modules 6 et 7 traitent ce point (GitOps, canary piloté par Git, décision
à partir des métriques).

## 5. Points d'amélioration

- **Plusieurs workers uvicorn par pod** : un seul worker par pod limite le débit par pod.
- **Cible de l'autoscaler** : ajuster `scaleTarget` (200 req/s) à la capacité réelle d'un pod,
  ou passer à la métrique `concurrency`.
- **Batching** : regrouper les demandes divise le coût par prédiction.
- **Triton** : batching dynamique et protocole V2, au prix d'une image très lourde et d'une
  décision au seuil métier déportée chez le client.
- **Banc d'essai** : Locust sur une machine séparée pour ne pas partager les cœurs du cluster.
- **Canary automatisé** : surveillance des erreurs, de la latence et de la distribution des
  scores, avec rollback automatique.

## Difficultés rencontrées

- `make kserve` a échoué à l'étape des `LLMInferenceServiceConfig` (webhook refusant le champ
  `TrustRemoteCode`, incohérence de version de KServe 0.21 sur une fonctionnalité LLM inutile
  ici). Contournement local : cette étape de `infra/kserve/install.sh` a été rendue non bloquante
  (non commité).
- `make pf` se termine lui-même (`pkill -f` qui correspond au shell de la recette) : port-forwards
  lancés à la main.
