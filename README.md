# Lumia 950 · UniXNU / iOS port

> **目标设备：Microsoft Lumia 950（MSM8992 / Snapdragon 808，非 950 XL）**  
> **目标：在不依赖本地 Mac 的前提下，通过 GitHub Actions 产出并逐级验证 UniXNU / XNU 启动链。**

本仓库以 `TwisstedToast/UniXNU-lumia950` 的 Lumia 950 专用研究成果为代码基线，保留其历史与来源，并用 `upstream` remote 跟踪原项目。它不是 Lumia 950 XL 或 Xperia Z5 Compact 的移植副本。

## 当前真实状态

| 层级 | 当前证据 | 状态 |
|---|---|---|
| Lumia 原厂 UEFI / Boot Shim | 手机已启动 UniXNU EFI 菜单；GOP 和音量键输入已测 | 已验证 |
| UEFI 运行环境 | 2026-10-26 EFI probe：EL1、1080×1920 BGR GOP、帧缓冲区 `0x00400000`、计数器 19.2 MHz | 已测量 |
| UniXNU 菜单 | EFI 菜单可在真机显示；音量键可选择 | 已验证 |
| DarwinBoot | 可由 CI 构建并进入 payload 配置，但尚无 XNU 真机交接证明 | 未完成 |
| XNU 16.x + iOS 16.7.16 kernelcache 合并 | GitHub Actions 曾完成编译、链接、prelink candidate 生成 | 构建证据，不等于启动 |
| XNU 真机入口 | 尚未证明 | 未完成 |
| eMMC 存储 | NativeSdhci 核心有主机模拟测试，驱动曾 ABI 编译；尚无真机 XNU 读盘证明 | 未完成 |
| 显示 | NativeMdss 目前只完成 rung 1 寄存器探测；没有向 XNU 发布 framebuffer | 未完成 |
| GPU | Adreno 418 目前只完成身份/电源域探测；没有 iOS GPU 服务 | 未完成 |
| iOS 根文件系统 / launchd / SpringBoard | 950 项目尚未完成 | 未完成 |

**因此本仓库当前应被称为 P1 bring-up / research，而不是“已经能在 Lumia 950 运行 iOS”。** 首个可交付目标是稳定、可重复地构建 EFI payload 和 XNU candidate；后续必须分别通过真机 XNU entry、storage/root、display 和 userland checkpoint。

## 为什么选这个基线

- `TwisstedToast/UniXNU-lumia950` 是 Lumia 950（MSM8992）设备仓库的后续 fork，包含设备探测、GICv2、eMMC、显示/GPU 的分阶段实现和 CI。
- `shrimpapplepro/UniXNU-lumia950xl` 的成果是 Lumia 950 XL（MSM8994），不能直接作为 950 的驱动配置。
- `DankPeng420/UniXNU-suzuran` 是 Xperia Z5 Compact（MSM8994、Adreno 430、Sony S1 bootloader）项目；可参考启动阶段隔离、userland 工具和 GPU 研究，但不可直接移植其 SoC/显示/触摸寄存器配置。
- `WOA-Project/linux` 的 `v5.8-rc3-lumia` 分支是 2020 年的 Linux 5.8 开发线，可用作设备树、时钟/电源/存储/显示寄存器的交叉参考，不是 XNU 内核的构建基线。
- UniXNU 官方目录目前仍把 Lumia 950 记录为 **Format 1、MSM8992、P1、使用手机自身 UEFI、尚无 XNU boot**。没有可直接复用的 MSM8992 Format 2 SoC common 仓库，因此不能伪造 `soc_source` 或把 MSM8996/8994 配置套用过来。

## Git remotes

```text
origin    https://github.com/hnmrxz/lumia950-ios-port.git
upstream  https://github.com/TwisstedToast/UniXNU-lumia950.git
```

UniXNU 主框架是单独的构建依赖：`https://github.com/UniXNU/UniXNU`。目前 16.x kernel patch overlay 依赖的框架提交仍固定在设备仓库 CI 的已验证基线，不能未经兼容性验证直接改成 UniXNU `main`。

## GitHub Actions

- 每次涉及 `board.toml`、`configs/`、`drivers/`、`scripts/`、`payload/`、`ci/`、`feeds.toml` 或 workflow 的 `main` 推送：Ubuntu 验证 + macOS XNU 构建。
- Pull Request：运行快速 Ubuntu 验证；重型 macOS kernel job 可手动触发，避免每个 PR 消耗长时间 runner。
- `Actions → build → Run workflow` 可选 `payload`、`kernel` 或 `both`。
- 默认 macOS runner 为 `macos-26`，可在仓库 `Settings → Secrets and variables → Actions → Variables` 中设置 `MACOS_RUNNER` 覆盖，例如 `macos-latest` 或 `macos-26-intel`。
- `macos-latest` 是浮动标签。当前 GitHub 将它映射到 macOS 26 Apple Silicon runner；框架上游选择固定 `macos-26` 是为了避免 Xcode/clang 镜像漂移。本项目默认使用固定镜像，并提供变量覆盖；若 XNU 编译遇到内存瓶颈，可尝试 `macos-26-intel` 并对比日志中的资源数据。每次构建都会记录 Xcode、SDK、clang、架构和磁盘空间。

### 必需的 GitHub 设置

- 启用 Actions。
- `Settings → Actions → General` 允许 workflow 创建 Actions artifacts。
- （可选）设置 Actions variable `MACOS_RUNNER`。
- 不需要 Mac，不需要在个人电脑安装 Xcode。
- 首轮 kernel job 从苹果公开 IPSW 获取 pinned kernelcache；**不要把 IPSW、Apple kernel extensions、预链接 kernel 或设备身份数据提交到 Git 仓库或公开 Release**。检查 Actions artifact 的访问范围和保留时间；涉及 Apple 二进制的构建请保持仓库私有。

## 开始构建

1. 打开 GitHub 仓库的 Actions，先运行 `build` workflow 的 `target=payload`。
2. 下载 `lumia950-payload` artifact，检查 `UniXNU.efi`、`DarwinBoot.efi` 和 payload 配置。
3. 再手动运行 `target=kernel`，重点检查每个设备 driver 的 XNU ABI 编译记录、archive 成员、kernel link 和 prelink report。
4. 只有构建产物通过静态检查后，才进入真机测试。第一次 XNU entry 测试必须保留可回滚的 Windows boot route，不要先改分区或覆盖原厂启动文件。

具体门槛见 [docs/BUILD-VERIFICATION.md](docs/BUILD-VERIFICATION.md)，硬件资料见 [docs/HARDWARE-INVENTORY.md](docs/HARDWARE-INVENTORY.md)，路线图见 [docs/PORTING-ROADMAP.md](docs/PORTING-ROADMAP.md)。

## 安全边界

- 不在自动化脚本中执行 WPInternals 解锁、写入 UEFI、修改 BCD、改 GPT 或写 eMMC。
- 不把 Lumia 950 XL / Xperia Z5 Compact 的驱动参数当作 Lumia 950 实测值。
- 未实测的寄存器地址、内存保留区、分区起止 LBA、面板 DSI PHY/PLL 表均保持 TODO，不用猜测值填充。
- 构建成功只代表该阶段构建通过，不代表硬件启动或 iOS 可用。
