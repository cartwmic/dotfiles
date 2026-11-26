# Axiomatic Design step (Step 4b)

What an agent needs to run the design-matrix step. Read it when Step 4b says so. Sources are cited as author, title, year, venue and locator; the research behind them is the report "What an Axiomatic Design audit really involves" (no URLs: none were verified). `l.N` is a line number in the saved text of the source, `~` means within about 5 lines.

Contents: the method · the steps · the X rule · what the matrix does not show · limits · sources

## The method in six lines

1. Write the **FRs**: what the system must do, independent of each other and neutral about the solution.
2. Pair each FR with one **DP**, the part of the design that delivers it. The matrix is then square.
3. Mark X where a DP affects an FR other than its own, 0 elsewhere.
4. Classify: **uncoupled** (only the diagonal), **decoupled** (triangular after reordering; the DPs must be set in that order), **coupled** (anything else). Suh, ch. 1, 1996: "When the matrix is triangular, the independence of FRs can be guaranteed if and only if the DPs are changed in a proper sequence" (l.~951-956).
5. Where it is coupled, find the DP choice that causes it and change it: add a DP, change one, fix the order, or relax or merge an FR. Suh, *Axiomatic Design: Advances and Applications*, 2001 (excerpt, ABS example, l.~1743): "make DP12 = accelerometer. Then the design matrix becomes triangular". Axiomatic design itself does not say how to decouple (Shin, "Decoupling process of a coupled design using the TRIZ module", ICAD2006-04, intro; the report names Park as co-author, the saved text shows only Gwang-Seob Shin).
6. Zigzag: decompose one level down only where it is needed, pairing the new FRs with new DPs (Suh 1996, l.~1012-1016).

Theorems for a matrix that is not square (Suh 1996, App. 1-A): fewer DPs than FRs means "either a coupled design results, or the FRs cannot be satisfied" (Theorem 1); more DPs than FRs means "either a redundant design or a coupled design" (Theorem 3); an ideal design has as many DPs as FRs (Theorem 4). Adding DPs can decouple (Theorem 2).

## The steps here

**FRs.** 5 to 9 at level 1, written from owner intent: the owner's words, an interview answers file, the README or PRD purpose. Never from the code's structure: "If FRs are defined based on an existing design, then we will simply be specifying the FRs of that product" (Suh 1996, l.~1141); also "FRs must be defined without ever thinking about something that has been already designed" (Suh 1996, 1.7.3). Test each: would it still hold after a rewrite with a different structure? If it names a file, module, table or mechanism, it is a DP.
- With a `requirements/2` register: every product or behavioral `R` row maps to exactly one FR. A row that maps to none is a missed FR, a constraint, or accidental behaviour; record which.
- `quality` and `technical` rows are **constraints** (Cs) by default: "Constraints provide the bounds on the acceptable design solutions and differ from the FRs in that they do not have be independent" (Suh 1996, l.979-982). A quality becomes an FR only if the owner names it as a top-level FR.
- The owner confirms the list when the session can ask. Otherwise mark it `unconfirmed` and list it under "Open for owner".

**DPs.** One per FR. As found: the existing part or set of parts that delivers the FR (so "DP = a source folder" is not the rule: Suh and Do map an FR to an object and a DP to its data, "Axiomatic design of software systems", 2000, CIRP Annals 49/1, section 2; Pimentel and Stadzisz map use cases to FRs and collaborations to DPs, ICAD2006-29, section 2). Write the parts in the DP table's `parts` column. Target: the parts of the target design. A DP that no FR names is a removal candidate; an FR with no DP is unmet.

**Matrix.** Write the table in the format at the head of `scripts/design_matrix.py` (FRs with their `dp`, DPs with `parts`, X cells with reason and evidence), once for as found and once for the target, and run `python3 <skill-dir>/scripts/design_matrix.py FILE --label "As found"`. It rejects a missing reason or evidence, classifies, orders, lists coupled blocks (strongly connected components, using repo_facts.py's code) and renders markdown for DESIGN.md.

**Zigzag.** Go one level down only inside a coupled block, or for an FR the redesign changes. At most 2 levels. Sub-matrices are smaller than 5 to 9 and the script does not mind.

**Fixes.** For each coupled block write one fix: add a DP, change a DP, fix the order, or relax or merge an FR ("the designer must compromise the FRs by eliminating some of the FRs or by giving much larger tolerance", Suh 1996, l.~1960-1966). Link each fix to a decision in Section 5 and an increment in Section 6. Removal candidates and FRs without a DP become simplifications. Re-render the target matrix after the fixes; it should be uncoupled or decoupled, or say why not.

## The X rule (this skill's convention, not Suh's)

Mark X(i,j), i not j, when **changing DP j to tune its own FR forces a change to keep FR i met**. Each X carries a one-line reason and evidence: a code `path:line`, a change-coupling pair from `repo_facts.py` (`cochange:<a>+<b>`), a commit (`commit:<sha>`) or a register finding id (`F-n`, `DF-n`, `U-n`). An import alone is not an X: a part may depend on another and be stable against it. In the audits found, the engineer judges each cell by hand (Yoong et al., "Towards Systematically Deriving Defence Mechanisms from Functional Requirements of Cyber-Physical Systems", 2020, CPSS '20, section 3.1); that judgment is the work here. A small term is a judgment call about tolerance (Suh 2001, l.~1911-1919): record it as X only if it can break the FR.

## What the matrix shows that the other passes do not

`repo_facts.py` and `auditing-clean-architecture` report dependencies between parts of the code. The matrix is between functions and parts: it can show a part that cannot be tuned for one FR without moving another, and an FR nothing delivers. A code dependency measures reach, not functional independence (MacCormack, Rusnak and Baldwin, "Exploring the Duality between Product and Organizational Architectures: A Test of the Mirroring Hypothesis", HBS working paper 08-039, 2007-2011, section 4; Sangal and Jordan, "Using Dependency Models to Manage Complex Software Architecture", OOPSLA 2005, abstract). State in DESIGN.md what the matrix added; "nothing new" is allowed.

## Limits (keep them in DESIGN.md)

- **The result depends on how you decompose.** "difficulties in developing a good decomposition, and appropriately prioritizing the elements, are common impediments" (Brown, "Decomposition and prioritization in engineering design", ICAD2011-07, abstract). Say which FR list you used.
- **A part serving several FRs is not coupling by itself.** "Many practitioners are confused by coupling and physical integration" (Park, "Teaching Axiomatic Design to Students and Practitioners", ICAD-2011-29, section 6). The independence is of functions, "not the physical parts" (Suh 1996, l.~862-864). The script reports shared parts and does not judge them.
- **Good designs can be coupled.** "Many mature and evolved designs are strongly coupled and are considered good designs" (Jones, "Axiomatic Design of Space Life Support Systems", 2017, ICES-2017-82, section A; an assertion with no data). A coupled result is a finding, not a defect; the fix may cost more than it saves. Slightly coupled designs are often relaxed instead of fixed.
- **The axioms are heuristics.** "the two axioms should not properly be called axioms, but rather hypotheses" (Maier and Fadel, "Affordance based design: a relational theory for design", 2009, Research in Engineering Design 20, section 2.4); AD is "a design method rather than a design theory" (Thompson, "Rational Design Theory: A Decision-Based Foundation for Studying Design Methods", PhD dissertation, Georgia Institute of Technology, 2011, fn. 2). Use independence as a test, not a law.
- **No source recovers an AD matrix from existing code.** The audits found are one plant (Yoong et al. 2020) and one industrial case (Nordlund, Tate and Suh, "Growth of Axiomatic Design through Industrial Practice", 1996, 3rd CIRP Workshop, Tokyo, pp. 77-84). Applying the method to an as-found codebase is this skill's adaptation; the as-found matrix is a judgment, not a measurement.
- **The Information Axiom is not used.** For software FRs with no design range it is "either zero or infinity" (Suh 2001, ch. 5 excerpt, l.1532).
- Large matrices are hard to read ("It is often difficult to visually identify the matrix structure", "An axiomatic system engineering design method based on NSGA-II algorithm applied to complex systems", 2025, Scientific Reports, intro): keep level 1 small and zigzag only where needed.

## Sources

| Author | Title | Year | Venue | Used for |
|---|---|---|---|---|
| Suh, N. P. | Introduction to Axiomatic Design, ch. 1 (draft) | 1996 | MIT 2.882 course text | method, theorems, FR and constraint rules |
| Suh, N. P. | Axiomatic Design: Advances and Applications (excerpts) | 2001 | Oxford University Press | ABS decoupling, tolerances, software chapter |
| Suh, N. P.; Do, S. H. | Axiomatic design of software systems | 2000 | CIRP Annals 49/1 | FR to object, DP to data |
| Pimentel, A. R.; Stadzisz, P. C. | A use case based object-oriented software design approach using the axiomatic design theory | 2006 | ICAD2006-29 | use cases as FRs |
| Yoong, C. H.; Palleti, V. R.; Silva, A.; Poskitt, C. M. | Towards systematically deriving defence mechanisms from functional requirements of cyber-physical systems | 2020 | CPSS '20 | as-found audit, manual X |
| Nordlund, M.; Tate, D.; Suh, N. P. | Growth of Axiomatic Design through industrial practice | 1996 | 3rd CIRP Workshop on Design and the Implementation of Intelligent Manufacturing Systems | audit outcome |
| Shin, G.-S. (the report also names Park) | Decoupling process of a coupled design using the TRIZ module | 2006 | ICAD2006-04 | AD does not say how to decouple |
| Park, G.-J. | Teaching Axiomatic Design to Students and Practitioners | 2011 | ICAD-2011-29 | physical integration |
| Jones, H. W. | Axiomatic Design of Space Life Support Systems | 2017 | ICES-2017-82 | good coupled designs |
| Brown, C. A. | Decomposition and prioritization in engineering design | 2011 | ICAD2011-07 | decomposition dependence |
| Maier, J. R. A.; Fadel, G. M. | Affordance based design: a relational theory for design | 2009 | Research in Engineering Design 20:13-27 | axioms as hypotheses |
| Thompson, S. C. | Rational Design Theory: a decision-based foundation for studying design methods | 2011 | PhD dissertation, Georgia Tech | AD as a method, not a theory |
| (authors not read) | An axiomatic system engineering design method based on NSGA-II algorithm applied to complex systems | 2025 | Scientific Reports | matrix readability |
| MacCormack, A.; Rusnak, J.; Baldwin, C. | Exploring the duality between product and organizational architectures: a test of the mirroring hypothesis | 2007-2011 | HBS working paper 08-039 | dependency reach |
| Sangal, N.; Jordan, E. | Using dependency models to manage complex software architecture | 2005 | OOPSLA | code DSM and design rules |
