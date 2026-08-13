# House voice excerpts

Verbatim passages from documents the repository owner wrote, grouped by register. Use as
exemplars under the Establish Voice step in [SKILL.md](SKILL.md); the derived rules are in
[voice-profile.md](voice-profile.md).

Internal service names, regions, tables, and product terms are genericised — `ServiceA`,
`ServiceB`, `R1`, `the tracker`. Sentence structure, punctuation, hedging, and typos are
unchanged, because those carry the voice and the proper nouns do not. Where an excerpt's
value was its shape rather than its content, only the shape is given.

Do not copy these sentences into a document. Match their construction.

---

## Opinion and recommendation

> This is not meant to be a full comparison or a universal ranking. It is a short list of patterns I have found useful after spending a lot of time with both tools personally and at work.

Opens by narrowing the claim. Substitutes personal experience for universal authority.

> If you can use both, I think that is probably the strongest setup. If you cannot, I would not assume Claude is automatically the better engineering tool.

Hedged superlative, then a firmer warning against the default assumption.

> I've found that context hygiene matters a lot more than I originally thought. I used to think, I get 200k context, might as well use it up!

Admits a changed mind and reenacts the old thought informally. Comma splice and exclamation left intact.

> For personal projects, that difference matters a lot. For work, less so.

Closes a comparison on a fragment instead of restating the reasoning.

> Some of my earlier frustration with Claude around following instructions specifically may have been partly mixed up with weaker context-management habits on my side at the time, so I do not think the comparison is perfectly clean.

Stacked hedges that assign part of the problem to himself.

> Can also use a sub agent for this.

Subjectless afterthought fragment.

> In my brief testing so far, it's been a good setup.

How a document ends: a small, provisional experience report. No summary, no call to action.

---

## Design and decision

> ServiceA is already a public HTTP service (albeit with auth as another layer of security) - adding an additional HTTP service that interacts with ServiceA data doesn't introduce new attack vectors but increases the size of the existing attack vector. I think this is potentially acceptable from a security standpoint.

Names the degradation precisely, then marks acceptance as a personal, hedged judgment rather than a fact. This is the canonical example of rule V1.

> This simple solution is not throwaway work. An HTTP Server accessing data from a data store will be required in all designs.

Anticipates the obvious objection and answers it with a reusable-core argument.

> The simplicity of implementation is very much worth the tradeoff of losing real time updates — especially given our 24hr SLA for our data.

Endorses the weaker behaviour openly by tying it to an already accepted tolerance.

> We have ~9 weeks until [deadline]. The lowest estimate solution is 24 (16 backend) weeks. The simpler the better even with multiple engineers working on it.

Rough numbers and a compressed maxim, letting schedule pressure override architectural purity.

> Answer - likely doesn't matter but will need to troubleshoot come implementation

Records uncertainty in place and defers to implementation instead of manufacturing confidence.

> Likely not materialized views due to no known prior art here and that they are in preview.

Terse hedge with two practical reasons attached. Rule V3.

> If we take a step back, we can actually view the above design suggestions as iterations chasing the following goal - decoupling ServiceB from ServiceA as needed.

Reframes competing options as an incremental sequence, with informal transition language.

> I would place this as the least secure method of interacting with ServiceA data as it increases the attack surface by adding another publicly accessible service with access to that data.

Personal ownership of a debatable ranking, inside an otherwise impersonal document.

---

## Specification

> Any later edit to those columns — or to the inputs/outputs a judge consumes — requires a fresh privacy review.

States the contract, then the change-control consequence. Rule first, reason second.

> Output is null (actual null, not the string "null") when no field value is surfaced in the response.

Anticipates the likely implementation error and specifies both the correct representation and its trigger.

> Note: online eval provides a plausibility proxy; definitive measurement requires offline eval with gold labels.

Warns against overclaiming the mechanism he is himself specifying.

> The user_id is included (unlike some telemetry systems that drop it) to support per-user quality analysis

Acknowledges the alternative in brackets, then gives the reason for the chosen contract. Rule V7.

> The following are dashboard-level aggregations over existing metric outputs, not separate services. They require no new judge calls or embedding computations.

Defines category membership by saying what the items are and are not.

> Only the label is durably stored.

Repeated verbatim rather than stated once globally, so the constraint is visible locally. Repetition is deliberate; do not vary it for elegance.

Plain micro-heads used instead of bold lead-ins — a fragment as a label, then explanation:

> Signal classification.
> What is durably stored.
> Orthogonal signals.

---

## Systems explainer

> The nature of [this process] is spread across a number of different services, with each service owned by a different team, and each team making changes often without the knowledge of other teams.

Attributes uncertainty to the organisation rather than to himself.

> However, this document should still serve as a good basis for the general flow regardless of future changes (unless a total refactor is performed across these services/teams!)

Rescues the document's usefulness after a caveat. Weary humour in the parenthetical; the exclamation mark is his.

> "Stale" in this context means records that have a date_created value before some passed in time value. Essentially, records that are stuck in that table are considered "stale"

Technical definition first, then a plainer restatement introduced by "Essentially". Scare quotes mark a locally defined label.

> As of [date], ServiceA still sets status manually

Date-stamps a claim inline rather than versioning it abstractly. Rule V5.

> Relevant because it is responsible for handling the deletion queue and actual deletion automatically via a cronjob

Annotates a definition with why the reader should care about it, as a separate line.

---

## Incident review

Synopsis opening — reuse the shape, not the numbers:

> Starting on [time] and lasting until [time] ([computed duration]), [N] customers experienced at least [lower bound] and up to [upper bound] of [degradation]. During this time, nearly all of the impact was in [region], where [count] were affected and up to [count] of those could have shown as failed to the user.

Exact endpoints, a parenthetical duration, then impact bounded on both sides with "at least", "up to", "nearly all", "could have".

> This is a repeat of a similar incident that happened in [region] on [date]. No review was created for this previous event, but the symptoms exactly match what we see in this incident, along with an identified root cause being the same as in this incident. The solution to the root cause of this previous incident was not implemented, leading to his incident.

States the uncomfortable finding plainly, substantiates recurrence before assigning follow-through failure, and names no individual. The `his` for `this` typo is his.

> The above abbreviated history illustrates the inconsistent ownership of the service which, in large part, motivated the creation of the current team.

Blunt organisational criticism, cushioned by "abbreviated" and "in large part".

> Because they thought their role was to shadow and that the primary on call engineer would be able to handle the situation given the details they were aware of at the time

Gives a wrong call the benefit of what was known at the time. Rule V11.

> [The team] are not [that system's] experts

Admits a capability gap without euphemism, then elevates it from a team deficiency to a system-design mismatch.

> The context around [the deprioritised project] is important to understand because it clarifies where engineering effort has been spent in the last 2 years

Justifies a digression before taking it, rather than apologising for it.

> While the error logs were elevated, the [subject-matter expert] in the call did not think they were a root cause but instead thought they were more likely a symptom of some sort (a red herring)

Narrates a wrong turn as a sequence of appearance and interpretation, not as an individual's mistake.

> Many of the dashboards have graphs with no or missing data, graphs on metrics without context on what the metrics mean, a general disorganization within dashboards, etc.

Blunt defect inventory ending in "etc." rather than a padded complete list.

Closing of a review — a short deficit inventory, no synthesis:

> - [The service] has insufficient testing for edge case/load based scenarios (manual or automated)
> - There is a lack of knowledge around the service and common libraries
> - [The service] is missing metrics/alerts
> - [The service] may not be following best practices given it's age

The most critical item is hedged with "may", and the list simply stops.
