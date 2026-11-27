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

## 合并镜像现在能跑到 `bsd_init` 了：单次 PRNG 注册解开了整条链

`ci/prng-single-init.py` 生效后的第一次成功构建（run 45858986402，head `c834080`），fixture 的报告是：

```
milestones : arm_vm_init_entry → arm_vm_init_return → kernel_bootstrap_entry →
             source_crypto_bootstrap_entry → source_crypto_bootstrap_return →
             iokit_entry → iokit_return → bsd_init_entry
stop       : _panic
panic      : Failed to mount root device @%s:%d
past_bsd   : root-wait
```

也就是说：**合并（prelinked）镜像已经穿过 IOKit 并进入 BSD 初始化**，然后停在"没有根设备"——这正是需求本身。
此前它停在 `!prng_ready` 断言，一行幂等保护就把整条链解开了。

同一轮里另外两件成立的事：

- kext 步骤在 kernel 之前跑通：`NativeSdhci: kext`（645 符号）、`NativeSdhci: blob`、两个 mkext（校验和一致）；
- **源码镜像的 `bsd_init` 门禁仍然 PASS**，说明补丁没有破坏已经成立的部分。

### 这把问题的形状彻底改变了

| 之前 | 现在 |
|---|---|
| 合并镜像起不来（`!prng_ready`） | 合并镜像**能到 BSD 初始化** |
| 存储 kext 没有可用的投递通道 | **prelink 通道可用**，只差把我们的 kext 放进 prelink 信息 |

下一步因此非常具体：**把 `NativeSdhci` 的 kext 条目写进合并镜像的 prelink 信息**，让内核按它加载 Apple kext 的同一路径
加载我们的驱动；随后 `Failed to mount root device` 就该变成"找到介质但格式不对"或"挂载成功"——两者都是新的、可读的证据。

## 容器确实躺在内核里：95,462 字节的 mkext 在运行时被读到

本机用最新源码镜像（run 45858986402 的 unstripped）加 `lumia-kext` 启动，dmesg 里出现两行，把"嵌入是否真的存在"
这件事钉死了：

```
LUMIA: vinfo base=fffffff038c04000 row=3200 height=600
       args=-v cpus=1 lumia-bars2 lumia-kext skmem_seg_size=16384 ...
lumia: 95462 bytes of kext container are embedded, but OSKext::loadFromMkext() is private
       in this kernel; the load is not wired yet
```

- **95,462 字节**正是 `NativeSdhci.mkext` 的大小（本机与 runner 两边一致）；
- 命令行里的开关被正确识别（token 匹配）；
- 调用路径走到了"API 私有"这一步，说明**嵌入、符号、调用点全部成立**，只差一个可用的加载入口。

至此存储侧不再有"可能没做对"的部分：kext（645 符号）、容器（95 KB）、C 数组、编译进归档、运行时可达，全部有证据。

## 手机已就位：下一次开机就会真的跑内核（不再停在对照条）

本轮检查发现两件事，都影响"你按一次电源能得到什么"：

1. **手机确实连在这台电脑上**（`MSFT Phone MMC Stor` 大容量存储），分区都在：`H:` 是 MainOS，`R:` 是 EFIESP。
2. 但 `R:\EFI\BOOT\BOOTAA64.EFI` 之前是**3,072 字节的对照条程序**（它画两条杠后死等），**永远不会启动内核**。
   也就是说：在这种状态下按下电源，屏幕上不可能出现"底部绿条"——那不是内核没跑，而是我们没让它跑。

已把真正的加载器恢复回去（用的是本仓库自己的备份，不碰刷机迷的文件）：

```
R:\EFI\BOOT\BOOTAA64.EFI                        94,208 B   SHA256 9d9311b3…   PE AArch64, subsystem 10
R:\EFI\BOOT\BOOTAA64.EFI.before-control-mark     94,208 B   （同一文件，留作回滚）
R:\EFI\BOOT\BootShim.efi                         53,744 B   ARM32 subsystem 16 —— 刷机迷的文件，未改动
R:\EFI\BOOT\bootarm.efi                         870,856 B   —— 未改动
```

`R:\EFI\UniXNU\unixnu.toml`：`default = "xnu"`、`timeout = 20`、`args = "-v cpus=1 lumia-bars2"`。

`H:\EFI\UniXNU\Payloads\kernel.macho`：18,822,808 B，SHA256 `7ae95f48…`——本机实测能画底部绿条（12,800 像素）的那一份。

### 所以现在按一次电源，应该看到

1. 加载器阶段（UniXNU 菜单，20 秒倒计时后自动进 `xnu`）；
2. DarwinBoot 交接；
3. **屏幕最底部 16 行出现绿色条**（那代表内核在真机跑到了 `bsd_init`）；
4. 或者：菜单/交接页之后**全黑**（那代表内核在真机没执行，或视频初始化失败）。

**请各拍一张：菜单/交接页、以及屏幕最底部**。这张图决定后续所有优先级。

## 手机上的**那一份文件**在本机跑通了：到 `bsd_init` 并画出底部绿条

与其等一次开机来验证布置对不对，不如把手机里的文件原样搬到本机跑一遍。`scripts/stage-phone-esp.py` 做的事：

- 取 `R:\EFI\BOOT\BOOTAA64.EFI`（94,208 B，即恢复后的真加载器）；
- **整棵** `R:\EFI\UniXNU`（含 `UniXNU.efi`、`Drivers\DarwinBoot.efi` 26,624 B、`Drivers\ntfs.efi`、`unixnu.toml`）；
- 取 `H:\EFI\UniXNU\Payloads\kernel.macho`（7ae95f48）与其 ADT 边车。

第一次搬漏了 `Drivers\` 目录，菜单当场报 `no loader protocol installed`——**问题在我的搬运，不在手机**。补齐后本机启动结果：

```
PASS: ... returned from arm_vm_init and the real source-provider POST/bootstrap and
      PE_init_iokit and bsd_init

milestones : arm_vm_init_entry → arm_vm_init_return → kernel_bootstrap_entry →
             source_crypto_bootstrap_entry → source_crypto_bootstrap_return →
             iokit_entry → iokit_return → bsd_init_entry
[    7.609069]: LUMIA: vinfo base=fffffff059804000 row=3200 height=600 args=-v cpus=1 lumia-bars2
```

帧缓冲回读（800×600）：

| 区域 | 亮像素 |
|---|---|
| **最后 16 行** | **12,800**（= 800 × 16，满宽绿条） |
| 第 100–140 行 | 4,582（控制台文字等） |

之后的 panic 是 `Calling {k,z}alloc from interrupt disabled context isn't allowed`——那是 CI 用 `skmem_*` 参数绕过的已知问题，
发生在**绿条之后**，不影响这次要的证据。

### 这条结论的价值

**部署在手机上的那一份文件，内容上是被验证过的**：它在本机能穿过 IOKit 进入 `bsd_init` 并画出底部绿条。
剩下的唯一未知是"这台手机的实际硬件会不会跑它"——那正是需要一次开机照片的东西。

## 找到一个会让真机"画完绿条就崩"的 bug：**DAIF 只屏蔽、没恢复**

把手机里那份内核在本机跑，`LUMIA:` 之后立刻 panic：

```
panic : Calling {k,z}alloc from interrupt disabled context isn't allowed
format: %s:%d Assertion failed: %s
```

顺着这条线索读 `drivers/NativeBootProgress/NativeBootProgress.cpp`：画第 2 条（post-MMU）色块的代码做了

```c
asm volatile("msr DAIFSet, #0xf" ::: "memory");   // 屏蔽所有中断
... 写帧缓冲 ...
asm volatile("dsb sy" ::: "memory");
```

**它屏蔽了中断却从不恢复**。于是 `bsd_init` 里紧接着的第一次分配（`throttle_init`）就在"中断已屏蔽"的上下文里调用
`kalloc`，命中内核断言。

这意味着：**真机若跑到 `bsd_init`，会被我们自己的埋点搞崩**——绿条出现后随即 panic。这不是 QEMU 的怪癖，是与硬件无关的代码缺陷。

### 修法（已改）

```c
uint64_t daif = 0;
asm volatile("mrs %0, DAIF" : "=r"(daif) :: "memory");   // 先保存
asm volatile("msr DAIFSet, #0xf" ::: "memory");          // 再屏蔽
... 写帧缓冲 ...
asm volatile("dsb sy" ::: "memory");
asm volatile("msr DAIF, %0" :: "r"(daif) : "memory");     // 最后恢复
```

主机测试无法执行内联汇编，所以用源码不变量来钉：`scripts/test-diaf-restored.py` 断言"有屏蔽就必须先保存、后恢复，且恢复在屏蔽之后"。
`preflight` 的 aarch64 编译也重新通过。

## DAIF 修复已在模拟器验证，并把修好的内核装到了手机上

修复后的内核（run 45869127033）用**手机自己的配置**启动本机：

```
past_bsd_outcome : stopped            （之前是 panicked）
panic            : None
bottom 16 rows   : 12,800 亮像素       （绿条仍在）
dmesg 末段       : dlil_init … skmem_region_init seg_size 16384 …
```

也就是说：**绿条照旧，而"绿条之后立刻 panic"消失了**，内核继续走到 `dlil_init`/`skmem_region_init` 之后才停在
`_fleh_synchronous`——一个新的、更靠后的失败，而不是被我们自己的埋点打断。

已把这份内核装到手机上（`scripts/deploy-kernel.py`，旧内核留在 `kernel.macho.prev`）：

```
H:\EFI\UniXNU\Payloads\kernel.macho        18,921,840 B   sha256 3b65f550…
H:\EFI\UniXNU\Payloads\kernel.macho.prev   18,822,808 B   sha256 7ae95f48…（上一份，可回滚）
H:\EFI\UniXNU\Payloads\DEPLOYED.txt        记录这次装的是哪一份
```

所以下一次开机（不论谁按电源）跑的是**没有 DAIF bug 的内核**：绿条会出现，并且不会因为埋点而立刻崩。

## 手机现在的配置：本机跑到 **root-wait**，而且绿条还在

上一轮把修好的内核（`3b65f550`）装进手机后，本机复跑又暴露一个**配置层**的问题：停点是 `_skmem_sysctl_init+0x44`。
这正是 CI 用 `skmem_sysctl_skip=1` 关掉的那段发布逻辑——而手机的 `args` 里没有它。

把该参数加进 `R:\EFI\UniXNU\unixnu.toml` 后重跑（**用的就是手机上的文件**）：

```
args = "-v cpus=1 lumia-bars2 skmem_sysctl_skip=1"

past_bsd  : root-wait
panic     : Failed to mount root device        ← 这正是目标里的"没有根设备"
milestones: … iokit_return → bsd_init_entry
bottom 16 rows bright: 12,800                  ← 绿条仍在
```

### 现在的状态（手机侧的三个文件都是"最好的已知版本"）

| 文件 | 内容 |
|---|---|
| `R:\EFI\BOOT\BOOTAA64.EFI` | 真加载器 94,208 B `9d9311b3` |
| `R:\EFI\UniXNU\unixnu.toml` | `args = "-v cpus=1 lumia-bars2 skmem_sysctl_skip=1"` |
| `H:\EFI\UniXNU\Payloads\kernel.macho` | 18,921,840 B `3b65f550`（含 DAIF 修复） |

**本机用这套文件启动：穿过 IOKit、进入 `bsd_init`、画出 12,800 像素底部绿条，最后停在"找不到根设备"。**

也就是说：手机若与 QEMU 一致，按下电源应看到绿条并停留在根设备等待——那正是这个目标要跨过去的最后一道门。

## 为什么这一步必须由你按一次电源（而不是我远程做）

本轮又试了一次"能不能自己让手机开机"，结论是不能：

| 路径 | 结果 |
|---|---|
| 大容量存储模式的 USB 设备 | 只是把 eMMC 暴露成磁盘；写入不会重启设备 |
| `thor2`（Samsung/Microsoft 刷机工具） | 只能看到处于 Thor/紧急下载模式的设备，当前模式看不到 |
| `WPinternals.exe`（SJMG 自带那份） | **需要提权**：本会话的审批提示被禁用，无法提权运行 |

所以"按电源"这一步只能由你做。它不需要任何准备：手机现在就插在这台电脑上，三个文件都是最佳版本（见上节）。

### 按下电源后，三种结果与对应的下一步

| 你看到的 | 含义 | 我下一步做什么 |
|---|---|---|
| **底部 16 行绿条，然后停住** | 内核在真机跑到 `bsd_init`，与模拟器一致 | 立刻转"根设备"：ADR-0005 选卷 + 存储投递（prelink 或公开 loader） |
| **绿条出现后立刻重启/黑屏** | 真机特有差异（缓存/中断/时钟） | 用绿条出现的时间点定位：先关掉色块埋点、再看是否仍重启，二分定位 |
| **只有加载器的顶部绿条，之后全黑** | 内核没有拿到控制权 | 回到引导层：检查 EL1 状态、`ExitBootServices` 后的缓存与 MMU 假设 |

### 本轮确认的一件事（避免再白跑）

`skmem_sysctl_skip=1` 必须留在手机的 `args` 里：去掉它，本机启动就会停在 `_skmem_sysctl_init+0x44`。
把它留在配置里，本机启动才走到 `root-wait`。这条不是可选项，是本机验证过的必要条件。

## 撤回一次"看起来很好"的改进：`arm/pmap.h` 不在 SDK 里

上一轮加了"写帧缓冲前先问 pmap 是否映射"，本机 preflight 通过、主机测试通过——但 **runner 上编译失败**：

```
drivers/NativeBootProgress/Mapped.cpp:16:10: fatal error: 'arm/pmap.h' file not found
```

原因很清楚：`pmap_find_phys()` 在 XNU 的**私有**头文件里（`osfmk/arm/pmap/pmap.h`），而内核构建用的是 iPhoneOS SDK 的
导出头（`libkern/c++/OSKext.h` 在 SDK 里，`arm/pmap.h` 不在）。**本机能编，是因为本机不编那个单元**——preflight 只编
`NativeBootProgress.cpp`。

所以这条改进被撤回（`Mapped.cpp` 与调用一起删除）。教训记在这里：

- 含 XNU 私有头的代码**只能在 runner 上验证**；
- 因此"本机 preflight 通过"**不等于**"内核构建会通过"，凡是新增内核头依赖，必须直接看 runner。

### 真机上"写未映射地址"的风险，仍然没有防护

撤回之后，埋点依旧是直接写 `vinfo.v_baseaddr`。若真机上那一页未映射，内核会因我们而死，且现象与"内核没启动"相同。
可用的替代方案都需要私有头或另建单元，因此这件事暂时**只能靠一次真机开机来回答**：如果底部绿条出现，说明映射没问题；
如果全黑且日志显示内核跑到了 `bsd_init`（需要串口/别的通道），才谈得上区分。

这一点已经写进"三种结果 → 三条下一步"的表里：全黑时优先怀疑执行路径，而不是映射。

## 当前停在哪里（一页结论，给下一轮或下一个人）

**代码侧能做的都做了，剩下的卡在一件物理动作上。**

### 已经成立的（都有证据）

| 事实 | 标签 |
|---|---|
| 真机 EFI 链到内核交接；面板可由我们的代码写入 | hardware-tested |
| 源码内核穿过 IOKit 进入 `bsd_init`（模拟器） | QEMU-tested |
| **手机上现装的那三个文件**在本机跑到 `root-wait` 并画出 12,800 像素底部绿条 | QEMU-tested |
| 埋点 DAIF 泄漏（会让内核画完绿条即崩）已修复并验证 | QEMU-tested + host-tested |
| 存储 kext：645 符号、95 KB 容器、嵌入内核、运行时可达 | ABI-compiled / QEMU-tested |
| prelink 字典可读可写，内核会校验我们插入的条目 | QEMU-tested |

### 卡住的唯一一件事

**没有"这一次真机开机到底发生了什么"的观测。** 三种可能的差别（执行 / 映射 / 存储）都只能由屏幕结果区分，而：

- 手机处于 USB 大容量存储模式，写入不会重启它；
- `thor2` 只认 Thor/紧急下载模式，当前看不到设备；
- `WPinternals.exe` 需要提权，本会话无法提权。

因此需要一次**物理按键开机**，并有人看一眼屏幕最底部。

### 按电源后的三行判断表

| 看到 | 结论 | 下一步 |
|---|---|---|
| 底部 16 行绿 | 真机到 `bsd_init` | 转根设备（ADR-0005）与存储投递 |
| 绿条后立刻重启 | 真机特有差异 | 关埋点做二分（`lumia-bars` 不带 2） |
| 只有顶部加载器绿条 | 内核未取得控制权 | 引导层：EL1 状态、缓存、MMU 假设 |

### 下一轮若要继续做"不需要真机"的事

1. 扩展 prelink 发射器（把我们的 kext 当 module 放进占位段）——数周级，ADR 已写明；
2. 让源码内核自带的 `NativeRamBlock` 真正发布 IOMedia——需要 IOStorageFamily 在链接期可见，除非把它一起编进内核；
3. 以上两条都需要先有"真机到 bsd_init"这个前提，否则是在给未验证的假设加代码。

## 实测：`arm_init` 里还不能 kprintf（一次失败换来的事实）

想在真机上"看见内核是否启动"，最直接的办法是在 `PE_init_platform()` 之后打一行 `kprintf`——那正是图形控制台被安装的时刻。
试了，结果是：

```
error: early native kernel boot stopped before VM setup: ['_sleh_synchronous_sp1']
```

**`_sleh_synchronous_sp1` = EL1 上的同步异常，位置在 VM 初始化之前。** 也就是说：平台专家装了控制台，但控制台的写入路径
（它自己的帧缓冲映射）**要到 VM 工作之后才可用**；在此之前 `kprintf` 会踩空。同一点的色块之所以能画，是因为它直接往加载器
报告的那个地址写，走的是另一条路。

因此这条尝试被撤回，并记在这个注记里：**内核的第一行文字只能出现在 `arm_vm_init` 之后**，本移植现在就是 `bsd_init` 里那一行
（`LUMIA: vinfo …`）。这也解释了真机那张照片为什么只有加载器页面：如果内核死在 VM 之前，它**没有任何办法**把话说出来。
