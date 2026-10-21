# Rapport comparatif — Kubeflow Pipelines vs Airflow (Lab 2)

## 1. Contexte

Le pipeline de credit scoring du Lab 1 (dataset german-credit, 1000 lignes, 20 variables, 30 % de mauvais payeurs) a été porté sur deux orchestrateurs : Kubeflow Pipelines 2.17 et Airflow 3.3. Il compte six étapes : ingest, validate, prepare, train, evaluate, register. Les deux versions exécutent le même code (src/) dans la même image scoring-pipeline:1.0.0, sur un cluster kind à trois nœuds. Les résultats sont identiques (roc_auc 0,8094, seuil de décision 0,3182) et chaque run produit une version de scoring-model dans MLflow, taguée launched_by=kfp ou launched_by=airflow.

## 2. Résultats quantitatifs

| Mesure | Kubeflow Pipelines | Airflow |
|---|---|---|
| Code propre à l'orchestrateur | 347 lignes (components.py 257 + scoring_pipeline.py 90) | 71 lignes (scoring_dag.py) |
| Durée d'un run | 1er run : 13 min 46 (incidents réseau inclus), 2e run : 2 min 14 | environ 1 min 20 |
| Cache | 2e run beaucoup plus court : les étapes data sont servies depuis le cache | aucun |
| Mémoire | intégré au cluster kind (environ 3,3 Gio pour tout le cluster, MLflow compris) | environ 1,5 Gio de conteneurs permanents |
| Taille de l'image | 1,08 Go | 1,08 Go (même image) |

Les mesures de mémoire ont été prises au repos, après les runs : les pics pendant l'exécution sont plus élevés. Le premier run KFP n'est pas représentatif : il inclut le téléchargement des images par les nœuds et la correction d'un problème de résolution du registry local.

## 3. Analyse qualitative

### Developer experience

Airflow demande beaucoup moins de code (71 lignes contre 347), car un DAG se limite à enchaîner des pods. KFP en demande davantage, mais gère les artefacts typés (Dataset, Model, Metrics), les affiche dans l'interface (métriques, matrice de confusion) et les relie entre les steps sans code supplémentaire. Avec Airflow, il a fallu écrire la seconde moitié de stage.py pour passer les fichiers par S3, et utiliser XCom pour les petites valeurs.

### Scaling

Dans les deux cas, un step est un pod : la montée en charge repose sur Kubernetes. KFP exécute naturellement en parallèle les steps indépendants et offre le caching, qui a ramené un run de 13 min 46 à 2 min 14 en évitant de refaire les étapes data. Airflow est plus souple (planification, nombreux opérateurs) mais n'a pas de cache natif. Sur ce petit cas, Airflow était plus rapide (environ 1 min 20) que le run KFP en cache, KFP ajoutant des pods de pilotage à chaque step. Je n'ai pas testé de parallélisme réel : cette partie reste théorique.

### Debugging

Mon principal incident (image du pipeline introuvable, car les nœuds ne résolvaient pas le nom du registry local) n'était lisible clairement que via kubectl (describe et events), pas depuis l'interface de l'un ou l'autre outil. Une fois les pods lancés, les logs par step sont faciles à consulter dans les deux interfaces, et Airflow permet de relancer seulement une task échouée.

## 4. Recommandation

Je choisirais KFP pour un projet centré sur le machine learning : artefacts typés, métriques visibles, caching et reproductibilité par composant, à condition d'avoir un cluster Kubernetes stable et de la mémoire disponible. Je choisirais Airflow pour des workflows de données variés où le ML n'est qu'une partie, avec de la planification et des intégrations, et une équipe qui le connaît déjà. Dans les deux cas, versionner l'image et la réutiliser partout, comme ici, évite que le code diverge entre orchestrateurs.

## 5. Limites de la comparaison

Cette comparaison repose sur un petit dataset, un cluster kind local et un seul utilisateur. Je n'ai pas testé de vrai cluster (GKE par exemple), le KubernetesExecutor d'Airflow, ni plusieurs runs en parallèle. Les temps d'installation ne sont pas représentatifs : un réseau instable (DNS des nœuds, accès à GitHub et aux registries) a fortement ralenti l'installation de KFP. Les durées de run proviennent d'un seul essai chacune, et les mesures de mémoire ont été prises au repos.
