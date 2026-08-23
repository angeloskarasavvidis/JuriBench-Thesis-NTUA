## source of data

Good instinct, but no — it's a lookup chain, not a circle. Let me kill the egg-chicken worry precisely, because you're right to poke it.

Is MQ built from SCDB? Yes. Martin-Quinn ideal points are estimated by an IRT model run on SCDB justice votes across terms. MQ is a function of SCDB voting data. True.

Does that make our use circular? No. Watch what each thing supplies:

┌─────────────────────────┬────────────────────┬───────────────────────────────────────────────────────────────────────────────────┐
│          Fact           │       Source       │                                    What it is                                     │
├─────────────────────────┼────────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
│ Who wrote this case     │ SCDB majOpinWriter │ an identity (a code)                                                              │
├─────────────────────────┼────────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
│ That justice's ideology │ MQ post_mn         │ their career ideal point, smoothed over all their votes that term — not this case │
├─────────────────────────┼────────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
│ This case's topic       │ SCDB issueArea     │ a topic label                                                                     │
└─────────────────────────┴────────────────────┴───────────────────────────────────────────────────────────────────────────────────┘

The ideology label we attach = the author's personal, career-aggregated ideal point. It is ntext, this case's outcome, or this case's votes. So the classifier's input (opinion text) and the label (author's trait) are independent — that independence is the whole hypothesis you're testing ("does judicial writing carry ideological signal"). Nothing circular.

Where it WOULD be circular: if you labeled ideology with SCDB decisionDirection — the coded liberal/conservative outcome of this very case, derived from this case's votes. That's leakage. We are explicitly not using that as the ideology label (it's a separate column, case outcome ≠ author ideology).

And the two SCDB columns we do use — majOpinWriter (who) and issueArea (topic) — are different variables that don't feed into each other. No self-reference.

Do we even need SCDB for ideology? To score the author you must first know the author. MQ can case — only SCDB (or parsing the broken opinion text) can. That's the only role SCDB playsfor ideology: naming the author. It doesn't supply the score.

Your issue_area answer — locked: "valid data from external source, [don't] mess with probabilities" → use SCDB issueArea ground truth for SCOTUS, Lawma only for CA5/CA9. Agreed and correct — never Lawma-guess what SCDB already codes by hand.