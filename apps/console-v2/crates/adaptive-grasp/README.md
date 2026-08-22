# adaptive-grasp

面向操作员的纯自适应抓取状态机。支持 O6/L6/L7/L10/L20；G20/L21/L25 通过 `try_new` 和 `is_available` 明确不可用。

流程是 `Calibrating → Ready → Approaching → Grasping → Holding → Releasing → Ready`，任意运行阶段都可 `abort`。`tick` 使用 fake clock 和固定 50ms 步长，检查断线、遥测越界、超时、过流和触觉缺失，并返回可解释的 `FailureReason`。

输出为完整 normalized joint vector。触碰的单指会锁存当前位置，直到释放；无触觉时默认失败，只有 `GraspConfig::allow_degraded_without_tactile` 显式开启才会返回 `degraded: true`。EMA、死区和 raw 阈值留在高级诊断配置，不是默认操作 UI。

前端公开的 `features/smart-grasp` `GraspController` 是 UI 与运行时之间的 feature-local Port：它覆盖标定、接近、抓取、释放、中止和状态/`rawTouch` 订阅。未接线或没有 rawTouch 时显示明确空态。
