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

## 合并镜像的 panic 位置又靠前了一步（本轮实测）

本机对 `lumia950-prelinked`（54 MB，run 45832509015 的产物）跑一次 `--past-bsd --finish-iokit`：

- FIPS POST **全部通过**：`fipspost_post:206: all tests PASSED (118 ms)`；
- dmesg 一直写到 `IOKit IOMD setownership ENABLED`，然后停在 `_panic`；
- **dmesg 里没有 panic 文本**，serial.log 也停在 DarwinBoot 的交接页。

也就是说：合并镜像不是"起不来"，而是**进到 IOKit 早期、在第一次 kext 匹配之前就 panic 了**，而且 panic 的信息没有被
kprintf 缓冲下来（这正是 fixture 用 `_panic` 符号判断的原因）。

下一步（小而确定）：用 GDB 在 `_panic` 处停下并读 `x0`（panic 的格式串），把这条信息拿出来——它决定 prelink 这条路
是否值得继续，也决定第 3 个阻塞项是"我们的 kext 不兼容"还是"合并镜像本身有更早的问题"。

## 合并镜像 panic 的原因读出来了：`!prng_ready` 断言

fixture 在 `_panic` 停下时已经解出了格式串与参数，不必再上 GDB：

```
panic_format : "%s:%d Assertion failed: %s"
panic_args   : ['!prng_ready']
milestones   : arm_vm_init → kernel_bootstrap → source_crypto_bootstrap → iokit_entry
```

**`!prng_ready`** 的含义是"这里断言 PRNG 还没有初始化"——可是它已经被初始化了。合并镜像里同时存在两份
corecrypto 初始化路径：

- 框架补丁 `patches/xnu/source-corecrypto14-bootstrap.patch` 在 `STARTUP(EARLY_BOOT, RANK_FIRST)` 里调用
  `corecrypto_kext_start()`；
- 合并镜像里还带着 Apple 自己的 `com.apple.kec.corecrypto`（prelink 的 roots 之一）。

于是 PRNG 被初始化两次，后一次撞上 `!prng_ready`。源码内核没有这个问题（同一份补丁只跑一次），这也解释了为什么
源码镜像能 PASS 而合并镜像不能。

### 这对存储路线的意义

prelink 是**唯一不依赖私有 API** 的第三方 kext 通道，而它必须先通过"合并镜像能启动"这一关。现在的阻塞点非常具体：
**要避免双重 corecrypto 初始化**——要么让源码补丁在存在 prelinked corecrypto 时不执行，要么给断言加前置判断。
两者都在框架补丁层，不在本仓库的驱动里。
