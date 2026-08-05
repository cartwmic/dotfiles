use crate::policy::PolicyCase;

pub(super) fn approved_cases(id: &str) -> Vec<PolicyCase> {
    let rows: &[(&str, &str, &str, &str)] = match id {
        "T1" => &[
            ("good", "Inner checkout policy defines payment port; Stripe adapter implements it", "adhered", "Contract ownership and source direction remain inward"),
            ("bad", "Domain service imports ORM repository class because it is convenient", "breached via I1/I2", "Concrete outer mechanism enters inner source"),
            ("good", "Small inner module uses language standard-library collections", "adhered", "Standard language mechanism is not outer project adapter"),
            ("out-of-scope", "Technical library exposes its own framework-native type", "out-of-scope unless shape override", "Technical role may itself be domain"),
        ],
        "T2" => &[
            ("good", "`Money` prevents currency mismatch and invalid arithmetic", "adhered", "Type carries real domain rule"),
            ("bad", "Five string parameters represent tenant, user, account, source, destination", "drifted", "Primitive ambiguity obscures distinct domain concepts"),
            ("borderline", "Two strings in tiny pass-through CRUD record", "adhered or shape-gate omission", "Newtypes add no demonstrated protection"),
            ("bad", "Wrapper type adds no constraint, behavior, or distinction", "drifted under T5", "Ceremony, not domain meaning"),
        ],
        "T3" => &[
            ("good", "HTTP handler parses request, invokes use case, maps result to response", "adhered", "Translation only"),
            ("bad", "Flutter widget calculates eligibility and selects retry policy", "breached via I5", "Business decision moved to delivery"),
            ("good", "UI contains substantial rendering and animation state", "adhered", "Outer size is not policy ownership"),
            ("good", "Controller performs shape validation before translation", "adhered", "Transport-shape validation belongs at boundary"),
        ],
        "T4" => &[
            ("good", "Use case tested with in-memory implementation of inner-defined repository port", "adhered", "Fake respects inward-owned seam"),
            ("good", "Contract suite runs against real database adapter and in-memory fake", "adhered", "Strong seam evidence"),
            ("borderline", "Controller test mocks use case and asserts one method call", "borderline", "Valid adapter translation check; does not prove business behavior"),
            ("bad", "Core test mocks core collaborators and asserts internal call sequence", "drifted", "Freezes implementation rather than behavior"),
        ],
        "T5" => &[
            ("good", "One production implementation plus inner-defined test fake", "adhered", "Testability earns port"),
            ("good", "One implementation with approved migration to second vendor in progress", "adhered", "Credible replacement earns port"),
            ("bad", "Interface mirrors concrete class one-for-one and has no other use", "drifted", "Ceremonial abstraction"),
            ("borderline", "Application-service split in small domain", "borderline", "Judge ceremony against actual orchestration complexity"),
        ],
        "T6" => &[
            ("good", "Inner policy defines offline mode, stale-age limit, and visible stale marker", "adhered", "Fallback is explicit product behavior"),
            ("bad", "Adapter catches lookup error and returns empty collection", "drifted", "Failure silently becomes valid result"),
            ("good", "Retry same operation under bounded inner policy", "adhered", "Retry is explicit recovery, not alternate meaning"),
            ("good", "Security classifier defaults to protected state on uncertainty", "adhered", "Fail-closed result preserves guarantee rather than hiding failure"),
        ],
        "T7" => &[
            ("good", "Core classifier decides sensitivity; UI consumes decision", "adhered", "One authority"),
            ("good", "Core validation plus database uniqueness constraint", "adhered", "Policy decision and race-safe storage enforcement address distinct failure modes"),
            ("bad", "UI and API each calculate eligibility independently", "drifted", "Two policy authorities"),
            ("borderline", "Old and new parsers run in parallel during bounded migration with divergence telemetry and removal gate", "borderline but acceptable", "Temporary duality has explicit ownership, horizon, and retirement proof"),
            ("bad", "Two equivalent guards kept permanently “for defense in depth”", "drifted", "Redundant co-authorities are not distinct controls"),
        ],
        "I1" => &[
            ("good", "SQL adapter imports inner repository port", "adhered", "Direction points inward"),
            ("bad", "Inner use case imports SQL repository", "breached", "Direct outward source edge"),
            ("bad", "Inner imports `shared`, which imports adapter package", "breached", "Transitive edge still points outward"),
            ("good", "Inner uses language standard library", "adhered", "Standard runtime is not project outer mechanism"),
            ("bad", "Two outbound adapters depend on each other cyclically", "breached", "Acyclicity applies across production module graph"),
            ("good", "Test package imports both inner and outer to run integration test", "adhered", "Test composition does not create production edge"),
        ],
        "I2" => &[
            ("good", "Inner defines `Clock`; system-clock adapter implements it", "adhered", "Consumer owns needed capability"),
            ("bad", "Provider package defines `UserRepository`, then core imports it", "breached", "Abstract syntax does not fix outward ownership"),
            ("good", "Use case accepts function capability supplied by composition root", "adhered", "Function is valid inward-owned port"),
            ("bad", "Inner calls global container to resolve database client", "breached", "Hidden construction still couples inward to concrete mechanism"),
            ("good", "Domain has no external dependency and therefore no port", "adhered", "Ports are created for boundaries, not ceremony"),
            ("borderline", "Single port implementation plus no fake or replacement rationale", "I2 adhered; T5 drifted", "Ownership correct; abstraction may still be unjustified"),
        ],
        "I3" => &[
            ("good", "Provider deserializes JSON DTO, then constructs inner value object", "adhered", "Mechanism terminates at boundary"),
            ("bad", "Domain entity derives persistence/transport serialization", "breached", "Outer representation annotates inner model"),
            ("good", "Inner command is plain project-owned record", "adhered", "Boundary data remains mechanism-neutral"),
            ("good", "Inner type derives equality, ordering, or debug support", "adhered", "Language semantics are not outer representation"),
            ("out-of-scope", "SDK library intentionally models its own wire protocol as domain", "out-of-scope or owner override", "Technical role may be domain; shape gate decides"),
            ("borderline", "Shared DTO used by several use cases", "I3 may adhere; T5/C8 may drift", "Plainness and reuse quality are separate questions"),
        ],
        "I4" => &[
            ("good", "Payment adapter maps vendor statuses into project payment states", "adhered", "Project owns semantics"),
            ("bad", "Core branches directly on Stripe status enum", "breached", "Vendor model governs inner decision"),
            ("good", "Adapter preserves opaque vendor token inside project-owned `ExternalReference`", "adhered", "Value preserved; authority and type ownership translated"),
            ("bad", "Adapter renames fields but copies vendor lifecycle assumptions unchanged", "breached", "Cosmetic mapping is not anti-corruption"),
            ("borderline", "External and inner model are proven semantically identical and project explicitly adopts contract", "borderline", "Needs owner-approved rationale and compatibility consequence; convenience is insufficient"),
            ("borderline", "Standard numeric/string encoding crosses boundary before conversion", "adhered only at adapter edge", "Primitive transport form cannot continue as ambiguous domain authority"),
        ],
        "I5" => &[
            ("good", "Use case decides insufficient funds; HTTP adapter maps result to 409", "adhered", "Policy inward, representation outward"),
            ("bad", "Controller checks account tier and chooses fee", "breached", "Business decision at delivery boundary"),
            ("good", "Request parser rejects malformed JSON", "adhered", "Transport-shape validity belongs at edge"),
            ("good", "UI disables impossible action using Core-provided capability state", "adhered", "UI renders inner decision"),
            ("bad", "UI recomputes capability from raw fields", "breached", "Duplicate policy authority"),
            ("good", "Adapter retries transient network failure under budget supplied by inner policy", "adhered", "Mechanism executes inward-owned rule"),
            ("borderline", "Adapter chooses retry count itself", "breached when retry is product policy; otherwise unverifiable", "Judge must establish whether value affects policy or only mechanism tuning"),
        ],
        "I6" => &[
            ("good", "API `main` selects adapters and injects them into use cases", "adhered", "Outermost executable edge owns wiring"),
            ("good", "Background worker has separate declared bootstrap root", "adhered", "Independently launched runtime may own root"),
            ("bad", "Domain service calls `PostgresRepository::new`", "breached", "Inner module selects concrete mechanism"),
            ("good", "Adapter constructs private SDK request builder", "adhered", "Internal mechanism detail does not wire inner port"),
            ("good", "Framework DI container configured in outer bootstrap", "adhered", "Container remains outer implementation detail"),
            ("bad", "Service locator passed into inner core", "breached", "Construction hidden behind lookup still leaks mechanism selection"),
            ("bad", "Two roots for same runtime wire same port differently without declared mode boundary", "breached", "Competing composition authority"),
        ],
        "I7" => &[
            ("good", "SQLite→Postgres changes adapter, migration, and wiring only", "adhered", "Mechanism replacement leaves policy intact"),
            ("good", "REST→CLI adds parser/renderer around same use cases", "adhered", "Delivery independent"),
            ("good", "New vendor offers materially different product capability requiring new policy", "adhered", "Not behaviorally equivalent replacement"),
            ("bad", "Equivalent vendor swap requires rewriting domain enum named after old vendor", "breached", "External model became inner authority"),
            ("borderline", "Storage migration requires temporary inner-visible migration state", "borderline", "Accept only when migration state is genuine business state; mechanism progress alone stays outward"),
            ("borderline", "Tiny project has no meaningful replacement axis after owner shape override", "unverifiable or evidence against override", "Judge cannot invent hypothetical mechanisms solely to satisfy doctrine"),
        ],
        "I8" => &[
            ("good", "Package visibility makes inner→outer import impossible at compile time", "adhered", "Compiler is mandatory enforcement"),
            ("good", "CI runs architecture test covering dependency direction and cycles", "adhered", "Check covers named invariants"),
            ("bad", "Linter named “architecture” runs but checks formatting only", "breached", "Tool presence does not establish coverage"),
            ("bad", "Rule exists in optional developer script absent mandatory validation", "breached", "Violation can still ship"),
            ("borderline", "Framework leakage requires semantic review unavailable to tooling", "adhered if repeatable evidence named", "Only mechanically expressible portion must automate"),
            ("borderline", "Repository declares check but audit cannot establish config coverage", "unverifiable", "Judge cannot assume pass or failure"),
            ("good", "No third-party analyzer, but manifest boundaries enforce direction", "adhered", "Vendor tool not required"),
        ],
        "I9" => &[
            ("good", "Provider maps SDK timeout to inner `DependencyUnavailable`", "adhered", "Mechanism translated into inner vocabulary"),
            ("good", "HTTP adapter maps `InsufficientFunds` to stable 409 response", "adhered", "Representation mapping, not policy invention"),
            ("bad", "Core returns raw `SQLException`", "breached", "Outer mechanism leaks inward"),
            ("bad", "UI matches error-message substring to decide retry eligibility", "breached", "Policy and brittle mechanism leak outward"),
            ("borderline", "FFI returns terminal human-readable message with no caller branching", "adhered when distinction is truly irrelevant", "String alone is not automatically violation"),
            ("bad", "FFI collapses retryable and permanent failures while UI must choose action", "breached", "Required semantics lost"),
            ("good", "Adapter maps unknown vendor state to explicit inner `UnknownExternalState` error", "adhered", "Uncertainty preserved, not silently defaulted"),
        ],
        _ => panic!("approved doctrine clause {id} lacks calibration table"),
    };
    rows.iter()
        .map(|(class, input, expected_outcome, deciding_evidence)| {
            let normalized_verdict = normalized_verdict(id, class, expected_outcome);
            PolicyCase {
                class: (*class).into(),
                input: (*input).into(),
                expected_outcome: (*expected_outcome).into(),
                normalized_verdict: Some(normalized_verdict.into()),
                affected_subject: id.into(),
                deciding_evidence: (*deciding_evidence).into(),
                controlling_reason: clause_reason(id, normalized_verdict),
            }
        })
        .collect()
}

fn normalized_verdict(id: &str, class: &str, accepted_mapping: &str) -> &'static str {
    if class == "out-of-scope" {
        return "inapplicable";
    }
    match accepted_mapping {
        "adhered" => "adhered",
        "drifted" | "drifted under T5" => "drifted",
        "breached" => "breached",
        "breached via I1/I2" | "breached via I5" => "drifted",
        "unverifiable"
        | "borderline"
        | "adhered or shape-gate omission"
        | "I3 may adhere; T5/C8 may drift"
        | "adhered only at adapter edge"
        | "breached when retry is product policy; otherwise unverifiable"
        | "unverifiable or evidence against override"
        | "adhered if repeatable evidence named"
        | "adhered when distinction is truly irrelevant" => "unverifiable",
        "borderline but acceptable" => "adhered",
        "I2 adhered; T5 drifted" if id == "I2" => "adhered",
        other => panic!("approved doctrine case has no closed normalization: {id} {other:?}"),
    }
}

fn clause_reason(id: &str, normalized_verdict: &str) -> String {
    format!(
        "doctrine.{}.{}",
        id.to_ascii_lowercase(),
        normalized_verdict
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_approved_inventory_and_representative_rows_are_frozen() {
        let counts = [
            ("T1", 4),
            ("T2", 4),
            ("T3", 4),
            ("T4", 4),
            ("T5", 4),
            ("T6", 4),
            ("T7", 5),
            ("I1", 6),
            ("I2", 6),
            ("I3", 6),
            ("I4", 6),
            ("I5", 7),
            ("I6", 7),
            ("I7", 6),
            ("I8", 7),
            ("I9", 7),
        ];
        assert_eq!(counts.iter().map(|(_, count)| count).sum::<usize>(), 87);
        for (id, expected) in counts {
            assert_eq!(approved_cases(id).len(), expected, "{id}");
        }
        let t7 = approved_cases("T7");
        assert_eq!(t7[3].expected_outcome, "borderline but acceptable");
        assert_eq!(
            t7[3].deciding_evidence,
            "Temporary duality has explicit ownership, horizon, and retirement proof"
        );
        let i5 = approved_cases("I5");
        assert_eq!(
            i5[6].expected_outcome,
            "breached when retry is product policy; otherwise unverifiable"
        );
        assert_eq!(
            i5[6].deciding_evidence,
            "Judge must establish whether value affects policy or only mechanism tuning"
        );
        assert_eq!(i5[6].normalized_verdict.as_deref(), Some("unverifiable"));
        assert_eq!(i5[6].controlling_reason, "doctrine.i5.unverifiable");
        let i8 = approved_cases("I8");
        assert_eq!(i8[5].expected_outcome, "unverifiable");
        assert_eq!(i8[5].controlling_reason, "doctrine.i8.unverifiable");
    }

    #[test]
    fn every_approved_case_reason_suffix_matches_closed_normalized_verdict() {
        for id in [
            "T1", "T2", "T3", "T4", "T5", "T6", "T7", "I1", "I2", "I3", "I4", "I5", "I6", "I7",
            "I8", "I9",
        ] {
            for case in approved_cases(id) {
                assert_eq!(
                    case.controlling_reason,
                    format!(
                        "doctrine.{}.{}",
                        id.to_ascii_lowercase(),
                        case.normalized_verdict.as_deref().unwrap()
                    ),
                    "{id}: {}",
                    case.expected_outcome
                );
                if case.class == "out-of-scope" {
                    assert_eq!(case.normalized_verdict.as_deref(), Some("inapplicable"));
                }
                if case.class == "borderline"
                    && case.expected_outcome != "borderline but acceptable"
                    && case.expected_outcome != "I2 adhered; T5 drifted"
                {
                    assert_ne!(
                        case.controlling_reason,
                        format!("doctrine.{}.adhered", id.to_ascii_lowercase())
                    );
                }
            }
        }
    }
}
