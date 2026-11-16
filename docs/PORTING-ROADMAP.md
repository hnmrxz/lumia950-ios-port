# Lumia 950 iOS 移植路线图（基于 UniXNU 当前架构）

更新：2026-11-16。目标设备固定为 Lumia 950 / MSM8992。目标 OS 沿用已研究的 iOS 16.7.16（20H392）参考线，直到明确完成 OS/profile 升级评估。

## 架构决策

### 先保持 Lumia 950 Format 1，不伪造 Format 2

UniXNU 当前官方文档将新设备引导到 Format 2：SoC common source、OS profile、DTS、component catalog、device package 与明确版本锁。但官方 `devices.toml` 对 Lumia 950 仍记录为 `format = 1`、`soc = MSM8992`、`board = lumia950`、`summary = device uses phone's own UEFI; no boot`。当前官方 SoC common 生态没有可确认的 MSM8992 package。强行声明为 MSM8996/8994 SoC source 会制造错误资源映射。

因此：

1. 短期沿用当前 Lumia 950 已有的 board.toml、defconfig、patches、drivers、payload、scripts 和 CI。
2. 继续用官方 UniXNU 工具链构建，但固定已验证的 16.x compatibility base；在官方主干支持 xnu-8796 overlay 后再迁移。
3. 先把实际硬件输入整理为 porting record；每个 subsystem 有 source/revision、实现、测试、最后通过的 bring-up rung。
4. 将 Format 2 迁移作为单独 PR/阶段：只有找到/实现 MSM8992 SoC common repository、完成 DTS 与 board package 映射，并由 `unixnu status --json`、`unixnu tree` 和完整 kernel build 验证后才进行。

## 代码与成果复用策略

| 项目 | 可复用内容 | 不可直接复用的部分 |
|---|---|---|
| `ManGuy-Legend/UniXNU-lumia950` | 原始 Lumia 950 board 架构与初始研究 | 不是比 TwisstedToast 更新的主线 |
| `TwisstedToast/UniXNU-lumia950` | 本项目代码基线；MSM8992 probe、GICv2、NativeSdhci、MDSS/A418 分阶段实现、EFI menu/payload | 当前仍 P1；不得把编译或 EFI 菜单当成 XNU boot |
| `shrimpapplepro/UniXNU-lumia950xl` | 同家族手机的 UniXNU boot 组织、iOS root 构建与硬件测试方法 | MSM8994 / Snapdragon 810，不能复制 CPU、PMIC、GPU、存储、触摸值到 MSM8992 |
| `DankPeng420/UniXNU-suzuran` | iOS 16.7.16 root/userland、userland CI、trust cache / add-on 设计、Adreno 430 实验方法 | Xperia Z5 Compact / MSM8994 / Sony S1 bootloader；不能把其 fastboot loader、A430、PMIC/SMP 代码当 Lumia 950 驱动 |
| `WOA-Project/linux` | Linux/设备树和 Qualcomm 驱动作为寄存器/时钟/中断交叉来源 | 旧 Linux kernel 5.8 分支不是 XNU 内核构建基础，也不证明苹果驱动 ABI |
| `UniXNU/UniXNU` | 官方 build engine、component catalog、bring-up、QEMU fixtures、porting-record、当前 runner workflow 规范 | 最新 `main` 默认 XNU/profile 已更新，不能不经 16.x patch-overlay 验证就替换旧的 build-framework pin |

## 阶段计划

### P0 — 仓库、构建和证据管理

- [x] 选择 Lumia 950（MSM8992）为唯一目标，明确排除 950 XL 和 suzuran 直接移植。
- [x] 采用 TwisstedToast Lumia 950 分支作为起点并保留 upstream remote。
- [ ] 自动验证基础 CI：Ubuntu host tests、ADT/payload checks、EFI preflight、GICv2 QEMU tests。
- [ ] macOS XNU job 稳定运行：记录 Xcode/iPhoneOS SDK、ABI 编译、archive、kernel link、prelink report、SHA-256。
- [ ] 自动归档每次 run 的文本日志和 JSON reports；Apple 相关 binary artifact 保持私有和短时保留。

**出口条件：**同一 commit 可重复获得可识别的 payload、kernel candidate 和 machine-readable build report；没有“build green = boot works”的误报。

### P1 — EFI → DarwinBoot → XNU entry

- [x] Lumia 原厂 UEFI 可链式启动 UniXNU 菜单。
- [x] EFI 设备报告已实测 EL1、GOP、RAM descriptors、CPU topology。
- [ ] DarwinBoot handoff 使用实际 1080×1920 GOP、EL1、真实 EFI memory map；保留固件映射策略有明确检查。
- [ ] 在屏幕不可用时建立可读取的持久日志/串口/内存日志路径。
- [ ] XNU 进入 `arm_init` / platform expert / timer / GICv2；逐个 checkpoint 记录日志。
- [ ] 先只启动单核；完成 IRQ/timer，再逐核 bring-up，最后启用 SMP。
- [ ] 成功一次从 DarwinBoot 进入 XNU 后才评估删除 `board.example = true`。

**出口条件：**真机记录证明 XNU 已取控制权，明确日志 checkpoint，不是单凭黑屏、重启或 EFI probe。

### P2 — 存储与 iOS root

- [ ] 实测 MSM8992 SDCC/eMMC 初始化、时钟、电源、总线宽度、PIO read，再做 ADMA2。
- [ ] 只读枚举真实 GPT、分区边界、原始备份；不先写入或重分区。
- [ ] 确定 iOS 16.7.16 使用的 OS/SystemOS/数据窗口、文件系统、UUID、trust cache 和设备树身份。
- [ ] 在 host/macOS builder 构建 root image；CI 产物不含原始 IPSW 或未授权 Apple binaries。
- [ ] XNU 只读挂载 root，逐步到 `launchd`。

**出口条件：**可重复只读挂载 iOS root、`launchd` 启动，设备存储范围与回滚策略已验证。

### P3 — 显示与输入

- [ ] 基于 950 自己的 MDP/DSI/PHY/panel source 补齐 NativeMdss 逐级 bring-up。
- [ ] 优先复用 UEFI GOP framebuffer 作为首屏路径，验证 XNU 映射/缓存属性/scanout 后再接管原生 MDP。
- [ ] 实现 NativeDisplay / IOSurface 最小 CPU renderer。
- [ ] 实测触摸控制器、I2C、GPIO、IRQ，建立 IOHIDEventService。
- [ ] 实测实体按键映射、旋转/分辨率/刷新率。

**出口条件：**iOS kernel console、Apple logo、锁屏首帧可见；触摸/按键事件有端到端证据。

### P4 — userland / 系统服务

- [ ] 构建 iOS root/userland pipeline，匹配 16.7.16 kernelcache 与 OS ABI。
- [ ] 补齐 AMFI、trust cache、keybag/SEP 缺失能力的边界与安全策略。
- [ ] 让 `launchd`、`backboardd`、`SpringBoard` 依次稳定运行。
- [ ] 先采用软件渲染；A418 的 GPU/Metal 工作作为独立项目，不阻塞首个桌面目标。
- [ ] 逐个评估 Wi-Fi、蜂窝、蓝牙、音频、相机、传感器，未完成的功能要明确标成 unsupported。

**出口条件：**桌面可见且基本交互稳定；不以“SpringBoard 偶然启动”宣称可作为日用系统。

### P5 — Format 2 迁移和上游回馈

- [ ] 为 MSM8992 选定/维护 SoC common repo，记录寄存器/DTI/CPU/GIC/SDCC 公共部分。
- [ ] 创建完整 device DTS 和 Format 2 `board.toml`、`feeds.toml`、`porting.toml`、`proprietary-files.txt`、component selections。
- [ ] 将设备专用源码从旧 board package 提炼为组件或留在 device package。
- [ ] 通过 `unixnu status --json`、`unixnu tree`、kernel、payload 和 firmware/package 检查。
- [ ] 把可复用的 MSM8992 或 UniXNU 16.x patch work 上游提交，删除已被官方吸收的本地 shim。

## GitHub Actions 优化原则

- Linux runner 做快检：Python/TOML/YAML、host tests、ADT、payload、QEMU fixture。
- macOS runner 只负责依赖 Xcode / iPhoneOS SDK 的 XNU/IOKit ABI compile、link 和 kernelcache prelink。
- docs-only 提交不触发重型 kernel job；main 上硬件代码变更自动构建；PR 先跑快检，kernel 可手动运行。
- Homebrew 不自动更新；工具和 framework source ref 有明确锁定，运行时记录环境。
- 每个 job 使用 `timeout-minutes`、并发组、日志 artifact 和短保留期；失败时上传第一条 compiler error 和完整日志。
- 不把 `macos-latest` 当作永久固定工具链。可通过 `MACOS_RUNNER` 切换 runner；对比 build result、Xcode SDK、RAM 和磁盘后再固定。

## 绝不提前做的事

- 不自动解锁 bootloader / WPInternals，不自动刷写 UEFI。
- 不自动修改 Windows BCD，不覆盖 Windows 启动文件。
- 不自动修改 GPT / format userdata，不写入 eMMC。
- 不猜测物理地址、GPIO、IRQ、PSCI method、panel PLL 或分区 LBA。
- 不把 950 XL / Xperia 的驱动完整支持状态移植到 Lumia 950 的状态表。
