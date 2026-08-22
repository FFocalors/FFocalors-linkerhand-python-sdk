//! Bounded structured log storage with deterministic pagination and export DTOs.
use console_contracts::{LogLevel, StructuredLogEntry};
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct LogFilter {
    pub min_level: Option<LogLevel>,
    pub event: Option<String>,
    /// Case-insensitive search over event and message.
    pub keyword: Option<String>,
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
    /// Ingest a batch while applying the same capacity bound after every item.
    /// The iterator is consumed incrementally, so callers can stream large input.
    pub fn push_batch<I>(&mut self, entries: I)
    where
        I: IntoIterator<Item = StructuredLogEntry>,
    {
        for entry in entries {
            self.push(entry);
        }
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
        let page_limit = limit.clamp(1, 512);
        for e in self
            .entries
            .iter()
            .filter(|e| cursor.is_none_or(|c| e.monotonic_time_ms > c))
            .filter(|e| Self::matches_filter(e, filter))
            .take(page_limit)
        {
            out.push(e.clone());
        }
        let next = out.last().map(|e| e.monotonic_time_ms);
        LogPage {
            entries: out,
            next_cursor: next,
            total_dropped: self.dropped,
        }
    }
    pub fn export_json(&self, filter: Option<&LogFilter>) -> String {
        self.try_export_json(filter).expect("log DTO serializable")
    }
    pub fn try_export_json(&self, filter: Option<&LogFilter>) -> Result<String, serde_json::Error> {
        // Export is intentionally separate from UI pagination: the store is
        // already bounded by capacity, so every matching retained entry is safe.
        let entries: Vec<_> = self
            .entries
            .iter()
            .filter(|entry| Self::matches_filter(entry, filter))
            .cloned()
            .collect();
        serde_json::to_string(&entries)
    }
    fn matches_filter(entry: &StructuredLogEntry, filter: Option<&LogFilter>) -> bool {
        filter.is_none_or(|f| {
            f.min_level.as_ref().is_none_or(|l| &entry.level >= l)
                && f.event.as_ref().is_none_or(|x| &entry.event == x)
                && f.keyword.as_ref().is_none_or(|x| {
                    let needle = x.to_lowercase();
                    entry.event.to_lowercase().contains(&needle)
                        || entry.message.to_lowercase().contains(&needle)
                })
        })
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn e(i: u64) -> StructuredLogEntry {
        StructuredLogEntry {
            schema_version: 1,
            id: i.to_string(),
            monotonic_time_ms: i,
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

    #[test]
    fn batch_filter_and_cursor_are_bounded() {
        let mut s = LogStore::new(4);
        s.push_batch((0..100_000).map(|i| StructuredLogEntry {
            schema_version: 1,
            id: i.to_string(),
            monotonic_time_ms: i,
            level: if i % 2 == 0 {
                LogLevel::Info
            } else {
                LogLevel::Warn
            },
            event: if i % 2 == 0 {
                "telemetry.sample".into()
            } else {
                "connection.retry".into()
            },
            message: format!("sample {i}"),
            fields: serde_json::json!({}),
        }));
        let page = s.page(
            Some(99_995),
            100_000,
            Some(&LogFilter {
                min_level: Some(LogLevel::Warn),
                event: None,
                keyword: Some("retry".into()),
            }),
        );
        assert!(page.entries.len() <= 4);
        assert!(page.entries.iter().all(|e| e.event == "connection.retry"));
        assert_eq!(s.len(), 4);
        assert_eq!(s.dropped(), 99_996);
    }

    #[test]
    fn export_includes_every_retained_entry_over_ui_page_limit() {
        let mut s = LogStore::new(1_024);
        s.push_batch((0..1_024).map(e));
        let json = s.try_export_json(None).unwrap();
        let exported: Vec<StructuredLogEntry> = serde_json::from_str(&json).unwrap();
        assert_eq!(exported.len(), 1_024);
        assert_eq!(exported.first().unwrap().monotonic_time_ms, 0);
        assert_eq!(exported.last().unwrap().monotonic_time_ms, 1_023);
    }
}
