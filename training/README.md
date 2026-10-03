# Model training and evaluation

`reproduce_training.py` contains the training/evaluation procedure used for the bundled four-class rotating-machine model.

It uses the repository's `app/replay_data/` recordings and reproduces the same evaluation design:

- 100 Hz sampling
- 256-sample windows with 64-sample step
- 383 engineered time/frequency/control/current features
- candidate models: `RandomForestClassifier` and `ExtraTreesClassifier`
- **leave-one-file-out (LOFO)** evaluation: every test fold holds out an entire CSV recording, so windows from the held-out recording never appear in that fold's training set
- file-level decision by majority vote across window predictions, with mean class probability as the tie-breaker
- final selected model retrained on all available recordings after model selection

Run from the repository root:

```bash
python training/reproduce_training.py
```

Outputs are written to `training/output/`, which is intentionally ignored by Git. The committed reference evaluation artifacts are under `docs/evaluation/`.

> Full LOFO evaluation fits hundreds of ensemble models and can take substantial CPU time. The committed CSV reports let reviewers inspect the recorded results without rerunning the full experiment.
