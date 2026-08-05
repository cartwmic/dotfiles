pub mod authority;
pub mod boundary;
pub mod codec;
pub mod protocol;
pub mod repository;
pub mod schema;
pub mod storage;

pub const PROVIDER_VERSION: &str = concat!("documentation-maintenance/", env!("CARGO_PKG_VERSION"));
