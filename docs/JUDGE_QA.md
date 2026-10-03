# Judge Q&A preparation

## What is NEXis in one sentence?

NEXis is an AI end-of-line spin-inspection prototype that briefly runs an assembled rotating-drive module, analyzes synchronized vibration/current/RPM, and identifies Normal, Unbalance, Misalignment, or Looseness before shipment.

## Why is this not just another vibration monitor?

A normal condition-monitoring dashboard mainly trends machine signals. NEXis is organized around a **manufacturing inspection workflow**: controlled spin → synchronized multi-sensor capture → machine-condition classification → stored result → PASS-candidate or investigate/reject decision support.

## Why use three signal types?

Different assembly faults can affect mechanical vibration, rotational stability/control behavior, and electrical load differently. NEXis preserves these signals together and derives cross-signal features rather than relying on one sensor channel alone.

## Is 96.44% from random window splitting?

No. The reference model-selection run uses **leave-one-file-out validation**: one complete CSV recording is held out per fold, so windows from that recording do not enter training for that fold.

## Does that prove the model works on any motor?

No. It proves performance on the supplied prototype dataset under its measured operating setup. A different machine design, sensor mount, speed range, or load should be validated separately.

## Is the inspection really 2.56 seconds?

2.56 seconds is the data duration of one 256-sample window at 100 Hz. A complete physical test also includes spin-up and stabilization, so the repository does not claim a fixed 2.56-second total cycle time.

## Why RandomForest instead of a deep model?

For this prototype dataset, engineered time/frequency/current/control features with an ensemble classifier provide a compact and interpretable baseline that is inexpensive to run. The novelty claim is the **end-to-end physical inspection workflow**, not RandomForest itself.

## What is innovative here?

The useful combination is the workflow: a controlled physical spin test, synchronized multi-sensor evidence, file-level validation, fault diagnosis, replayable data, and a browser result path aimed at catching dynamic assembly issues before shipment.

## Why not make Vision AI the main feature?

The strongest current evidence is the sensor-based spin diagnosis. Vision is more valuable as a **measurement-quality gate** — for example, verifying that sensors or fixtures are positioned correctly before a spin test — and should stay a roadmap/event-specific module until it is implemented in the submitted branch.

## How can this scale to other machines?

The safe path is not to claim that the existing four-class classifier transfers unchanged. A scalable product can add configurable recipes, generalized edge connectors, normal-baseline anomaly detection, and then asset-specific diagnosis once relevant labeled data exists.

## What happens if the network fails?

The public architecture is a prototype and should not be treated as a safety controller. Industrial deployment should add explicit offline behavior, local safeguards, retries/buffering, health monitoring, and independent hardware safety controls.

## What would you build next?

The next product layer is measurement-setup validation plus repeatable inspection recipes. For sponsor-specific hackathons, an agent, vision component, cloud deployment, or DevSecOps automation can be added around the validated spin-test core if it performs a real measurable function.

## What should judges remember after the demo?

Three things:

1. **It is a real physical test, not only a dashboard.**
2. **The result is backed by 225 recordings and 217/225 LOFO-correct files.**
3. **The current claim is narrow and demonstrated; broader FlexInspect capabilities are a roadmap, not a hidden overclaim.**
