//! loop-engine provider protocol v1 — stdio transport.
//!
//! One fresh process per invocation: read exactly one JSON object from stdin
//! until EOF, dispatch on `role`, write exactly one JSON object to stdout, exit.
//! Stderr carries human diagnostics only and is never authoritative.

mod cache;
mod config;
mod framing;
mod gates;
mod graph;
mod protocol;
mod roles;
mod situation;
mod util;

use std::io::{Read, Write};

use protocol::{RequestEnvelope, REQUEST_LIMIT_BYTES, RESULT_LIMIT_BYTES};

fn main() {
    if let Err(error) = run() {
        eprintln!("software-change provider: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), String> {
    let mut raw = Vec::new();
    std::io::stdin()
        .take((REQUEST_LIMIT_BYTES + 1) as u64)
        .read_to_end(&mut raw)
        .map_err(|error| format!("read request: {error}"))?;
    if raw.len() > REQUEST_LIMIT_BYTES {
        return Err("request exceeds the 4 MiB protocol limit".to_string());
    }

    let text =
        std::str::from_utf8(&raw).map_err(|error| format!("request is not UTF-8: {error}"))?;
    framing::validate_single_object(text)?;

    let request: RequestEnvelope =
        serde_json::from_str(text).map_err(|error| format!("decode request: {error}"))?;
    let response = roles::handle(request)?;

    let encoded =
        serde_json::to_vec(&response).map_err(|error| format!("encode result: {error}"))?;
    if encoded.len() > RESULT_LIMIT_BYTES {
        return Err("result exceeds the 1 MiB protocol limit".to_string());
    }

    let mut stdout = std::io::stdout().lock();
    stdout.write_all(&encoded).map_err(|error| format!("write result: {error}"))?;
    stdout.flush().map_err(|error| format!("flush result: {error}"))?;
    Ok(())
}
