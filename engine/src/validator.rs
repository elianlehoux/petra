use serde::{Deserialize, Serialize};
use std::process::{Command, Stdio};
use std::time::Instant;
use std::io::Write;
use regex::Regex;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationResult {
    pub passed: bool,
    pub gate_name: String,
    pub message: String,
    pub duration_ms: u64,
}

pub fn validate_syntax(script: &str) -> ValidationResult {
    let start = Instant::now();
    let mut child = Command::new("python3")
        .arg("-c")
        .arg("import ast, sys; ast.parse(sys.stdin.read())")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn();

    if let Ok(mut child_proc) = child {
        if let Some(mut stdin) = child_proc.stdin.take() {
            let _ = stdin.write_all(script.as_bytes());
        }
        let output = child_proc.wait_with_output();
        let duration_ms = start.elapsed().as_millis() as u64;

        if let Ok(out) = output {
            if out.status.success() {
                return ValidationResult {
                    passed: true,
                    gate_name: "syntax".to_string(),
                    message: "Syntax is valid".to_string(),
                    duration_ms,
                };
            } else {
                return ValidationResult {
                    passed: false,
                    gate_name: "syntax".to_string(),
                    message: String::from_utf8_lossy(&out.stderr).into_owned(),
                    duration_ms,
                };
            }
        }
    }

    ValidationResult {
        passed: false,
        gate_name: "syntax".to_string(),
        message: "Failed to run python3".to_string(),
        duration_ms: start.elapsed().as_millis() as u64,
    }
}

pub fn validate_security(script: &str) -> ValidationResult {
    let start = Instant::now();
    
    let dangerous_patterns = [
        r"os\.system",
        r"subprocess",
        r"eval\s*\(",
        r"exec\s*\(",
        r"__import__",
        r"shutil\.rmtree",
        r"open\s*\([^,]+,\s*['\"]w",
        r"requests\.",
        r"socket\.",
    ];

    for pattern in &dangerous_patterns {
        let re = Regex::new(pattern).unwrap();
        if re.is_match(script) {
            return ValidationResult {
                passed: false,
                gate_name: "security".to_string(),
                message: format!("Security violation found: match for pattern {}", pattern),
                duration_ms: start.elapsed().as_millis() as u64,
            };
        }
    }

    ValidationResult {
        passed: true,
        gate_name: "security".to_string(),
        message: "Security check passed".to_string(),
        duration_ms: start.elapsed().as_millis() as u64,
    }
}

pub fn validate_execution(script: &str, test_input: &str, _timeout_secs: u64) -> ValidationResult {
    let start = Instant::now();
    
    let mut child = Command::new("python3")
        .arg("-c")
        .arg(script)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn();

    if let Ok(mut child_proc) = child {
        if let Some(mut stdin) = child_proc.stdin.take() {
            let _ = stdin.write_all(test_input.as_bytes());
        }
        
        // Basic execution without strict timeout enforcement in std::process for now
        // To do real timeout in rust we'd need wait_timeout crate or async, 
        // for standard library we just wait.
        let output = child_proc.wait_with_output();
        let duration_ms = start.elapsed().as_millis() as u64;

        if let Ok(out) = output {
            if out.status.success() {
                return ValidationResult {
                    passed: true,
                    gate_name: "execution".to_string(),
                    message: String::from_utf8_lossy(&out.stdout).into_owned(),
                    duration_ms,
                };
            } else {
                return ValidationResult {
                    passed: false,
                    gate_name: "execution".to_string(),
                    message: String::from_utf8_lossy(&out.stderr).into_owned(),
                    duration_ms,
                };
            }
        }
    }

    ValidationResult {
        passed: false,
        gate_name: "execution".to_string(),
        message: "Execution failed".to_string(),
        duration_ms: start.elapsed().as_millis() as u64,
    }
}

pub fn validate_output(actual: &str, expected: &str) -> ValidationResult {
    let start = Instant::now();
    let passed = actual.trim() == expected.trim();
    let duration_ms = start.elapsed().as_millis() as u64;

    ValidationResult {
        passed,
        gate_name: "output".to_string(),
        message: if passed { "Output matched".to_string() } else { "Output did not match".to_string() },
        duration_ms,
    }
}

pub fn run_validation_pipeline(script: &str, test_input: &str, expected_output: Option<&str>) -> Vec<ValidationResult> {
    let mut results = Vec::new();

    let syntax_res = validate_syntax(script);
    results.push(syntax_res.clone());
    if !syntax_res.passed { return results; }

    let sec_res = validate_security(script);
    results.push(sec_res.clone());
    if !sec_res.passed { return results; }

    let exec_res = validate_execution(script, test_input, 30);
    results.push(exec_res.clone());
    if !exec_res.passed { return results; }

    if let Some(expected) = expected_output {
        let out_res = validate_output(&exec_res.message, expected);
        results.push(out_res);
    }

    results
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validate_security() {
        let script1 = "print('hello')";
        assert!(validate_security(script1).passed);

        let script2 = "import os\nos.system('ls')";
        assert!(!validate_security(script2).passed);

        let script3 = "import subprocess";
        assert!(!validate_security(script3).passed);
        
        let script4 = "eval('1 + 1')";
        assert!(!validate_security(script4).passed);
    }
}
