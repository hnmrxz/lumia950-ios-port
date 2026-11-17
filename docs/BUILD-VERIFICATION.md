# Build / verification contract

## Workflow matrix

| Workflow/job | Runner | 触发 | 它能证明什么 | 它不能证明什么 |
|---|---|---|---|---|
| `validate` | Ubuntu | push / PR / dispatch | TOML/defconfig、脚本语法、host tests、ADT、payload checks、QEMU fixtures（按当前 workflow） | IOKit driver 编译、XNU boot、手机硬件 |
| `efi-preflight` | Ubuntu | push / PR / dispatch | EFI build/preflight 和模拟协议/设备检查 | 手机固件上实际行为、XNU entry |
| `gicv2-emulation` | Ubuntu + QEMU | push / PR / dispatch | GICv2 timer/SGI/SPI 模拟路径 | XNU kernel 中断路径及真机 SMP |
| `payload` | Ubuntu | 手动 `target=payload` / `both` | UniXNU EFI menu、DarwinBoot、配置/文件树 | XNU kernel ABI 编译、kernel handoff |
| `stage` | macOS | 手动 `target=both` | 由同一次 run 的 payload / kernel / GPU artifact 拼出的可部署树，kernel 哈希与 `build-manifest.json` 一致，并通过安装器的前置校验（manifest、七个文件哈希、菜单与 crypto 契约） | 真机写入；托管 runner 没有到手机的 USB 通路 |
| `installer-windows` | windows-2022 | push / PR / dispatch | 安装器的 Windows 后端在真实 Windows 文件系统上的行为：卷识别、身份拒绝、原子写、备份、回读 | 真机写入；没有接手机的卷 |
| `kernel` | macOS + Xcode | 手动 `kernel` / `both`（macOS 分钟按 10 倍计费，推送不再触发） | xnu-8796 kernel build、设备 IOKit ABI compile、archive/link、iOS 16.7.16 kernelcache prelink report | XNU 真机执行、eMMC、屏幕、iOS root/userland |

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
- `lumia950-stage`：只有 `target=both` 的 `stage` job 产出。它是 `scripts/install-native-bringup.py`
  唯一接受的输入形状，由同一次 run 的 payload / kernel / GPU artifact 拼出，kernel 的 SHA-256 与
  `build-manifest.json` 记录一致才继续；`native-bringup.json` 里因此有 `build_manifest_sha256`、
  `build_repo_commit`、`adt_profile`。保留 3 天，因为它虽然只含 source-only 二进制，却是设备树。
- `lumia950-kernel` 携带 `out/build-manifest.json`：本仓库 commit、决定构建内容的四个文件
  （workflow、`ci/unixnu-16x.patch`、`feeds.toml`、`board.toml`）的 SHA-256、pinned framework
  ref 与 tree id、`unixnu.lock`、`[kernel.prelink] kernelcache_sha256`、`board.toml` 与 CI 一次性
  副本的守卫状态、Xcode/SDK/clang，以及每个产物的字节数与 SHA-256。缺任一输入、或产物哈希与
  文件不符，kernel job 在写完 manifest 的同一分钟失败（`scripts/build-manifest.py --check
  --verify-outputs`）。**没有 manifest 的 artifact 不算证据**，只有日志。

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
