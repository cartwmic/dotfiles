//! Frozen proposal-only doctrine. Source files are provenance, never runtime inputs.

use crate::policy::PolicyCase;
use serde::{Deserialize, Serialize};

#[path = "doctrine_cases.rs"]
mod cases;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Provenance {
    pub source_id: String,
    pub source_locator: String,
    pub source_clause: String,
    pub derivation: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct DoctrineClause {
    pub id: String,
    pub title: String,
    pub force: String,
    pub statement: String,
    pub rationale: String,
    pub operational_effect: String,
    pub evidence_of_drift_or_breach: Vec<String>,
    pub provenance: Vec<Provenance>,
    pub mapping_requirements: Vec<String>,
    pub reasons: Vec<String>,
    pub examples: Vec<PolicyCase>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct DoctrinePack {
    pub id: String,
    pub component_ids: Vec<String>,
    pub clause_ids: Vec<String>,
    pub authority: String,
    pub applicability: Applicability,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Applicability {
    pub shape_gate: String,
    pub inclusion_conditions: Vec<String>,
    pub omission_conditions: Vec<String>,
    pub override_rule: String,
    pub whole_pack_rule: String,
    pub mapping_rule: String,
    pub proposal_rule: String,
}

pub fn doctrine_clauses() -> Vec<DoctrineClause> {
    vec![
        tenet("T1", "Dependency-directed independence", "Inner core owns stable policy and defines abstractions. Outer delivery, adapters, frameworks, persistence, and vendors implement or translate those abstractions. Source dependencies cross boundaries inward only.", "Stable policy should outlive mechanism replacement.", "New dependencies and interface ownership preserve inward source direction.", &["framework convenience is chosen at policy-independence cost"], &["C1","C2","C16","C18"]),
        tenet("T2", "Domain model carries domain meaning", "Model important concepts and rules in inner core rather than primitives, transport shapes, or framework conventions.", "Important rules become harder to misuse when represented where they belong.", "Repeated meaningful concepts and state transitions gain domain vocabulary and constraints when value exceeds ceremony.", &["important state is represented by ambiguous primitives", "validation repeats at edges", "entities only hold fields while adapters decide behavior"], &["C9","C11","C12"]),
        tenet("T3", "Boundaries stay humble", "Untestable shells capture input, render output, and translate. Decisions and multi-step orchestration move into testable inner objects.", "Framework-controlled shells are hard to test and replace.", "UI, controllers, FFI, handlers, and persistence adapters capture, translate, delegate, and render; outer size alone is not drift.", &["delivery branches on business state", "adapter coordinates multi-step policy", "lifecycle callback contains domain decisions"], &["C13","C14","C15"]),
        tenet("T4", "Test seams, not internal structure", "Prefer behavior evidence through real adapters or inner-defined faithful fakes. Do not mock inner core merely to isolate implementation detail.", "Tests should survive refactors while exposing broken integration contracts.", "Exercise inner behavior through ports; mocking inner structure is last resort and needs rationale.", &["tests assert internal call order", "test mocks object under test", "adapter-free happy path is claimed as integration evidence"], &["C19"]),
        tenet("T5", "Abstractions must earn existence", "Add a port, layer, DTO, or indirection for demonstrated independence, testability, contract ownership, or credible replacement—not architectural ceremony.", "Dependency inversion without a boundary creates indirection, not independence.", "Every abstraction has current contract ownership, test seam, real replacement, or credible documented migration.", &["single implementation has no fake, swap pressure, contract role, or rationale"], &["C8","C9","C20"]),
        oxide_tenet("T6", "No fallback by default", "Failure stays failure unless fallback is explicit inner policy.", "Hidden fallback converts uncertainty into false success and creates parallel behavior.", "Fallback policy defines trigger, result semantics, observability, and limits; fail-closed protection is not silent fallback.", &["catch-all returns ordinary default", "stale-data fallback is undisclosed", "unknown value becomes ordinary mode"]),
        oxide_tenet("T7", "One load-bearing mechanism", "Each guarantee has one canonical enforcement mechanism. Defense in depth remains valid when controls address distinct failure modes.", "Competing authorities drift and make guarantee ownership unknowable.", "Name canonical decision/enforcement point; bounded migration removes superseded authority; secondary controls have distinct responsibility.", &["same policy independently implemented at multiple edges", "two classifiers can disagree", "obsolete compatibility authority remains active indefinitely"]),
        invariant("I1", "Dependencies point inward and remain acyclic", "Within each declared clean-architecture subsystem, production source dependencies point from outer mechanisms toward inner policy, never outward from inner policy; production module graph remains acyclic.", "One outward edge makes policy depend on mechanism lifecycle and transitive erosion.", "Declare subsystem and layer map; direct and transitive production edges count; test composition is classified separately.", &["inner imports concrete outer module", "inner manifest depends on outer package", "inner public signature names outer type", "production cycle exists"], &["C1","C2"]),
        invariant("I2", "Inner core owns ports", "Abstractions required by inner policy are owned inward. Outer adapters implement them. Inner code neither constructs nor names concrete outer adapters.", "Interface beside implementation leaves policy dependent on provider-owned contract.", "Port may be trait, interface, protocol, function capability, algebra, or equivalent; ceremonial interface class is not required.", &["inner imports interface declared beside outer implementation", "concrete adapter construction occurs inward", "service locator retrieves mechanism inward"], &["C1","C16"]),
        invariant("I3", "Inner contracts remain mechanism-free", "Inner entities, values, services, ports, and public signatures contain plain project-owned data and behavior, not framework handles, transport objects, persistence rows, serialization annotations, or concrete third-party models unless technical model is repository domain under approved override.", "Mechanism types crossing inward make dependency inversion cosmetic.", "Outer layers own DTOs and serialization; boundary translation creates plain inner values.", &["ORM annotation on domain entity", "HTTP type in use-case signature", "database row returned by inner port", "SDK object stored as domain state"], &["C3","C4","C5"]),
        invariant("I4", "External models cross anti-corruption boundaries", "Every external system with semantics different from inner model is translated at an outer boundary. External identifiers, states, errors, units, and lifecycle assumptions do not become inner authority by passthrough.", "Third-party model leakage lets vendor changes redefine project policy.", "Adapter maps shape and meaning; identical-looking fields do not prove identical semantics.", &["third-party enum controls inner state", "vendor ID type appears in domain contract", "external error taxonomy becomes inner policy"] , &["C5","C6"]),
        invariant("I5", "Policy decisions remain inward", "Validation beyond boundary shape, business-state branching, state transitions, retry/retention/naming policy, outcome distinctions, and multi-step use-case orchestration are owned by inner core. Outer layers capture, translate, execute mechanisms, and render.", "Distributed policy creates divergent behavior and an anemic core.", "Equivalent UI, API, CLI, job, and adapter paths reach the same inner decision.", &["controller determines eligibility", "UI duplicates transition", "adapter chooses retention", "delivery bypasses inner validation"], &["C7","C10","C11","C13","C14"]),
        invariant("I6", "Concrete wiring has declared outer composition roots", "Concrete implementations of inner ports and process/runtime-scoped services are selected and wired only at declared outer composition roots. Each independently launched runtime may have its own root; inner modules and ordinary adapters cannot be hidden roots.", "Scattered construction makes mechanisms implicit dependencies and blocks coherent replacement and lifecycle control.", "Intent names composition ownership per runtime or subsystem; private adapter helpers that do not implement inner ports may remain local.", &["use case constructs database client", "inner module uses global locator", "process singleton is created outside declared root"], &["C16"]),
        invariant("I7", "Equivalent outer mechanisms are replaceable", "Replacing an outer delivery or infrastructure mechanism with a behaviorally equivalent implementation may require adapter, migration, configuration, and composition changes, but cannot require unrelated inner-policy modification.", "Replaceability proves dependency inversion is real rather than diagrammatic.", "Test explicit relevant counterfactual axes such as delivery, persistence, transport, vendor, clock, filesystem, or queue.", &["database swap changes domain ORM shape", "transport swap changes use-case request type", "vendor swap rewrites leaked domain enum"] , &["C18"]),
        invariant("I8", "Dependency rule has stable mandatory enforcement", "Every mechanically expressible binding architecture rule is enforced by stable repository-owned build, compiler, lint, dependency-graph, AST, or architecture-test evidence included in mandatory validation. Judgment-only rules name repeatable review evidence and breach indicators.", "Documentation-only architecture permits accidental violation to compile and ship.", "Coverage must enforce the actual rule; stable identifier or location provides traceability; documentation audit inspects but never executes or installs tools.", &["inward import passes mandatory checks", "analyzer config omits claimed rule", "architecture test is optional", "enforceable rule has prose only despite stack support"], &["C17"]),
        invariant("I9", "Boundary outcomes translate without leakage", "Outer failures are translated before entering inner core, and inner outcomes before reaching delivery consumers. Translation preserves required distinctions and context without exposing raw mechanism types or moving business decisions outward.", "Raw errors couple layers; lossy strings and outward branching move policy across boundaries.", "Error ownership follows semantic boundary; raw framework/vendor errors are forbidden and adapter mapping cannot invent outcomes.", &["SQL or SDK exception enters inner signature", "frontend interprets raw inner text", "FFI erases required distinction", "adapter converts failure to default success"], &["C6","C7"]),
    ]
}

fn clean_provenance(ids: &[&str]) -> Vec<Provenance> {
    ids.iter().map(|id| Provenance { source_id:format!("auditing-clean-architecture:{id}"), source_locator:"/Users/cartwmic/.pi/agent/skills/auditing-clean-architecture/corollaries.md".into(), source_clause:(*id).into(), derivation:"Frozen provider wording generalizes approved clean-architecture corollary without runtime dependency on skill text.".into() }).collect()
}
fn oxide_provenance(source_id: &str, source_clause: &str, locator: &str) -> Vec<Provenance> {
    vec![Provenance {
        source_id: source_id.into(),
        source_locator: locator.into(),
        source_clause: source_clause.into(),
        derivation: "Oxide-specific nouns were removed while preserving approved engineering force; recovered approval text is retained in /tmp/doc-audit-doctrine-history.txt.".into(),
    }]
}

fn doctrine_cases(id: &str, _invariant: bool, _reason_prefix: &str) -> Vec<PolicyCase> {
    cases::approved_cases(id)
}

fn tenet(
    id: &str,
    title: &str,
    statement: &str,
    rationale: &str,
    effect: &str,
    evidence: &[&str],
    sources: &[&str],
) -> DoctrineClause {
    let prefix = format!("doctrine.{}", id.to_ascii_lowercase());
    DoctrineClause {
        id: id.into(),
        title: title.into(),
        force: "defeasible-tenet-proposal".into(),
        statement: statement.into(),
        rationale: rationale.into(),
        operational_effect: effect.into(),
        evidence_of_drift_or_breach: evidence.iter().map(|s| (*s).into()).collect(),
        provenance: clean_provenance(sources),
        mapping_requirements: vec![
            "owner-approved subsystem".into(),
            "owner-approved inner and outer boundaries".into(),
        ],
        reasons: vec![
            format!("{prefix}.adhered"),
            format!("{prefix}.drifted"),
            format!("{prefix}.unverifiable"),
            format!("{prefix}.inapplicable"),
            "tenet.tradeoff.accepted".into(),
        ],
        examples: doctrine_cases(id, false, &prefix),
    }
}
fn oxide_tenet(
    id: &str,
    title: &str,
    statement: &str,
    rationale: &str,
    effect: &str,
    evidence: &[&str],
) -> DoctrineClause {
    let prefix = format!("doctrine.{}", id.to_ascii_lowercase());
    DoctrineClause {
        id: id.into(),
        title: title.into(),
        force: "defeasible-tenet-proposal".into(),
        statement: statement.into(),
        rationale: rationale.into(),
        operational_effect: effect.into(),
        evidence_of_drift_or_breach: evidence.iter().map(|s| (*s).into()).collect(),
        provenance: match id {
            "T6" => oxide_provenance(
                "oxide:constitution:no-fallback-by-default",
                "Constitution III — No fallback by default",
                "oxide-clone openspec/constitution.md at parent of fbfcca97eadc6a4ea6ad95230cf3a8c8e3a5bd29",
            ),
            "T7" => oxide_provenance(
                "oxide:agents:single-load-bearing-mechanism",
                "AGENTS.md tenet — Single load-bearing mechanism",
                "oxide-clone AGENTS.md lines 68-74 as recovered in /tmp/doc-audit-doctrine-history.txt",
            ),
            _ => panic!("oxide engineering clause {id} has no actual source"),
        },
        mapping_requirements: vec![
            "manifest-bound repository practice addressed by proposal".into()
        ],
        reasons: vec![
            format!("{prefix}.adhered"),
            format!("{prefix}.drifted"),
            format!("{prefix}.unverifiable"),
            format!("{prefix}.inapplicable"),
            "tenet.tradeoff.accepted".into(),
        ],
        examples: doctrine_cases(id, false, &prefix),
    }
}
fn invariant(
    id: &str,
    title: &str,
    statement: &str,
    rationale: &str,
    effect: &str,
    evidence: &[&str],
    sources: &[&str],
) -> DoctrineClause {
    let prefix = format!("doctrine.{}", id.to_ascii_lowercase());
    let provenance = clean_provenance(sources);
    DoctrineClause {
        id: id.into(),
        title: title.into(),
        force: "binding-invariant-proposal".into(),
        statement: statement.into(),
        rationale: rationale.into(),
        operational_effect: effect.into(),
        evidence_of_drift_or_breach: evidence.iter().map(|s| (*s).into()).collect(),
        provenance,
        mapping_requirements: vec![
            "owner-approved subsystem identity".into(),
            "owner-approved clause-specific inner and outer boundary".into(),
            "owner-approved composition-root ownership where relevant".into(),
            "owner-approved replaceability axis where relevant".into(),
            "owner-approved enforcement and translation boundaries where relevant".into(),
        ],
        reasons: vec![
            format!("{prefix}.adhered"),
            format!("{prefix}.breached"),
            format!("{prefix}.unverifiable"),
            format!("{prefix}.inapplicable"),
        ],
        examples: doctrine_cases(id, true, &prefix),
    }
}

pub fn doctrine_packs() -> Vec<DoctrinePack> {
    let applicability = Applicability {
        shape_gate:"Evaluate each declared subsystem before clean doctrine. Include only when stable policy, meaningful decisions, replaceable mechanisms or delivery, and boundary/test leverage make layering protective rather than ceremonial.".into(),
        inclusion_conditions:vec!["subsystem has stable policy distinct from one or more replaceable mechanisms".into(),"dependency direction, boundary ownership, composition, translation, or replaceability can affect correctness".into(),"layering protects change or test seams more than it costs".into()],
        omission_conditions:vec!["single-purpose script".into(),"intentionally thin CRUD wrapper".into(),"code-generation-dominated tree".into(),"library whose technical role is its domain".into(),"thin event handler or data pipeline with no stable policy boundary".into(),"layering cost exceeds demonstrated protection".into()],
        override_rule:"Shape exclusion records every absent condition and offers clean-doctrine-shape-override only through exact owner attestation binding rationale, subsystem, manifest, and complete clean pack.".into(),
        whole_pack_rule:"For an included or overridden subsystem T1-T5 and I1-I9 are selected together. Owner may opt whole clean pack in or out; clause cherry-picking is forbidden.".into(),
        mapping_rule:"I1-I9 can bind or be evaluated only after owner-approved clause-specific subsystem, inner/outer, composition-root, replaceability, enforcement, and translation mapping. Ambiguity is unverifiable; existing layout cannot relabel boundaries; mapping change is material intent amendment.".into(),
        proposal_rule:"All unapproved doctrine is proposal-only. It may cause a revision proposal or omission record, never breach. Only exact owner-approved intent bytes make selected clauses ordinary authority.".into(),
    };
    vec![
        DoctrinePack { id:"clean-architecture-v1".into(), component_ids:vec![], clause_ids:(1..=5).map(|n|format!("T{n}")).chain((1..=9).map(|n|format!("I{n}"))).collect(), authority:"proposal-only-until-exact-owner-approved-intent".into(), applicability:applicability.clone() },
        DoctrinePack { id:"oxide-engineering-v1".into(), component_ids:vec![], clause_ids:vec!["T6".into(),"T7".into()], authority:"proposal-only-until-exact-owner-approved-intent".into(), applicability:Applicability { shape_gate:"Assess T6 and T7 independently of clean repository shape against evidenced fallback and guarantee-ownership practices.".into(), inclusion_conditions:vec!["repository has failure handling or load-bearing guarantees".into()], omission_conditions:vec!["no corresponding failure or guarantee condition exists".into()], override_rule:"No clean-shape override applies.".into(), whole_pack_rule:"T6-T7 are independently assessable as oxide-engineering-v1 component.".into(), mapping_rule:"Each proposal cites manifest-bound failure mode or guarantee authority.".into(), proposal_rule:applicability.proposal_rule.clone() } },
        DoctrinePack { id:"general-code-project-v1".into(), component_ids:vec!["clean-architecture-v1".into(),"oxide-engineering-v1".into()], clause_ids:(1..=7).map(|n|format!("T{n}")).chain((1..=9).map(|n|format!("I{n}"))).collect(), authority:"proposal-only-until-exact-owner-approved-intent".into(), applicability },
    ]
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exact_clause_and_approved_case_inventory_is_complete() {
        let clauses = doctrine_clauses();
        assert_eq!(
            clauses.iter().map(|c| c.id.as_str()).collect::<Vec<_>>(),
            [
                "T1", "T2", "T3", "T4", "T5", "T6", "T7", "I1", "I2", "I3", "I4", "I5", "I6", "I7",
                "I8", "I9"
            ]
        );
        assert_eq!(
            clauses
                .iter()
                .map(|clause| clause.examples.len())
                .collect::<Vec<_>>(),
            [5, 5, 6, 5, 5, 6, 6, 8, 7, 6, 7, 8, 9, 7, 8, 8]
        );
        assert_eq!(
            clauses
                .iter()
                .map(|clause| clause.examples.len())
                .sum::<usize>(),
            106
        );
        for clause in &clauses {
            let classes = clause
                .examples
                .iter()
                .map(|example| example.class.as_str())
                .collect::<std::collections::BTreeSet<_>>();
            assert_eq!(
                classes,
                ["bad", "borderline", "good", "out-of-scope"].into()
            );
        }
        assert!(clauses
            .into_iter()
            .flat_map(|clause| clause.examples)
            .all(|example| !example.controlling_reason.is_empty()
                && !example.deciding_evidence.is_empty()));
    }
    #[test]
    fn clean_pack_is_whole_pack_and_all_doctrine_is_proposal_only() {
        let packs = doctrine_packs();
        let clean = &packs[0];
        assert_eq!(clean.clause_ids.len(), 14);
        assert!(clean
            .applicability
            .whole_pack_rule
            .contains("cherry-picking is forbidden"));
        assert!(packs
            .iter()
            .all(|p| p.authority.starts_with("proposal-only")));
        assert!(doctrine_clauses()
            .iter()
            .all(|c| c.force.ends_with("proposal")));
    }
    #[test]
    fn mappings_shape_override_and_provenance_are_closed() {
        for clause in doctrine_clauses() {
            assert!(!clause.provenance.is_empty());
            assert!(!clause.mapping_requirements.is_empty());
        }
        let general = doctrine_packs()
            .into_iter()
            .find(|p| p.id == "general-code-project-v1")
            .unwrap();
        assert!(general
            .applicability
            .override_rule
            .contains("exact owner attestation"));
        assert!(general
            .applicability
            .mapping_rule
            .contains("Ambiguity is unverifiable"));
    }
}
