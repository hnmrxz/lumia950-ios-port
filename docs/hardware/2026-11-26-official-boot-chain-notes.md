# 官方启动链与诊断文档，对照本移植（2026-11-26）

读了 [启动链](https://unixnu.com/zh/concepts/boot-chain) 与 [调试与日志](https://unixnu.com/zh/guide/debugging) 之后，把
与本机现状直接相关的部分摘出来，并标注我们对应到了哪一步。原文为外部文档，本文只做对照，不复制其实现。

## 一、启动链的四次交接（官方说法）与本机对应

| 阶段 | 官方描述 | 本机现状 |
|---|---|---|
| 1 bootloader → BootShim | Android bootloader 装入 gzip 镜像（shim+固件卷），BootShim 重定位固件卷进入 UEFI | 本机不是 Android bootloader：stock UEFI 的 ARM32 `bootarm.efi` → BCD `{default}` → 部署工具的 ARM32 `BootShim.efi`（subsystem 0x10）→ `UEFI.elf` |
| 2 UEFI → UniXNU | `UniXNUDxe` 注册 `Boot####`；启动管理器先扫启动卷再扫其他卷找 `\EFI\UniXNU\unixnu.toml` | **已通过**：菜单显示 `config: \EFI\UniXNU\unixnu.toml`，`drivers 2 loaded / 0 failed` |
| 3 UniXNU → DarwinBoot | `xnu` 菜单项通过 loader protocol 交给 DarwinBoot：卷、`KernelPath`、`BootArgs`、设备树、ramdisk、kexts；UniXNU 准备并安装 DTB 为 `EFI_DTB_TABLE` | **已通过**：`DARWINBOOT: loader v2 installed EL1`、`inputs validated`、`hand-off to the kernel` |
| 4 DarwinBoot → XNU | 校验 `kernel.macho`（`MH_MAGIC_64`/`ARM64`/`MH_EXECUTE`/`LC_MAIN`/段页对齐/256 MiB 窗口）、读 `.adt` 与 `trustcache`、从 GOP 取 framebuffer、关 MMU 与缓存、EL1 跳转 | **已通过**（否则 DarwinBoot 会 `EFI_COMPROMISED_DATA` 并留给固件继续跑）；本机打印的 `entry words`/`CurrentEL 1` 即此阶段末尾 |
| 5 XNU → 用户态 | `start.s` → bootstrap 页表 → C 启动路径 → 平台专家发布 IOKit registry；平台专家匹配 ADT 根节点；存储驱动发布 userdata，分区方案发布 `OS`/`SystemOS`；XNU 按 UUID 匹配根卷、挂载、启动 `launchd` | **卡在这里**：交接后屏幕上没有任何内核输出 |

官方失败表也印证了这一点：`XNU | 缺少平台或存储驱动 | panic 日志给出缺失的 provider`——也就是说，正常路径下
"没有平台/存储驱动"会**panic 并在串口/panic 屏幕给出 provider 名字**，而不是无声停住。

## 二、官方对"绿条之后无输出"给的诊断手段（本机适用性）

| 手段 | 官方说明 | 本机 |
|---|---|---|
| 颜色条 | 绿 = DarwinBoot 已退出 boot services；**蓝 = 内核入口代码已执行（MMU 仍关）**；**品红 = 到达开 MMU 前**；阶段 3 无色条，改为 `entry_probe_reset_delay` 秒后 **PSCI 复位**，设备自己重启即证明 MMU 已打开 | 本机只有绿条 → 蓝条没有 → 与"入口探针未安装"一致；我们的自建两格探针正是补蓝/品红 |
| panic 屏幕 | `[payload] panic_screen = true`，`patch-xnu-entry-probe.py --panic-screen --no-reset`，把 panic 文本+寄存器画到 framebuffer 并保留 | **未启用**（我们的 payload 步骤里没有这项） |
| 串口 | `-v serial=3 debug=0x14e`；UniXNU 行 `UNIXNU:`，加载器行 `DARWINBOOT:`，内核行走串口 | 本机无可用 UART，`serial=` 无效 |
| 诊断页 | `boot-progress=1/2`，48×120 文本覆盖层，含 `last PC`、`TCR/TTBR/SCTLR`、存储与进程计数 | 属上游较新内核功能，本 pin 无 |
| 持久化日志 | 预留存储区 + Linux/recovery 读取；记录 `Darwin Kernel Version`、`SourceStorage: Data disk started` 等检查点 | 本机尚无（需存储驱动先工作） |
| 复位检查点 | `entry_probe_reset_after = "_arm_vm_init"` 等，过 MMU 后延时复位 | 我们的探针**只到 MMU 前**；复位检查点可后补 |

## 三、官方文档给出的两个"本机应照着做"的结论

1. **根卷不是 ramdisk，也不是合成介质**：官方第 5 阶段明确是"存储驱动发布 userdata，分区方案发布
   `OS`/`SystemOS`，XNU 按 UUID 匹配根卷"。参照实现（950 XL）用的是 eMMC 上的 HFS+ 分区
   （`rd=disk0s55`），由 `NativeSdhci` 读——这解释了本项目在 QEMU 里为何只能停"等 Apple_HFS"，也说明
   **真机路线的下一块拼图就是 `NativeSdhci`，而不是继续在无介质条件下折腾 vfs_mountroot**。
2. **无 UART 的板子靠 framebuffer 当仪表**：官方把"入口探针色条 + panic 屏幕 + 诊断页 + 持久化日志"
   作为一条递进的证据链。本机目前只有第一条（绿条），因此**下一步的正确投入顺序**是：
   蓝/品红条（入口探针）→ panic 屏幕 → 持久化日志。

## 四、对本轮实现的影响

我们自建的 `NativeBootProgress`（`drivers/NativeBootProgress/`，两格：`PE_init_platform` 之后、`arm_vm_init` 之前）
与官方"蓝色=内核入口已执行、品红=到达 MMU 前"的语义一致，且都只在 MMU 关闭时绘制——这正是官方文档说明
"阶段 3 没有色条、改用复位"的原因：MMU 打开后帧缓冲不能再直写。

两处已知偏差，按官方文档修正过的方向：

- 面板参数取自 `boot_args.Video`（官方也是"使用记录的 framebuffer 基址和行跨度"）。
- 不再在 MMU 之后绘制；若要"过 MMU"的检查点，应照官方用**复位**（`entry_probe_reset_delay`）而不是写屏幕。

## 五、引用

- 启动链：<https://unixnu.com/zh/concepts/boot-chain>
- 调试与日志：<https://unixnu.com/zh/guide/debugging>
- 故障排查：<https://unixnu.com/zh/reference/troubleshooting>
