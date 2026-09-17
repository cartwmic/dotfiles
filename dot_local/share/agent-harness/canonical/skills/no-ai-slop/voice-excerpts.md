# House voice excerpts

Verbatim passages from documents and team-channel posts the repository owner wrote,
grouped by register. Use as exemplars under the Establish Voice step in
[SKILL.md](SKILL.md); the derived rules are in [voice-profile.md](voice-profile.md).

Internal service names, regions, tables, product terms, colleague names, and company
names are genericised — `ServiceA`, `ServiceB`, `R1`, `the tracker`, `[stakeholder]`,
`[the company]`. Sentence structure, punctuation, hedging, and typos are unchanged.
Genericised passages preserve sentence shape.

Additional sources include review comments on a shared proposal, task prompts, and a small
set of direct-message excerpts the owner explicitly supplied. All follow the same
genericisation rules.

Do not copy these sentences into a document. Match their construction. Only the
blockquotes are voice evidence; surrounding prose records provenance and register boundaries.

---

## Opinion and recommendation

> This is not meant to be a full comparison or a universal ranking. It is a short list of patterns I have found useful after spending a lot of time with both tools personally and at work.

> If you can use both, I think that is probably the strongest setup. If you cannot, I would not assume Claude is automatically the better engineering tool.

> I've found that context hygiene matters a lot more than I originally thought. I used to think, I get 200k context, might as well use it up!

> For personal projects, that difference matters a lot. For work, less so.

> Some of my earlier frustration with Claude around following instructions specifically may have been partly mixed up with weaker context-management habits on my side at the time, so I do not think the comparison is perfectly clean.

> Can also use a sub agent for this.

> In my brief testing so far, it's been a good setup.

---

## Design and decision

> ServiceA is already a public HTTP service (albeit with auth as another layer of security) - adding an additional HTTP service that interacts with ServiceA data doesn't introduce new attack vectors but increases the size of the existing attack vector. I think this is potentially acceptable from a security standpoint.

> This simple solution is not throwaway work. An HTTP Server accessing data from a data store will be required in all designs.

> The simplicity of implementation is very much worth the tradeoff of losing real time updates — especially given our 24hr SLA for our data.

> We have [time remaining] until [deadline]. The lowest estimate solution is [total estimate] ([backend estimate]) weeks. The simpler the better even with multiple engineers working on it.

> Answer - likely doesn't matter but will need to troubleshoot come implementation

> Likely not materialized views due to no known prior art here and that they are in preview.

> If we take a step back, we can actually view the above design suggestions as iterations chasing the following goal - decoupling ServiceB from ServiceA as needed.

> I would place this as the least secure method of interacting with ServiceA data as it increases the attack surface by adding another publicly accessible service with access to that data.

---

## Specification

> Any later edit to those columns — or to the inputs/outputs a judge consumes — requires a fresh privacy review.

> Output is null (actual null, not the string "null") when no field value is surfaced in the response.

> Note: online eval provides a plausibility proxy; definitive measurement requires offline eval with gold labels.

> The user_id is included (unlike some telemetry systems that drop it) to support per-user quality analysis

> The following are dashboard-level aggregations over existing metric outputs, not separate services. They require no new judge calls or embedding computations.

> Only the label is durably stored.

Plain micro-head examples use a fragment as a label, followed by explanation:

> Signal classification.
> What is durably stored.
> Orthogonal signals.

---

## Systems explainer

> The nature of [this process] is spread across a number of different services, with each service owned by a different team, and each team making changes often without the knowledge of other teams.

> However, this document should still serve as a good basis for the general flow regardless of future changes (unless a total refactor is performed across these services/teams!)

> "Stale" in this context means records that have a date_created value before some passed in time value. Essentially, records that are stuck in that table are considered "stale"

> As of [date], ServiceA still sets status manually

> Relevant because it is responsible for handling the deletion queue and actual deletion automatically via a cronjob

---

## Incident review

Synopsis opening with genericised values:

> Starting on [time] and lasting until [time] ([computed duration]), [N] customers experienced at least [lower bound] and up to [upper bound] of [degradation]. During this time, nearly all of the impact was in [region], where [count] were affected and up to [count] of those could have shown as failed to the user.

> This is a repeat of a similar incident that happened in [region] on [date]. No review was created for this previous event, but the symptoms exactly match what we see in this incident, along with an identified root cause being the same as in this incident. The solution to the root cause of this previous incident was not implemented, leading to his incident.

> The above abbreviated history illustrates the inconsistent ownership of the service which, in large part, motivated [a later ownership change].

> Because they thought their role was to shadow and that the primary on call engineer would be able to handle the situation given the details they were aware of at the time

> [The team] are not [that system's] experts

> The context around [the deprioritised project] is important to understand because it clarifies where engineering effort has been spent over [a multi-year period]

> While the error logs were elevated, the [subject-matter expert] in the call did not think they were a root cause but instead thought they were more likely a symptom of some sort (a red herring)

> Many of the dashboards have graphs with no or missing data, graphs on metrics without context on what the metrics mean, a general disorganization within dashboards, etc.

Closing of a review — a short deficit inventory, no synthesis:

> - [The service] has insufficient testing for edge case/load based scenarios (manual or automated)
> - There is a lack of knowledge around the service and common libraries
> - [The service] is missing metrics/alerts
> - [The service] may not be following best practices given it's age

---

## Review comments on a shared proposal

Doc comments the owner posted on a colleague's design document. This register uses
questions that carry the objection, hedged pushback, and self-deprecating follow-ups.
Product, model, person, and company identifiers are replaced. These excerpts are
unmeasured.

> Does this essentially mean "agent driven workflows via chat interface"
>
> Trying to understand the exact intent here

> This also needs defining/contextualizing IMO. perhaps before tenets we include an example "happy path" to follow along and get the general shape of "what this [framework] is"?

> What is the difference between a critical and important requirement?

> I truly am not being critical for the sake of disparaging the idea - I mean this to seek further clarity on the idea and applicability for us at [the company].
>
> But is the tenets described here that govern the shape of the [framework] not just describing existing harnesses with first class support for workflows built in?

> I.e. [ModelA] has workflow concepts + of course skills + orchestration, etc.
>
> so does [ModelB], there's even open source harnesses that let you tune the harness exactly as you'd like, extend it infinitely, etc.

> mostly curious how this differs if it does at all (perhaps it's an implementation detail in this context?)

> e.g. [an open source harness]
>
> I use this myself at work and at home and have tuned it extensively to my own needs for example

> This to me reads like "there could be an option of saving these assembled _workflows_ for any future use and for sharing with others"
>
> IMO an agent uses a workflow, and workflows can themselves have steps that invoke agents which could in theory invoke further workflows. IDK why i'm stuck on this :P

> No, the idea on principle makes sense, I'm just arguing semantics heh

> The framing of agent as a workflow is also a bit counter intuitive to me given how we use agents in our day to day dev environments. IMO, a workflow is a workflow, an agent invokes and orchestrates no? not sure if the distinction is meaningful here though.

> What plan do you mean here? From a [methodology] perspective, this would mean the plan to implement a list of requirements/intents. but if the framework is workflow agnostic, then plans may not apply to all workflows? Clarity on the definition would be awesome.

> can we link to what this is for those ignorant among us... ;P

> another implementation detail, but I've enjoyed using [a memory service] as a drop in no tuning comprehensive memory management system for my own harness. this or something like this might be viable for even _user_ specific memory that agents can reach for.

> what is the compaction process? this may be more of an implementation detail, just curious if you already had an idea of how you will compact in practice (i.e. what's the compaction prompt)

> I think something like this could be a great second iteration goal if initially too complex.

---

## Tasking prompts

The owner's recent task prompts to agents: first person, imperative, one gap offered with
hedging, subagent policy inline. Same anonymisation rules. Not counted in the profile.

> audit the way we calculate spend and savings in the [dashboard] for correctness against current frontier models. one gap I might have found is we don't take into consideration the caching pricing that commercial providers use, so our cost savings are inflated. find other issues if there are any and report them. you may use subagents as needed to review and audit. if you do, use [ModelA] agents

> validate your findings are true with an [ModelB] from [ProviderA] blind subagent

> give me a useable, not noisy, monitor command to allow me to monitor myself

> make it so it only ever shows the last 5 lines, but always the header

> that redraws over my command submission, which is bad ux. any solution?

> 1. make sure the acceptance criteria doesn't allow implementation to game the validation by artificailly forcing the length of the candidate draft to match the certified draft - the candidate draft should organically reach semantic similarity to the candidate draft in prose if not fully length without superflous additions and gaming
> 2. is the listed template structure correct? please validate the [provider] template structure for me
> 3. we need to explore and settle on what "review" means in the drafting graph. I think it should be somewhat similar to [the other provider]
>
> I've otherwise made minor edits to the current intent. address the above for me

---

## Casual status, outreach, and alignment

Casual Slack writing. Use this register only for casual/status work. Private exchanges
appear where the owner explicitly supplied redacted excerpts; other private exchanges
contribute aggregate traits only. Keep emoji, word-level italics, thank-you closers, and
live-chat fragments out of specifications, designs, and incident reviews.

Shape of a status update with genericised work items:

> Update for those curious:
> • Met with [stakeholder] last week to go over the PRD draft I had for the [review] automation I've named `ProjectA`
> • [stakeholder] had a lot of good feedback on improvements I could make, things I could naildown/explore, people and prior art I could reach out to and investigate.
> • So far this week I've been working on that feedback and integrating it into a new draft of the PRD that I will post when it's ready.
> • In the meantime, [stakeholder] and I have mutually agreed that some general purpose "[Review] Draft" evaluation framework/harness is merited on its own regardless of how `ProjectA` eventually is implemented. I will start on this harness tomorrow
> • The goal after the harness is in place is to begin evaluating existing [review] drafting solutions at [the company], then prototype a basic version of `ProjectA`, then compare the results.

> things I could naildown/explore, people and prior art I could reach out to and investigate.

> I will start on this harness tomorrow

> Summary of my alignment with [colleague] from the misunderstanding at the sync meeting:

> Think of the situation "`ProjectA` drafts good [reviews], I just used it to draft my [review] and passed through the workflow's quality gates with flying colors, let me just jump straight in to review meetings!". The author then gets destroyed in their review meetings because they can't defend the claims/narrative/RCA in the [review] that was drafted.

> [colleague] is suggesting adding explicit tooling/support in `ProjectA` to help substitute the implicit understanding an author gets from drafting their own [review]. E.g. a guided "understand the [review] to be able to defend it and explain it yourself" step of the `ProjectA` workflow
> I agree with this take and will incorporate it as such in the PRD soon here. Thank you [colleague] :)

> `ProjectA` isn't pretending to help manage follow through of action items, that's a separate issue, but there _should_ be tooling and gates in place to help guide authors through how to help ensure good active ownership of action items that come from the [reviews] drafted via `ProjectA`.

> More specifically, the _active_ ownership of those action items.

> I will also add this into the prd going as well. Thank you [colleague] :)

---

Public-channel exemplars. Product, model, organization, person, date, and quantity
identifiers are replaced. Sentence structure, punctuation, hedging, and typos are unchanged.

> Another update on my `ProjectA` workstream. Writing here for posterity. I will still be attending the weekly sync.

> I decided it would be better to start fresh with a simpler approach to the workflow, so I had agents implement most of that workflow over the weekend and am much happier with the current work, but have not gotten to the point of a full eval run over an existing [artifact] and it's backing evidence against the [review criteria], nor against nominal AI metrics like citation/evidence precision, recall, hallucination, etc.

> I of course and very optimistic it will be worth it and will have a strong narrative for [authors] to continue to adopt, but I want the numbers and the evidence/testimonies to back that up after these [time period].

> Summary - my timeline is beginning to slip, but will decide if meaningfully slipped or not by next weeks update.

> I've come to really appreciate [ModelA] + [ModelB] as a capable and in many cases seemingly cheaper or more efficient alternative than [ModelC] + [ModelD], the latter being quite inconsistent and prone to overconfidence whereas the former exhibits stronger agentic capabilities at the risk of overengineering tendencies (in my own experience at home and at work).

> I'm also aware we _used_ to have access to [ToolA] which included the [ModelA] models and that is no longer the case. I'm not sure if that is a fully shut door, but would love some way to get access to [ModelA] models again once [ToolB] loses access.

> I'm always open to helping out, what would this look like? We can chat separately about this also. If we can optimize how quickly we can exchange and/or additionally host open source models that would be awesome

> Nice to hear. At the end of the day, whatever works best for us to have simple and relatively cost effective access from a company resources perspective, I'm down for. I'm not married to [ProviderA] as the provider by any means :P

> Anyways, I digress. Hoping other's are feeling similarly and there might be a reasonable path towards more flexible model usage here :)

Shape of a counter-experience post:

> A counter experience. I've completely switched off of [ModelA] for [ModelB] (I have not tried [ModelA]'s latest though). To me its much better at being "agentic" if that makes sense and in the work I'm doing at home, agent/developer tooling, it has been more consistent, capable, and reliable at getting things done.

> I use a fairly opinionated custom agent graph solution for doing autonmous software change work, which I've built to include lots of direction and handholding throughout the last few months as I've used many different models from frontier to [ModelC], [ModelD], [ModelE], etc. Those lesser, older models definitely need the guardrails and restraints to strong arm them into doing decent software work.

> [ModelA] didn't need nearly as much of the harness features to get better work done, but I found myself questioning its completeness and direction following.

> AKA less of me teaching the model what I think the best process is and more it just knowing for the most part.

> The major caveat here is that the majority of my experience with [ModelA] and [ModelB] (and other models for that matter) have been in my tuned workflow. I've done some adhoc/one shot work for small utilities, scripts, and changes to existing code. While my amount of experience in this area is somewhat less, I still think those patterns I've noticed are still largely present in this "unstructured" work - which makes sense given my what I've noticed from the model in general.

> Outside of software, I've found the general knowledge of [ModelB] more capable than [ModelA], but I don't often reach for the frontier models in these circumstances so I can't say if I truly would advocate for [ModelB] being better in non software tasks. The benchmarks seem to indicate such, but we know how that can be...

> It has gotten to the point that I'm, like, pretty bummed we don't have access to it for software related work :P

Explicitly supplied direct-message excerpts. The owner asked for these to be retained;
identifiers are replaced and the voice is left intact. Conversational register only.

> so the tool is "useable" but honestly not super "useful" atm. so let's take the time i set aside for us to start drafting the spec together with my agent. I'll drive and we'll just talk it out and have some draft at the end of the meeting. doesn't need to be perfect, just need to get your pm thoughts and my engineering thoughts out of our heads and onto a paper in some form. then after the tool is in a better spot, we use the existing draft as the baseline and I'll run it through the tool to conform it to the "correct" output and we can go from there

> I used to feel confident in [DomainA], somewhat confident in [DomainB], not really in [DomainC]. but we've been out of those areas for so long... I wouldn't feel confident now haha

> for some additional historical context on me pre AI era - I'm the guy who codes in the terminal with [EditorA] lol so [ToolA] to me is like [EditorA] is to ides

> for myself, ive adopted this "no-ai-slop" skill that I've been tailoring. its basically like "don't do the following [ModelA]isms" and a bunch of examples and excerpts of how I normally write (e.g. even in this conversation I could add anonymized version as excerpts) to try to get it to write more like I do
>
> I've had mixed results. it writes better, especially when used with [ModelA], but it's still pretty clearly AI.

> I'm torn because, as long as the content is meaningful, digestible, relevant, and not fluffed, then I don't really care if it seems like its AI. except for maybe common [ModelA]isms. I cant stand [ModelA] writing.
>
> but you're very right, most of the people who use ai to write aren't curating it enough and it really effects my motivation to want to consume or analyze the text

> part of me is also like "eh it is what it is" for now mostly because things are improving so much faster than I thought. I could see a conversation like ours being outdated and like "what were we even worried about" in like 6 months or a year.

> but it sure does suck now

> interestingly enough, I haven't really thought to try to optimize for speed. just hasn't been a limiting factor enough to factor into my analyses

> it lines up a bit for me. I've often felt [ModelB] was much more "verbose" in its reasoning steps which made it take longer between actions. but, again, its not something I look for so could be a bit of confirmation bias for the topic

> since [ProviderB] has been memed on so hard prior to their recent model releases, [ProviderB] models had fallen into my "too many models to try so I don't bother" category for most of my time using llms.

> also it is so exhausting keeping up with these things man. like I find it so fun in a lot of ways but its like a never ending onslaught lol
