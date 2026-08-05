pub mod audit;
pub mod authority;
pub mod boundary;
pub mod bundle;
pub mod claims;
mod codec;
pub mod doctrine;
pub mod evidence;
pub mod judgment;
pub mod policy;
pub mod protocol;
pub mod recovery;
pub mod repository;
mod schema;
pub mod storage;
pub mod workflow;

pub use codec::parse_json_object;
pub use protocol::{handle, RequestEnvelope, REQUEST_LIMIT_BYTES, RESULT_LIMIT_BYTES};

pub const PROVIDER_VERSION: &str = concat!("documentation-maintenance/", env!("CARGO_PKG_VERSION"));
