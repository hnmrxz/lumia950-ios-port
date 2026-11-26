# 观测阶梯：从"有没有色块"到"内核跑到哪一步"

一页纸，说明每一种仪器能回答什么、依赖什么、以及失败时怎么解读。所有仪器都在 framebuffer 上画，
因为这台机器没有可用 UART；顺序按"依赖的映射从弱到强"排列。

## 阶梯

| # | 仪器 | 依赖 | 触发 | 回答的问题 | 状态 |
|---|---|---|---|---|---|
| 1 | 第 1 条色块（红） | bootstrap 恒等映射（`start.s` 建立） | `arm_init` 内、`PE_init_platform` 前 | 内核入口 C 代码是否执行 | 已实现，受 `lumia-bars` 控制 |
| 2 | 第 2 条色块（黄） | 同上 | `arm_vm_init` 调用前 | 是否走到建立 VM 的最后一步 | 已实现 |
| 3 | 第 3 条色块（绿） | **pexpert 已装视频控制台**，`PE_state.video.v_baseAddr` 为映射过的地址 | `bsd_init` 入口 | 是否越过 VM 建立、进入 BSD 初始化 | 已实现（run 45781718126 起的镜像） |
| 4 | 第 4 条色块（青） | 自己在 `bsd_init` 里 `ml_io_map()` 面板物理地址 | 同第 3 条 + `lumia-bars4` 开关 | 面板是否可被显式映射并写入（不依赖 pexpert 的映射） | 已实现，待构建验证 |
| 5 | 复位检查点 | PSCI `SYSTEM_RESET` **不可用**（`board.toml` 记录了 8992 的 PSCI 没有该调用） | — | （改用 PMIC/PSHOLD 需另行验证） | 未采用 |

## 为什么第 1、2 条在模拟器里必然崩

本机 QEMU 复现（9 秒一轮）后读寄存器：`x9 = 0xe03030`（色块颜色）、`x11 = 0x6c7fdc00`（写入地址）、
`ESR_EL1 = 0x96000005` → EC `0x25`（同 EL 数据中止）、FSC `0b000101`（**translation fault, level 1**）。

`start.s` 在进入 C 之前建立了 bootstrap 恒等映射，只覆盖 RAM；模拟器的面板在 `0x6C7A0000`（RAM 之上）→ 未映射。
真机面板在 `0x400000`，落在 ADT 声明的 DRAM 窗口 `0x0 + 0xaf600000` 内 → 应当可写。第 3、4 条不依赖这个假设。

## 如何用本地 QEMU 迭代（不花 CI）

```powershell
# 1) 组一个"带开关"的 ESP（stage-kernel 会把 args 写进 unixnu.toml）
python scripts\stage-kernel.py --kernel <kernel.macho> --unique-chip-id 0 `
    --menu-tree out\payload --out out\qemu-x --ntfs-driver out\ntfs_aa64.efi `
    --args "-v cpus=1 lumia-bars lumia-bars4 skmem_seg_size=16384 skmem_md_seg_size=16384 skmem_drv_buf_seg_size=65536 skmem_usr_buf_seg_size=16384 skmem_sysctl_skip=1"

# 2) fixture 要求菜单是"显式非自动启动"：toml 里 default = "exit"、timeout = 300
#    （它自己会改成 default="xnu"、timeout=1 再启动）

# 3) 跑（主机有 QEMU 11.1.0 与 edk2-aarch64-code.fd）
python scripts\test-native-xnu-entry.py --kernel out\qemu-x\EFI\UniXNU\Payloads\kernel.macho `
    --esp out\qemu-x --firmware 'C:\Program Files\qemu\share\edk2-aarch64-code.fd' `
    --output out\qemu-x-run --qemu 'C:\Program Files\qemu\qemu-system-aarch64.exe' `
    --allow-prelinked --past-bsd --dump-dmesg --dump-framebuffer --adt-profile qemu --smt 2 `
    --timeout 240 --gdb-transport tcp
```

注：`--allow-prelinked` 会跳过 strip 校验与 source-crypto 契约（本地实验用）；`--smp 2` 是正确拼写。

## 解读矩阵（真机）

| 屏幕 | 结论 | 下一步 |
|---|---|---|
| 0 条色块 | 内核没到 `arm_init` | 检查 DarwinBoot 跳转到 EL1 之后的路径；考虑把第 1 条改成"在 `start.s` 之后由异常向量写入"或用 panic 屏 |
| 1 条 | 入口 C 代码执行，卡在 `arm_init` 里 | 用第 3/4 条判断是否卡在 VM 建立 |
| 2 条 | 卡在 `arm_vm_init` 内或其后 | 对照 ADT 的 DRAM/窗口参数 |
| 3 条 | 越过 VM 建立，进入 `bsd_init` | 继续往 `vfs_mountroot` 做仪器 |
| 4 条 | 显式映射面板成功 | 说明可以把任意物理地址映射后绘制 → 可做更细的日志页 |

## 与官方文档的对应

- 官方把入口探针画成"蓝/品红"两条，并明确 **MMU 打开后不再画条、改用复位**；我们的第 1、2 条对应蓝/品红。
- 官方的第 3 阶段用 `entry_probe_reset_delay` 触发 PSCI 复位；本机 PSCI 无 `SYSTEM_RESET`，所以改用
  "在 `bsd_init` 用已映射地址画第 3 条"这一等价观测点（见 `docs/hardware/2026-11-26-official-boot-chain-notes.md`）。

## 结论修正：`arm_init` 里画不出任何东西，因为 MMU 在调用它之前就已经打开

读 pin 的 `osfmk/arm64/start.s` 得到的时间线：

| start.s 行 | 动作 |
|---|---|
| 509-512 | 把 `arm_init` 的 KVA 装进 `lr` |
| 514-523 | 建立 bootstrap 页表：**V=P 一个块入口 + KVA 一个块入口，其余全部无效** |
| 744-746 | `MOV64 x0, SCTLR_EL1_DEFAULT` / `MSR_SCTLR_EL1_X0` / `isb sy` → **MMU 与缓存在这里打开** |
| 之后 | 跳入 `arm_init` |

也就是说：**`arm_init` 的第一条指令执行时，MMU 已经是开的**，而映射只覆盖内核镜像自己（V=P 块 + KVA 块）。
帧缓冲**在任何平台上都没有被映射**——真机 `0x400000`、模拟器 `0x6C7A0000` 都一样。

这与本机 QEMU 的实测完全一致（`ESR_EL1 0x96000005` = translation fault, level 1，写入地址正是我们算出的
色块地址），也解释了一个更朴素的事实：**真机装了带开关的两色块内核后，屏幕与不带开关时一模一样**——因为
一旦开关打开，内核在 `arm_init` 的第一条 store 上就同步中止了，根本走不到任何后续阶段。

因此：

* 第 1、2 条色块的**位置是错的**，不是"地址错"；
* 正确的"MMU 之前"是 start.s 第 744 行**之前**，那里 V=P 映射尚未启用、物理访问生效；
* 官方文档说的"蓝条/品红条在 MMU 之前"必然由**加载器（DarwinBoot/GOP）**或 start.s 内的汇编写入，而不是
  由 C 代码在 `arm_init` 里写。

### 处置

1. 已经把手机配置里的 `lumia-bars` 开关**移除**（`args = "-v cpus=1"`），避免部署在机上的内核被仪器打死；
2. 内核侧的 pre-MMU 色块方案**停止**，不再往 `arm_init` 注入任何绘制；
3. 下一件该做的事变成二选一，且都要先在本机 QEMU 上验证：
   - **加载器侧对照条**：由 DarwinBoot 在交接前用 GOP 在**同一坐标**画一条，作为"面板可写且坐标正确"的
     基准；这样"有对照条、无内核条"就等价于"内核没执行"。
   - **start.s 内的汇编探针**：在第 744 行之前插入几条指令写物理地址；风险高（寄存器占用、块映射前），
     但它是唯一能表达"MMU 之前"的内核侧位置。

## 本机读回：模拟器里 XNU **确实会往面板写字**

用 `--dump-framebuffer` 把内核跑完 BSD 初始化前的帧缓冲整块读回（QEMU，800×600）：

| 统计 | 数值 | 含义 |
|---|---|---|
| 纯黑像素 | 404,112 | 背景 |
| 纯绿像素 | 30,000（3,795 个亮像素中大部分属于文字区） | 交接条残留 |
| 灰度桶 `(7,8,8)` | 3,849 | **文字**（等宽、抗锯齿前的白/灰） |
| 亮像素总数 | 3,795 | 控制台输出 |

结论：**在模拟器里，XNU 的视频控制台能成功映射面板并打印文本**。所以"真机全黑"不能解释为
"内核构造本来就不画屏"——同一份代码在模拟器里是画的。

于是真机全黑只剩两类原因：

1. **内核根本没执行**（跳转后立刻中止/挂死）；
2. 内核执行了，但**它的视频初始化在这块面板上失败**（例如 Geometry/像素序与 `boot_args.Video` 不一致，
   或 `0x400000` 这段在真机上的映射方式与模拟器不同）。

这两者的分界正好由加载器侧对照条 + 屏上打印的 `width/height/stride/format/base` 给出：对照条能写、
内核文字不出现 ⇒ 落到第 2 类；对照条也写不出来 ⇒ 面板写入本身有问题，属于第 1 类之外的另一层。

## 真机实测（对照条，2026-11-26）：面板可写，GOP 模式是 1080×1920，stride 1080 像素

诊断版对照条作为 `\EFI\BOOT\BOOTAA64.EFI` 在真机上运行，屏幕上方出现**红条（y=120）与黄条（y=140）**，
下方由应用自己打印出五行数值：

| 打印项 | 实测值 | 含义 |
|---|---|---|
| width | **1080** | GOP 水平分辨率 |
| height | **1920** | GOP 垂直分辨率 |
| stride | **1080** | `PixelsPerScanLine`，即**像素**为单位的行距 |
| pixel format | **1** | `PixelBlueGreenRedReserved8BitPerColor`（BGR 顺序） |
| frame buffer base | **400000** | 与 `boot_args.Video.v_baseAddr` 一致 |

三件事由此确定：

1. **我们的代码能点亮这块面板**（在 y=120/140 处写入并可见），所以"真机全黑"不是"面板不可写"；
2. 固件 GOP 模式是 **1080×1920**，而行距是 **1080 像素 = 4320 字节**；DarwinBoot 报的 `row=4320` 是**字节**，
   与 `boot_args.Video.v_rowBytes` 的语义一致，也印证了 `drivers/NativeBootProgress` 把 stride 当字节是对的；
3. 物理面板是 **1440×2560**（ADT 的 `panel-width/height`），与固件运行模式**不是一回事**：显示驱动要走的是
   面板时序，而不是 GOP 模式，两者不能混用。

