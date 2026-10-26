# openedx-tier-plugin v0.4 (GATE CSE and UGC NET CS)

Gives every learner a tier per course. Runs inside the LMS of an Open edX site installed with Tutor.
Inputs come from Open edX itself (grades, attempts, activity), not from school records.

## Why not the DIKSHA-CALAS model as it is
It was built for Class 11/12 and dropper students preparing for JEE/NEET. For GATE and UGC NET learners:
- Many inputs do not exist: Class 9-12 marks and slopes, school attendance terms, district percentile, district development index, dropper flag, JEE attempts.
- The zip has no trained model file (`models/saved/` is empty), so there is nothing to load.
- Its label (`crack_label`) is a proxy: the top 20% of a score built from the same inputs. A high accuracy on it only shows the model learned that score, not that it predicts an exam result. By design about 80% of learners are always in the lower group.
So: keep the idea (academic, consistency, behaviour), but retrain on this site's data with real outcomes. Until then the built-in `composite` backend gives a transparent readiness tier.

## Feature mapping (DIKSHA-CALAS to this plugin)
| DIKSHA-CALAS | Here | Source |
|---|---|---|
| S_weighted | S_weighted | graded subsection scores, newest weighs most |
| balance_index | balance_index | spread of subject averages |
| slope_junior / slope_senior | slope_assessments | score trend over assessments |
| attendance_mean | active_day_ratio | days with activity |
| attendance_trend_slope | activity_trend_slope | active days per week, trend |
| regularity_index | regularity_index | share of recent weeks with activity |
| completion_rate | completion_rate | attempted / all graded subsections |
| error_retry_ratio | error_retry_ratio | problems tried more than once |
| progression_speed | progression_speed | subsections attempted per week |
| recency_score | recency_score | exp(-days since last activity / 14) |
| sessions_count, hint_freq, tpp_deviation | not available | need event logs / authored hints |
| urban_rural, parent_edu, sec, first_gen, district index | not collected | optional: `TIER_USE_CONTEXTUAL` sends education level and age |
| (new) | subjects_covered_frac, longest_gap_days, avg_attempts_per_problem, days_enrolled | |

Activity days come from the timestamps Open edX keeps on each learner's course state. They are an approximation of real sessions.

## Set up the exams
Subject lists are in `tier_plugin/exams.py` (check them against the current official syllabus). A subject is matched
to a graded subsection by name, so name subsections like `Operating Systems: Practice Quiz`. The GATE course made earlier already does.
Tell the plugin which course is which exam (only listed courses are tiered):
```python
# $(tutor plugins printroot)/tier_settings.py
from tutor import hooks

hooks.Filters.ENV_PATCHES.add_item((
    "openedx-common-settings",
    'TIER_COURSE_EXAMS = {"course-v1:TestOrg+GATE101+gate_2026": "gate_cse", "course-v1:TestOrg+NET101+net_2026": "ugc_net_cs"}\n'
    'TIER_MODEL_BACKEND = "composite"\n'
    'TIER_SHOW_TO_LEARNERS = False\n',
))
```
`tutor plugins enable tier_settings && tutor config save`

## Install or upgrade
```
tutor config save --append OPENEDX_EXTRA_PIP_REQUIREMENTS="git+https://github.com/YOU/openedx-tier-plugin.git@main"
tutor images build openedx
tutor local launch
tutor local run lms ./manage.py lms showmigrations tier_plugin      # expect 0001 and 0002 ticked
tutor local run lms ./manage.py lms compute_tiers --course-id course-v1:TestOrg+GATE101+gate_2026
```
Upgrading from v0.1: the same commands; migration 0002 adds two columns.

## Train your own model
```
tutor local run lms ./manage.py lms export_features --course-id course-v1:TestOrg+GATE101+gate_2026 --out /openedx/data/features.csv
```
One row per learner: pseudonymous `learner_id`, the 14 inputs, `subject_scores`, and an empty `outcome` column.
Fill `outcome` with the real result (exam result, or a mock-exam score taken later) and train on that.
Do not use a label made from the same features.

## Connect the trained model (your other site)
Set `TIER_MODEL_BACKEND = "http"`, `TIER_MODEL_URL`, `TIER_MODEL_TOKEN`. The plugin sends:
```json
POST {"schema_version": 2, "exam": "gate_cse",
      "features": {"S_weighted": 71.2, "...": 0.0},
      "subject_scores": {"Operating Systems": 64.0},
      "profile": {"level_of_education": "b", "age": 24}}
```
(`profile` only when `TIER_USE_CONTEXTUAL = True`) and expects `{"tier": "Tier 1", "score": 0.91, "version": "v1", "explanation": [...optional SHAP...]}`.
Use HTTPS. Learner ids, names and emails are not sent.

## What learners see (new in v0.3)
A progress panel: average score, subjects attempted, quizzes done, active weeks, a bar per subject, and rule-based notifications
(back after a break, weak subjects, rising or falling scores, steady routine, subjects not started) plus one next step.
The tier is shown only when `TIER_SHOW_TO_LEARNERS = True`. The courses in this bundle embed the panel in the "Start Here > My progress and notifications" unit.
It is also served as a page: `/api/tier/progress/` (add `?course_id=...`). The panel reads `/api/tier/v1/me/progress/` with the learner's own login.
Notifications are computed on each visit from the stored inputs, so they are not emailed or pushed (see the bundle README for next steps).

## CPF score and explanation (new in v0.4)
When `TIER_SHOW_TO_LEARNERS = True` the panel also shows a CPF score (0-100), the points to the next level, and two lists:
what is helping the learner and what is holding them back, each with points and one concrete action.
- With the built-in `composite` backend the score is a **readiness index**, not a probability of passing, and the panel says so.
  The breakdown is exact (the score is a sum of nine terms; each factor's impact = its term minus the same term for a benchmark learner).
- With a trained model on the `http` backend the panel shows the model's probability and **its SHAP values**. Your API returns them as
  `"explanation": [{"feature": "S_weighted", "impact": -0.12}, ...]` (same units as `score`, positive raises it, plugin feature names).
  Missing or malformed explanation entries are ignored; the tier still works. Add advice text for new feature names in `progress.FEATURE_INFO`.
- Stored in `StudentTier.explanation` (migration 0003). The composite breakdown is also computed from the stored inputs when the field is empty.
Courses embed the panel's HTML: after updating the plugin, rebuild and re-import the courses to refresh the panel inside them
(the standalone page `/api/tier/progress/` updates by itself).

## Dummy learners
```
tutor local run lms ./manage.py lms seed_dummy_learners --course-id course-v1:TestOrg+GATE101+gate_2026 --count 24
tutor local run lms ./manage.py lms seed_dummy_learners --course-id course-v1:TestOrg+NET101+net_2026 --count 24
tutor local run lms ./manage.py lms seed_dummy_learners --course-id ... --clean      # remove them again
```
Creates users `dummy_gate_01`, `dummy_net_01`, ... with nine made-up study patterns (steady topper, fast improver, slipping, crammer,
early dropout, narrow specialist, struggling, new joiner...), runs the real feature maths and model on them and saves tier rows.
Writes `dummy_learners.csv` (username, persona, tier). The passwords are unusable: to log in as one, set a password in the Django admin.
`--full` also enrols them and writes grades (this part has not been run against a live Open edX; try it on a spare course first).
Dummy data tests the pipeline and the screens. It cannot tell you whether the model predicts exam results.

## API
- `GET /api/tier/v1/me/progress/?course_id=...` the learner's own progress and notifications for ONE course (course_id required; only for learners enrolled in it).
- `GET /api/tier/v1/me/courses/` the learner's enrolled courses that have progress (the standalone page uses it to show a course picker).
- `GET /api/tier/v1/courses/<course_id>/` course staff: all tiers with inputs.
- `GET /api/tier/v1/me/?course_id=...` the learner's own tier, only when `TIER_SHOW_TO_LEARNERS = True`.

## Notes
- Tested here: feature maths (against hand-worked numbers), migrations, backends, service (39 tests, including a table that checks each dummy study pattern lands in a believable tier). Not tested inside a live Open edX: the database queries in `collect_features` and the grade signal. Check with the commands above.
- The composite backend has two guard rails found while testing with dummy learners: a weighted score under 40% is always Tier 3, and Tier 1 needs at least half the subjects attempted (`composite-v1`).
- The panel was tested in Chromium against a mock server (light, dark, phone width; no console errors). Not tested: inside the Learning MFE, whose iframe or Content-Security-Policy settings may block the script. If the panel stays on "Loading", use the standalone page.
- A learner with no graded work gets "Not enough data", not a low tier.
- Tiers affect real people: tell learners their activity is used, keep `TIER_SHOW_TO_LEARNERS` off until results are checked, and review results by group before acting on them.
