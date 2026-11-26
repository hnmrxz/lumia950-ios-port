# 让 prelink 带上我们的 kext：可行性笔记

合并镜像现在能跑到 `bsd_init`（run 45858986402，证据 `docs/hardware/measurements/merged-bsd-init/`），所以
"prelink 携带第三方 kext"从"不确定能不能用"变成"只差把 kext 放进 prelink 信息"。这份笔记记录投入之前应该知道的、
已经读出来的事实。

## 事实一：prelink 工具做的是真正的重定位，不是简单拼接

框架的 `emit_prelink.py`（pin：`UniXNU/NativePrelink@2b6ffb50`，20,136 字符）内部有：

| 环节 | 函数/位置 | 作用 |
|---|---|---|
| 取模块 | `modules`（由原始内核缓存解析） | 每个 Apple kext 的 segments、vmaddr、filesize |
| PC 相对修复 | `pc_relative_target` / `instruction_inventory` | 把模块里的 PC 相对指令改写到新地址 |
| 追加段 | `append_segment(name, va, blob, size, protection)` | 生成新的 `__PRELINK_TEXT`/`__PRELINK_DATA` |
| 元数据 | 写 `_PrelinkInfoDictionary`、`_PrelinkLinkKASLROffsets`、`_PrelinkKCID` | 让内核按 prelink 语义加载 |
| 每模块键 | `_PrelinkExecutableLoadAddr`、`_PrelinkExecutableSize`、`_PrelinkKmodInfo`、`_PrelinkExecutableSourceAddr` | 内核据此映射与启动 |

结论：**把我们自己的 kext 塞进去，等于自己实现一个 prelinker**（放置地址、段合并、指令修复、kmod 指针）。
这不是"序列化一个容器"，工程量在数周级。

## 事实二：即使有了块设备，还缺文件系统

pin 的 XNU 源码里没有 `bsd/hfs`，也没有 `md`（内存盘）。合并镜像能提供的是**内核缓存里的 kext**：`IOStorageFamily`、
`com.apple.filesystems.apfs` 等。也就是说：

- 块设备 + 根卷这条路，文件系统侧只能寄希望于 **APFS kext**（需要在 prelink roots 里，且需要一个 APFS 卷）；
- 设备上现在**没有 Apple 格式的卷**（MainOS=NTFS、EFIESP=FAT），创建它要重新分区或生成 FFU（见 ADR-0005）。

## 事实三：还有一条更便宜的路没试

`OSKext::loadKextWithIdentifier()` 是**公开**的，它按 bundle id 在 kext 目录里查找。它需要文件系统——但**合并镜像已经
有 IOStorageFamily**（Apple 的 kext）。如果将来出现任何一个块设备（哪怕是一个 RAM 介质），先挂一个最小文件系统、
把我们的 kext 放进去，再让它按 id 加载，可能比写 prelinker 便宜。

## 建议的决策顺序

1. **先在真机上确认内核执行**（等一张底部绿条的照片）——它决定这一切是否值得做；
2. 若真机也到 `bsd_init`，则评估：写 prelinker（贵但通用） vs 先用 RAM 介质 + 公开 loader（便宜但依赖文件系统）；
3. 两条都不做之前，不要声称"存储已通"——现在成立的是：kext 产物、容器、嵌入与调用诊断，**不是介质**。

## 已经能读它了：`scripts/inspect-prelink.py`

写入之前先证明能读。这个工具解析镜像的段表、取出 `__PRELINK_INFO` 的内容、把发射器那种"没有 plist 外壳、整数写成
`<integer size="64">0x...`"的片段规范化后用标准解析器读出来，并列出每个 kext 的 `_PrelinkExecutableLoadAddr` 与大小。
对真实的合并镜像（54 MB，run 45832509015）实跑：

```
16 prelinked kexts, prelink info segment 110592 bytes
  com.apple.kpi.bsd                              load=0xfffffff004004000 size=0x7c78
  com.apple.iokit.IOStorageFamily                load=0xfffffff00400b280 size=0x1fc0
  com.apple.filesystems.apfs                     load=0xfffffff004337000 size=0x3ca15
  ...
```

这一步本身有价值：任何"把我们的 kext 加进去"的尝试，都要先能读懂这张表；现在它可读、可断言（6 个主机测试）。

## 字典这一半也能写了

`scripts/add-prelink-entry.py` 往 `_PrelinkInfoDictionary` 的数组末尾插入一条新条目，其余字节原样保留。两件事值得记：

- **段里有富余空间**：真实合并镜像的文本是 108,416 字节，段是 110,592 字节，插一条 300 多字节的条目后用了 108,749，
  仍然放得下。所以改字典不需要挪动段表。
- **不能简单找第一个 `</array>`**：kext 条目内部自带数组（personality 之类），第一个 `</array>` 往往是内层的。
  工具改成按标签配平找 `_PrelinkInfoDictionary` 的那个收尾——第一版就栽在这里，插进去以后读不回来。

对真实镜像实跑：

```
inserted org.unixnu.NativeSdhci at offset 39581, 108749 of 110592 bytes used; 17 entries parse back
```

**仍然缺的一半**：条目里的 `_PrelinkExecutableLoadAddr` 必须指向镜像内被映射的模块文本，而把我们的 kext 放进去意味着
选地址、追加段、修复 PC 相对指令——即 ADR-0003 里评估为"数周级"的那部分。这条工具的价值是让字典这一半先可测。

## 内核真的读到了我们插入的条目

把上一步编辑过的合并镜像（`add-prelink-entry.py` 插入 `org.unixnu.NativeSdhci`）直接在本机 QEMU 里启动，dmesg 出现：

```
[    7.666566]: Kext org.unixnu.NativeSdhci error - CFBundleVersion missing/invalid type.
```

这一行同时说明三件事：

1. **prelink 字典的编辑确实被内核消费**——不是写进文件就算完，加载器读到了它；
2. 加载器**会校验条目字段**（这里抱怨 `CFBundleVersion` 缺失/类型不对）；
3. 随后它仍然 panic，因为条目里的 `_PrelinkExecutableLoadAddr` 指向的是内核自己的文本，而不是一个真实的模块。

这条结果把"注入路线是否可行"从推断变成了观测：**路是通的，缺的是条目字段与可执行文件的放置**。后者才是数周级的部分。

## 条目字段被加载器逐个"验收"：三个错误依次消失

把条目字段补齐后连续启动三次，加载器的抱怨按顺序推进，这本身就是一份由内核给出的字段规范：

| 条目内容 | 内核的反应 |
|---|---|
| 只有 id + 地址 + 大小 | `Kext org.unixnu.NativeSdhci error - CFBundleVersion missing/invalid type.` |
| 加上 `CFBundleVersion`、`CFBundleExecutable`、`CFBundlePackageType`、`OSBundleLibraries` | `Kext org.unixnu.NativeSdhci can't find prelinked kext kmod_info address.` |
| 再加上 `_PrelinkKmodInfo` | 不再抱怨字段，直接 `_fleh_synchronous` —— 它去用那个地址，而地址指向内核文本 |

**结论：条目结构已经对上，字段校验全部通过。** 现在缺的是"地址后面真的有我们的模块"——即把 kext 文本放进镜像并让地址指向它。
这正是预linker 的工作（选地址、追加段、修 PC 相对指令），也是 ADR-0003 评估为"数周级"的那部分。

另一个直接结论：校验顺序是 id → 版本 → kmod 记录 → 使用地址。写注入器时按这个顺序自检可以省下大量真机/模拟器往返。

## 放置的第一步：镜像头部还有 320 字节富余

`scripts/append-prelink-kext.py` 把 kext 字节追加到镜像尾部，并在头部**已有的 320 字节空隙**里新增一个
`LC_SEGMENT_64`（`__LUMIA_KEXT`，RX 权限，指向追加区）。两点是实测的：

- 头部命令区结束于 5,728 字节，第一个真实 section（`__const`）在 6,048 字节，空隙 320 字节，**刚好够一个 72 字节的段命令**；
- 因此不需要移动任何既有段——`ncmds +1`、`sizeofcmds +72`，其余字节不动。

它**故意不做**符号绑定与重定位修复。缺少这两步的 kext 一旦运行必然 fault，所以下一次启动实验得到的是"还缺绑定"这一信息，
而不是一次成功的加载。这正是把数周工作切成可观测小步的方式。

## 第一次真正的"放置实验"：容器拆出来了，地址选错了

整条流程在本机跑通（不需要 runner）：

1. 从内核镜像里按 `MKXT` 找到容器（95,462 字节，校验和 0x6329427F）；
2. 容器内第 52 字节起是 kext 可执行体（5 段：`__TEXT 0x0`、`__TEXT_EXEC 0x4000`、`__DATA 0x8000`、
   `__DATA_CONST 0xc000`、`__LINKEDIT 0x10000`，共 91,840 字节）；
3. `_kmod_info` 落在 0x8000，即"放置基址 + 0x8000"；
4. 用 `append-prelink-kext.py` 放到 0xfffffff009000000，字典里补上条目（含 `_PrelinkKmodInfo`）。

启动结果：

```
stop       : _fleh_synchronous
fault_elr  : _mach_vm_allocate_kernel+0x94
fault_far  : 0xfffffff03b5d97d4
milestones : ... iokit_entry（没有 iokit_return）
```

**读法**：条目这次通过了字段校验并进入"真正加载"，内核在为自己的映射分配内存时踩到了坏地址——说明
**0xfffffff009000000 这个基址与内核的映射安排冲突**（内核的 `__PRELINK_INFO` 到 `0xfffffff0082cc000 + 0x1b000`，
其后并不是可用的放置区，而且 kext 的段还没有任何绑定）。

下一步的两个具体候选：

1. 换基址：放到与 `__PLK_TEXT_EXEC` 相邻、或内核已映射的 `__PRELINK_TEXT` 区域内（需要连同段大小一起调整）；
2. 先做符号绑定（把 `_kmod_info` 里的函数指针与 `OSBundleLibraries` 的符号解析好），否则即使地址对了也会在 start 时 fault。

这两步都是 prelinker 的正体；本轮的价值是**把"放置"从纸面变成了可执行的多步实验**，并确定了第一个具体失败点。

## 修正与再测：之前用错了镜像；换成带 PRNG 保护的镜像后，失败点变成"滑动"

上一轮的三次放置实验用的是 run 45832509015 的合并镜像——它**早于 PRNG 幂等保护**。用该镜像做"只加段"的对照实验时，
panic 是 `!prng_ready`，这暴露了实验基准不对。换成 run 45858986402（第一个能到 `bsd_init` 的合并镜像）后重测：

| 镜像/改动 | 结果 |
|---|---|
| 带保护的合并镜像，未改 | 到 `bsd_init`（`Failed to mount root device`） |
| 同镜像 + `__LUMIA_KEXT` 段 + 字典条目 | `_fleh_synchronous`，`_mach_vm_allocate_kernel+0x94` |
| 同上，但段 `vmsize` 页对齐 | **同一个 fault** |

两次 fault 的 `fault_far` 分别是 `0xfffffff049fdaa94` 与 `0xfffffff05b7daa94`——**每次启动都不同**，这正是 KASLR 滑动的
数量级。结合 `mach_vm_allocate_kernel` 的位置，最合理的解释是：**内核在给 kext 分配/映射时按"已滑动"的地址处理，而我们
新增的段带着未滑动的绝对地址**，于是它去碰一个不属于自己的地址。

下一步（明确）：按发射器的做法，让段地址与 `__PRELINK_TEXT` 的 **slide** 语义一致——即把我们的 kext 放进
`__PRELINK_TEXT` 的地址空间内（增长该段），而不是新造一个绝对地址的段。这也解释了为什么"换基址"两次都没有改变 fault 形态。

## 按发射器的方式"长段"，被我们自己的加载器挡了一次——这次是好事

发射器不是凭空造映射，而是把 kext 塞进**内核已声明的占位段**（`__PRELINK_TEXT`、`__PLK_TEXT_EXEC` 等）。照这个思路写了
`scripts/grow-prelink-segment.py`：把字节插到目标段的文件末尾、把该段 `filesize`/`vmsize` 与首个 section 一起增大、
把插入点之后的所有文件偏移（段、section、`LC_SYMTAB` 等）整体后移。

对真实镜像把 91,840 字节的 kext 放进 `__PLK_TEXT_EXEC`（插入点 0x30a4000，增长 94,208 字节），启动时 **DarwinBoot 直接拒绝**：

```
error: overlapping virtual segments
```

这不是失败，而是**验证**：

- 我们改出来的镜像**结构和段几何被加载器读到并检查了**；
- 拒绝的原因具体：`__PLK_TEXT_EXEC` 的结尾正好是 `__PLK_DATA_CONST` 的起点，**该段没有 VA 余量**，一长大就与下一段重叠。

所以下一步不是"要不要长段"，而是"**长哪个段**"：`__PLK_DATA_CONST` 之后有约 10 MB 的 VA 空隙，但它是数据段（不可执行）；
可执行的 `__PRELINK_TEXT`/`__PLK_TEXT_EXEC` 都与后继段首尾相接。因此正确做法是**连同后继段的 VA 一起上移**，或者把模块拆成
"文本进可执行段、数据进数据段"——这正是发射器 `append_segment()` 在做的事（它要求 4K 对齐、拒绝与既有映射碰撞）。
