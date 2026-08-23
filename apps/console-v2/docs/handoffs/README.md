# 模块交接记录

本目录保存一次模块开发、修复或集成完成后的 handoff。总入口是 [`../DEVELOPMENT.md`](../DEVELOPMENT.md)，当前集成快速入口是 [`../HANDOFF.md`](../HANDOFF.md)，模块依赖边界见 [`../MODULES.md`](../MODULES.md)。

历史记录按主题命名，例如 `contract-freeze.md`、`core-wiring.md`、`release-integration.md`、`vision-worker-loader-fix.md`。历史记录中的测试结果属于记录所标注的分支/提交；接手后必须按当前 HEAD 复验，不能只复制“passed”。

## 新 handoff 模板

复制下面结构到 `docs/handoffs/<scope>.md`，按实际情况删改。不要填写没有证据的硬件、浏览器或发布结论。

```markdown
# <模块/任务> handoff

## Scope

- Branch: `<codex/v2-...>`
- Base / HEAD: `<commit>`
- Changed paths: `<paths>`
- Public contracts changed: `yes/no`
- Related docs: [`../MODULES.md`](../MODULES.md), `<ADR/contract links>`

## Delivered

- <行为、不变量、Port 或 assembly seam>
- <错误/停止/取消/降级语义>

## Verification

在 `apps/console-v2` 执行的真实命令和结果：

- `<command>` — `<pass/fail/not run; relevant output>`
- `<command>` — `<pass/fail/not run; relevant output>`

明确区分静态检查、fake/simulator、浏览器交互、sidecar subprocess 和真实硬件证据。

## Limits / remaining gates

- <未完成事项>
- <需要真实 O6 PCAN、clean Windows 或摄像头权限的事项>
- <不能宣称的行为，例如 stop 不是物理急停>

## Next agent entry points

1. <下一步从哪个文件/Port/测试开始>
2. <启动或复验命令>
3. <预期风险和回滚边界>
```

## 记录规则

- 记录当前实际分支、基线/HEAD 和公共契约是否变化。
- 只记录实际执行过的命令；历史结果要注明来源分支/提交。
- 硬件未接入时写“未验证”，不要把 simulator 或 fake sidecar 改写成真实设备证据。
- 交接后仍需由下一 Agent 维护当前集成 [`HANDOFF.md`](../HANDOFF.md) 的基线和优先级。

