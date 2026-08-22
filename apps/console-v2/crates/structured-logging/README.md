# structured-logging

职责：保存有界结构化日志，提供级别/事件/关键词过滤、游标分页、批量写入和 JSON DTO 导出。不负责文件系统、Tauri 权限或 UI 虚拟列表。

公开入口：`LogStore`、`LogFilter`、`LogPage`，以及 `push_batch`、`page`、`try_export_json`。

状态与不变量：capacity 始终限制内存；批量输入逐条应用容量上限；页大小最多 512；游标按 monotonic time 向前；过滤不改变存储。

错误：`try_export_json` 返回序列化错误；兼容旧调用的 `export_json` 仅在 DTO 不可序列化这一编程错误时 panic。

测试：包含 100,000 条批量输入的容量回归，以及过滤/游标验证。使用 `cargo test -p structured-logging`。

扩展点：未来可把游标换为稳定 token、把导出接到 Tauri Port，但不把文件 I/O 放入 crate。
