#!/usr/bin/env python3
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET


SPEC = importlib.util.spec_from_file_location("native_stage", Path(__file__).with_name("stage-native-bringup.py"))
STAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGE)


def symbols(blob, allow_prelinked=False):
    # The stager refuses a merged image because its __PRELINK segments are a provenance gate. A fixture
    # run that only asks "what does that image reach" is not that gate's subject, so the caller can say
    # so; anything else the contract objects to still raises.
    try:
        STAGE.contract(blob)
    except ValueError as error:
        if not (allow_prelinked and "runtime qualification gate" in str(error)):
            raise
    offset = 32
    result = {}
    for _ in range(struct.unpack_from("<I", blob, 16)[0]):
        command, length = struct.unpack_from("<II", blob, offset)
        if command == 2:
            table, count, strings, string_bytes = struct.unpack_from("<4I", blob, offset + 8)
            for index in range(count):
                name_offset, kind, section, _, value = struct.unpack_from("<IBBHQ", blob, table + index * 16)
                if not name_offset or kind & 0xE0 or (kind & 0xE) != 0xE or not section:
                    continue
                stop = blob.index(b"\0", strings + name_offset, strings + string_bytes)
                result[blob[strings + name_offset:stop].decode()] = value
        offset += length
    return result


def nearest_symbol(names, address):
    """The symbol an address falls in, as 'name+0xN', or None if it precedes the image."""
    best = None
    for name, value in names.items():
        if value <= address and (best is None or value > best[1]):
            best = (name, value)
    return None if best is None else f"{best[0]}+{address - best[1]:#x}"


def checkpoint_symbols():
    """The milestone name the fixture records to the kernel symbol it breaks on.

    docs/native-checkpoints.json is the single list: the fixture and the checkers read the same
    file, so a milestone cannot drift from the symbol that is supposed to prove it.
    """
    document = json.loads((STAGE.ROOT / "docs/native-checkpoints.json").read_text())
    mapping = {}
    for checkpoint in document["checkpoints"]:
        fixture = checkpoint.get("fixture")
        if fixture and fixture.endswith("_entry") and checkpoint.get("symbol"):
            mapping[fixture.removesuffix("_entry")] = checkpoint["symbol"]
    return mapping


def missing_bsd_providers(names):
    """The symbols a kernel needs before bsd_init can return, and which one are absent."""
    return [symbol for symbol in ("_pthread_start", "_source_pthread_bootstrap")
            if symbol not in names]


def choose_transport(kind):
    """'unix' where the emulator can share a socket file, 'tcp' where it cannot (Windows)."""
    if kind == "auto":
        return "tcp" if os.name == "nt" else "unix"
    return kind


def apply_adt_profile(esp, name):
    """Regenerate the ADT inside an ESP *copy* from a board.toml profile.

    The staged artifact carries the bring-up ADT, whose GIC sits at the Lumia's SoC addresses. The
    emulated machine put its own GICv2 at 0x08000000, so the copy needs the qemu profile -- the
    artifact and the handset profile are never touched. This runs the profile checker on the result
    as well, so a profile that produces an invalid tree fails here rather than as a QEMU fault.

    Returns the metadata worth recording in the report.
    """
    profile = STAGE.resolve_profile(STAGE.ROOT / "board.toml", name)
    adt = esp / "EFI/UniXNU/Payloads/kernel.macho.adt"
    if not adt.exists():
        raise ValueError(f"{adt} is missing; the ESP is not a staged bring-up tree")
    subprocess.run(STAGE.adt_command(profile, adt, "1122334455667788"),
                   check=True, cwd=STAGE.ROOT)
    subprocess.run([sys.executable, str(STAGE.ROOT / "scripts/check-adt.py"), str(adt),
                    "--profile", name], check=True, cwd=STAGE.ROOT)
    return {"adt_profile": name,
            "gic_windows": {"distributor": profile.get("gic_distributor"),
                            "cpu_interface": profile.get("gic_cpu_interface")}}


MSG_MAGIC = 0x063061


def read_dmesg(connection, names):
    """Extract the kernel's own message buffer.

    XNU's printf goes through msgbuf as well as the console, so on a machine with no console the
    text still exists in kernel memory. `struct msgbuf` is {int magic, size, bufx, bufr; char *bufc}
    and bufx/bufr walk a ring buffer, so a wrapped buffer is read as bufr..end + start..bufx.
    """
    pointer = int.from_bytes(read_memory(connection, names["_msgbufp"], 8), "little")
    if pointer == 0:
        pointer = names.get("_msgbuf", 0)
    if pointer == 0:
        raise ValueError("the kernel has no msgbuf pointer to read")
    header = read_memory(connection, pointer, 24)
    magic, size, bufx, bufr = (int.from_bytes(header[index:index + 4], "little")
                               for index in range(0, 16, 4))
    buffer = int.from_bytes(header[16:24], "little")
    if not buffer or size <= 0 or size > 16 * 1024 * 1024 or bufx > size or bufr > size:
        raise ValueError(f"msgbuf looks uninitialised: magic {magic:#x}, size {size}, "
                         f"bufx {bufx}, bufr {bufr}, buffer {buffer:#x}")
    data = read_chunked(connection, buffer, size)
    text = data[bufr:bufx] if bufr <= bufx else data[bufr:] + data[:bufx]
    return {"magic": magic, "size": size, "bufx": bufx, "bufr": bufr,
            "text": text.rstrip(b"\0").decode("utf-8", "replace")}


SCREEN_LINE = re.compile(r"initialize_screen: b=([0-9A-Fa-f]+), w=([0-9A-Fa-f]+), "
                         r"h=([0-9A-Fa-f]+), r=([0-9A-Fa-f]+), d=([0-9A-Fa-f]+)")


def screen_geometry(dmesg_text):
    """The framebuffer the kernel adopted, from its own initialize_screen line."""
    for line in dmesg_text.splitlines():
        match = SCREEN_LINE.search(line)
        if match:
            base, width, height, row, depth = (int(value, 16) for value in match.groups())
            if base and width and height and row:
                # The kernel logs d=0 when the depth is not set; 32 bpp is what the row width says.
                return {"base": base, "width": width, "height": height, "row_bytes": row,
                        "bpp": depth or 32}
    return None


def framebuffer_bytes(connection, geometry):
    return read_chunked(connection, geometry["base"], geometry["row_bytes"] * geometry["height"],
                        chunk=32768)


def write_ppm(path, data, geometry):
    """A PPM is enough to look at the screen and needs no image library."""
    width, height, row, bpp = (geometry["width"], geometry["height"],
                               geometry["row_bytes"], geometry["bpp"])
    if bpp != 32:
        raise ValueError(f"only 32 bpp framebuffers are written, not {bpp}")
    lines = [f"P6\n{width} {height}\n255\n".encode()]
    for y in range(height):
        pixels = data[y * row:y * row + width * 4]
        lines.append(bytes(component for index in range(0, len(pixels), 4)
                           for component in (pixels[index + 2], pixels[index + 1], pixels[index])))
    path.write_bytes(b"".join(lines))


def monitor_command(port, command, timeout=10.0):
    """Send one HMP command to QEMU's monitor and return everything it printed."""
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        output = b""
        deadline = time.monotonic() + timeout
        while b"(qemu)" not in output and time.monotonic() < deadline:
            try:
                chunk = connection.recv(4096)
            except TimeoutError:
                break
            if not chunk:
                break
            output += chunk
        connection.sendall(command.encode() + b"\n")
        output = b""
        while b"(qemu)" not in output and time.monotonic() < deadline:
            try:
                chunk = connection.recv(4096)
            except TimeoutError:
                break
            if not chunk:
                break
            output += chunk
    return output.decode("utf-8", "replace")


def save_physical_memory(port, address, size, path):
    """QEMU writes the bytes itself: the GDB stub speaks virtual addresses, pmemsave does not."""
    output = monitor_command(port, f"pmemsave {address:#x} {size} {path}")
    if not path.exists() or path.stat().st_size != size:
        raise ValueError(f"pmemsave produced no {size}-byte file: {output.strip()}")
    return path.read_bytes()


BOOT_ARGS_SIZE = 0x480
DARWINBOOT_ARGS = re.compile(r"args=(0x[0-9A-Fa-f]+)")


def boot_args_address(serial_log):
    """DarwinBoot prints the physical address of the boot_args it built."""
    match = DARWINBOOT_ARGS.search(serial_log)
    return int(match.group(1), 16) if match else None


def decode_boot_args(data):
    """Decode the arm64 boot_args (pexpert/pexpert/arm64/boot.h at xnu-8796.141.3)."""
    if len(data) < BOOT_ARGS_SIZE:
        raise ValueError(f"boot_args needs {BOOT_ARGS_SIZE:#x} bytes, got {len(data):#x}")

    def u16(offset):
        return int.from_bytes(data[offset:offset + 2], "little")

    def u32(offset):
        return int.from_bytes(data[offset:offset + 4], "little")

    def u64(offset):
        return int.from_bytes(data[offset:offset + 8], "little")

    video = {name: u64(0x28 + index * 8) for index, name in enumerate(
        ("v_baseAddr", "v_display", "v_rowBytes", "v_width", "v_height", "v_depth"))}
    depth = video["v_depth"] & 0xFF
    # CommandLine follows deviceTreeLength (0x68 + 4) with no padding: reading it at 0x70 drops
    # the first four characters, which is how the misspelt "-v" was noticed.
    command_line = data[0x6C:0x6C + 1024].split(b"\0")[0].decode("utf-8", "replace")
    return {
        "Revision": u16(0x00), "Version": u16(0x02),
        "virtBase": u64(0x08), "physBase": u64(0x10), "memSize": u64(0x18),
        "topOfKernelData": u64(0x20),
        "video": {**video, "depth_bits": depth},
        "machineType": u32(0x58),
        "deviceTreeP": u64(0x60), "deviceTreeLength": u32(0x68),
        "commandLine": command_line,
        "bootFlags": u64(0x470), "memSizeActual": u64(0x478),
    }


def read_chunked(connection, address, size, chunk=4096):
    """Read a large region: the GDB stub refuses a single packet the size of a message buffer."""
    data = b""
    while len(data) < size:
        length = min(chunk, size - len(data))
        data += read_memory(connection, address + len(data), length)
    return data


def read_debug_buffer(connection, names):
    """The panic output XNU keeps for a debugger: debug_buf_base .. debug_buf_ptr."""
    if not all(name in names for name in ("_debug_buf_base", "_debug_buf_ptr", "_debug_buf_size")):
        return ""
    base = int.from_bytes(read_memory(connection, names["_debug_buf_base"], 8), "little")
    write = int.from_bytes(read_memory(connection, names["_debug_buf_ptr"], 8), "little")
    size = int.from_bytes(read_memory(connection, names["_debug_buf_size"], 4), "little")
    if not base or not write or write < base or size <= 0 or write - base > size:
        return ""
    data = read_chunked(connection, base, write - base)
    return data.split(b"\0")[0].rstrip(b"\0").decode("utf-8", "replace").strip()


def receive(connection):
    while True:
        byte = connection.recv(1)
        if not byte:
            raise ValueError("GDB connection closed before a reply")
        if byte == b"$":
            break
    reply = bytearray()
    while True:
        byte = connection.recv(1)
        if not byte:
            raise ValueError("truncated GDB reply")
        if byte == b"#":
            break
        reply.extend(byte)
    checksum = bytearray()
    while len(checksum) < 2:
        byte = connection.recv(2 - len(checksum))
        if not byte:
            raise ValueError("truncated GDB checksum")
        checksum.extend(byte)
    if int(checksum, 16) != sum(reply) % 256:
        raise ValueError("GDB checksum mismatch")
    connection.sendall(b"+")
    return bytes(reply)


def request(connection, command):
    packet = command.encode()
    connection.sendall(b"$" + packet + b"#" + f"{sum(packet) % 256:02x}".encode())
    reply = receive(connection)
    while reply.startswith(b"O") and reply != b"OK":
        reply = receive(connection)
    return reply


def read_memory(connection, address, length):
    response = request(connection, f"m{address:x},{length:x}")
    if response.startswith(b"E"):
        raise ValueError(f"GDB could not read {address:#x}: {response!r}")
    data = bytes.fromhex(response.decode())
    if len(data) != length:
        raise ValueError("short GDB memory read")
    return data


def read_registers(connection):
    registers = bytes.fromhex(request(connection, "g").decode())
    if len(registers) < 268:
        raise ValueError("short AArch64 register set")
    values = {f"x{index}": int.from_bytes(registers[index * 8:index * 8 + 8], "little") for index in range(31)}
    values.update(sp=int.from_bytes(registers[248:256], "little"),
        pc=int.from_bytes(registers[256:264], "little"), cpsr=int.from_bytes(registers[264:268], "little"))
    return values


def read_system_registers(connection):
    result = {}
    number = 0
    visited = set()
    wanted = {"elr_el1", "esr_el1", "far_el1", "sctlr_el1", "tcr_el1", "cntfrq_el0"}

    def feature(name):
        nonlocal number
        if name in visited or len(visited) >= 8:
            return
        visited.add(name)
        content = bytearray()
        for offset in range(0, 131072, 4096):
            chunk = request(connection, f"qXfer:features:read:{name}:{offset:x},1000")
            if not chunk or chunk[:1] not in (b"m", b"l"):
                return
            content.extend(chunk[1:])
            if chunk[:1] == b"l":
                break
        else:
            raise ValueError("QEMU register description exceeds the bounded size")
        for node in ET.fromstring(content.replace(b"xi:include", b"include")).iter():
            kind = node.tag.rsplit("}", 1)[-1]
            if kind == "include":
                feature(node.attrib["href"])
            elif kind == "reg":
                number = int(node.attrib.get("regnum", str(number)), 0)
                name = node.attrib["name"].lower()
                if name in wanted:
                    data = request(connection, f"p{number:x}")
                    if data and not data.startswith(b"E"):
                        result[name] = hex(int.from_bytes(bytes.fromhex(data.decode()), "little"))
                number += 1

    feature("target.xml")
    return result


def run(args):
    original = args.kernel.read_bytes()
    lean = (args.esp / "EFI/UniXNU/Payloads/kernel.macho").read_bytes()
    if args.allow_prelinked:
        # An evidence boot of a merged image is not the staged pair this check compares: the payload
        # carries the merged kernel itself, so there is no lean copy derived from it to verify.
        print("note: evidence boot, strip verification skipped for the merged image")
    else:
        STAGE.verify_strip(original, lean)
    def contract(blob):
        """The stager's contract, with the provenance refusal waived for an evidence boot."""
        try:
            return STAGE.contract(blob)
        except ValueError as error:
            if not (args.allow_prelinked and "runtime qualification gate" in str(error)):
                raise
            return {"source_crypto_symbols": set()}

    names = symbols(original, allow_prelinked=args.allow_prelinked)
    required = ["_arm_vm_init", "_arm64_eventi", "_gPEClockFrequencyInfo"]
    if any(name not in names for name in required):
        raise ValueError("required real XNU symbols are missing")
    if args.crypto_post:
        if args.allow_prelinked:
            # The crypto contract describes the source-built kernel (source-provider POST mapping). A
            # merged image carries Apple extensions instead, so the comparison is not meaningful for it.
            print("note: evidence boot, crypto contract skipped for the merged image")
        else:
            STAGE.crypto_contract(original)
    if args.finish_iokit and "_PE_init_iokit" not in names:
        raise ValueError("real IOKit initialization symbol is missing")
    if args.finish_bsd:
        for symbol in ("_kernel_bootstrap", "_bsd_init"):
            if symbol not in names:
                raise ValueError(f"{symbol} is missing; the BSD start cannot be observed")
    stops = {name: address for name, address in names.items() if
        name.startswith("___ubsan_handle_") or name in (
            "_arm_vm_init", "_panic", "_panic_with_options", "_fleh_synchronous", "_sleh_synchronous_sp1")}
    if args.crypto_post:
        stops["_source_corecrypto14_bootstrap"] = names["_source_corecrypto14_bootstrap"]
    if args.finish_iokit:
        stops["_PE_init_iokit"] = names["_PE_init_iokit"]
    if args.past_bsd:
        args.finish_bsd = True
    providers_missing = []
    if args.finish_bsd:
        # Say why instead of letting the run panic: a kernel without the source pthread component
        # panics inside bsd_init with "pthread kernel extension not loaded (function table is NULL)".
        # --past-bsd asks for exactly that observation, so it records the condition instead of
        # refusing.
        missing = missing_bsd_providers(names)
        if missing and not args.past_bsd:
            raise ValueError(
                f"the kernel has no {', '.join(missing)}: CONFIG_XNU_SOURCE_PTHREAD did not reach "
                "the link, so bsd_init panics before a root volume is mounted "
                "(docs/emulation/2026-11-17-local-qemu-bsd-init-panic.json); check it with "
                "scripts/check-kernel-link.py --config configs/lumia950_defconfig, or use "
                "--past-bsd to observe the panic instead")
        if missing:
            providers_missing = list(missing)
        # The BSD subsystem starting is the last thing this port can observe before a root volume
        # is required: kernel_bootstrap calls bsd_init.
        stops["_kernel_bootstrap"] = names["_kernel_bootstrap"]
        stops["_bsd_init"] = names["_bsd_init"]
    watched = {}
    watch_names = list(args.watch)
    if args.past_bsd:
        # After bsd_init, the next thing worth seeing is whether a root volume is even attempted.
        watch_names.append(checkpoint_symbols()["vfs_mountroot"])
    if watch_names:
        # A one-shot "was this code reached?" probe: retire the breakpoint on the first hit so the
        # run can continue. It answers questions like "is any IRQ delivered at all?" without a
        # second instrumented build.
        for name in watch_names:
            if name not in names:
                raise ValueError(f"--watch {name} is not a symbol in this kernel")
            stops[name] = names[name]
            watched[name] = False
    watched_by_address = {names[name]: name for name in watched}
    for address in args.break_at:
        value = int(address, 16)
        stops[f"@0x{value:x}"] = value
    reads = []
    for spec in args.read:
        name, _, size = spec.partition(":")
        name, _, offset = name.partition("+")
        if name not in names:
            raise ValueError(f"--read {name} is not a symbol in this kernel")
        reads.append((name, int(offset or "0", 0), int(size or "8", 0)))
    output = args.output.resolve()
    if output.exists():
        raise ValueError("use a new output directory to preserve earlier evidence")
    output.mkdir(parents=True)
    report = {"schema": "lumia950-xnu-entry-emulation-v1", "emulator_only": True,
        "handset_boot_observed": False, "ios_userspace_booted": False, "gpu_frame_observed": False,
        "kernel_sha256": hashlib.sha256(original).hexdigest(), "arm_vm_init_entry_observed": False,
        "arm_vm_init_return_observed": False,
        "architectural_counter_hz": 19200000,
        "source_crypto_bootstrap_return_observed": False,
        "iokit_return_observed": False,
        "source_crypto_bootstrap_symbols_present": set(contract(original)["source_crypto_symbols"]) == STAGE.CRYPTO_SYMBOLS}
    with tempfile.TemporaryDirectory(prefix="lumia-xnu-") as temporary:
        directory = Path(temporary)
        esp = directory / "esp"
        shutil.copytree(args.esp, esp)
        config = esp / "EFI/UniXNU/unixnu.toml"
        text, changed = re.subn(r'^default = "exit"$', 'default = "xnu"', config.read_text(), flags=re.M)
        text, timeout_changed = re.subn(r'^timeout = 300$', 'timeout = 1', text, flags=re.M)
        if changed != 1 or timeout_changed != 1:
            raise ValueError("expected the explicit non-autoboot bring-up menu")
        config.write_text(text)
        endpoint = directory / "gdb.sock"
        if args.adt_profile:
            report.update(apply_adt_profile(esp, args.adt_profile))
        transport = choose_transport(args.gdb_transport)
        port = None
        if transport == "tcp":
            # A Windows host has no AF_UNIX for the emulator's GDB chardev here, so the stub is a
            # loopback TCP server instead. The port is picked from an ephemeral bind.
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", args.gdb_port))
                port = probe.getsockname()[1]
            gdb = f"tcp:127.0.0.1:{port}"
        else:
            gdb = f"unix:{endpoint},server=on,wait=off"
        # A monitor socket is how physical memory is read (pmemsave): the GDB stub speaks virtual
        # addresses, and the framebuffer the kernel logs is a physical one.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            monitor_port = probe.getsockname()[1]
        command = [args.qemu, "-machine", "virt,gic-version=2", "-cpu", "cortex-a53,cntfrq=19200000", "-smp", str(args.smp),
            "-m", "768", "-bios", str(args.firmware.resolve()), "-display", "none", "-serial", "stdio",
            "-monitor", f"tcp:127.0.0.1:{monitor_port},server=on,wait=off", "-nic", "none",
            "-no-reboot", "-device", "ramfb", "-S",
            "-gdb", gdb,
            "-drive", f"if=none,id=boot,format=raw,readonly=on,file=fat:ro:{esp}",
            "-device", "virtio-blk-pci,drive=boot"]
        with (output / "serial.log").open("wb") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + args.timeout
                if transport == "tcp":
                    while True:
                        if process.poll() is not None or time.monotonic() >= deadline:
                            raise ValueError("QEMU GDB server did not start")
                        try:
                            connection = socket.create_connection(("127.0.0.1", port), timeout=1)
                            break
                        except OSError:
                            time.sleep(0.1)
                else:
                    while not endpoint.exists():
                        if process.poll() is not None or time.monotonic() >= deadline:
                            raise ValueError("QEMU GDB server did not start")
                        time.sleep(0.1)
                    connection = socket.socket(socket.AF_UNIX)
                with connection:
                    connection.settimeout(max(1, deadline - time.monotonic()))
                    if transport == "unix":
                        connection.connect(str(endpoint))
                    request(connection, "qSupported")
                    for address in sorted(set(stops.values())):
                        if request(connection, f"Z1,{address:x},4") != b"OK":
                            raise ValueError("QEMU refused a real instruction breakpoint")
                    milestones = checkpoint_symbols()
                    entries = {names[milestones["arm_vm_init"]]: "arm_vm_init"}
                    if args.crypto_post:
                        entries[names[milestones["source_crypto_bootstrap"]]] = "source_crypto_bootstrap"
                    if args.finish_iokit:
                        entries[names[milestones["iokit"]]] = "iokit"
                    if args.finish_bsd:
                        entries[names[milestones["kernel_bootstrap"]]] = "kernel_bootstrap"
                        entries[names[milestones["bsd_init"]]] = "bsd_init"
                    returns = {}
                    report["milestones"] = []
                    for _ in range(12):
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("native boot observation deadline expired")
                        connection.settimeout(remaining)
                        try:
                            report["gdb_stop_reply"] = request(connection, "c").decode()
                        except TimeoutError:
                            report["observation_timed_out"] = True
                            connection.settimeout(5)
                            connection.sendall(b"\x03")
                            report["gdb_stop_reply"] = receive(connection).decode()
                            values = read_registers(connection)
                            break
                        values = read_registers(connection)
                        current = values["pc"]
                        if current in watched_by_address:
                            name = watched_by_address[current]
                            watched[name] = True
                            # Record where it was reached from, so "a thread blocked" can become
                            # "this call blocked", without a second instrumented build.
                            details = {"pc": hex(values["pc"]), "x30": hex(values["x30"]),
                                       "args": [hex(values[f"x{index}"]) for index in range(4)]}
                            try:
                                details["stack"] = read_memory(connection, values["sp"], 256).hex() if values["sp"] else ""
                            except ValueError:
                                details["stack"] = ""
                            report.setdefault("watch_details", {})[name] = details
                            if request(connection, f"z1,{current:x},4") != b"OK":
                                raise ValueError("could not retire a watch breakpoint")
                            continue
                        if current in entries:
                            milestone = entries.pop(current)
                            report[milestone + "_entry_observed"] = True
                            report["milestones"].append(milestone + "_entry")
                            if milestone == "arm_vm_init" and not args.finish_vm:
                                break
                            if milestone == "kernel_bootstrap":
                                # The bootstrap thread never returns to a caller this test can
                                # observe. The entry breakpoint still has to be retired, or resuming
                                # re-triggers it and the loop reads the same PC forever.
                                if request(connection, f"z1,{current:x},4") != b"OK":
                                    raise ValueError("could not retire the entry breakpoint")
                                continue
                            if milestone == "bsd_init" and not args.past_bsd:
                                if request(connection, f"z1,{current:x},4") != b"OK":
                                    raise ValueError("could not retire the entry breakpoint")
                                break
                            return_address = values["x30"]
                            report[milestone + "_return_target"] = hex(return_address)
                            returns[return_address] = milestone
                            if request(connection, f"z1,{current:x},4") != b"OK" or \
                                request(connection, f"Z1,{return_address:x},4") != b"OK":
                                raise ValueError("could not observe an actual caller return address")
                        elif current in returns:
                            milestone = returns.pop(current)
                            report[milestone + "_return_observed"] = True
                            report["milestones"].append(milestone + "_return")
                            if milestone == "source_crypto_bootstrap":
                                report["source_crypto_status"] = int.from_bytes(
                                    read_memory(connection, names["_source_corecrypto14_status"], 4), "little")
                            if request(connection, f"z1,{current:x},4") != b"OK":
                                raise ValueError("could not retire the return breakpoint")
                            if report["arm_vm_init_return_observed"] and \
                                (not args.crypto_post or report["source_crypto_bootstrap_return_observed"]) and \
                                (not args.finish_iokit or report["iokit_return_observed"]) and \
                                (not args.finish_bsd or report.get("bsd_init_entry_observed")) and \
                                (not args.past_bsd or report.get("bsd_init_return_observed")):
                                break
                        else:
                            break
                    report["registers"] = {name: hex(value) for name, value in values.items()}
                    report["system_registers"] = read_system_registers(connection)
                    report["stop_symbols"] = [name for name, address in stops.items() if address == values["pc"]]
                    # Name the code and the faulting instruction's site, so a stop that is not a
                    # breakpoint explains itself in the report instead of only in a log.
                    report["pc_symbol"] = nearest_symbol(names, values["pc"])
                    if providers_missing:
                        # --past-bsd tolerates a kernel that cannot get past bsd_init; say so in the
                        # report rather than letting the panic look like an emulator fault.
                        report["pthread_providers_missing"] = list(providers_missing)
                    if args.dump_boot_args:
                        # The hand-off structure DarwinBoot built, read from physical memory: this
                        # is what the EFI site claims it passed, checked at the XNU boundary.
                        try:
                            log.flush()
                            address = boot_args_address(
                                (output / "serial.log").read_text(errors="replace"))
                            if address is None:
                                raise ValueError("DarwinBoot printed no boot_args address in the "
                                                 "serial log")
                            data = save_physical_memory(monitor_port, address, BOOT_ARGS_SIZE,
                                                        output / "boot-args.bin")
                            decoded = decode_boot_args(data)
                            (output / "boot-args.json").write_text(
                                json.dumps(decoded, indent=2) + "\n")
                            video = {name: hex(value)
                                     for name, value in decoded["video"].items()}
                            report["boot_args"] = {
                                "address": hex(address),
                                **{name: hex(value) for name, value in decoded.items()
                                   if name != "video" and isinstance(value, int)},
                                "commandLine": decoded["commandLine"],
                                "video": video,
                            }
                        except ValueError as error:
                            report["boot_args"] = f"unreadable: {error}"
                    if args.dump_dmesg and "_panic" in report["stop_symbols"] \
                            and args.panic_settle > 0:
                        # A breakpoint at panic() entry happens before a single character of the
                        # panic is formatted. panic() prints the message, the caller and the stack,
                        # then halts, so let it run and stop it again afterwards; the buffer read
                        # below is then the complete record.
                        connection.sendall(b"c")
                        time.sleep(args.panic_settle)
                        connection.sendall(b"\x03")
                        try:
                            receive(connection)
                        except (TimeoutError, ValueError):
                            pass
                    if args.dump_dmesg:
                        try:
                            dmesg = read_dmesg(connection, names)
                            text = dmesg.pop("text")
                            # panic() prints to the debug buffer as well as the console; on a
                            # machine with no console that buffer is the only place the message and
                            # its caller chain appear. Append whatever it holds.
                            debug_text = read_debug_buffer(connection, names)
                            if debug_text:
                                text += "\n--- debug buffer ---\n" + debug_text
                            (output / "dmesg.txt").write_text(text + "\n")
                            if args.dump_framebuffer:
                                # initialize_screen logs the framebuffer's physical base, and the
                                # GDB stub speaks virtual addresses, so this only works when a
                                # kernel maps it and logs the mapping. Record the reason instead of
                                # losing the log over it.
                                try:
                                    geometry = screen_geometry(text)
                                    if geometry is None:
                                        report["framebuffer"] = ("no initialize_screen line in "
                                                                 "the kernel log")
                                    else:
                                        pixels = save_physical_memory(
                                            monitor_port, geometry["base"],
                                            geometry["row_bytes"] * geometry["height"],
                                            output / "framebuffer.bin")
                                        write_ppm(output / "framebuffer.ppm", pixels, geometry)
                                        counts = {}
                                        for index in range(0, len(pixels) - 3, 4 * 64):
                                            key = pixels[index:index + 3]
                                            counts[key] = counts.get(key, 0) + 1
                                        top = sorted(counts.items(),
                                                     key=lambda item: -item[1])[:4]
                                        report["framebuffer"] = {
                                            "base": hex(geometry["base"]),
                                            "width": geometry["width"],
                                            "height": geometry["height"],
                                            "row_bytes": geometry["row_bytes"],
                                            "bpp": geometry["bpp"],
                                            "bytes": len(pixels),
                                            "sha256": hashlib.sha256(pixels).hexdigest(),
                                            "top_colours_bgr": [
                                                {"bgr": colour.hex(), "samples": count}
                                                for colour, count in top],
                                        }
                                except ValueError as error:
                                    report["framebuffer"] = {
                                        "geometry": screen_geometry(text),
                                        "unreadable": str(error),
                                        "why": "initialize_screen logs a physical base; the GDB "
                                               "stub reads virtual addresses, so the screen is only "
                                               "readable once the kernel maps it and logs that",
                                    }
                            report["dmesg"] = {"magic": hex(dmesg["magic"]), "size": dmesg["size"],
                                               "bufx": dmesg["bufx"], "bufr": dmesg["bufr"],
                                               "chars": len(text),
                                               "debug_buffer_chars": len(debug_text),
                                               "sha256": hashlib.sha256(text.encode()).hexdigest()}
                        except ValueError as error:
                            report["dmesg"] = f"unreadable: {error}"
                    if args.past_bsd:
                        # The observation, not a gate: entering bsd_init was the requirement, and
                        # what happened after it is the result.
                        if report.get("bsd_init_return_observed"):
                            report["past_bsd_outcome"] = "returned"
                        elif "_panic" in report["stop_symbols"]:
                            report["past_bsd_outcome"] = "panicked"
                        elif report.get("observation_timed_out"):
                            report["past_bsd_outcome"] = "timed_out"
                        else:
                            report["past_bsd_outcome"] = "stopped"

                        # How far boot got is not the same question as how the machine stopped. A kernel
                        # that waited for a root device had already returned from BSD initialisation, so
                        # saying "panicked" for it hides the progress; classify it separately.
                        serial_text = ""
                        try:
                            serial_text = (output / "serial.log").read_text(errors="replace")
                        except OSError:
                            pass
                        # The dmesg read just above is the same boot output and is flushed before the
                        # serial log on some runs, so consider it too.
                        serial_text += report.get("dmesg_text", "") if isinstance(
                            report.get("dmesg_text"), str) else ""
                        if isinstance(report.get("dmesg"), dict):
                            dmesg_path = output / "dmesg.txt"
                            if dmesg_path.is_file():
                                serial_text += dmesg_path.read_text(errors="replace")
                        waited = ("Still waiting for root device" in serial_text
                                  or "Waiting on <dict" in serial_text)
                        if waited:
                            report["root_device_wait_observed"] = True
                            if report["past_bsd_outcome"] in ("panicked", "stopped", "timed_out"):
                                report["past_bsd_outcome"] = "root-wait"
                    if watched:
                        report["watched"] = watched
                    if reads or args.read_at:
                        # Globals the kernel keeps its state in, read at the stop. This is how a
                        # "blocked on a lock" observation becomes a number.
                        report["read"] = {}
                        for name, offset, size in reads:
                            try:
                                report["read"][f"{name}+{offset:#x}"] = read_memory(
                                    connection, names[name] + offset, size).hex()
                            except ValueError as error:
                                report["read"][f"{name}+{offset:#x}"] = f"unreadable: {error}"
                        for spec in args.read_at:
                            address, _, size = spec.partition(":")
                            try:
                                report["read"][spec] = read_memory(
                                    connection, int(address, 16), int(size or "16", 0)).hex()
                            except ValueError as error:
                                report["read"][spec] = f"unreadable: {error}"
                    try:
                        elr = int(report["system_registers"].get("elr_el1", "0"), 16)
                        report["fault_elr_symbol"] = nearest_symbol(names, elr) if elr else None
                    except ValueError:
                        report["fault_elr_symbol"] = None
                    report["fault_far"] = report["system_registers"].get("far_el1")
                    if "_panic" in report["stop_symbols"]:
                        # panic(fmt, ...) takes its format string in x0. Reading it makes every
                        # panic self-describing in the report instead of a symbol name alone.
                        try:
                            raw = read_memory(connection, values["x0"], 160)
                            report["panic_format"] = raw.split(b"\0")[0].decode("utf-8", "replace")
                        except ValueError as error:
                            report["panic_format"] = f"unreadable: {error}"
                        # "... @%s:%d" takes the file and the line as the next arguments, and on a
                        # machine with no console this is the only way to learn the panic site.
                        found = []
                        for register in ("x1", "x2", "x3"):
                            pointer = values.get(register, 0)
                            if pointer < 0xfffffff000000000:
                                continue
                            for _ in range(2):
                                try:
                                    raw = read_memory(connection, pointer, 128)
                                except ValueError:
                                    break
                                text = raw.split(b"\0")[0].decode("utf-8", "replace")
                                if text and text.isprintable() and len(text) > 2:
                                    found.append(text)
                                    break
                                # Some panic call sites pass a pointer to the string pointer.
                                if len(raw) >= 8:
                                    pointer = int.from_bytes(raw[:8], "little")
                                    if pointer < 0xfffffff000000000:
                                        break
                                else:
                                    break
                        if found:
                            report["panic_string_args"] = found
                    report["wfe_event_index"] = int.from_bytes(read_memory(connection, names["_arm64_eventi"], 4), "little")
                    report["clock_info_bytes"] = read_memory(connection, names["_gPEClockFrequencyInfo"], 0x58).hex()
                    report["stack_bytes"] = read_memory(connection, values["sp"], 256).hex()
                    if args.crypto_post:
                        report["source_crypto_status"] = int.from_bytes(
                            read_memory(connection, names["_source_corecrypto14_status"], 4), "little")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if report.get("system_registers", {}).get("cntfrq_el0") != hex(report["architectural_counter_hz"]):
        raise ValueError("the emulated architectural counter does not match the Lumia device-tree frequency")
    if not report["arm_vm_init_entry_observed"] or report["wfe_event_index"] != 4 or \
        args.finish_vm and not report["arm_vm_init_return_observed"]:
        raise ValueError(f"early native kernel boot stopped before VM setup: {report.get('stop_symbols')}; see {output}")
    if args.crypto_post and (not report["source_crypto_bootstrap_return_observed"] or report.get("source_crypto_status") != 0):
        raise ValueError(f"real source-provider initialization did not complete successfully: {report.get('stop_symbols')}; see {output}")
    if args.finish_iokit and not report["iokit_return_observed"]:
        raise ValueError(f"real IOKit initialization did not return: {report.get('stop_symbols')}; see {output}")
    if args.finish_iokit:
        # Order matters, contiguity does not: kernel_bootstrap may be entered between them, which
        # is why the milestones are checked as a subsequence.
        expected = ["arm_vm_init_entry", "arm_vm_init_return", "source_crypto_bootstrap_entry",
                    "source_crypto_bootstrap_return", "iokit_entry", "iokit_return"]
        observed = [m for m in report["milestones"] if m in expected]
        if observed != expected:
            raise ValueError(f"Iokit must initialize after the successful source crypto "
                             f"bootstrap; observed {observed}")
    if args.finish_bsd and not report.get("bsd_init_entry_observed"):
        raise ValueError(
            f"the kernel did not reach bsd_init: {report.get('stop_symbols') or report['milestones']}; "
            f"see {output}")
    if args.past_bsd:
        # This mode is an observation, not a gate: entering bsd_init is the requirement, and what
        # happened after it is already recorded in past_bsd_outcome.
        if report.get("past_bsd_outcome") is None:
            raise ValueError(f"--past-bsd recorded no outcome; see {output}")
    milestone = "returned from arm_vm_init" if args.finish_vm else "reached arm_vm_init entry"
    if args.crypto_post:
        milestone += " and the real source-provider POST/bootstrap"
    if args.finish_iokit:
        milestone += " and PE_init_iokit"
    if args.finish_bsd:
        milestone += " and bsd_init"
    if args.past_bsd:
        milestone += f" (after bsd_init: {report.get('past_bsd_outcome')})"
    print(f"PASS: real source XNU passed clock/WFE/topology setup and {milestone}; {output}")
    print("EMULATION ONLY. Handset boot, iOS userspace and GPU rendering are not proven.")


def main():
    parser = argparse.ArgumentParser(description="Bounded real ARM64 XNU early-boot instruction test; never accepts a loader bar as kernel proof")
    parser.add_argument("--kernel", required=True, type=Path)
    parser.add_argument("--allow-prelinked", action="store_true",
                        help="evidence only: accept a merged/prelinked image that the stager would refuse")
    parser.add_argument("--esp", required=True, type=Path)
    parser.add_argument("--firmware", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--qemu", default="qemu-system-aarch64")
    parser.add_argument("--gdb-transport", choices=("auto", "unix", "tcp"), default="auto",
                        help="how the fixture reaches the emulator's GDB stub (default: unix on "
                             "POSIX, tcp on Windows)")
    parser.add_argument("--gdb-port", type=int, default=0,
                        help="loopback port for the tcp transport; 0 picks a free one")
    parser.add_argument("--dump-boot-args", action="store_true",
                        help="read the boot_args DarwinBoot built from physical memory and decode "
                             "it (video, memory, command line, device tree), writing boot-args.json")
    parser.add_argument("--dump-framebuffer", action="store_true",
                        help="with --dump-dmesg, also save the screen the kernel adopted as "
                             "framebuffer.ppm (the geometry comes from its initialize_screen line). "
                             "This is the surface a framebuffer console would write on")
    parser.add_argument("--panic-settle", type=float, default=0.0, metavar="SECONDS",
                        help="when --dump-dmesg stops at a panic, let it print for this long before "
                             "reading the buffer. Measured at 0 on this kernel: panic output goes to "
                             "the console, and msgbuf and the debug buffer stay empty, so the delay "
                             "buys nothing here; it exists for kernels whose panic does reach a "
                             "buffer")
    parser.add_argument("--dump-dmesg", action="store_true",
                        help="also extract the kernel's own message buffer (msgbuf) at the stop and "
                             "write it to dmesg.txt; on a machine with no console this is the only "
                             "text the kernel left behind")
    parser.add_argument("--past-bsd", action="store_true",
                        help="after bsd_init is entered keep observing: record bsd_init_return if it "
                             "returns, watch _vfs_mountroot, and record the panic and its text if it "
                             "does not. Implies --finish-bsd and tolerates a kernel without the "
                             "pthread provider, because observing that panic is the point")
    parser.add_argument("--watch", action="append", default=[], metavar="SYMBOL",
                        help="record whether this symbol is reached at all (one shot, retired on "
                             "the first hit); repeatable")
    parser.add_argument("--smp", type=int, default=1,
                        help="CPUs in the emulated machine (default 1). QEMU returns zero for the "
                             "GIC target registers on a uniprocessor GICv2 (hw/intc/arm_gic.c: "
                             "'For uniprocessor GICs these RAZ/WI'), which is why ArmCpu's CPU "
                             "target probe fails there; a multiprocessor machine reports a mask")
    parser.add_argument("--break-at", action="append", default=[], metavar="ADDRESS",
                        help="set a breakpoint at a raw kernel virtual address and stop there; "
                             "the registers in the report then hold the values at that point "
                             "(for example a function's return value in x0)")
    parser.add_argument("--read", action="append", default=[], metavar="SYMBOL[:BYTES]",
                        help="dump the bytes at a symbol when the run stops; repeatable")
    parser.add_argument("--read-at", action="append", default=[], metavar="ADDRESS:BYTES",
                        help="dump the bytes at a raw kernel virtual address when the run stops "
                             "(for example a panic format string); repeatable")
    parser.add_argument("--adt-profile",
                        help="regenerate the ADT in the ESP copy from this board.toml profile "
                             "(for example qemu, whose GIC sits at 0x08000000); the staged tree "
                             "itself is left as it was")
    parser.add_argument("--timeout", default=90, type=float)
    parser.add_argument("--finish-vm", action="store_true", help="Also require a real return to the saved VM caller; stop on intervening faults")
    parser.add_argument("--crypto-post", action="store_true", help="After VM, observe the actual source provider return and KERN_SUCCESS status; no overrides")
    parser.add_argument("--finish-iokit", action="store_true", help="Also require actual IOKit initialization entry/return after the real crypto POST")
    parser.add_argument("--finish-bsd", action="store_true", help="Also require the kernel to enter bsd_init; that is the last milestone before a root volume is required")
    args = parser.parse_args()
    # Evidence only: let the stager parses merged images without the provenance refusal.
    STAGE.ALLOW_PRELINKED = args.allow_prelinked
    if args.past_bsd:
        args.finish_bsd = True
    if args.finish_bsd:
        args.finish_iokit = True
    if args.finish_iokit:
        args.crypto_post = True
    if args.crypto_post:
        args.finish_vm = True
    if not 1 <= args.timeout <= 300:
        parser.error("timeout must be 1..300 seconds")
    try:
        run(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        # For an evidence boot of a merged image, the message alone is not enough: the provenance gate has
        # been hit from several call sites, and a traceback names the next one instead of a guess.
        if getattr(args, "allow_prelinked", False):
            import traceback
            traceback.print_exc()
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
