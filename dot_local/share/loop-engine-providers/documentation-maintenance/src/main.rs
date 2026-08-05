use documentation_maintenance::{
    handle, parse_json_object, RequestEnvelope, REQUEST_LIMIT_BYTES, RESULT_LIMIT_BYTES,
};
use std::io::{Read, Write};

fn main() {
    if let Err(error) = run() {
        eprintln!("documentation-maintenance provider: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), String> {
    let mut bytes = Vec::new();
    std::io::stdin()
        .take((REQUEST_LIMIT_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|error| format!("read request: {error}"))?;
    if bytes.len() > REQUEST_LIMIT_BYTES {
        return Err("request exceeds protocol 4 MiB limit".to_string());
    }
    if bytes.starts_with(&[0xef, 0xbb, 0xbf]) {
        return Err("request must not contain a UTF-8 BOM".to_string());
    }
    let text =
        std::str::from_utf8(&bytes).map_err(|error| format!("request is not UTF-8: {error}"))?;
    let value = parse_json_object(text)?;
    let request: RequestEnvelope = serde_json::from_value(value)
        .map_err(|error| format!("decode request envelope: {error}"))?;
    let response = handle(request)?;
    let encoded =
        serde_json::to_vec(&response).map_err(|error| format!("encode result: {error}"))?;
    if encoded.len() > RESULT_LIMIT_BYTES {
        return Err("result exceeds protocol 1 MiB limit".to_string());
    }
    let mut stdout = std::io::stdout().lock();
    stdout
        .write_all(&encoded)
        .map_err(|error| format!("write result: {error}"))?;
    stdout
        .flush()
        .map_err(|error| format!("flush result: {error}"))
}
