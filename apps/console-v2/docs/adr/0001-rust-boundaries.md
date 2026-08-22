# ADR 0001: Tauri-free Rust core

Core crates do not depend on Tauri, frontend APIs, or Python. Tauri is an assembly concern in `src-tauri`; app coordination uses typed ports and direct ownership.
