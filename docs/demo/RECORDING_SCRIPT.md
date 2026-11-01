# Recording script (about 4 to 5 minutes)

A script for a screen recording or a live demo of FormFiller. Everything shown is real and was run from a fresh clone and a fresh virtual
environment before this script was written (see the [demo guide](DEMO_GUIDE.md) for the long version). No recording is included in the
repository: this is the plan for making one.

Keep the three claims the narration makes: FormFiller **abstains instead of guessing**, it **verifies by reading the page back**, and
**a person decides and submits**. Say it in your own words; the narration below is about 560 words, which is about four and a half minutes
at a calm pace.

## Before you record

- [ ] Fresh checkout, virtual environment active, `pip install -e ".[web]"` and `playwright install chromium` done (guide, section 1).
- [ ] Delete old output so the folder names on screen match the script: `Remove-Item -Recurse -Force output\demo, output\demo-reviewed, output\demo-submit` (ignore "not found").
- [ ] Rehearse once off-camera, then delete the output again. The first run takes about 12 seconds including browser start-up.
- [ ] Rehearsal check (about a minute, needs `pip install -e ".[dev]"`): `python -m pytest tests/web/test_demo_rfi.py -q` should print `26 passed`. It pins every number quoted below.
- [ ] Terminal: 16 to 18 pt font, at least 190 columns wide (the report table is wide), no personal path in the prompt (`cd` to the repository and, if needed, `function prompt { "PS> " }`).
- [ ] Windows: to record, press `Win + Alt + R` (Xbox Game Bar) or use OBS Studio. Record one window or one monitor, not the whole desktop, and close notifications.
- [ ] Browser window about 1200 px wide for the review page. Close other tabs. Do not show any other project, account or file path outside the repository.
- [ ] Have `docs/assets/demo-before-review.png` and `demo-after-review.png` open in a viewer as a fallback.

## Commands, in the order you will type them

```powershell
# scene 3: the first run (about 12 seconds)
python demo_web.py --form docs/demo/security_questionnaire.html --source docs/demo/company_source.json --out output/demo

# scene 5: the review page (prints a URL with a token; open exactly that URL; Ctrl+C when finished)
python -m formfill.web.review_server output/demo/result.json --build

# scene 6: apply the person's decisions
python demo_web.py --form docs/demo/security_questionnaire.html --source docs/demo/company_source.json --out output/demo-reviewed --review output/demo/review.json

# scene 7: ask it to submit, and watch it refuse
python demo_web.py --form docs/demo/security_questionnaire.html --source docs/demo/company_source.json --out output/demo-submit --submit

# optional bonus scene: the neighbouring-concept guard (RPO fact removed from a copy of the source)
python -c "import json,pathlib; d=json.load(open('docs/demo/company_source.json',encoding='utf-8')); del d['business_continuity']['rpo_hours']; pathlib.Path('output').mkdir(exist_ok=True); json.dump(d,open('output/source_no_rpo.json','w',encoding='utf-8'),indent=2)"
python demo_web.py --form docs/demo/security_questionnaire.html --source output/source_no_rpo.json --out output/demo-no-rpo
```

## Scenes

| Time | On screen | Say |
|---|---|---|
| 0:00 to 0:30 | 1. The problem. The README title and its first paragraph, then the top of `docs/demo/security_questionnaire.html` open in a browser | "Vendor security questionnaires ask the same few hundred questions again and again, and every answer has to be right: a wrong answer in a security questionnaire is worse than a blank one. FormFiller fills in the answers it can back with evidence from your own JSON file, leaves everything else to a person, and never submits anything itself. This is a fictional supplier questionnaire." |
| 0:30 to 1:00 | 2. The facts. Scroll the questionnaire quickly (eight sections, 33 questions, a file upload, a declaration), then open `docs/demo/company_source.json` in an editor and stop on the `business_continuity` block (`rto_hours` 8, `rpo_hours` 1) | "Its knowledge base is one JSON file of facts about a fictional company. Nothing else: no model, no guessing. It flattens these into facts like `business_continuity.rto_hours` equals 8. Notice both a recovery *time* and a recovery *point* objective: two facts that differ by one word." |
| 1:00 to 1:50 | 3. Discover, match, fill, verify. Run the first command; when the table appears, scroll it slowly. Pause on the `VERIFIED` rows, the RTO and RPO rows, then the `NEEDS_REVIEW` rows, then the last three lines. **Expected:** `22 verified \| 11 needs review \| 1 unsupported control(s)`, `Run status: NEEDS_REVIEW`, `Submission: not attempted` | "It opens the form in a real browser, discovers 33 questions, and matches each to a fact. Twenty-two are answered and **verified**: after typing, it reads the page back and compares. Each row names the fact and a confidence label, and the RTO and RPO each use their own fact. Eleven are **not** answered, and each says why: no fact, a contradiction in my own data, SOC 2 only 'in progress', a declaration. A file upload is reported and never touched." |
| 1:50 to 2:10 | 4. Empty means empty. Open `output/demo/filled.png` and point at the empty fields (encryption keys, password length, notification time) | "The uncertain fields really are empty. Some rows show a *proposal*, a similarity hint, but it is never typed in. Some proposals are wrong, for example it suggests an encryption algorithm for 'who manages your keys'. That is exactly why a person decides." |
| 2:10 to 3:30 | 5. Human review with evidence and confidence. Run the review command; open the printed URL. Scroll to a verified card (evidence and confidence), the remote-employees card, the password card, the declaration card. Decide: approve the hosting-region proposal; type `12` for the password; type `next Tuesday` into the exercise date and show the refusal, then `2026-03-10`; reject the encryption-keys proposal; click Acknowledge on the declaration. Stop the server | "This is the review page. It runs only on my machine and needs a token. Every card shows the evidence, the method and the confidence. The headcount question was refused because it asks about *remote* staff and the fact is the total; the proposal is shown but not entered. The password question shows both conflicting facts. A date I mistype is refused by the page. The declaration offers only 'acknowledge': software can never agree to a declaration for you. Approving here is not a signature and not a submission." |
| 3:30 to 4:00 | 6. Apply the decisions. Run the third command; point at the summary line. **Expected:** `29 verified \| 4 needs review \| 1 unsupported control(s)` | "Now it runs again with my decisions. They are validated, entered and read back like any other answer: twenty-nine verified, four still with me, and the upload untouched. The status is still needs-review, and nothing was submitted." |
| 4:00 to 4:30 | 7. Submission stays human. Run the `--submit` command and show the refusal. **Expected:** `Submission: {'attempted': False, 'outcome': 'SKIPPED', ...}` | "Submitting stays a human action. Even if code asks it to submit, FormFiller refuses while a declaration is open, an answer failed, or a control has no human decision. To be straight about limits: this is a prototype, tested on fixtures and public practice forms, not on real company portals, and matching is deliberately conservative. The repository has the benchmarks, the real-world test report and a security model that says what the network guard does *not* guarantee." |
| 4:30 to 5:00 (optional) | 8. Bonus: the guard. Run the two bonus commands. **Expected:** `21 verified \| 12 needs review`, and the RPO row `NEEDS_REVIEW ... different concept: the question says ['point'] where the key says ['time']` | "One more thing. I removed the RPO fact. An earlier version answered the RPO question with the RTO value, because the two questions share most of their words. I found that while preparing this demo and fixed it in a separate change with its own tests: now it leaves the field to a person. The guard catches pairs that differ by one word; it does not understand concepts, so it is a mitigation, not a proof." |

If you need a 3-minute cut, drop scenes 2 and 4 and the bonus.

## If someone asks

| Question | Honest answer |
|---|---|
| How accurate is it? | "On my two browser benchmarks, 98.1 % precision with 55.7 % coverage on the development set, and 100 % precision with 40.1 % on the second set. The second set is not independent: it was used to guide fixes. On ten public demo forms with a pre-written ground truth: 100 % precision, 59 % coverage, no wrong fills. That is a small sample on public practice forms, not company portals. The numbers on this demo describe one hand-written fixture and are not accuracy." |
| Does it work on any website? | "No. It handles the control types listed in the compatibility matrix, tested on local fixtures and a few public pages; custom widgets are handled by structure, on few examples. Where it cannot be sure, it stops or leaves the field for a person." |
| What did it get wrong? | "Matching compares words, so near-misses happen. The clearest case I found: with the RPO fact removed, it answered the recovery-*point* question with the recovery-*time* value. I fixed it with a guard for questions that differ from a fact by exactly one word. It was checked on 62 probes I wrote and 130 regression tests, so it is not proof that no other pair is confused. The fix also removed two plausible suggestions and made one worse. Suggestions can also be irrelevant; they are never entered automatically." |
| Is it safe to point at a real portal? | "Only with fictional data or explicit permission, and it never submits by default. During multi-step walks it blocks the browser's network on the channels I tested; that is not absolute isolation, and the security model lists the gaps." |
| Why no LLM? | "Matching is deterministic by default so every answer is explainable and repeatable. An optional LLM layer exists, off by default, can only make proposals, and has only been tested against a fake client." |

## Things not to say

- Do not call the demo's 22 / 11 / 1 or 29 / 4 / 1 an accuracy.
- Do not say it "works on any questionnaire", "is production ready" or that the confusion problem is "solved".
- Do not say the review page submits or signs anything; it does neither.
- Do not present the second benchmark as an independent test.
- Do not use real names, real portals or real data. If you adapt the demo, keep it fictional.
