# Worked Exemplar — oxide-clone

One concrete instantiation of the dependency rule. **Not the canon.** Use as illustration of how neutral corollaries land in a real repo. Do not cite oxide-specific patterns as authority when auditing other repos — they're one solution among many.

## The repo at a glance

- **Product:** Android media browser for rclone-backed remotes (local / SFTP / crypt). Rust + Flutter.
- **Stack:** Rust workspace (3 crates) + Flutter app + JNI/FFI bridge.
- **Layering vocabulary:** Core / Providers / Consumers / UI.

## Layer map

| Layer | Crate / module | Neutral term | Notes |
|-------|----------------|--------------|-------|
| Inner | `crates/core` | Inner core | Entities, services, port traits, policy (cache paths, error taxonomy) |
| Outbound adapters | `crates/providers` | Outbound adapters | `CliRcloneProvider`, settings stores — implement Core traits |
| Inbound adapters / transport | `crates/consumers` | Inbound adapters | `flutter_rust_bridge.rs`, JNI bindings — translate FFI in/out |
| Delivery | `flutter/lib` | Delivery / UI | Screens, providers (state mgmt), repositories (FFI wrappers), widgets |

## Corollary illustrations

| Corollary | Oxide instance |
|-----------|----------------|
| **C1 DIP** | Provider traits defined in `crates/core/src/provider.rs`; `CliRcloneProvider` in `crates/providers` implements them. Core imports never reach into providers. |
| **C3 Boundary data plain** | rclone CLI output parsed into plain Core structs at the Provider boundary. JSON / process handles never enter Core. |
| **C4 Plain domain objects** | Core entities free of `serde` derives that imply transport format. Serialization concerns sit in Consumers. |
| **C6 Errors translate** | Rust `Result<T, E>` propagates with `?` inside layers; at the FFI boundary in `crates/consumers/src/flutter_rust_bridge.rs`, errors map to `String` for Dart. |
| **C11 Policy in Core** | Cache paths generated in `core/cache_utils.rs`, not in providers. Crypt password lifecycle (memory-only, zeroize-on-exit) owned by Core. |
| **C13 UI thin** | Flutter is rendering / capture only. State derived from Core via repositories. Decisions (e.g. wallpaper rotation state machine) live in Core. |
| **C14 Humble object** | `WallpaperService` and `WallpaperEngine` (Android lifecycle shells) delegate to Core for decisions; engine code restricted to surface management + defensive-flag guards. |
| **C16 Composition root** | Wiring of concrete providers happens at FFI bridge initialisation in `consumers`. Core has no `new ConcreteProvider()` calls. |
| **C18 Independence axes** | rclone → S3 swap would replace the Provider impl; Core unchanged. FFI → HTTP swap would replace `consumers`; Core unchanged. |
| **C19 Integration tests** | Tests live in `crates/core/tests/` and exercise real Provider impls. Mock-heavy unit tests of Core are explicitly avoided per CLAUDE.md. |

## Healthy feature flow (C10) — concrete

Per the repo's `CLAUDE.md`, adding a feature lands in this order:

1. Domain logic in `crates/core/` (trait in `provider.rs` if I/O needed)
2. Implementation in `crates/providers/`
3. FFI bridge in `crates/consumers/src/flutter_rust_bridge.rs`
4. Generated FFI bindings via build script
5. Flutter UI consumes the new binding
6. Integration test in `crates/core/tests/`

Inner-out, then test at the seam. A feature requiring outer changes first is a signal an inner abstraction is missing.

## What oxide does NOT illustrate

- **C9 use-case split** — Core organizes by service, not by entities-vs-use-cases. A larger domain might want the split.
- **C5 anti-corruption layer** — rclone is the only external model; translation is light. Multi-third-party repos would need explicit ACLs.
- **C21 / C22 layout findings** — oxide is a media browser (UI-heavy by nature). Merit gate would downgrade most outer-fattening / framework-screaming findings to informational anyway.

## When citing oxide in a finding

Don't. Findings should cite the **corollary** and the audited repo's own locations. Oxide is a reference for the skill author; the audited project's reader doesn't need the lineage.
