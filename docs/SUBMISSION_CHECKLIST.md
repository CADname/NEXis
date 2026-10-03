# Reusable hackathon submission checklist

This checklist captures requirements that repeatedly matter across AI, hardware, agent, vision, DevSecOps, and product hackathons.

## First impression / project packaging

- [ ] Project title says what the product **does**, not only what technology it uses.
- [ ] The first README screen shows the **real physical rig** before architecture or roadmap material.
- [ ] The one-line story is immediately clear: `assembly → short spin → vibration/current/RPM → AI diagnosis → inspection decision`.
- [ ] The strongest evidence is visible early: **225 recordings / 217 of 225 correct / 96.44% LOFO accuracy**.
- [ ] The diagnosis/result is visually more important than raw graphs, framework names, or model internals.
- [ ] Digital twin, FlexInspect, Vision, Agent, and generalized Edge material does not appear before the validated spin-test core.
- [ ] If available, a 5–8 second real-hardware clip shows `rig starts → RPM rises → telemetry moves → diagnosis appears`.
- [ ] No synthetic animation is presented as proof of the physical demo.

## Repository

- [ ] Public repository is allowed by the event rules.
- [ ] README states the problem, target user, solution, and core workflow in the first screen.
- [ ] Setup/run instructions are reproducible.
- [ ] Architecture diagram is present.
- [ ] AI/model/tool usage is specific rather than a generic technology list.
- [ ] Evaluation method and metrics are documented.
- [ ] Failure cases and limitations are disclosed.
- [ ] No keys, passwords, private certificates, local-user paths, dumps, or deployment backups are committed.
- [ ] If the specific event requires an open-source license, decide and add one for that submission; this general repository does not add a project-wide license by default.
- [ ] Third-party assets/models are used under compatible terms.

## Demo video

- [ ] Real hardware or the product outcome appears in the first **5–10 seconds**.
- [ ] Problem is understandable immediately after the hook.
- [ ] Physical hardware is visibly operating for hardware/Physical-AI tracks.
- [ ] Video shows one complete workflow from input to outcome.
- [ ] Final condition / inspection result is easy to read.
- [ ] Metrics are shown immediately after the successful workflow and only with their evaluation scope.
- [ ] Sponsor technology is named and visibly meaningful if required.
- [ ] Roadmap is short and clearly separated from the implemented demo.
- [ ] Video stays inside the event's time limit.

## Written submission

- [ ] Clear manufacturing problem statement.
- [ ] Named target users/stakeholders.
- [ ] One-line product behavior before the technology stack.
- [ ] What was built and how it works.
- [ ] Measured evidence appears before deep implementation detail.
- [ ] Technical architecture/components.
- [ ] Why AI is useful in the workflow.
- [ ] Real-world impact and deployment path.
- [ ] Screenshots / diagrams / hardware photos.
- [ ] Source-code link and live-demo/test instructions if required.
- [ ] Clear base-repository and event-built contribution disclosure when required by the event.
- [ ] Significant event-period additions are itemized.
- [ ] Required sponsor feedback or tool disclosure is included.

## Before final submit

- [ ] Run `python scripts/public_repo_check.py`.
- [ ] Run `python scripts/validate_evidence.py`.
- [ ] Open every submission link in a private/incognito browser.
- [ ] Confirm video visibility and audio/subtitles.
- [ ] Confirm repo default branch and README rendering.
- [ ] Confirm the README hero asset renders correctly on GitHub.
- [ ] Confirm no private credentials are shown in screenshots/video/terminal history.
- [ ] Confirm the submitted branch/tag matches the demo.
