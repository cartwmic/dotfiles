pub mod authority;
pub mod boundary;
pub mod bundle;
pub mod codec;
pub mod doctrine;
pub mod policy;
pub mod protocol;
pub mod repository;
pub mod schema;
pub mod storage;
pub mod workflow;

pub const PROVIDER_VERSION: &str = concat!("documentation-maintenance/", env!("CARGO_PKG_VERSION"));
