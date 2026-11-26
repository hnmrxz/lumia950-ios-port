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
