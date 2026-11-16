# Build / verification contract

## Workflow matrix

| Workflow/job | Runner | 触发 | 它能证明什么 | 它不能证明什么 |
|---|---|---|---|---|
| `validate` | Ubuntu | push / PR / dispatch | TOML/defconfig、脚本语法、host tests、ADT、payload checks、QEMU fixtures（按当前 workflow） | IOKit driver 编译、XNU boot、手机硬件 |
| `efi-preflight` | Ubuntu | push / PR / dispatch | EFI build/preflight 和模拟协议/设备检查 | 手机固件上实际行为、XNU entry |
| `gicv2-emulation` | Ubuntu + QEMU | push / PR / dispatch | GICv2 timer/SGI/SPI 模拟路径 | XNU kernel 中断路径及真机 SMP |
| `payload` | Ubuntu | 手动 `target=payload` / `both` | UniXNU EFI menu、DarwinBoot、配置/文件树 | XNU kernel ABI 编译、kernel handoff |
| `kernel` | macOS + Xcode | main 设备代码 push；或手动 `kernel` / `both` | xnu-8796 kernel build、设备 IOKit ABI compile、archive/link、iOS 16.7.16 kernelcache prelink report | XNU 真机执行、eMMC、屏幕、iOS root/userland |

## Manual commands

GitHub CLI：

```bash
gh workflow run build.yml -f target=payload --repo hnmrxz/lumia950-ios-port
gh workflow run build.yml -f target=kernel --repo hnmrxz/lumia950-ios-port
gh workflow run build.yml -f target=both --repo hnmrxz/lumia950-ios-port
gh run list --workflow build.yml --repo hnmrxz/lumia950-ios-port
gh run watch <RUN_ID> --repo hnmrxz/lumia950-ios-port
gh run download <RUN_ID> -n lumia950-kernel --repo hnmrxz/lumia950-ios-port
```

## macOS runner

默认由 workflow 中 `vars.MACOS_RUNNER || 'macos-26'` 选择。可以在仓库 Actions Variables 中设置：

- `macos-latest`：当前映射到 macOS 26 Apple Silicon，但这是浮动别名。
- `macos-26`：固定 macOS 26 Apple Silicon 镜像，对齐官方 UniXNU 当前 macOS workflow。
- `macos-26-intel`：固定 macOS 26 Intel 标准 runner；如果 XNU 编译遇到内存瓶颈，可测试此标签并对比耗时/资源。

每次运行都必须记录 `sw_vers`、`uname -m`、`xcodebuild -version`、`xcrun --sdk iphoneos --show-sdk-version`、`clang --version`、`df -h`。若 Xcode 或 SDK 不匹配，job 应失败而不是静默改用其他版本。

## 产物与隐私

- `lumia950-payload`：EFI 程序、配置和 payload tree。
- `lumia950-kernel`：kernel logs、build reports、prelinked candidate（包含从 Apple IPSW kernelcache 合并的 Apple kernel extensions）。
- 对 Apple 相关 binary artifacts，保持私有仓库和短保留期；不要发布到公开 Release、Pages、公开 artifact 镜像或 git history。
- 不上传完整 IPSW、firmware image、trust cache、UniqueChipID 或未经脱敏的设备日志。

## 通过证据的级别

1. `host-tested`：主机测试通过。
2. `QEMU-tested`：指定 QEMU fixture 通过。
3. `ABI-compiled`：driver 使用指定 XNU compile records / iPhoneOS SDK 成功编译。
4. `kernel-linked`：archive 确实被链接，预期符号存在。
5. `prelink-checked`：kernelcache SHA、rebindings、sparse index 和 report 检查通过。
6. `EFI-tested`：Lumia 真机显示并操作 EFI 菜单。
7. `XNU-entry-tested`：真机进入 XNU，记录 platform expert/timer/IRQ checkpoint。
8. `hardware-tested`：对应设备驱动完成一次端到端真实硬件 I/O。
9. `userland-booted`：launchd / backboardd / SpringBoard 的启动证据。

任何一个级别不能仅凭下一阶段以外的测试通过而升级。
