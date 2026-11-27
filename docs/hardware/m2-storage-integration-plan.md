# M2 集成计划：让 NativeSdhci 真正进入内核并发布块设备

2026-11-27。**这是计划，不是结果**。M2 的定义是"XNU 原生驱动初始化 eMMC、发布 IOMedia、**只读**"，
目前驱动**已 ABI 编译、未链入镜像**，因为它的超类在 prelink 之后才存在。

## 1. 当前事实（可核对）

| 事实 | 出处 |
|---|---|
| `NativeSdhci` 子类化 `IOBlockStorageDevice` | `drivers/NativeSdhci/NativeSdhci.h` |
| `IOStorageFamily` 只在 prelink 合并之后存在 | `board.toml` 的 `[kernel.link_excluded]` 注释 |
| 因此源内核链接**解析不到**它的 vtable 与超类调用 | 同上；`kernel-linked` 未对 NativeSdhci 声明 |
| 驱动不发写/擦除命令、`kIODirectionOut` 直接返回 `kIOReturnUnsupported`、上报写保护 | `scripts/test-storage-read-only.py` 的 5 条断言 |

## 2. 挡在 M2 前面的三件事（按依赖排序）

1. **投递方式**：源内核链接不到 → 必须让驱动以 *kext* 形式存在，并在 prelink 合并时被包含；
2. **匹配时机**：即使包含，也必须确认 IOKit 在 `PE_init_iokit` 之后真的实例化它（而不是只躺在镜像里）；
3. **只读保证**：即使实例化，也必须证明它**没有**向 eMMC 发出写命令（现在只有源码断言，没有运行时证据）。

## 3. 两条投递路径（选一条先走）

| 路径 | 做法 | 优点 | 风险 |
|---|---|---|---|
| **A. prelink 注入**（先用） | 把 `NativeSdhci` 编成 kext bundle，作为条目加入 prelinked 镜像（仓库已有 `add-prelink-entry.py` / `append-prelink-kext.py` 的经验） | 不动加载器；合并后自然有 IOStorageFamily | 之前"追加条目"被 DarwinBoot 拒绝（`overlapping virtual segments`）；需要按 prelink 工具的规则填占位段 |
| **B. 加载器投递** | 由 `DarwinBoot.efi`/UniXNU 在启动时把 kext 读进内存并交给内核 | 不改 prelink 布局 | 需要公开的 kext 加载 API；本 pin 上 `OSKext::loadFromMkext`/`withBooterData` 是私有的，`loadKextWithIdentifier` 需要文件系统 |

**决策规则**：先走 A，因为它的失败模式已知（虚拟段冲突）、可离线检查（`scripts/inspect-prelink.py`），且不需要改启动链。
只有 A 被证明不可行（例如工具不接受我们的条目），才评估 B。

## 4. 分步与验收（每步都能在 QEMU 判定）

| 步 | 动作 | 通过判据 | 失败判据 |
|---|---|---|---|
| S1 | 把 `NativeSdhci` 编成 kext bundle（`Info.plist` + 二进制） | 产物存在且 `plutil`/`file` 检查通过 | 编译失败 |
| S2 | 作为条目加入 prelinked 镜像 | 合并后的镜像里能查到它的类符号与 bundle id | 合并被拒（例如段冲突） |
| S3 | QEMU 启动到 `bsd_init` | fixture 的 PASS 行仍然成立（不因加入而回归） | 启动失败 |
| S4 | 观察是否实例化 | 出现驱动的初始化日志（IOLog）或对应 IORegistry 条目 | 无任何痕迹 ⇒ 匹配条件不满足 |
| S5 | 只读读取 | 能读到扇区 0 的前 512 字节，且内容与已知基准一致 | 读失败/内容不符 |
| S6 | 只读保证 | 整个过程中**没有**任何 CMD24/25/38 被发出（可在驱动内计数并打印） | 出现写命令 |

**S5 的"已知基准"**：QEMU 下的块设备不是 eMMC，所以 S5 只证明"驱动能通过 IOStorage 读扇区"；
真机 eMMC 的 S5 要等 handbook run，且**只读**。

## 5. 与 GPT 解析器的接合点

解析器（`drivers/Common/GptRead.c`，已在内核内自检通过）接受**扇区回调**。S5 通过后，回调实现就是
"对 block device 发一次读请求"，于是 M3 的"从设备读 GPT"自然成立，而不再依赖内存里的合成盘。

## 6. 明确不做

- 不为进入 M2 而格式化 MainOS、改分区表或写 eMMC；
- 不在未验证只读保证前让任何文件系统挂载该设备；
- 不把"编译通过/prelink 有条目"当作 M2 达成（里程碑文档已写明这条规则）。

## 7. S1 已经成立（2026-11-28 实测）

kernel 作业现在按顺序构建容器并检查它，build 46028655982 的输出：

```
ok   .../org.unixnu.NativeSdhci/Contents/MacOS/NativeSdhci: arm64 kext bundle, 645 symbols,
     segments ['__DATA','__DATA_CONST','__LINKEDIT','__TEXT','__TEXT_EXEC']
.../NativeSdhci.mkext: 95462 bytes, plist at 94208, checksum 0x4AEB457C
.../generated/mkext_blob.cpp: 95462 bytes as lumia_sdhci_mkext
```

同一份构建里 `archive` 步骤的失败数为 **0**（此前 `mkext_blob.cpp is missing` 被作业吞掉）。

**因此 S1 通过、S2 未尝试**：bundle 与 container 都已生成并通过格式检查，但把它放进 prelinked 镜像仍被拒（已知的段冲突）。

## 8. S6 的计数器已就位（2026-11-28）

S6 要求"整个过程中**没有**发出 CMD24/25/38"，而且要是**运行时**的证据。为此在 `PollingHost::issue()` 里加了两件事：

| 计数器 | 含义 |
|---|---|
| `native_sdhci_commands_issued` | 每一条离开 `issue()` 的命令 |
| `native_sdhci_write_commands` | 其中写/擦除的那几条（24/25/38） |

写入/擦除**在触碰命令寄存器之前**就被计数并直接拒绝（返回 `InvalidArgument`），所以计数一定先于任何设备动作。
两个计数器都是非 `static`，等驱动真正跑起来时可以被内核打印。

写入相关的 opcode 用**数字**引用（`24u`/`25u`/`38u`），因为 `scripts/test-storage-read-only.py` 断言这个驱动**不得出现**写命令的名字，
而 `SdhciRegs.h` 也不声明 CMD38——"没声明"不等于"不会到达"，所以计数器三种都覆盖。

**仍未成立的是运行时读数**：驱动还没有在 QEMU/真机里跑过，S6 的判据（计数为 0）要等 S4 之后才能读。

## 9. S2 为什么被拒：读 prelink 工具源码得到的答案（2026-11-28）

把 `UniXNU/NativePrelink` 的 `native_prelink.py` 读了一遍（本地临时 clone 用于阅读，不入库）。它判断"哪些东西算组件、各自占哪段地址"的方式是：

| 行 | 规则 |
|---|---|
| 161–171 | 组件来自**父镜像自己的 plist 条目**，用条目的 `_PrelinkExecutableLoadAddr` 找到它的 Mach-O，并要求 `MH_KEXT_BUNDLE` |
| 167 | 那个地址必须**已经落在父镜像的段里**（`backed_offset(parent, va, …)`）——不是"写在旁边"，而是"必须被父镜像装下" |
| 172–174 | 组件的每个非 `__LINKEDIT` 段都被登记为一段**归属区间** |
| 182–185 | 归属区间按地址排序后**不允许互相重叠**，否则 `Overlapping component extents` |

也就是说：**追加一个第三方 kext 不是"加一条 plist"，而是要一个布局槽位**——它的代码必须被父镜像的某个段覆盖，且所有段的地址区间不能与既有组件相交。
框架自己的 `fileset_layout.py` 正是为**它 manifest 里的组件**计算这种槽位的（"places native segments in space freed by the replaced kernel and omitted entries"）；
我们手工追加的条目没有参与那次布局计算，所以段的虚拟地址必然与已有内容相交——这正是之前 `overlapping virtual segments` 的来源。

### 9.1 因此 S2 要满足的四件事（缺一不可）

1. 一个**不与任何既有组件相交**的虚拟地址区间（由布局计算给出，或手工验证过整个镜像的空洞）；
2. 把 kext 的字节放进父镜像的某个段里，使 `backed_offset` 能取到它；
3. 在 plist 里写 `_PrelinkExecutableLoadAddr` / `_PrelinkExecutableSize` / `_PrelinkKmodInfo` 等字段；
4. 组件之间段区间不重叠（工具会逐段校验）。

### 9.2 结论

- **S2 不是"再写一个注入器"能解决的**：它需要参与**布局计算**。可行路径只有两条：
  (a) 让框架的布局工具把 `NativeSdhci` 当组件看待（改框架/manifest，需单独评审）；
  (b) 走**加载器投递**（路线 B），不动 prelinked 镜像的布局。
- 本仓库现有的 `scripts/add-prelink-entry.py` 做的是"插入条目"，而**布局**不在它手里，所以它永远会撞上第 4 条。

## 10. 第三条路线（C）：把轮询主机直接编进内核，先拿到"能读 eMMC"

`NativeSdhci.cpp` 之所以必须当 kext，是因为它子类化 `IOBlockStorageDevice`。但真正做事的两个文件——
`PollingHost.cpp` 与 `SdhciCore.cpp`——**不继承任何 IOKit 类**：它们只操作 SDHCI 寄存器、轮询状态、读 512 字节。
这一点值得单独记下来，因为仓库已经有一条成熟通道把**普通代码编进内核镜像**（同一套注入器把 GPT 解析器送了进去）。

| 项 | 说明 |
|---|---|
| 做法 | 用注入通道把 `PollingHost`/`SdhciCore` + 一个小适配器编进镜像；post-VM 后用 `ml_io_map` 映射 SDHCI 寄存器窗口，初始化并读扇区，把结果交给 GPT 解析器 |
| 能得到 | **M3 的真实证据**（从 eMMC 读分区表），以及 M2 的"控制器初始化 + 读块"实质部分 |
| 不能得到 | **M2 的"发布 IOMedia"**——没有 IOKit 类就没有 IOMedia，这一项仍要等 kext 投递 |
| 前置 | SDHCI 的**时钟/复位/供电**配置（`BoardConstants.h` 有地址，但上电时序只能真机验证）；MMU 映射（post-VM 可用） |
| 风险 | **在 QEMU 上无法验证**（没有对应 SDHCI 设备），第一次运行就是真机 ⇒ 必须有"失败即停、只读"的保护，且不能因此改动分区 |

### 10.1 决策规则

1. 只要 kext 投递仍未解决，**C 是唯一能推进 M3 到真机的路线**；
2. 但 C 的每一行都只能在真机上验证，因此**先做完 A 的替代或 B**，除非时间上更需要 M3 的真机证据；
3. 无论走哪条，C 的读路径必须与 S6 同样的只读保证（同一套计数器）——它复用 `PollingHost`，计数器自然生效。

**当前不启动 C**：本轮只把这条路线与它的边界记录下来，避免以后把"能编进内核"误当成"能读 eMMC"。

## 11. SDHCI 探针在 QEMU 的结果（2026-11-28）

artifact `661770a9…`（build 46034996420，commit `37abf24`）。

| 运行 | 结果 |
|---|---|
| 不带 `lumia-sdhci-probe` | 六形态全部 root-wait（4 / 1 / 0 / 0 / 0 / 30）⇒ **默认路径无回归** |
| 带 `lumia-sdhci-probe` | 到 `arm_vm_init returned`、`early map state 4`、`gpt self-check 0`，随后**第一次读 SDHCI 窗口就 fault**：ESR `0x96000010`、FAR `0xfffffff0406009fe` |

**读法**：

1. 探针**确实被执行**（不带参数时没有这个 fault，带参数才出现）——所以它真的进了镜像并走到了 `ml_io_map`；
2. `ml_io_map` 返回了一个 **KVA**（FAR 是 `0xfffffff0…`），读它 fault：QEMU 里 `0xf9824900` **没有设备**，映射背后是空的；
3. **风险已记录**：探针里的 fault 会让内核停住，所以它只能永远躲在自己的启动参数后面——现在就是这样接的。

**这一步买到什么**：探针的接线、`ml_io_map` 分支、以及"失败会以 fault 的形式出现"这一事实。
**没买到什么**：任何真实寄存器的读数——那要真机。
