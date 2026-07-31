use crate::error::{EngineError, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CompiledArtifact {
    pub id: String,
    pub original_prompt_hash: String,
    pub script_content: String,
    pub metadata: Value,
    pub created_at: DateTime<Utc>,
    pub validation_status: String,
    pub execution_count: u64,
    pub avg_execution_time_ms: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArtifactMetadata {
    pub id: String,
    pub original_prompt_hash: String,
    pub created_at: DateTime<Utc>,
    pub validation_status: String,
    pub execution_count: u64,
    pub avg_execution_time_ms: f64,
}

pub struct ArtifactStore {
    base_dir: PathBuf,
}

impl ArtifactStore {
    pub fn new(base_dir: PathBuf) -> Self {
        fs::create_dir_all(&base_dir).unwrap_or_default();
        Self { base_dir }
    }

    fn get_artifact_path(&self, id: &str) -> PathBuf {
        self.base_dir.join(format!("{}.json", id))
    }

    pub fn save(&self, artifact: &CompiledArtifact) -> Result<()> {
        let path = self.get_artifact_path(&artifact.id);
        let content = serde_json::to_string_pretty(artifact)?;
        fs::write(path, content)?;
        Ok(())
    }

    pub fn find_by_prompt_hash(&self, hash: &str) -> Result<Option<CompiledArtifact>> {
        for entry in fs::read_dir(&self.base_dir)? {
            let entry = entry?;
            if entry.path().extension().and_then(|e| e.to_str()) == Some("json") {
                let content = fs::read_to_string(entry.path())?;
                if let Ok(artifact) = serde_json::from_str::<CompiledArtifact>(&content) {
                    if artifact.original_prompt_hash == hash {
                        return Ok(Some(artifact));
                    }
                }
            }
        }
        Ok(None)
    }

    pub fn list(&self) -> Result<Vec<ArtifactMetadata>> {
        let mut list = Vec::new();
        for entry in fs::read_dir(&self.base_dir)? {
            let entry = entry?;
            if entry.path().extension().and_then(|e| e.to_str()) == Some("json") {
                let content = fs::read_to_string(entry.path())?;
                if let Ok(artifact) = serde_json::from_str::<CompiledArtifact>(&content) {
                    list.push(ArtifactMetadata {
                        id: artifact.id,
                        original_prompt_hash: artifact.original_prompt_hash,
                        created_at: artifact.created_at,
                        validation_status: artifact.validation_status,
                        execution_count: artifact.execution_count,
                        avg_execution_time_ms: artifact.avg_execution_time_ms,
                    });
                }
            }
        }
        Ok(list)
    }

    pub fn update_stats(&self, id: &str, execution_time: u64) -> Result<()> {
        let path = self.get_artifact_path(id);
        if !path.exists() {
            return Err(EngineError::ArtifactNotFound(id.to_string()));
        }
        let content = fs::read_to_string(&path)?;
        let mut artifact: CompiledArtifact = serde_json::from_str(&content)?;

        let total_time = (artifact.avg_execution_time_ms * artifact.execution_count as f64) + execution_time as f64;
        artifact.execution_count += 1;
        artifact.avg_execution_time_ms = total_time / artifact.execution_count as f64;

        let new_content = serde_json::to_string_pretty(&artifact)?;
        fs::write(path, new_content)?;
        Ok(())
    }

    pub fn delete(&self, id: &str) -> Result<()> {
        let path = self.get_artifact_path(id);
        if path.exists() {
            fs::remove_file(path)?;
        }
        Ok(())
    }
}
