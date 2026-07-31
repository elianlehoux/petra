use thiserror::Error;

#[derive(Error, Debug)]
pub enum EngineError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),

    #[error("Execution timeout")]
    Timeout,

    #[error("Artifact not found: {0}")]
    ArtifactNotFound(String),

    #[error("Execution failed: {0}")]
    ExecutionFailed(String),
}

pub type Result<T> = std::result::Result<T, EngineError>;
