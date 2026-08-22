//! Bounded structured log storage with deterministic pagination and export DTOs.
use console_contracts::{LogLevel, StructuredLogEntry};
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct LogFilter {
    pub min_level: Option<LogLevel>,
    pub event: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct LogPage {
    pub entries: Vec<StructuredLogEntry>,
    pub next_cursor: Option<u64>,
    pub total_dropped: u64,
}
#[derive(Clone, Debug)]
pub struct LogStore {
    capacity: usize,
    entries: VecDeque<StructuredLogEntry>,
    dropped: u64,
}
impl LogStore {
    pub fn new(capacity: usize) -> Self {
        assert!(capacity > 0);
        Self {
            capacity,
            entries: VecDeque::with_capacity(capacity),
            dropped: 0,
        }
    }
    pub fn push(&mut self, entry: StructuredLogEntry) {
        if self.entries.len() == self.capacity {
            self.entries.pop_front();
            self.dropped += 1;
        }
        self.entries.push_back(entry);
    }
    pub fn len(&self) -> usize {
        self.entries.len()
    }
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
    pub fn dropped(&self) -> u64 {
        self.dropped
    }
    pub fn page(&self, cursor: Option<u64>, limit: usize, filter: Option<&LogFilter>) -> LogPage {
        let mut out = Vec::new();
        for e in self
            .entries
            .iter()
            .filter(|e| cursor.is_none_or(|c| e.sequence > c))
            .filter(|e| {
                filter.is_none_or(|f| {
                    f.min_level.as_ref().is_none_or(|l| &e.level >= l)
                        && f.event.as_ref().is_none_or(|x| &e.event == x)
                })
            })
            .take(limit.max(1))
        {
            out.push(e.clone());
        }
        let next = out.last().map(|e| e.sequence);
        LogPage {
            entries: out,
            next_cursor: next,
            total_dropped: self.dropped,
        }
    }
    pub fn export_json(&self, filter: Option<&LogFilter>) -> String {
        let p = self.page(None, self.entries.len().max(1), filter);
        serde_json::to_string(&p.entries).expect("log DTO serializable")
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn e(i: u64) -> StructuredLogEntry {
        StructuredLogEntry {
            schema_version: 1,
            sequence: i,
            monotonic_ms: i,
            level: LogLevel::Info,
            event: "x".into(),
            message: i.to_string(),
            fields: serde_json::json!({}),
        }
    }
    #[test]
    fn one_hundred_thousand_writes_stay_bounded() {
        let mut s = LogStore::new(8);
        for i in 0..100_000 {
            s.push(e(i));
        }
        assert_eq!(s.len(), 8);
        assert_eq!(s.dropped(), 99_992);
    }
}
