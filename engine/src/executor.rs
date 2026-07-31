use crate::error::Result;
use serde::{Deserialize, Serialize};
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};
use std::io::Write;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionResult {
    pub output: String,
    pub execution_time_ms: u64,
    pub success: bool,
    pub error: Option<String>,
}

pub fn execute_artifact(artifact_path: &Path, input: &str) -> Result<ExecutionResult> {
    let start = Instant::now();
    
    let mut child = Command::new("python3")
        .arg(artifact_path)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;

    if let Some(mut stdin) = child.stdin.take() {
        stdin.write_all(input.as_bytes())?;
    }

    let output = child.wait_with_output()?;
    let duration = start.elapsed().as_millis() as u64;

    let success = output.status.success();
    let stdout_str = String::from_utf8_lossy(&output.stdout).into_owned();
    let stderr_str = String::from_utf8_lossy(&output.stderr).into_owned();

    let (final_output, err_msg) = if success {
        (stdout_str, None)
    } else {
        (stdout_str, Some(stderr_str))
    };

    Ok(ExecutionResult {
        output: final_output,
        execution_time_ms: duration,
        success,
        error: err_msg,
    })
}
