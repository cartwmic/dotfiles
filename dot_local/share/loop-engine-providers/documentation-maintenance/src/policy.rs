//! Provider-owned frozen policy registries for phase P2.
//!
//! Nothing in this module loads repository files. Contracts may enter the
//! production registry only through compiled provider code.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

pub const AGENTS_MAX_BYTES: usize = 32_768;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Clause {
    pub id: String,
    pub title: String,
    pub obligation: String,
    pub required: String,
    pub out_of_scope: String,
    pub discriminators: Vec<String>,
    pub revision_rule: String,
    pub reasons: ClauseReasons,
    pub examples: Vec<PolicyCase>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ClauseReasons {
    pub satisfied: String,
    pub deficient: String,
    pub unverifiable: String,
    pub out_of_scope: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct PolicyCase {
    pub class: String,
    pub input: String,
    /// Exact accepted calibration-table mapping, including conditional wording.
    pub expected_outcome: String,
    /// Closed clause-local verdict used to select conditional doctrine reasons.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub normalized_verdict: Option<String>,
    pub affected_subject: String,
    pub deciding_evidence: String,
    pub controlling_reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct DocumentContract {
    pub id: String,
    pub path: String,
    pub authority_rank: u8,
    pub role: String,
    pub required_content: String,
    pub out_of_scope_content: String,
    pub claim_kinds: Vec<String>,
    pub force_rules: Vec<String>,
    pub materiality_rules: Vec<String>,
    pub reason_ids: Vec<String>,
    pub claim_examples: Vec<PolicyCase>,
    pub revision_rules: Vec<String>,
    pub max_bytes: Option<usize>,
    pub clauses: Vec<Clause>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct DocumentProfile {
    pub id: String,
    pub contract_ids: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedProfile {
    pub id: String,
    pub contracts: Vec<DocumentContract>,
}

#[derive(Debug, Default)]
pub struct DocumentContractRegistry {
    contracts: BTreeMap<String, DocumentContract>,
    profiles: BTreeMap<String, DocumentProfile>,
}

impl DocumentContractRegistry {
    pub fn repository_core() -> Self {
        let mut registry = Self::default();
        registry.insert_compiled(readme_contract());
        registry.insert_compiled(agents_contract());
        registry.insert_compiled(intent_contract());
        registry.profiles.insert(
            "repository-core".into(),
            DocumentProfile {
                id: "repository-core".into(),
                contract_ids: vec![
                    "repository-intent-v1".into(),
                    "agent-instructions-v1".into(),
                    "root-readme-v1".into(),
                ],
            },
        );
        registry
    }

    fn insert_compiled(&mut self, contract: DocumentContract) {
        self.contracts.insert(contract.id.clone(), contract);
    }

    pub fn resolve_profile(&self, id: &str) -> Result<ResolvedProfile, String> {
        let profile = self
            .profiles
            .get(id)
            .ok_or_else(|| format!("unsupported provider-owned document profile {id:?}"))?;
        let contracts = profile
            .contract_ids
            .iter()
            .map(|contract_id| {
                self.contracts.get(contract_id).cloned().ok_or_else(|| {
                    format!("profile {id:?} names unsupported contract {contract_id:?}")
                })
            })
            .collect::<Result<Vec<_>, _>>()?;
        Ok(ResolvedProfile {
            id: profile.id.clone(),
            contracts,
        })
    }

    /// Repository or caller supplied definitions never enter the registry.
    pub fn refuse_external(&self, source: &str, id: &str) -> Result<(), String> {
        Err(format!(
            "document contract {id:?} from {source:?} is unsupported: version 1 accepts provider-owned compiled contracts only"
        ))
    }

    #[cfg(test)]
    fn register_test_provider_contract(
        &mut self,
        contract: DocumentContract,
        profile: DocumentProfile,
    ) -> Result<(), String> {
        if self.contracts.contains_key(&contract.id) || self.profiles.contains_key(&profile.id) {
            return Err("test provider contract or profile already registered".into());
        }
        if !profile.contract_ids.iter().any(|id| id == &contract.id) {
            return Err("test profile must select test contract".into());
        }
        self.insert_compiled(contract);
        self.profiles.insert(profile.id.clone(), profile);
        Ok(())
    }
}

fn clause(
    id: &str,
    title: &str,
    obligation: &str,
    required: &str,
    out: &str,
    revision: &str,
) -> Clause {
    let lower = id.to_ascii_lowercase();
    let reasons = ClauseReasons {
        satisfied: format!("role.{lower}.satisfied"),
        deficient: format!("role.{lower}.deficient"),
        unverifiable: format!("role.{lower}.unverifiable"),
        out_of_scope: format!("role.{lower}.out-of-scope"),
    };
    let [good, bad, borderline, out_of_scope] = concrete_role_inputs(id);
    let discriminators = clause_discriminators(id);
    let evidence = [
        discriminators[0].clone(),
        discriminators.get(1).unwrap_or(&discriminators[0]).clone(),
        required.to_string(),
        out.to_string(),
    ];
    let examples = vec![
        PolicyCase {
            class: "good".into(),
            input: good.into(),
            expected_outcome: "satisfied".into(),
            normalized_verdict: None,
            affected_subject: id.into(),
            deciding_evidence: evidence[0].clone(),
            controlling_reason: reasons.satisfied.clone(),
        },
        PolicyCase {
            class: "bad".into(),
            input: bad.into(),
            expected_outcome: "deficient".into(),
            normalized_verdict: None,
            affected_subject: id.into(),
            deciding_evidence: evidence[1].clone(),
            controlling_reason: reasons.deficient.clone(),
        },
        PolicyCase {
            class: "borderline".into(),
            input: borderline.into(),
            expected_outcome: "unverifiable".into(),
            normalized_verdict: None,
            affected_subject: id.into(),
            deciding_evidence: evidence[2].clone(),
            controlling_reason: reasons.unverifiable.clone(),
        },
        PolicyCase {
            class: "out-of-scope".into(),
            input: out_of_scope.into(),
            expected_outcome: "satisfied".into(),
            normalized_verdict: None,
            affected_subject: id.into(),
            deciding_evidence: evidence[3].clone(),
            controlling_reason: reasons.out_of_scope.clone(),
        },
    ];
    Clause {
        id: id.into(),
        title: title.into(),
        obligation: obligation.into(),
        required: required.into(),
        out_of_scope: out.into(),
        discriminators,
        revision_rule: revision.into(),
        reasons,
        examples,
    }
}

fn clause_discriminators(id: &str) -> Vec<String> {
    let values: &[&str] = match id {
        "R1" => &["Pass only when a new capable user can determine project identity, intended outcome, beneficiary or surrounding system, capabilities, prerequisites, limitations, and fit before deeper detail.", "Deficient when badges, screenshots, history, marketing claims, or internals precede or replace facts needed for fit."],
        "R2" => &["Pass only when shortest demonstrated outcome names repository-supported steps, prerequisites, invocation scope, and repository-evidenced stable observable result.", "Deficient when tutorial, command, result, or variant is speculative, unsupported, or required first-success evidence is absent."],
        "R3" => &["Evaluate every action-changing capability, prerequisite, limitation, command, path, permission, safety boundary, and expected outcome against active manifest evidence.", "Contradiction is drifted; unavailable support is unverifiable and must be removed or narrowed rather than replaced with invented fact."],
        "R4" => &["Fit and first representative success precede operational, diagnostic, contribution, and implementation detail; deeper detail remains discoverable at maintained destinations.", "Heading style alone is never a defect; ordering matters only when it changes target-user understanding or action."],
        "R5" => &["Route setup, advertised operation, expected-failure diagnosis, and safe contribution tasks exposed by maintained entry points or configuration.", "Canonical routing passes; duplicated runbooks, unsupported tasks, and destinations without repository support fail or remain out of scope."],
        "R6" => &["Each section must uniquely advance R1-R5 and must not compete with a stronger canonical source.", "Removal test is semantic: if removal leaves every README obligation unchanged, section is redundant; prose taste and accurate rewording do not count."],
        "A1" => &["Name operationally important source, configuration, verification-input, generated-output, restricted-content, canonical-policy, composition, entry-point, and unusual source-of-truth paths when present.", "Distinguish editable authority from projection or generated output; broad directory inventory without agent consequence is deficient."],
        "A2" => &["For each common change class give exact repository-supported command or canonical script, cwd/scope, non-obvious prerequisites or external effects, what it checks or produces, and stable success observation.", "Distinguish focused and full validation where supported; audit establishes static support and never executes commands."],
        "A3" => &["Every material property must preserve chain property → agent consequence → verification evidence → canonical intent link.", "Bare architecture nouns, diagrams, slogans, or links without recoverable implementation consequence are deficient."],
        "A4" => &["Always identifies autonomous mandatory action; ask identifies owner-gated material intent, compatibility, destructive, external, or uncertain-authority action; never identifies forbidden action.", "At minimum preserve binding intent/checks, never weaken intent to excuse breach, never expose secrets, and never edit generated authority projections."],
        "A5" => &["Root scope, evidenced nested scopes, local differences, conflict resolution, and higher-authority intent precedence must be recoverable for target path.", "No nested file must be created merely because tooling supports one; absent nested scope creates no defect."],
        "A6" => &["Include only evidenced non-obvious hazards whose omission can cause wrong edit, false diagnosis, unsafe execution, or false completion, and include correct response for each.", "Hypothetical, historical-only, obvious, or consequence-free hazards are out of scope."],
        "A7" => &["Loaded AGENTS bytes must not exceed 32,768 and every section must advance repository-specific operational obligation.", "Reject generic advice, duplicated full intent/runbooks, temporary notes, stale status, personal preference, and repeated rules without distinct scope."],
        "RI1" => &["State why repository exists, durable outcome or responsibility, beneficiary or surrounding system, and identity boundaries needed to decide whether proposed work belongs.", "Explicit None passes only with evidence-backed consideration; feature catalog, marketing copy, roadmap, and volatile status are out of scope."],
        "RI2" => &["Purpose/descriptive identity describes; tenet defeasibly guides; invariant, boundary, and non-goal bind; aspiration remains non-binding future direction.", "Headings provide default force and every exception is explicit; reader must never infer whether statement guides, binds, excludes, or aspires."],
        "RI3" => &["Each tenet contains durable principle, rationale, competing-choice consequence, drift evidence, and acknowledged trade-off space.", "Reject slogans, mechanism mandates, and principles unable to discriminate plausible choices; broad current contradiction cannot masquerade as adherence."],
        "RI4" => &["Each invariant, boundary, and non-goal states precise condition, rationale, operational consequence, observable breach evidence, and applicability scope.", "New binding statement must adhere at effective revision; otherwise remediate first or retain as aspiration; enforceable selected doctrine needs stable evidence."],
        "RI5" => &["Identify owned policy/data/lifecycle, excluded ownership, dependency or authority direction, material trust/integration edges, subsystem scope, and non-goal implications.", "Reject directory inventories and accidental implementation limitations presented as permanent policy."],
        "RI6" => &["Future direction is explicitly non-binding, explains why it matters, and names observable progress where meaningful.", "Aspirations cannot claim current guarantee, hide present breach, or weaken binding rule; task lists and dates are out of scope unless durable commitments."],
        "RI7" => &["Material exact-diff approval covers creation and changes to meaning, force, scope, rationale, operational effect, breach evidence, governance, classification, binding removal/weakening, or tenet abandonment/force reduction.", "Semantic-neutral formatting and link repair are non-material; owner authority cannot be replaced by workflow judge and intent cannot be rewritten to excuse breach."],
        "RI8" => &["docs/intent.md owns durable purpose and policy; AGENTS owns executable projection; README owns user-facing summary.", "Install/build/test procedures, agent steps, feature requirements, active plans, dated status, changelog, exhaustive inventories, and volatile details are out of intent scope."],
        "C1" => &["Test-only provider clause requires release identity and supported change evidence."],
        _ => panic!("provider clause {id} lacks exact discriminator corpus"),
    };
    values.iter().map(|value| (*value).to_string()).collect()
}

fn concrete_role_inputs(id: &str) -> [&'static str; 4] {
    match id {
        "R1" => ["README opens with project identity, intended user outcome, beneficiary, capabilities, prerequisites, and limitations needed to decide fit.", "README opens with badges and architecture history but never says what outcome project provides or who should use it.", "README says it is a platform, while repository evidence does not establish whether named interface is product identity or replaceable delivery.", "Release history and marketing screenshots change no project-fit decision."],
        "R2" => ["README gives shortest repository-supported invocation, required prerequisite, invocation scope, and stable observable result for first success.", "README tutorial invokes a command absent from active manifest and promises an unobserved result.", "One maintained script supports first-success command while another marks it replaced; lifecycle authority is unavailable.", "Exhaustive advanced variants are not required for representative first success."],
        "R3" => ["README states supported capability, prerequisite, limitation, permission, safety boundary, and expected result exactly as active evidence supports them.", "README claims offline operation although source requires network access.", "README promises a capability that available source, tests, and configuration neither support nor contradict.", "Implementation trivia that changes no user action is outside decision-critical truth."],
        "R4" => ["README presents fit and first success before diagnostics, contribution, and implementation details, with maintained links to deeper material.", "README requires reading internal architecture and contribution policy before user can find first supported invocation.", "Heading order is unusual, but evidence cannot establish whether target user needs one section before first success.", "Aesthetic heading preferences with no audience consequence are outside layered disclosure."],
        "R5" => ["README routes supported setup, operation, expected-failure diagnosis, and contribution tasks to maintained canonical instructions without copying runbooks.", "README advertises backup operation but gives no maintained destination for required configuration or recovery.", "A task appears common in source but no maintained entry point establishes it as supported.", "Rare unsupported tasks and duplicated runbook detail are outside required routing."],
        "R6" => ["Every README section uniquely advances fit, first success, truth, disclosure, or task routing and yields to stronger canonical sources.", "Two README sections repeat same setup facts and neither adds audience-specific obligation.", "Two similar sections target different audiences, but evidence cannot establish whether removal changes required role.", "Stylistic concision and accurate rewording with unchanged semantics are outside canonical-density defect."],
        "A1" => ["AGENTS names crates/core as policy source, generated FFI as do-not-edit output, composition entry point, validation input, and restricted secret paths.", "AGENTS lists every directory but does not distinguish editable source from generated projection or canonical policy.", "AGENTS names a generated directory without evidence identifying authoritative generator source.", "Broad package inventory that changes no agent action is outside executable orientation."],
        "A2" => ["AGENTS gives `./run_tests.sh rust` and `./run_tests.sh all`, root cwd, Docker prerequisite, checked scope, and stable success evidence.", "AGENTS says `test all changes` without repository-supported command, scope, prerequisite, or completion observation.", "AGENTS names `./run_tests.sh all`, but active evidence cannot establish required Docker service or stable success signal.", "Editor setup and unused command variants are outside ordinary safe completion."],
        "A3" => ["AGENTS states policy belongs in crates/core, outer providers implement ports, architecture test verifies direction, and docs/intent.md owns rationale.", "AGENTS says `use clean architecture` and links intent without agent consequence or verification evidence.", "AGENTS maps ownership and consequence but names a check whose coverage cannot be established.", "Bare diagrams and package slogans with no implementation consequence are outside actionable projection."],
        "A4" => ["AGENTS concretely says always preserve binding intent, ask before material intent or destructive changes, and never edit generated authority or expose secrets.", "AGENTS says only `be careful with secrets and destructive commands` without required, gated, or forbidden triggers.", "AGENTS labels compatibility change `ask` but does not define scope that makes change material.", "Generic best-practice cautions with no scoped action classification are outside authority boundary."],
        "A5" => ["Root AGENTS identifies existing nested instruction scope, states local difference, and preserves docs/intent.md precedence.", "Two applicable instruction files conflict for same path and root contract gives no precedence resolution.", "Nested file exists, but active evidence cannot establish whether its path scope applies to target work.", "Nested-scope discussion is unnecessary where no nested instruction or evidenced scope exists."],
        "A6" => ["AGENTS warns generated bindings are build output, names generator, and explains missing output is resolved by repository build path.", "AGENTS omits credentialed-test side effect, causing ordinary full-validation instruction to expose unsafe execution.", "Historical note describes cache trap, but current evidence cannot show it remains active.", "Hypothetical and obvious hazards with no likely wrong action are outside known traps."],
        "A7" => ["AGENTS is repository-specific, operationally dense, canonical, and 12,400 bytes on disk.", "AGENTS is 40,000 bytes and duplicates full intent, runbooks, generic style advice, and temporary task status.", "AGENTS is below byte limit but repeated rules may or may not serve distinct scoped audiences.", "Commit style, screenshots, and release prose are outside scope unless ordinary safe completion requires them."],
        "RI1" => ["Purpose states: Maintain a framework-independent rules engine producing deterministic policy decisions for supported delivery surfaces.", "Purpose says: Build the best modern platform with an amazing developer experience.", "Purpose says: Provide REST APIs for account management; evidence cannot establish whether REST is durable responsibility or replaceable delivery.", "Feature catalogs, marketing copy, current roadmap, and volatile status are outside durable purpose."],
        "RI2" => ["Intent explicitly distinguishes descriptive purpose, defeasible tenets, binding invariants/boundaries/non-goals, and non-binding aspirations.", "Intent mixes `should`, `must`, and future goals under one Principles heading so force cannot be determined.", "A statement appears beneath Invariants but inline wording calls it optional; explicit exception authority is unresolved.", "Unclassified prose carrying no durable decision force is outside force-model defect."],
        "RI3" => ["Tenet states one load-bearing mechanism, explains drift risk, permits distinct defense-in-depth controls, and names duplicate authorities as drift evidence.", "Tenet says only: Use traits for every service.", "Tenet says only: Prefer simplicity; no rationale, competing consequence, or drift discriminator exists.", "Mechanism trivia and slogans impossible to trade against real concerns are outside valid tenets."],
        "RI4" => ["Invariant forbids direct/transitive inner-to-outer imports, explains replaceability, names breach evidence and subsystem scope, and binds mandatory validation.", "Invariant says only: Architecture remains clean.", "Intent says PostgreSQL is always used, but evidence cannot establish whether database choice is durable repository domain or replaceable mechanism.", "Subjective quality language, mechanism trivia, violated proposals, and unauditable claims are outside executable binding statements."],
        "RI5" => ["Boundary states repository owns policy outcomes while host owns authentication and credentials; trust edge and subsystem scope are explicit.", "Intent says authentication is out of scope while repository validates tokens and stores credentials.", "Boundary names owned data but not lifecycle or adjacent-system authority, leaving scope dispute unresolved.", "Directory inventories and accidental current limitations are outside durable ownership policy."],
        "RI6" => ["Aspiration seeks mandatory enforcement of all expressible architecture rules and measures progress by shrinking review-only list.", "Intent claims all invariants are mechanically enforced although active evidence shows prose-only rules.", "Future direction is labeled aspiration but supplies no observable progress signal where one is meaningful.", "Task lists and dates are outside aspiration unless date itself is durable commitment."],
        "RI7" => ["Governance requires owner review of exact semantic diff for creation, force/scope/rationale changes, weakening, or abandonment and exempts semantic-neutral formatting.", "Governance permits any maintainer to rewrite intent without exact owner approval or materiality classification.", "Link repair also changes linked normative text, but record does not establish whether semantic meaning changed.", "Ephemeral approval IDs and workflow implementation details are outside durable governance text."],
        "RI8" => ["docs/intent.md keeps durable purpose/policy canonical; AGENTS projects action and README summarizes users through canonical links.", "docs/intent.md contains install steps, active milestones, package inventory, changelog, and agent runbook as duplicate authority.", "Architecture inventory includes rationale, but evidence cannot establish whether details are durable policy or volatile implementation.", "Product instructions, active plans, dated status, and exhaustive implementation inventory are outside intent role."],
        "C1" => ["Release entry names version, date, and repository-supported change.", "Release entry omits release identity.", "Release evidence cannot establish whether entry is released.", "Unreleased planning notes are outside released-entry role."],
        _ => panic!("provider clause {id} lacks concrete approved corpus"),
    }
}

fn contract_claim_kinds() -> Vec<String> {
    [
        "identity",
        "capability",
        "prerequisite",
        "limitation",
        "command",
        "path",
        "permission",
        "safety-boundary",
        "binding-rule",
        "expected-outcome",
        "role-obligation",
        "doctrine-proposal",
    ]
    .into_iter()
    .map(str::to_string)
    .collect()
}

fn contract_force_rules() -> Vec<String> {
    vec![
        "purpose statements default to descriptive identity".into(),
        "tenets are defeasible".into(),
        "invariants, boundaries, and non-goals are binding".into(),
        "aspirations are non-binding".into(),
        "headings supply default force; exceptions must be explicit".into(),
    ]
}

fn contract_materiality_rules() -> Vec<String> {
    vec![
        "Material: creation; meaning, force, scope, rationale, operational-effect, breach-evidence, governance, or classification change; binding-rule removal or weakening; tenet abandonment or force reduction.".into(),
        "Non-material: semantic-neutral formatting or link repair without semantic change.".into(),
    ]
}

fn claim_examples(path: &str) -> Vec<PolicyCase> {
    let inputs = match path {
        "README.md" => [
            "README states `./run_tests.sh all` is full validation command; active manifest contains executable script and dispatch supports `all`.",
            "README says configuration lives at config/legacy.toml while active entry point loads config/current.toml.",
            "README promises offline operation, but available source, configuration, and tests neither support nor contradict capability.",
            "README claims repository conforms to binding inward-dependency rule while manifest evidence shows inner module imports SQL adapter.",
            "README is accurate about identity and installation but provides no representative first-success path or observable result.",
            "README calls command stable while one maintained entry point supports it and another names replacement; lifecycle authority is absent.",
            "README omits release history and preferred prose voice; neither omission changes fit, first success, safety, operation, or contribution.",
        ],
        "AGENTS.md" => [
            "AGENTS names `./run_tests.sh all`, root cwd, Docker prerequisite, checked scope, and output exactly supported by active script/config evidence.",
            "AGENTS instructs editing generated FFI output even though generator and repository policy identify it as derived build output.",
            "AGENTS requires a credentialed integration check, but active evidence neither establishes command nor contradicts requirement.",
            "AGENTS says inner modules never name adapters while active source shows use case constructing PostgresRepository.",
            "AGENTS gives accurate command but omits generated-source ownership and always/ask/never authority needed for safe work.",
            "AGENTS names architecture check while declared config coverage and mandatory CI invocation conflict.",
            "AGENTS omits commit-message preference and screenshots; neither affects ordinary safe completion.",
        ],
        "docs/intent.md" => [
            "Intent states inner policy owns ports and active manifests, signatures, and architecture checks support exact scoped condition.",
            "Intent says repository does not persist credentials while active source writes credential bytes to disk.",
            "Intent declares queue replacement independent, but available boundaries and tests neither support nor contradict swap claim.",
            "Intent binds inner policy against concrete adapter dependencies while active source shows inner module importing SQL adapter.",
            "Intent states accurate purpose and invariant but omits explicit boundaries, non-goals, aspirations, and exact-diff governance.",
            "Intent labels PostgreSQL binding while evidence does not establish whether database is durable domain or replaceable mechanism.",
            "Intent omits roadmap dates and package inventory; neither belongs to durable repository intent.",
        ],
        _ => panic!("provider contract {path} lacks concrete claim corpus"),
    };
    let classes = [
        "accurate",
        "stale",
        "uncertain",
        "breached",
        "missing-role",
        "borderline",
        "out-of-scope",
    ];
    let outcomes = [
        "adhered",
        "drifted",
        "unverifiable",
        "breached",
        "deficient",
        "unverifiable",
        "inapplicable",
    ];
    let evidence = [
        "manifest-bound evidence supports exact action-changing proposition",
        "active manifest evidence directly contradicts documented proposition",
        "action-changing proposition has neither supporting nor contradicting active evidence",
        "owner-approved binding rule and scoped production evidence establish same breach",
        "accurate claims do not satisfy omitted required document-role obligation",
        "conflicting evidence lacks authority needed to decide closed content verdict",
        "content changes no contract role or action-changing proposition",
    ];
    let reasons = [
        "claim.accurate.supported",
        "claim.stale.contradicted",
        "claim.uncertain.evidence-missing",
        "claim.binding-rule.breached",
        "claim.role-obligation.missing",
        "claim.borderline.unresolved-evidence",
        "claim.out-of-scope.no-role-effect",
    ];
    (0..7)
        .map(|index| PolicyCase {
            class: classes[index].into(),
            input: inputs[index].into(),
            expected_outcome: outcomes[index].into(),
            normalized_verdict: None,
            affected_subject: path.into(),
            deciding_evidence: evidence[index].into(),
            controlling_reason: reasons[index].into(),
        })
        .collect()
}

fn contract_reason_ids(clauses: &[Clause]) -> Vec<String> {
    let mut reasons = vec![
        "claim.accurate.supported".into(),
        "claim.stale.contradicted".into(),
        "claim.uncertain.evidence-missing".into(),
        "claim.binding-rule.breached".into(),
        "claim.role-obligation.missing".into(),
        "claim.borderline.unresolved-evidence".into(),
        "claim.out-of-scope.no-role-effect".into(),
        "claim.evaluation-error".into(),
        "finding.one-fact.primary".into(),
        "finding.linked-consequence".into(),
        "tenet.tradeoff.accepted".into(),
    ];
    for clause in clauses {
        reasons.extend([
            clause.reasons.satisfied.clone(),
            clause.reasons.deficient.clone(),
            clause.reasons.unverifiable.clone(),
            clause.reasons.out_of_scope.clone(),
        ]);
    }
    reasons.sort();
    reasons.dedup();
    reasons
}

fn finish_contract(mut contract: DocumentContract) -> DocumentContract {
    contract.claim_kinds = contract_claim_kinds();
    contract.force_rules = contract_force_rules();
    contract.materiality_rules = contract_materiality_rules();
    contract.claim_examples = claim_examples(&contract.path);
    contract.reason_ids = contract_reason_ids(&contract.clauses);
    contract
}

fn readme_contract() -> DocumentContract {
    let specs = [
        ("R1", "Outcome and fit", "Let a new capable user determine project identity, intended outcome, and fit before deeper detail.", "Identity, beneficiaries, capabilities, prerequisites, limitations, and decision-critical fit truths precede deep detail.", "Marketing voice, badges, screenshots, history, or exhaustive internals that change no fit decision."),
        ("R2", "Representative first success", "Give the shortest demonstrated user outcome through repository-supported steps and a repository-evidenced stable expected result.", "Steps, prerequisites, invocation scope, and observable result are statically supported by repository evidence.", "Undemonstrated tutorials, speculative commands, or exhaustive variants."),
        ("R3", "Decision-critical truth", "State actual capabilities, prerequisites, limitations, commands, paths, permissions, safety boundaries, and expected outcomes that can change user action.", "Every action-changing proposition is supported or contradicted; uncertainty requires removal or narrowing, never invention.", "Facts that cannot change whether or how target user acts."),
        ("R4", "Layered disclosure", "Put fit and first success before deeper operational, diagnostic, contribution, or implementation detail.", "Information appears at earliest layer where target user needs it and deeper detail remains discoverable.", "Aesthetic heading or prose preferences with no role consequence."),
        ("R5", "Task-oriented routing", "Route common supported tasks to maintained canonical instructions without unnecessary duplication.", "Tasks needed for representative outcome, advertised capabilities, expected failures, or safe contribution have evidenced destinations.", "Rare or unsupported tasks and duplicated runbooks."),
        ("R6", "Canonical density", "Contain no semantically redundant section whose removal leaves every README role unchanged.", "Each section advances at least one R1-R5 obligation and does not compete with a stronger canonical source.", "Stylistic concision, formatting taste, or rewording accurate dense prose."),
    ];
    finish_contract(DocumentContract {
        id: "root-readme-v1".into(), path: "README.md".into(), authority_rank: 3,
        role: "User-facing project identity, fit, first demonstrated outcome, truth, layering, and task routing.".into(),
        required_content: "R1-R6 all apply; absence of README.md or any required role axis is revision_required.".into(),
        out_of_scope_content: "Agent-only operating policy, durable repository intent authority, style-only rewriting, roadmap, changelog, and exhaustive architecture inventory.".into(),
        claim_kinds: vec![], force_rules: vec![], materiality_rules: vec![], reason_ids: vec![], claim_examples: vec![],
        revision_rules: vec!["Preserve higher-authority docs/intent.md and AGENTS.md decisions.".into(), "Correct only inaccurate, unverifiable, missing-role, contradictory, or redundant content; no taste-only rewrite.".into()],
        max_bytes: None,
        clauses: specs.into_iter().map(|(id,t,o,r,x)| clause(id,t,o,r,x,"Revise one README draft outside worktree; remove or narrow unsupported action-changing claims and preserve higher authority.")).collect(),
    })
}

fn agents_contract() -> DocumentContract {
    let specs = [
        ("A1", "Executable orientation", "Name operationally important source, configuration, verification-input, generated-output, restricted-content, canonical-policy, composition, entry-point, and unusual source-of-truth paths when present.", "Map only paths whose ownership or behavior changes agent action; distinguish editable authority from projection/output.", "Broad directory inventories and project-description detail that changes no agent obligation."),
        ("A2", "Commands and completion evidence", "Name exact repository-supported commands, cwd/scope, non-obvious prerequisites or effects, what each checks or produces, and stable success evidence.", "Cover common change classes and focused-versus-full validation where repository supports them; static support only, never execute commands.", "Editor setup or command variants not needed for ordinary safe completion."),
        ("A3", "Intent projection", "Connect each material repository property through property → agent consequence → verification evidence → canonical intent link.", "Project relevant intent into executable behavior without copying full rationale.", "Bare architecture nouns, diagrams, slogans, or links with no agent consequence."),
        ("A4", "Always ask never", "Classify concrete scoped actions as always when autonomous, ask when owner-gated, or never when forbidden.", "At minimum preserve binding intent and checks; ask on material intent, compatibility, destruction, or uncertain authority; never weaken intent, expose secrets, or edit generated authority projections.", "Generic cautions such as be careful or use best practices."),
        ("A5", "Scope and precedence", "Resolve root and evidenced nested instruction scopes, local differences, conflicts, and higher-authority intent.", "Name operationally relevant nested files without requiring new nested files.", "Nested-scope discussion when no nested instruction or evidenced scope exists."),
        ("A6", "Known traps", "Name evidenced non-obvious traps and correct responses when omission could cause wrong edits, false diagnosis, unsafe execution, or false completion.", "Each included trap cites repository evidence and a correct response.", "Hypothetical, historical-only, or obvious hazards with no likely agent consequence."),
        ("A7", "Canonical density and byte ceiling", "Remain repository-specific, operationally dense, canonical, and at most 32,768 on-disk bytes.", "Every section advances an operational obligation; avoid generic advice, duplicated intent/runbooks, temporary notes, and repeated rules.", "Commit style, PR templates, screenshots, release process, editor setup, or style catalogs unless ordinary safe completion requires them."),
    ];
    finish_contract(DocumentContract {
        id: "agent-instructions-v1".into(), path: "AGENTS.md".into(), authority_rank: 2,
        role: "Repository-specific executable operating contract for coding agents.".into(),
        required_content: "A1-A7 all apply when corresponding repository condition exists; A7 byte ceiling always applies.".into(),
        out_of_scope_content: "Generic coding advice, full intent or runbook copies, product documentation, temporary task notes, changelog, and personal preference without consequence.".into(),
        claim_kinds: vec![], force_rules: vec![], materiality_rules: vec![], reason_ids: vec![], claim_examples: vec![],
        revision_rules: vec!["docs/intent.md authority resolves first; intent byte changes invalidate AGENTS and README drafts.".into(), "One exact AGENTS draft may be reviewed only after higher authority is stable.".into()],
        max_bytes: Some(AGENTS_MAX_BYTES),
        clauses: specs.into_iter().map(|(id,t,o,r,x)| clause(id,t,o,r,x,"Revise one AGENTS draft outside worktree after intent; preserve intent force and invalidate dependent README when accepted bytes change.")).collect(),
    })
}

fn intent_contract() -> DocumentContract {
    let specs = [
        ("RI1", "Durable purpose", "State an evidence-backed durable current purpose or explicit None, including outcome, beneficiary or surrounding system, and identity boundaries.", "Purpose must decide whether proposed work belongs; None requires recorded evidence-backed consideration.", "Feature catalog, marketing copy, current roadmap, or volatile status."),
        ("RI2", "Explicit force", "Use explicit purpose/descriptive identity, defeasible tenet, binding invariant, binding boundary, binding non-goal, and non-binding aspiration force; headings default and exceptions are explicit.", "Reader can determine whether each statement describes, guides, binds, excludes, or aspires.", "Unclassified prose that carries no durable decision force."),
        ("RI3", "Decision-capable tenets", "Each tenet states durable principle, rationale, competing-choice consequence, drift evidence, and acknowledged trade-off space.", "Tenets discriminate plausible choices; deviation needs documented competing trade-off rationale.", "Slogans, mechanism mandates, and principles impossible to trade against real concerns."),
        ("RI4", "Executable binding statements", "Each invariant, boundary, and non-goal gives precise condition, rationale, operational effect, observable breach evidence, and applicability scope.", "New binding statements are adhered at effective revision and practically enforceable selected doctrine has stable machine evidence.", "Subjective quality language, mechanism trivia, currently violated proposals, or unauditable claims."),
        ("RI5", "Ownership and scope", "Define owned policy/data/lifecycle, excluded ownership, dependency or authority direction, material trust/integration edges, subsystem scope, and non-goal implications.", "Resolve scope disputes without freezing accidental implementation layout as policy.", "Directory inventories and accidental current limitations presented as permanent policy."),
        ("RI6", "Honest aspirations", "Keep future direction explicitly non-binding, explain why it matters, and name observable progress where meaningful.", "Aspirations cannot masquerade as current guarantees or weaken binding rules to avoid remediation.", "Task lists, dates, or roadmap detail unless itself a durable commitment."),
        ("RI7", "Exact-diff governance", "Require owner approval of exact semantic diff for creation or changes to meaning, force, scope, rationale, operational effect, breach evidence, governance, classification, binding removal/weakening, or tenet abandonment/force reduction.", "Formatting and link repair without semantic change are non-material; approved intent cannot be rewritten to excuse breach.", "Ephemeral approval IDs or workflow implementation detail inside intent."),
        ("RI8", "Role purity", "Keep durable purpose and policy canonical in docs/intent.md and project executable projections to AGENTS and user summary to README.", "Purpose through aspirations remain explicit even when empty; None records consideration.", "Install/build/test procedures, agent steps, feature requirements, active plans, dated status, changelog, exhaustive architecture inventory, or volatile implementation detail."),
    ];
    finish_contract(DocumentContract {
        id: "repository-intent-v1".into(), path: "docs/intent.md".into(), authority_rank: 1,
        role: "Highest-authority durable repository purpose, tenets, binding policy, boundaries, non-goals, aspirations, and governance.".into(),
        required_content: "Purpose, tenets, invariants, boundaries, non-goals, aspirations, and governance are explicit; evidence-backed None is permitted for purpose through aspirations.".into(),
        out_of_scope_content: "Product instructions, runbooks, active plans, implementation inventories, agent procedures, and user onboarding.".into(),
        claim_kinds: vec![], force_rules: vec![], materiality_rules: vec![], reason_ids: vec![], claim_examples: vec![],
        revision_rules: vec!["Intent resolves before AGENTS and README; every material semantic diff needs exact owner attestation.".into(), "Existing binding intent cannot be narrowed, weakened, deleted, or relabelled to excuse drift; proposed violated binding policy remains aspiration until external remediation.".into()],
        max_bytes: None,
        clauses: specs.into_iter().map(|(id,t,o,r,x)| clause(id,t,o,r,x,"Material intent revision requires exact semantic-diff owner attestation; higher-authority change invalidates dependent accepted drafts.")).collect(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

    #[test]
    fn core_profile_resolves_exact_paths_clauses_authority_and_agents_budget() {
        let resolved = DocumentContractRegistry::repository_core()
            .resolve_profile("repository-core")
            .unwrap();
        assert_eq!(
            resolved
                .contracts
                .iter()
                .map(|c| c.path.as_str())
                .collect::<Vec<_>>(),
            ["docs/intent.md", "AGENTS.md", "README.md"]
        );
        assert_eq!(
            resolved
                .contracts
                .iter()
                .map(|c| c.clauses.len())
                .collect::<Vec<_>>(),
            [8, 7, 6]
        );
        assert_eq!(resolved.contracts[1].max_bytes, Some(32_768));
        assert_eq!(
            resolved
                .contracts
                .iter()
                .map(|c| c.authority_rank)
                .collect::<Vec<_>>(),
            [1, 2, 3]
        );
    }

    #[test]
    fn test_only_provider_extension_uses_same_interface() {
        let mut registry = DocumentContractRegistry::repository_core();
        let contract = DocumentContract {
            id: "provider-changelog-v1".into(),
            path: "CHANGELOG.md".into(),
            authority_rank: 4,
            role: "test fixture".into(),
            required_content: "entries".into(),
            out_of_scope_content: "anything else".into(),
            claim_kinds: vec![],
            force_rules: vec![],
            materiality_rules: vec![],
            reason_ids: vec![],
            claim_examples: vec![],
            revision_rules: vec!["exact bytes".into()],
            max_bytes: None,
            clauses: vec![clause(
                "C1",
                "entry",
                "record release",
                "release identity",
                "unreleased notes",
                "revise entry",
            )],
        };
        registry
            .register_test_provider_contract(
                contract,
                DocumentProfile {
                    id: "test-profile".into(),
                    contract_ids: vec!["provider-changelog-v1".into()],
                },
            )
            .unwrap();
        assert_eq!(
            registry.resolve_profile("test-profile").unwrap().contracts[0].path,
            "CHANGELOG.md"
        );
    }

    #[test]
    fn repository_and_unsupported_contract_sources_are_refused() {
        let registry = DocumentContractRegistry::repository_core();
        assert!(registry
            .resolve_profile("repository/.doc-contract.json")
            .is_err());
        assert!(registry
            .refuse_external("repository", "weakened-readme-v1")
            .unwrap_err()
            .contains("provider-owned"));
        assert!(registry
            .refuse_external("third-party", "vendor-profile")
            .is_err());
    }

    #[test]
    fn every_role_clause_has_all_case_classes_and_closed_mapping() {
        let profile = DocumentContractRegistry::repository_core()
            .resolve_profile("repository-core")
            .unwrap();
        let mut ids = Vec::new();
        for contract in profile.contracts {
            assert_eq!(
                contract
                    .claim_examples
                    .iter()
                    .map(|case| case.class.as_str())
                    .collect::<Vec<_>>(),
                [
                    "accurate",
                    "stale",
                    "uncertain",
                    "breached",
                    "missing-role",
                    "borderline",
                    "out-of-scope"
                ]
            );
            assert!(!contract.claim_kinds.is_empty());
            assert!(!contract.force_rules.is_empty());
            assert!(!contract.materiality_rules.is_empty());
            assert!(!contract.reason_ids.is_empty());
            for clause in contract.clauses {
                ids.push(clause.id.clone());
                assert_eq!(
                    clause
                        .examples
                        .iter()
                        .map(|c| c.class.as_str())
                        .collect::<Vec<_>>(),
                    ["good", "bad", "borderline", "out-of-scope"]
                );
                for case in clause.examples {
                    assert!(matches!(
                        case.expected_outcome.as_str(),
                        "satisfied" | "deficient" | "unverifiable"
                    ));
                    assert_eq!(case.affected_subject, clause.id);
                    assert!(!case.deciding_evidence.is_empty());
                    assert!(!case.controlling_reason.is_empty());
                }
            }
        }
        assert_eq!(
            ids,
            [
                "RI1", "RI2", "RI3", "RI4", "RI5", "RI6", "RI7", "RI8", "A1", "A2", "A3", "A4",
                "A5", "A6", "A7", "R1", "R2", "R3", "R4", "R5", "R6"
            ]
        );
    }

    #[test]
    fn role_case_evidence_is_clause_specific_and_uses_exact_discriminators() {
        let clauses = DocumentContractRegistry::repository_core()
            .resolve_profile("repository-core")
            .unwrap()
            .contracts
            .into_iter()
            .flat_map(|contract| contract.clauses)
            .collect::<Vec<_>>();
        let all_evidence = clauses
            .iter()
            .flat_map(|clause| clause.examples.iter())
            .map(|case| case.deciding_evidence.as_str())
            .collect::<BTreeSet<_>>();
        assert_eq!(all_evidence.len(), clauses.len() * 4);
        for clause in &clauses {
            assert!(clause.examples[0]
                .deciding_evidence
                .contains(&clause.discriminators[0]));
            assert!(clause.examples[1]
                .deciding_evidence
                .contains(&clause.discriminators[1]));
            assert!(clause.examples[2]
                .deciding_evidence
                .contains(&clause.required));
            assert!(clause.examples[3]
                .deciding_evidence
                .contains(&clause.out_of_scope));
        }
        let r1 = clauses.iter().find(|clause| clause.id == "R1").unwrap();
        assert!(r1.examples[0]
            .deciding_evidence
            .contains("Pass only when a new capable user can determine project identity"));
        let a2 = clauses.iter().find(|clause| clause.id == "A2").unwrap();
        assert!(a2.examples[1]
            .deciding_evidence
            .contains("Distinguish focused and full validation where supported"));
        let ri4 = clauses.iter().find(|clause| clause.id == "RI4").unwrap();
        assert_eq!(ri4.examples[2].deciding_evidence, ri4.required);
    }
}
