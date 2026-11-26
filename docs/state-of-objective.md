# 目标现状：哪一段通了，哪一段被什么挡住

一页纸，给"越过 BSD 初始化并进入 iOS 用户态/显示/桌面"这个目标做现状盘点。每条都指向可核对的证据，
不用"应该能行"这种说法。

## 已经成立的

| 环节 | 证据 | 标签 |
|---|---|---|
| 真机 EFI 链：固件 → 刷机迷 BootShim/UEFI.elf → 本移植加载器 → UniXNU 菜单 → DarwinBoot → 内核交接 | 真机照片与 DarwinBoot 交接页（`docs/hardware/2026-11-26-first-hardware-boot.md`） | hardware-tested |
| 面板可由**我们的代码**写入（y=120/140，满宽），固件报告的显示模式 = 1080×1920、stride 1080 像素、BGR、基址 0x400000 | 真机对照条照片 `docs/hardware/control-mark/handset-photo.jpg` | hardware-tested |
| 源码内核能跑到 `bsd_init`（含 `arm_vm_init`、source-crypto POST、PE_init_iokit） | QEMU：`PASS ... returned from arm_vm_init and ... bsd_init` | QEMU-tested |
| 内核控制台会往面板写文字 | 帧缓冲回读：3,795 个亮像素成行分布 | QEMU-tested |
| 第 3 条（post-MMU）色块能画：本机 12,800 像素 = 最后 16 行 | `docs/hardware/measurements/post-mmu-bar/` | QEMU-tested |
| `NativeSdhci` 能链成 kext（645 符号）并打成 95,462 B mkext | runner 日志（kext + mkext 校验通过） | ABI-compiled |
| 容器能转 C 数组并编进内核归档 | `scripts/embed-blob.py` + 5 个主机测试 | host-tested |

## 卡住的三件事（各有明确原因）

1. **真机内核是否执行：未知。** 我们从未在真机上看到任何内核输出。对照条证明面板可写，所以"全黑"只剩
   "内核没执行"或"内核视频初始化失败"两种解释，而区分它们需要一次真机开机照片（底部绿条）。
2. **存储驱动进不了内核：API 边界。** `OSKext::loadFromMkext()` 与 `withBooterData()` 在 pin 里都是 `private`；
   公开的 `loadKextWithIdentifier()` 需要从磁盘找 bundle，而磁盘正是驱动要提供的——成环。
   见 ADR-0003 的 "M4 blocker found at compile time"。
3. **合并镜像（prelinked）在模拟器里到不了 IOKit。** 多次运行停在 `_panic`，也就是说这条路目前连"能启动"
   都还没成立；而它恰恰是 prelink 携带第三方 kext 的唯一通道。

## 下一步的三个候选（按"能不能在本机验证"排序）

1. **等一张真机照片**（底部绿条）：一次开机就能把未知项 1 变成确定项，决定后续是修显示控制台还是修执行路径。
2. **把容器写进 `__PRELINK_INFO`**：不碰私有 API，但要求同时解决未知项 3（合并镜像先在模拟器里跑通）。
3. **走 `kmod_control()`/`OSKext::handleRequest()`**：公开入口，但请求格式是用户态形状，工程量最大。

## 不该再做的事

- 再往 `arm_init` 里画东西（面板在那时未映射，已在 `docs/hardware/2026-11-26-instrument-plan.md` 证明）；
- 再把 staged 镜像当成"被验证过的镜像"（它过不了内核自己的 FIPS 完整性 POST）；
- 再靠"色块没出现"推断内核没跑（仪器缺失、开关子串匹配、指针读错都曾造成同样的现象）。
