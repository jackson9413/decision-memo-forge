"""Built-in sample decision documents for Decision Memo Forge.

Six documents that cover the useful range: a clean memo, a proposal with a
straw-man alternative, a hard-to-reverse RFC, an exploratory spike, a status
update and a postmortem. Each one is a real shape of document people
actually send, so the reviewer can be calibrated against them.
"""

SAMPLES = {
    "checkout-postgres-memo": {
        "title": "Checkout database migration (strong memo)",
        "blurb": "A well-built decision memo: context, decision, four options on shared criteria, a named recommendation, risks, owners, dates and an explicit ask.",
        "doc_type": "memo",
        "stakes": "high",
        "reversibility": "two_way",
        "audience": "exec",
        "text": """Subject: Move the checkout service to Postgres 16

Context
We run checkout orders in MySQL 5.7. During Black Friday 2025 the replica lag ceiling hit at 14:00 and the order write path reached 900 ms at peak. We turned away 3 percent of checkouts, roughly 4,200 orders, and paid 18,000 dollars in goodwill credits.

Decision
We need to decide whether to migrate the checkout service to Postgres 16 now, or stay on MySQL through Q1 2027.

Options
| Option | Cost | Effort | Risk | Reversible |
| --- | --- | --- | --- | --- |
| Migrate to Postgres 16 | 120,000 dollars | 8 weeks | Medium | Yes |
| Stay on MySQL and shard | 60,000 dollars | 14 weeks | High | Yes |
| Add read replicas only | 40,000 dollars | 3 weeks | Medium | Yes |
| Do nothing | 0 dollars | 0 weeks | High | Yes |

Recommendation
I recommend Migrate to Postgres 16. It removes the write-path ceiling permanently, and we have two engineers free from 2026-12-01.

Trade-offs
The cost of this choice is 8 weeks of frozen checkout feature work and a 120,000 dollar spend. We also delay the fraud-model retraining by one quarter.

Risks
Dual writes could lose orders during cutover. We mitigate this with a shadow read comparison for 2 weeks before the switch, and we keep the MySQL replica warm for 30 days.

Reversibility
We can roll back to MySQL for 30 days after cutover. After that the reverse migration is 6 weeks of work.

Timeline
Decision needed by 2026-11-20. Migration starts 2026-12-01 and finishes 2026-12-28. Shadow comparison runs 2026-12-08 to 2026-12-21.

Owners
Owner: Dana Ruiz. Owner: Priya Nair.

Ask
Please approve the 120,000 dollar budget and the December feature freeze by 2026-11-20.
""",
    },
    "pricing-proposal": {
        "title": "Pricing change proposal (straw-man options)",
        "blurb": "A business proposal where the preferred option gets five sentences and every alternative gets five words, with no risks and no dates.",
        "doc_type": "proposal",
        "stakes": "medium",
        "reversibility": "unknown",
        "audience": "exec",
        "text": """Proposal: Move to usage based pricing

Background
Our current flat-rate plan no longer covers the cost of serving heavy users. Several significant accounts have raised this with us and it is clearly a problem for the business.

Options
- Usage based pricing. This is the only approach that lets us charge heavy users more, and it directly addresses the core problem. We would meter API calls and bill at the end of each month. Metering infrastructure already exists in the billing service, so the build is well understood and low risk. It also creates a natural upsell path and aligns us with how the rest of the industry charges. Customer research from 14 interviews showed strong interest in usage pricing, which means adoption should be smooth.
- Increase flat rate.
- Keep flat rate.
- Hybrid model.

Recommendation
I recommend usage based pricing because it solves the problem properly and we have the infrastructure already.

Next steps
We should probably move ahead relatively quickly before the next quarter starts.

Ask
Can you approve this?
""",
    },
    "payment-processor-rfc": {
        "title": "Payment processor switch (hard to reverse)",
        "blurb": "A technical RFC for a one-way door: no risks, no rollback, no numbers, and no owner. The caps fire hard here.",
        "doc_type": "rfc",
        "stakes": "high",
        "reversibility": "one_way",
        "audience": "technical",
        "text": """RFC: Replace the payment processor

Motivation
Our current processor has been somewhat limiting for our needs. Their API might be a bit slow and support has been difficult to get hold of. It could be that moving would be better for us going forward.

Alternatives
- Stripe
- Adyen
- Braintree

We should probably look into this and decide soon. The team is fairly confident that Stripe would be a robust and scalable solution that leverages modern payments infrastructure and delivers a seamless customer experience. It could possibly be the best option for us and is likely to be quick to integrate.

Recommendation
We will proceed with Stripe.

Next steps
We will start integration soon and hopefully have it live before the end of the year.
""",
    },
    "hiring-spike": {
        "title": "Hiring exploration (exploratory note)",
        "blurb": "Early thinking with no decision yet. The tool detects it as an exploratory note and stops demanding a recommendation.",
        "doc_type": "exploratory",
        "stakes": "low",
        "reversibility": "two_way",
        "audience": "peer",
        "text": """Exploration: How should we hire the first platform engineer?

Context
We are a team of 9 engineers and we have never hired outside engineering. We need to figure out what role to open and how to run the process. Right now the founders have been doing the screening informally and it has not really worked well.

Options we are weighing
- A senior generalist role that owns the deployment pipeline end to end.
- A narrow SRE role focused on alerting and on-call.
- A contract engineer for 6 months to validate the role before we hire permanently.

Open questions
We do not know yet what the first hire should optimize for. It might be delivery speed, it might be on-call relief, and it might be that we need someone to own the cloud spend. There is also an open question about compensation band, because we have no market data for this role and we do not know whether our budget is competitive.

Next steps
Dana will talk to three engineering leaders for calibration by 2026-11-15. Priya will draft a role scorecard by 2026-11-22. We will compare the three options again once we have both.
""",
    },
    "launch-status": {
        "title": "Launch status update",
        "blurb": "A short status update. It is not a decision document, and the tool says so instead of pretending otherwise.",
        "doc_type": "status_update",
        "stakes": "low",
        "reversibility": "two_way",
        "audience": "peer",
        "text": """Status update: Billing launch week

Where we are
We are 90 percent through the billing launch. Everything in the checklist is done except the invoice reconciliation job, which is still blocked on the finance team's mapping file.

Impact
The launch supports 41 enterprise accounts and 12,000 invoices this month. If we slip past 2026-11-10 we will miss the November billing cycle for 6 accounts, which is roughly 40,000 dollars in delayed revenue.

Next steps
Priya will finish the reconciliation job and test it against 3 months of history. Sam will run the load test at 4x normal volume on 2026-11-06. Finance confirmed the mapping file will land on 2026-11-05.

Blocked
We need the finance mapping file. Owner: Sam Okoro. Due: 2026-11-05.
""",
    },
    "incident-postmortem": {
        "title": "Checkout outage postmortem",
        "blurb": "A postmortem with impact, timeline and owned actions. The archetype changes which sections are required.",
        "doc_type": "postmortem",
        "stakes": "medium",
        "reversibility": "two_way",
        "audience": "peer",
        "text": """Postmortem: Checkout outage on 2026-10-14

Summary
Checkout was unavailable for 47 minutes on 2026-10-14, from 09:12 to 09:59 CST. A bad deploy shipped a schema change that was not backwards compatible with the running application version. The rollback took 12 minutes because the previous image was not cached.

Impact
41 percent of checkout attempts failed during the window. We estimate 3,900 lost orders and 24,000 dollars in refunds and goodwill credits. No customer data was lost.

Timeline of events
- 2026-10-14 08:40 deploy of release 2026.10.3
- 2026-10-14 09:12 error rate alert fires
- 2026-10-14 09:27 rollback attempted, image not cached, 12 minutes
- 2026-10-14 09:59 checkout restored

Actions
Owner: Marco Diaz. Action: keep the last three release images in the build cache, due 2026-11-14. Owner: Wen Li. Action: add a schema compatibility check to the deploy pipeline, due 2026-12-01. Owner: Marco Diaz. Action: document the rollback runbook, due 2026-11-28.

Open questions
We do not yet know why the release pipeline did not block on the schema change. We need to check whether the check exists but was disabled, or whether it was never implemented.

Lessons
A deploy that cannot be rolled back quickly is a deploy that will cost us an hour. We should treat image caching as part of the release process rather than an optimisation.
""",
    },
}


SAMPLE_ORDER = [
    "checkout-postgres-memo",
    "pricing-proposal",
    "payment-processor-rfc",
    "hiring-spike",
    "launch-status",
    "incident-postmortem",
]


def list_samples():
    return [
        {
            "id": sid,
            "title": SAMPLES[sid]["title"],
            "blurb": SAMPLES[sid]["blurb"],
            "doc_type": SAMPLES[sid]["doc_type"],
            "stakes": SAMPLES[sid]["stakes"],
            "reversibility": SAMPLES[sid]["reversibility"],
            "audience": SAMPLES[sid]["audience"],
            "words": len(SAMPLES[sid]["text"].split()),
        }
        for sid in SAMPLE_ORDER
    ]


def get_sample(sid):
    return SAMPLES.get(sid)
