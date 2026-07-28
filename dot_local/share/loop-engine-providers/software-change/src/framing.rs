//! Strict "exactly one JSON object" framing.
//!
//! `serde_json` resolves duplicate object keys last-wins and would let a
//! trailing value pass unnoticed. The engine parses provider output strictly and
//! treats duplicate keys as `provider.graph.invalid`, so this provider refuses
//! the same inputs on the way in rather than disagreeing about what it read.

use std::collections::HashSet;

pub fn validate_single_object(text: &str) -> Result<(), String> {
    let bytes = text.as_bytes();
    let mut cursor = Cursor { bytes, index: 0 };

    cursor.skip_whitespace();
    if cursor.peek() != Some(b'{') {
        return Err("request must be one JSON object".to_string());
    }
    cursor.value()?;
    cursor.skip_whitespace();
    if cursor.index != bytes.len() {
        return Err("request contains a trailing JSON value".to_string());
    }
    Ok(())
}

struct Cursor<'a> {
    bytes: &'a [u8],
    index: usize,
}

impl<'a> Cursor<'a> {
    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.index).copied()
    }

    fn bump(&mut self) -> Option<u8> {
        let byte = self.peek();
        if byte.is_some() {
            self.index += 1;
        }
        byte
    }

    fn skip_whitespace(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\t' | b'\n' | b'\r')) {
            self.index += 1;
        }
    }

    fn expect(&mut self, byte: u8) -> Result<(), String> {
        self.skip_whitespace();
        if self.bump() == Some(byte) {
            Ok(())
        } else {
            Err(format!("expected {:?} at byte {}", byte as char, self.index))
        }
    }

    fn value(&mut self) -> Result<(), String> {
        self.skip_whitespace();
        match self.peek() {
            Some(b'{') => self.object(),
            Some(b'[') => self.array(),
            Some(b'"') => self.string().map(|_| ()),
            Some(_) => self.scalar(),
            None => Err("unexpected end of request".to_string()),
        }
    }

    fn object(&mut self) -> Result<(), String> {
        self.expect(b'{')?;
        let mut seen: HashSet<String> = HashSet::new();

        self.skip_whitespace();
        if self.peek() == Some(b'}') {
            self.index += 1;
            return Ok(());
        }

        loop {
            self.skip_whitespace();
            if self.peek() != Some(b'"') {
                return Err("object key must be a string".to_string());
            }
            let key = self.string()?;
            if !seen.insert(key.clone()) {
                return Err(format!("request contains duplicate object key {key:?}"));
            }
            self.expect(b':')?;
            self.value()?;
            self.skip_whitespace();
            match self.bump() {
                Some(b',') => continue,
                Some(b'}') => return Ok(()),
                _ => return Err("object missing closing delimiter".to_string()),
            }
        }
    }

    fn array(&mut self) -> Result<(), String> {
        self.expect(b'[')?;
        self.skip_whitespace();
        if self.peek() == Some(b']') {
            self.index += 1;
            return Ok(());
        }
        loop {
            self.value()?;
            self.skip_whitespace();
            match self.bump() {
                Some(b',') => continue,
                Some(b']') => return Ok(()),
                _ => return Err("array missing closing delimiter".to_string()),
            }
        }
    }

    fn string(&mut self) -> Result<String, String> {
        self.expect(b'"')?;
        let start = self.index;
        loop {
            match self.bump() {
                Some(b'\\') => {
                    self.bump().ok_or_else(|| "unterminated escape".to_string())?;
                }
                Some(b'"') => {
                    let raw = &self.bytes[start..self.index - 1];
                    return String::from_utf8(raw.to_vec())
                        .map_err(|error| format!("invalid string in request: {error}"));
                }
                Some(_) => {}
                None => return Err("unterminated string in request".to_string()),
            }
        }
    }

    fn scalar(&mut self) -> Result<(), String> {
        let start = self.index;
        while matches!(
            self.peek(),
            Some(b'-' | b'+' | b'.' | b'e' | b'E' | b'0'..=b'9' | b'a'..=b'd' | b'f'..=b'z')
        ) {
            self.index += 1;
        }
        if self.index == start {
            return Err(format!("unexpected byte at offset {}", self.index));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::validate_single_object;

    #[test]
    fn accepts_one_object() {
        validate_single_object(r#"{"a":1,"b":[1,2,{"c":null}]}"#).unwrap();
    }

    #[test]
    fn rejects_duplicate_key_at_any_depth() {
        assert!(validate_single_object(r#"{"a":1,"a":2}"#).is_err());
        assert!(validate_single_object(r#"{"outer":{"a":1,"a":2}}"#).is_err());
        assert!(validate_single_object(r#"{"list":[{"a":1,"a":2}]}"#).is_err());
    }

    #[test]
    fn rejects_trailing_value() {
        assert!(validate_single_object(r#"{"a":1} {"b":2}"#).is_err());
    }

    #[test]
    fn rejects_non_object_root() {
        assert!(validate_single_object("[1,2]").is_err());
        assert!(validate_single_object("\"text\"").is_err());
    }

    #[test]
    fn allows_escaped_quote_in_key() {
        validate_single_object(r#"{"a\"b":1,"ab":2}"#).unwrap();
    }
}
