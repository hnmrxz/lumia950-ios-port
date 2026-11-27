# 里程碑 M1–M5：真机启动链的最终目标与验收

本文件是目标的唯一权威表述，2026-11-27 由机主重定义。**终点不是苹果标志，也不是 DarwinBoot 的 hand-off**，而是：

> Lumia 950（Talkman / MSM8992）真机启动 XNU，稳定进入 BSD 初始化，通过 XNU 原生存储栈**只读**访问 eMMC，正确解析 GPT，
> 识别 APFS 容器并挂载 APFS root，最终进入可持续运行的 BSD 用户空间。

microSD 载荷实验是**辅助**（验证替代读取路径）；MainOS 格式化**不是必要条件**，且在拿到真实 APFS root 启动证据之前禁止。

## 里程碑与验收证据

| 里程碑 | 目标 | 验收证据（缺一不可） | 当前状态 |
|---|---|---|---|
| **M1** | XNU 稳定进入 BSD 初始化 | ① 真机 XNU 执行轨迹（屏幕/日志，非 QEMU 推断）；② 明确的 BSD 初始化阶段标记；③ **连续多次冷启动**达到同一阶段 | **未达成**：真机目前停在 hand-off 之后、`arm_vm_init` 之前的某处；`vinfo` 在 `PE_init_platform()` 返回时全零（已实测），VM 之前无任何可写帧缓冲 |
| **M2** | eMMC 控制器与块设备初始化 | ① 控制器初始化成功；② 容量与逻辑块大小正确；③ XNU 内部出现对应 IOMedia；④ **无任何写入** | 未达成：驱动已 ABI 编译、容器已嵌入内核，但未在真机加载；kext 投递受 private API 限制 |
| **M3** | 只读读取 GPT | ① GPT 签名与 CRC 正确；② 分区数/类型 GUID/起止 LBA 与独立基准一致；③ 能识别 EFIESP、MainOS 等实际分区；④ 多次读取一致 | 未达成：尚无真机块设备 |
| **M4** | APFS 容器与卷识别 | ① 容器结构识别成功；② 容器/卷标识正确；③ 可读必要元数据；④ **不触发修复或写入** | 未达成：合并镜像已 prelink apfs，但无块设备、无 root-matching 结论 |
| **M5** | 挂载 APFS root 并稳定运行 | ① root 挂载成功；② root device 与预期分区对应；③ 完成 init/launchd 等启动；④ 多次冷启动复测 | 未达成 |

## 不可跳级的原因（工程原则）

| 常见误判 | 为什么不行 |
|---|---|
| "GPT 读出来就等于能挂 APFS root" | GPT 是分区表；APFS 在分区之上，中间还有块设备驱动、IOMedia、存储匹配、APFS 驱动、root 选择与挂载时序 |
| "驱动编译通过/prelink 里有条目就等于真机初始化" | 编译与 prelink 只证明产物存在，不证明真机执行 |
| "QEMU 到了 `bsd_init` 就等于真机到了" | 真机目前**没有**任何内核输出；QEMU 结论不能替代 M1 的证据 |
| "mount -o ro 就保证只读" | 只读必须在**驱动层**保证：本仓库的 `NativeSdhci` 不发写/擦除命令，`kIODirectionOut` 直接 `kIOReturnUnsupported`，并上报写保护（由 `scripts/test-storage-read-only.py` 守住） |

## 优先级（按依赖排序）

1. **M1 观测链**：先知道内核停在何处（见下节的两条候选路线）。
2. **NativeSdhci 集成**：确认驱动真正进入内核并执行（kext 投递）。
3. **eMMC 只读块设备**：建立不写盘的读取能力。
4. **GPT 解析**：先不引入 APFS 复杂度。
5. **APFS 容器/卷识别**。
6. **APFS root 挂载与用户态启动**。

microSD 可作为独立辅助平台，但**不能用它的成功替代 eMMC 真机验证**。

## M1 的两条候选观测路线（下一轮工作）

已验证的硬约束：`arm_vm_init` 之前，内核没有帧缓冲映射（`vinfo` 全零，已用断点实测），因此"早期色块"不可能出现；
而 `kprintf` 在 `kernel_startup_initialize_upto(STARTUP_SUB_KPRINTF)` 之前也不可用。

| 路线 | 做法 | 优点 | 风险/代价 |
|---|---|---|---|
| **A. bootstrap 页表映射帧缓冲** | 在 `start.s` 增加一条把物理帧缓冲映射到保留 KVA 的表项，之后任何早期代码可写屏 | 纯内核改动，可在 QEMU 验证；能定位到 `arm_vm_init` 之前的停点 | 触碰 MMU 初始化，回归风险最高；必须先在 QEMU 通过全部既有门禁 |
| **B. RAM mailbox + 热复位** | 把阶段标记写进内核镜像内（已映射）的变量，热复位后由加载器读出并显示 | 不改页表；加载器已能显示文字 | 需要加载器改动；热复位是否保持 DRAM 未知；需要真机配合 |

**决策规则**：先做 A 的 QEMU 原型（不改真机）；只有当 A 在 QEMU 通过全部既有门禁、且真机装上后仍无输出时，才投入 B。

## 安全边界（继续有效）

1. 保留已验证的 WOA 启动链与 **EFIESP + MainOS 成对恢复**能力。
2. eMMC 初期只读：驱动层不发写命令；不允许分区表写入、文件系统修复或自动挂载写入。
3. 没有真实 APFS root 启动证据前，**不格式化 MainOS**。
4. 不为内核调试更换 `BootShim.efi`、`UEFI.elf`、BCD 或已验证的 UniXNU 启动文件；任何受保护对象改动必须走 `scripts/boot-chain-io.py` 的四项证据。

## M1 进展（2026-11-27 晚）：五个开关已验证、两个新开关撤回

| 事实 | 证据 |
|---|---|
| 五个开关（rtclock/topology/timercall/cpuinit/processor）全开时，内核在 QEMU **仍到 root-wait** 并打出 post-VM 标记 | `scripts/check-staged-tree.py` 用同一棵树换了参考内核后 `past_bsd=root-wait`、`marker=True` |
| 真机把五个全开后**仍无任何输出** | 机主两次开机照片（`docs/hardware/measurements/menu-after-handoff/`） |
| 新增的 `lumia-skip-wfe` / `lumia-skip-startup` **在 QEMU 里即使开关关闭也会让内核早期 fault** | 四种配置全停 `_sleh_synchronous_sp1`；同一棵树换回参考内核即到 root-wait（`docs/hardware/measurements/switch-regression/`） |

**结论**：
1. 五个开关的二分已经做到头——卡点在它们**之前**，且**不能靠"再加跳过"继续逼近**；
2. 新开关本身会破坏启动，**已撤回**，不再写进启动参数；
3. 要到 `arm_vm_init` 之前观测，只能走文档里那两条路线（A：bootstrap 页表映射帧缓冲；B：RAM mailbox + 热复位）。

下一步按决策规则执行：**先做 A 的 QEMU 原型**（不改真机），并用现有门禁（`past_bsd=root-wait`、底部分段色块、`check-evidence`）验证它没有破坏已验证路径。

## M1 观测路线 A 的设计（读源码后落地前的记录）

docs/hardware/m1-observability.md 把路线 A 的机制写到了可以直接照着写代码的程度：start.s 的
create_bootstrap_mapping 的寄存器契约、块大小（16K 页内核 32 MB、4K 页内核 2 MB）、块模板
ARM_TTE_BOOT_BLOCK 是 write-back 因此必须 dc civac、以及运行时从 boot args 读 video 物理基址以同时适配真机与 QEMU。

它同时列出四条风险（内存属性别名、KVA 槽选择、两平台帧缓冲位置不同、30 分钟构建周期）和 QEMU 侧的验收标准：
不启用开关时行为与改动前完全一致；启用时在 rm_vm_init 之前出现可回读色块且内核仍到 root-wait。
**没有这两条，代码不允许上真机。**

## M1 仪器状态（2026-11-27 收尾）

M1（真机进入 BSD 初始化）**仍未达成**，但"看不见内核停在哪"这个障碍**已经解除**：

| 项 | 状态 | 证据 |
|---|---|---|
| 内核能在 `arm_vm_init` **之前**写屏 | ✅ QEMU 成立 | 状态 0，artifact `717752f7…` |
| 真机将要走的页表分支（帧缓冲所在 GB 已有表） | ✅ QEMU 成立 | selftest 状态 30，同一 artifact |
| 真机几何（stride 4320 / width 1080 / 行 8–15） | ✅ QEMU 执行过 | 同上 |
| 内核到 BSD 初始化与 root-wait | ✅ QEMU | fixture PASS 行 |
| **真机出现该色带** | ❌ **未运行** | 只差一次开机 |
| **真机进入 BSD 初始化** | ❌ **未达成** | — |

部署方式已收敛成一条带闸门的命令（`scripts/deploy-early-map.py`），真机验证单在
`docs/hardware/m1-early-map-handset-plan.md`。**没有照片之前，任何一步都不升级为已验证。**

## M3 参考实现（2026-11-27）

M3 要求"只读读取 GPT 并用独立基准核对"。在真机可用之前，先把**参考读者**建立起来：

| 文件 | 作用 |
|---|---|
| `scripts/gpt-read.py` | 只读解析：保护性 MBR、header CRC、entry-array CRC、主/备头一致性、分区重叠检查；任何一项不过即拒绝并给原因 |
| `scripts/make-gpt-fixture.py` | 合成 GPT 镜像（8 MiB、512 B 扇区、两个分区），可注入 mbr/header/entries/overlap 四种损坏 |
| `scripts/test-gpt-read.py` | 10 条：正常读回两分区、CRC 校验、备份头一致性、四种损坏各自被拒、截断镜像被拒、CLI 退出码与 JSON |

**边界**：这是一份**合成 fixture**（分区名与 LBA 都是声明为合成的，不来自任何设备）。
它的用途是给内核侧的读取器一个**可核对的基准**，以及把"拒绝条件"写死；它**不是**真机 GPT 的证据。
真机 M3 仍需要一次只读 dump 与它的 GP 对照（`docs/hardware/mainos-replacement-readiness.md` 的 GPT 采集步骤）。

## M3 的 C 侧解析器与参考读者一致（2026-11-27）

`drivers/Common/GptRead.c` 是内核侧要用的只读 GPT 解析器：不依赖 IOKit，通过调用者提供的扇区回调读取，
校验保护性 MBR、header CRC、entry-array CRC、分区重叠与主/备头一致性，任何一项不过就返回对应状态码而非猜测。

`tools/gpt-harness/main.c` 把它编成主机程序，`scripts/test-gpt-parser-parity.py`（5 条）在同一份合成镜像上
**逐字段对比** C 解析器与 Python 参考读者：

| 项 | 结果 |
|---|---|
| 编译 | `zig cc -std=c11 -Wall -Wextra -Werror` 干净通过 |
| header CRC / entries CRC / 分区号、类型、起止 LBA、名称 | 两者**完全一致** |
| 主/备头一致性 | 两者都报 `agrees` |
| 四种损坏（`mbr` / `header` / `entries` / `overlap`） | 两者都拒绝，且**原因类别相同** |

边界不变：镜像仍是**合成 fixture**。这一步证明的是"内核解析器与独立参考读者口径一致"，
**不是**真机 GPT 的证据；真机 M3 仍需一次只读 dump。

### M3 解析器的编译证据

| 证据 | 内容 |
|---|---|
| host-tested | 与 Python 参考读者在合成镜像上逐字段一致；四种损坏同样被拒 |
| ABI-compiled（arm64 交叉编译） | `zig cc -target aarch64-windows-gnu -std=c11 -Wall -Wextra -Werror -c`，产出 arm64 目标文件 |

**仍未包含**：链接进 XNU（`kernel-linked`）与读真机磁盘（`hardware-tested`）。这两项都要等真机与内核集成。

## M3：解析器已进入内核镜像（2026-11-27）

`ci/inject-gpt-parser.py` 把 `drivers/Common/GptRead.c` 追加到 `arm_init.c`（内核构建本来就在编译的文件），
于是解析器**进入镜像**：

| 证据 | 内容 |
|---|---|
| ABI-compiled | arm64 交叉编译通过 |
| **kernel-linked** | 在 unstripped 内核里能查到符号：`gpt_parse` @ `0xfffffff0073fb088`、`gpt_status_text` @ `0xfffffff0073fb828` |
| QEMU 无回归 | 同一份 artifact 的六种标记形态仍全部到 root-wait（4 / 1 / 0 / 0 / 0 / 30） |

**注入是惰性的**：辅助函数标 `__attribute__((unused))`，`gpt_parse` 为全局以便链接保留；**没有任何调用者**，
因为能喂给它的块设备还不存在。

**因此这一步只买到 `kernel-linked`**：没有调用、没有磁盘读取、没有真机 GPT ⇒ 不声明 `hardware-tested`。
