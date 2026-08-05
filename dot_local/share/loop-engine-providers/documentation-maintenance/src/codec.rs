use crate::schema::{self, RecordKind};
use serde::de::{DeserializeSeed, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Number, Value};
use sha2::{Digest, Sha256};
use std::fmt;

pub const MAX_RECORD_BYTES: usize = 64 * 1024 * 1024;

#[derive(Debug, Clone)]
pub struct DecodedRecord {
    pub kind: RecordKind,
    pub value: Value,
    pub canonical: Vec<u8>,
    pub digest: String,
}

pub fn decode_record(
    bytes: &[u8],
    kind: RecordKind,
    expected_run_id: &str,
) -> Result<DecodedRecord, String> {
    if bytes.len() > MAX_RECORD_BYTES {
        return Err(format!("record exceeds {MAX_RECORD_BYTES} byte limit"));
    }
    if bytes.starts_with(&[0xef, 0xbb, 0xbf]) {
        return Err("record must not contain a UTF-8 BOM".to_string());
    }
    let text =
        std::str::from_utf8(bytes).map_err(|error| format!("record is not UTF-8: {error}"))?;
    let value = parse_json_object(text)?;
    schema::validate(kind, &value)?;
    let run_id = value
        .get("run_id")
        .and_then(Value::as_str)
        .expect("schema requires run_id");
    if run_id != expected_run_id {
        return Err(format!(
            "record run_id mismatch: expected {expected_run_id:?}, found {run_id:?}"
        ));
    }
    let canonical = canonicalize(&value)?;
    let digest = sha256(&canonical);
    Ok(DecodedRecord {
        kind,
        value,
        canonical,
        digest,
    })
}

pub fn encode_record(
    value: &Value,
    kind: RecordKind,
    expected_run_id: &str,
) -> Result<DecodedRecord, String> {
    schema::validate(kind, value)?;
    let run_id = value
        .get("run_id")
        .and_then(Value::as_str)
        .expect("schema requires run_id");
    if run_id != expected_run_id {
        return Err(format!(
            "record run_id mismatch: expected {expected_run_id:?}, found {run_id:?}"
        ));
    }
    let canonical = canonicalize(value)?;
    if canonical.len() > MAX_RECORD_BYTES {
        return Err(format!(
            "canonical record exceeds {MAX_RECORD_BYTES} byte limit"
        ));
    }
    let digest = sha256(&canonical);
    Ok(DecodedRecord {
        kind,
        value: value.clone(),
        canonical,
        digest,
    })
}

pub fn canonicalize(value: &Value) -> Result<Vec<u8>, String> {
    serde_json_canonicalizer::to_vec(value)
        .map_err(|error| format!("RFC 8785 encoding failed: {error}"))
}

pub fn sha256(bytes: &[u8]) -> String {
    format!("sha256:{}", hex::encode(Sha256::digest(bytes)))
}

pub fn verify_digest(bytes: &[u8], claimed: &str) -> Result<(), String> {
    validate_digest(claimed)?;
    let actual = sha256(bytes);
    if actual != claimed {
        return Err(format!(
            "sha256 mismatch: expected {claimed}, computed {actual}"
        ));
    }
    Ok(())
}

pub fn validate_digest(value: &str) -> Result<(), String> {
    let Some(hex) = value.strip_prefix("sha256:") else {
        return Err("digest must have sha256: prefix".to_string());
    };
    if hex.len() != 64
        || !hex
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(
            "digest must be sha256 followed by 64 lowercase hexadecimal digits".to_string(),
        );
    }
    Ok(())
}

pub fn parse_json_object(text: &str) -> Result<Value, String> {
    let mut deserializer = serde_json::Deserializer::from_str(text);
    let value = NoDuplicates
        .deserialize(&mut deserializer)
        .map_err(|error| format!("invalid JSON record: {error}"))?;
    deserializer
        .end()
        .map_err(|error| format!("trailing JSON data: {error}"))?;
    if !value.is_object() {
        return Err("record root must be an object".to_string());
    }
    Ok(value)
}

struct NoDuplicates;

impl<'de> DeserializeSeed<'de> for NoDuplicates {
    type Value = Value;

    fn deserialize<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        deserializer.deserialize_any(NoDuplicateVisitor)
    }
}

struct NoDuplicateVisitor;

impl<'de> Visitor<'de> for NoDuplicateVisitor {
    type Value = Value;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("valid JSON without duplicate object keys")
    }

    fn visit_bool<E>(self, value: bool) -> Result<Value, E> {
        Ok(Value::Bool(value))
    }

    fn visit_i64<E>(self, value: i64) -> Result<Value, E> {
        Ok(Value::Number(Number::from(value)))
    }

    fn visit_u64<E>(self, value: u64) -> Result<Value, E> {
        Ok(Value::Number(Number::from(value)))
    }

    fn visit_f64<E>(self, value: f64) -> Result<Value, E>
    where
        E: serde::de::Error,
    {
        Number::from_f64(value)
            .map(Value::Number)
            .ok_or_else(|| E::custom("non-finite JSON number"))
    }

    fn visit_str<E>(self, value: &str) -> Result<Value, E> {
        Ok(Value::String(value.to_owned()))
    }

    fn visit_string<E>(self, value: String) -> Result<Value, E> {
        Ok(Value::String(value))
    }

    fn visit_none<E>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }

    fn visit_unit<E>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }

    fn visit_seq<A>(self, mut sequence: A) -> Result<Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        let mut values = Vec::new();
        while let Some(value) = sequence.next_element_seed(NoDuplicates)? {
            values.push(value);
        }
        Ok(Value::Array(values))
    }

    fn visit_map<A>(self, mut object: A) -> Result<Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        let mut values = Map::new();
        while let Some(key) = object.next_key::<String>()? {
            if values.contains_key(&key) {
                return Err(serde::de::Error::custom(format!(
                    "duplicate object key {key:?}"
                )));
            }
            let value = object.next_value_seed(NoDuplicates)?;
            values.insert(key, value);
        }
        Ok(Value::Object(values))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn fixture() -> Vec<u8> {
        let root = env!("CARGO_MANIFEST_DIR");
        fs::read(format!("{root}/fixtures/records/valid/claim-set-v1.json")).unwrap()
    }

    #[test]
    fn canonical_equivalents_have_identical_bytes() {
        let a = br#"{"schema":"claim-set-v1","run_id":"run-1","manifest_digest":"sha256:0000000000000000000000000000000000000000000000000000000000000000","claims":[]}"#;
        let b = fixture();
        let a = decode_record(a, RecordKind::ClaimSet, "run-1").unwrap();
        let b = decode_record(&b, RecordKind::ClaimSet, "run-1").unwrap();
        assert_eq!(a.canonical, b.canonical);
        assert_eq!(a.digest, b.digest);
    }

    #[test]
    fn rejects_bom_invalid_utf8_duplicate_key_schema_and_run_mismatch() {
        let mut bom = vec![0xef, 0xbb, 0xbf];
        bom.extend(fixture());
        assert!(decode_record(&bom, RecordKind::ClaimSet, "run-1").is_err());
        assert!(decode_record(&[0xff], RecordKind::ClaimSet, "run-1").is_err());
        let root = env!("CARGO_MANIFEST_DIR");
        let duplicate = fs::read(format!(
            "{root}/fixtures/records/invalid/duplicate-key.json"
        ))
        .unwrap();
        assert!(decode_record(&duplicate, RecordKind::ClaimSet, "run-1").is_err());
        assert!(decode_record(&fixture(), RecordKind::AuditReport, "run-1").is_err());
        assert!(decode_record(&fixture(), RecordKind::ClaimSet, "run-2").is_err());
    }

    #[test]
    fn digest_requires_lowercase_and_matches_canonical_bytes() {
        let record = decode_record(&fixture(), RecordKind::ClaimSet, "run-1").unwrap();
        verify_digest(&record.canonical, &record.digest).unwrap();
        assert!(verify_digest(&record.canonical, &record.digest.to_uppercase()).is_err());
        assert!(verify_digest(b"different", &record.digest).is_err());
    }

    #[test]
    fn rfc8785_number_and_unicode_vectors() {
        let value: Value =
            serde_json::from_str(r#"{"\u20ac":"x","a":1e21,"b":-0.0,"c":5e-324}"#).unwrap();
        let encoded = String::from_utf8(canonicalize(&value).unwrap()).unwrap();
        assert_eq!(encoded, r#"{"a":1e+21,"b":0,"c":5e-324,"€":"x"}"#);
    }
}
