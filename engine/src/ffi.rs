use crate::executor;
use crate::hasher;
use crate::metrics::{MetricsTracker, MetricsSummary};
use crate::validator;
use once_cell::sync::Lazy;
use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::path::Path;
use std::sync::{Arc, Mutex};
use serde_json;

pub static METRICS_TRACKER: Lazy<Arc<Mutex<MetricsTracker>>> = Lazy::new(|| {
    Arc::new(Mutex::new(MetricsTracker::new()))
});

fn safe_cstr_to_str(s: *const c_char) -> Option<&'static str> {
    if s.is_null() {
        return None;
    }
    unsafe { CStr::from_ptr(s).to_str().ok() }
}

fn string_to_c_char(s: String) -> *mut c_char {
    CString::new(s).unwrap().into_raw()
}

#[no_mangle]
pub extern "C" fn compiled_router_execute(artifact_path: *const c_char, input: *const c_char) -> *mut c_char {
    let path_str = match safe_cstr_to_str(artifact_path) {
        Some(s) => s,
        None => return string_to_c_char(r#"{"error": "invalid path"}"#.to_string()),
    };
    let input_str = match safe_cstr_to_str(input) {
        Some(s) => s,
        None => "",
    };

    match executor::execute_artifact(Path::new(path_str), input_str) {
        Ok(res) => {
            let json = serde_json::to_string(&res).unwrap_or_else(|_| r#"{"error": "serialization error"}"#.to_string());
            string_to_c_char(json)
        },
        Err(e) => string_to_c_char(format!(r#"{{"error": "{}"}}"#, e)),
    }
}

#[no_mangle]
pub extern "C" fn compiled_router_hash_prompt(prompt: *const c_char) -> *mut c_char {
    let prompt_str = match safe_cstr_to_str(prompt) {
        Some(s) => s,
        None => "",
    };
    let hash = hasher::hash_prompt(prompt_str);
    string_to_c_char(hash)
}

#[no_mangle]
pub extern "C" fn compiled_router_validate(script: *const c_char, test_input: *const c_char) -> *mut c_char {
    let script_str = safe_cstr_to_str(script).unwrap_or("");
    let input_str = safe_cstr_to_str(test_input).unwrap_or("");

    let results = validator::run_validation_pipeline(script_str, input_str, None);
    let json = serde_json::to_string(&results).unwrap_or_else(|_| "[]".to_string());
    string_to_c_char(json)
}

#[no_mangle]
pub extern "C" fn compiled_router_get_metrics() -> *mut c_char {
    let tracker = METRICS_TRACKER.lock().unwrap();
    let summary = tracker.get_summary();
    let json = serde_json::to_string(&summary).unwrap_or_else(|_| "{}".to_string());
    string_to_c_char(json)
}

#[no_mangle]
pub extern "C" fn compiled_router_free_string(s: *mut c_char) {
    if !s.is_null() {
        unsafe {
            let _ = CString::from_raw(s);
        }
    }
}
