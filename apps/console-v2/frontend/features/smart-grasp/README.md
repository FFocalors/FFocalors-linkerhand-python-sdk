# 智能抓取

智能抓取页面向 O6/L6/L7/L10/L20 等支持的型号，提供空载标定、预抓取定位、预设化抓取、释放与中止的状态机控制。

## 职责

- 通过 `GraspController` 驱动标定、逼近、抓取、释放与中止；页面不直接访问设备。
- 展示抓取阶段（idle → calibrating → calibrated → approaching → closingCoarse → closingFine → preloading → holding → success → releasing / aborted / failed）、关节接触评分与负载。
- 首次抓取强制要求先完成空载标定（标定结果仅会话内缓存）。

## 调试模式

- 页面能力 `canOperate = isPhysicalDevice || debugMode`。
- 调试模式 ON + 未连接物理手：智能抓取可用（作用于虚拟手）。
- 调试模式 OFF + 未连接物理手：标定、逼近、抓取、释放、中止与预设选择全部禁用，显示「未连接机械手，智能抓取不可用」提示。
- 真实物理手已连接时（`isPhysicalDevice` 为真）无论开关状态均可用。
- 调试模式不改变抓取状态机的语义：`release` 仍是软件急停式释放，不是物理断电急停。

## 不负责

本 feature 不直接调用设备、不实现 Tauri Channel、sidecar 或 3D。未接入 controller 或型号不支持时，对应控件禁用并给出明确说明。
