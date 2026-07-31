use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex};

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct MetricsSummary {
    pub total_requests: u64,
    pub compiled_hits: u64,
    pub compilations: u64,
    pub passthroughs: u64,
    pub total_tokens_saved: u64,
    pub total_cost_saved_usd: f64,
    pub compiled_latencies_ms: Vec<u64>,
    pub passthrough_latencies_ms: Vec<u64>,
}

pub struct MetricsTracker {
    summary: MetricsSummary,
}

impl Default for MetricsTracker {
    fn default() -> Self {
        Self::new()
    }
}

impl MetricsTracker {
    pub fn new() -> Self {
        Self {
            summary: MetricsSummary::default(),
        }
    }

    pub fn record_compiled_hit(&mut self, latency_ms: u64, tokens_saved: u64, cost_saved: f64) {
        self.summary.total_requests += 1;
        self.summary.compiled_hits += 1;
        self.summary.total_tokens_saved += tokens_saved;
        self.summary.total_cost_saved_usd += cost_saved;
        self.summary.compiled_latencies_ms.push(latency_ms);
    }

    pub fn record_compilation(&mut self, _latency_ms: u64, _tokens_used: u64, _cost: f64) {
        self.summary.total_requests += 1;
        self.summary.compilations += 1;
        // Depending on design, we might track latency for compilation, but not required by prompt
    }

    pub fn record_passthrough(&mut self, latency_ms: u64, _tokens_used: u64, _cost: f64) {
        self.summary.total_requests += 1;
        self.summary.passthroughs += 1;
        self.summary.passthrough_latencies_ms.push(latency_ms);
    }

    pub fn get_summary(&self) -> MetricsSummary {
        self.summary.clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_metrics_tracker() {
        let mut tracker = MetricsTracker::new();
        tracker.record_compiled_hit(100, 50, 0.05);
        let summary = tracker.get_summary();
        assert_eq!(summary.total_requests, 1);
        assert_eq!(summary.compiled_hits, 1);
        assert_eq!(summary.total_tokens_saved, 50);
    }
}
