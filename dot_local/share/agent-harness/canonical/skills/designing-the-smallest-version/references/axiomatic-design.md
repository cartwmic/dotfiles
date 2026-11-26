# Axiomatic Design step (Step 4b)

What an agent needs to run the design-matrix step. Quotes are cited by source id (list at the end) with a section or theorem where one is known. No URLs were verified: find a source by its title.

## The method

1. Write the **FRs**: what the system must do, independent of each other and neutral about the solution.
2. Pair each FR with one **DP**, the part of the design that delivers it. The matrix is then square.
3. Mark X where a DP affects an FR other than its own, 0 elsewhere.
4. Classify: **uncoupled** (diagonal), **decoupled** (triangular after reordering; the DPs must be set in that order: "the independence of FRs can be guaranteed if and only if the DPs are changed in a proper sequence", Suh96, **coupled** (anything else).
5. For a coupled block, find the DP choice that causes it and change it: add a DP, change one, fix the order, or relax or merge an FR. Example: "make DP12 = accelerometer. Then the design matrix becomes triangular" (Suh01b). Relaxing: "the designer must compromise the FRs by eliminating some of the FRs or by giving much larger tolerance" (Suh96b). AD does not say how to decouple (Shin06).
6. Zigzag: decompose one level down only where needed, pairing new FRs with new DPs (Suh96).

Not square (Suh96 App. 1-A): fewer DPs than FRs, "either a coupled design results, or the FRs cannot be satisfied" (Theorem 1); more DPs than FRs, "a redundant design or a coupled design" (Theorem 3); an ideal design has as many DPs as FRs (Theorem 4); adding DPs can decouple (Theorem 2).

## How this skill applies it

**FRs** are written in Step 3, before the parts inventory, from owner intent and never from the code: "If FRs are defined based on an existing design, then we will simply be specifying the FRs of that product" (Suh96b); "FRs must be defined without ever thinking about something that has been already designed" (Suh96). 5 to 9 at level 1. Test each: would it still hold after a rewrite with a different structure? If it names a file, module, table or mechanism, it is a DP. Bad: "Ledger module stores asks". Good: "Every owner ask is kept until answered". Six FRs that map to six files are the anti-pattern: that is the code's structure written as requirements.
- With a `requirements/2` register, every product or behavioral `R` row maps to exactly one FR. A row that maps to none is a missed FR, a constraint, or accidental behaviour; record which.
- `quality` and `technical` rows are **constraints** by default: they "provide the bounds on the acceptable design solutions and differ from the FRs in that they do not have be independent" (Suh96). A quality becomes an FR only if the owner names it as a top-level FR.
- The owner confirms the list when the session can ask; else mark it `unconfirmed` and list it under Section 8 "Decide".

**DPs**: one per FR. As found, the existing part or set of parts that delivers the FR, so a DP is not "a source folder" (Suh and Do map an FR to an object and a DP to its data, SuhDo00 §2; Pimentel and Stadzisz map use cases to FRs and collaborations to DPs, Pim06 §2). A part may sit in several DPs, but each pair of such DPs needs an X between them or a written reason (`## Shared`); a DP delivering several FRs (a god module) is a coupled or redundant design that owes a fix.

**Matrix**: tables in the format at the head of `scripts/design_matrix.py`, one for as found and one for the target. The script rejects an X without reason or evidence, classifies, orders, lists coupled blocks (strongly connected components, using repo_facts.py), and with `--as-found` checks that every dropped X names the decision that removes it. It lists a **fix owed** for each coupled block, DP delivering several FRs, unmet FR and non-square result. Link each fix to a Section 5 decision and a Section 6 increment, or record the reason the owner accepted. Removal candidates (a DP no FR names) and FRs without a DP become simplifications. Increments that build DPs follow the target DP order, or the design says why not.

**Zigzag**: at most 2 levels, inside a coupled block or for an FR the redesign changes.

## The X rule (this skill's convention, not Suh's)

Mark X(i,j), i not j, when **changing DP j to tune its own FR forces a change to keep FR i met**. Each X has a one-line reason and evidence: a code `path:line`; a change-coupling pair from `repo_facts.py` (`cochange:<a>+<b>`); a commit (`commit:<sha>`); a register finding id (`F-n`, `DF-n`, `U-n`). In a target matrix (`--target`; mode B has no as-found table) it cites the DESIGN.md decision, gap, tension or requirement that creates the dependency (`D2`, `G1`, `T1`, `OR-3`); the script refuses a target X that cites only `path:line`, since the target has no code yet. An import alone is not an X. Co-change is correlation: an X resting only on it needs a reason that stands on its own. In the audits found the engineer judges each cell by hand (Yoong20 §3.1); that judgment is the work. The evidence check is format only: the script sees that an X cites something, not that the citation shows coupling. A small term is a tolerance call (Suh01b): record it only if it can break the FR.

## What the matrix shows that the other passes do not

`repo_facts.py` and `auditing-clean-architecture` report dependencies between code parts. The matrix relates functions to parts: it can show a part that cannot be tuned for one FR without moving another, and an FR nothing delivers. A code dependency measures reach, not functional independence (MacC08 §4, Sang05 abstract). DESIGN.md says what the matrix added; "nothing new" is allowed.

## Limits (keep them in DESIGN.md)

- **The result depends on how you decompose**: "difficulties in developing a good decomposition, and appropriately prioritizing the elements, are common impediments" (Brown11 abstract). Say which FR list you used.
- **A part serving several FRs is not coupling by itself**: "Many practitioners are confused by coupling and physical integration" (Park11 §6); independence is of functions, not parts (Suh96). The script does not judge a shared part: it asks for an X or a written reason per pair of DPs.
- **Good designs can be coupled**: "Many mature and evolved designs are strongly coupled and are considered good designs" (Jones17 §A; an assertion without data). A coupled result is a finding; the fix may cost more than it saves.
- **The axioms are heuristics**: "hypotheses" (MF09 §2.4); AD is "a design method rather than a design theory" (Thom11 fn. 2).
- **No source recovers an AD matrix from existing code.** The audits found are one plant (Yoong20) and one industrial case (Nord96). Applying the method to an as-found codebase is this skill's adaptation; the as-found matrix is a judgment, not a measurement.
- The Information Axiom is not used: for software FRs with no design range it is "either zero or infinity" (Suh01a).
- Large matrices are hard to read (SciRep25 intro): keep level 1 small.

## Sources

Titles and the short extracts quoted above, to check at the source. No URLs were verified.

| Id | Source |
|---|---|
| Suh96, Suh96b | N. P. Suh, Introduction to Axiomatic Design, ch. 1 (draft), 1996, MIT 2.882; two saved copies |
| Suh01a, Suh01b | N. P. Suh, Axiomatic Design: Advances and Applications, 2001, Oxford UP; ch. 5 excerpt, and the glass-bulb and ABS excerpt |
| SuhDo00 | N. P. Suh, S. H. Do, Axiomatic design of software systems, 2000, CIRP Annals 49/1 |
| Pim06 | A. R. Pimentel, P. C. Stadzisz, A use case based object-oriented software design approach using the axiomatic design theory, 2006, ICAD2006-29 |
| Yoong20 | C. H. Yoong et al., Towards systematically deriving defence mechanisms from functional requirements of cyber-physical systems, 2020, CPSS '20 |
| Nord96 | M. Nordlund, D. Tate, N. P. Suh, Growth of Axiomatic Design through industrial practice, 1996, 3rd CIRP Workshop, Tokyo |
| Shin06 | G.-S. Shin, Decoupling process of a coupled design using the TRIZ module, 2006, ICAD2006-04 |
| Park11 | G.-J. Park, Teaching Axiomatic Design to Students and Practitioners, 2011, ICAD-2011-29 |
| Jones17 | H. W. Jones, Axiomatic Design of Space Life Support Systems, 2017, ICES-2017-82 |
| Brown11 | C. A. Brown, Decomposition and prioritization in engineering design, 2011, ICAD2011-07 |
| MF09 | J. R. A. Maier, G. M. Fadel, Affordance based design: a relational theory for design, 2009, Research in Engineering Design 20:13-27 |
| Thom11 | S. C. Thompson, Rational Design Theory, PhD dissertation, Georgia Tech, 2011 |
| MacC08 | A. MacCormack, J. Rusnak, C. Baldwin, Exploring the duality between product and organizational architectures, HBS working paper 08-039 |
| Sang05 | N. Sangal, E. Jordan, Using dependency models to manage complex software architecture, 2005, OOPSLA |
| SciRep25 | An axiomatic system engineering design method based on NSGA-II algorithm applied to complex systems, 2025, Scientific Reports |
